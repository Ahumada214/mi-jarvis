import os
import json
import re
import threading
import httpx
from datetime import datetime
from typing import Optional
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
import edge_tts
import urllib.parse
import urllib.request
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# Integración Claude (Anthropic)
try:
    import anthropic
except ImportError:
    anthropic = None

# Integraciones de Google Calendar y búsqueda web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tavily import TavilyClient
from obsidian_sync import save_to_obsidian
from spotify_player import get_spotify_oauth, reproducir_en_spotify, reset_spotify_client

# ==========================================
# 1. CREDENCIALES Y VARIABLES DE ENTORNO
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
BLAND_AI_API_KEY = os.environ.get("BLAND_AI_API_KEY", "").strip()
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
GOOGLE_CREDS_RAW = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
OBSIDIAN_FOLDER = os.environ.get("OBSIDIAN_FOLDER", "Jarvis_Notes").strip() or "Jarvis_Notes"
SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "").strip()
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "").strip()
SPOTIPY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "").strip()
RENDER_APP_URL = "https://mi-jarvis.onrender.com"

groq_client = Groq(api_key=GROQ_API_KEY)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (anthropic and ANTHROPIC_API_KEY) else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ==========================================
# 2. MOTOR DE REDACCIÓN (CLAUDE / GROQ VIGENTE)
# ==========================================
def obtener_modelo_groq():
    """Detecta qué modelo de chat estándar está disponible en la cuenta de Groq."""
    candidatos_validos = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768"
    ]
    try:
        modelos_remotos = groq_client.models.list()
        ids_disponibles = {m.id for m in modelos_remotos.data}
        for modelo in candidatos_validos:
            if modelo in ids_disponibles:
                return modelo
    except Exception as e:
        print(f"[GROQ MODEL LIST ERROR] {e}")
    return "openai/gpt-oss-120b"

def redactar_investigacion_profunda(tema: str, contexto: str) -> str:
    """Usa Claude 3.5 Sonnet si la API key existe; si no, usa el modelo vigente de Groq."""
    prompt_redaccion = f"""Eres un analista financiero e investigador sénior de banca de inversión.
Redacta un análisis exhaustivo, técnico y estructurado sobre: {tema}.

Contexto y solicitud: {contexto}

Estructura obligatoria:
- # {tema}
- ## Resumen Ejecutivo y Tesis de Inversión
- ## Métricas de Valuación y Múltiplos Financieros (P/E, EV/EBITDA, márgenes, crecimiento)
- ## Ventajas Competitivas Cuantitativas y Foso Económico (Moat)
- ## Riesgos Clave y Amenazas de Mercado
- ## Conclusión y Perspectiva
- Tags recomendados al pie

Usa formato Markdown limpio apto para notas de Obsidian."""

    if claude_client:
        try:
            res = claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt_redaccion}]
            )
            return res.content[0].text
        except Exception as e:
            print(f"[CLAUDE ERROR, USANDO FALLBACK GROQ] {e}")

    # Fallback con Groq activo
    modelo = obtener_modelo_groq()
    res = groq_client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt_redaccion}],
        max_tokens=3000,
        temperature=0.2
    )
    return res.choices[0].message.content

# ==========================================
# 3. GENERADOR PARA OBSIDIAN (.MD) Y HTML
# ==========================================
def formatear_para_obsidian(titulo: str, contenido_md: str) -> bytes:
    """Estructura el documento con frontmatter YAML compatible nativamente con Obsidian."""
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag_limpio = re.sub(r'[^a-zA-Z0-9_]', '', titulo.split()[0].lower()) if titulo else "general"
    
    nota_obsidian = f"""---
title: "{titulo}"
date_created: "{fecha_actual}"
author: "Jarvis AI"
tags:
  - segundo_cerebro
  - {tag_limpio}
  - finanzas
  - equity_research
---

{contenido_md}

---
*Nota generada automáticamente por Jarvis para tu bóveda de Obsidian.*
"""
    return nota_obsidian.encode('utf-8')

def formatear_documento_html(titulo: str, texto_contenido: str) -> bytes:
    lineas = texto_contenido.split('\n')
    cuerpo_html = "".join([f"<h2>{l.lstrip('#').strip()}</h2>" if l.startswith('#') else f"<p>{l}</p>" for l in lineas if l.strip()])
    return f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'><title>{titulo}</title></head><body style='font-family:sans-serif;padding:30px;line-height:1.6;background:#0f172a;color:#f8fafc;'><div style='max-width:850px;margin:auto;background:#1e293b;padding:35px;border-radius:12px;border:1px solid #334155;'><h1>{titulo}</h1>{cuerpo_html}</div></body></html>".encode('utf-8')

# ==========================================
# 4. MULTIMEDIA, CALENDAR Y BÚSQUEDA WEB
# ==========================================
def buscar_y_enviar_audio(chat_id, query_cancion):
    try:
        query_encoded = urllib.parse.quote(query_cancion)
        html = urllib.request.urlopen(f"https://www.youtube.com/results?search_query={query_encoded}").read().decode('utf-8')
        resultados = re.findall(r'\"watchEndpoint\":\{\"videoId\":\"(.*?)\"', html)
        if resultados:
            video_id = resultados[0]
            url_video = f"https://www.youtube.com/watch?v={video_id}"
            url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': f"🎸 *Pista multimedia lista:*\n🎶 [Escuchar {query_cancion} en YouTube]({url_video})",
                'parse_mode': 'Markdown'
            }
            httpx.post(url_tg, json=payload, timeout=20.0)
            return "Pista activada."
    except Exception as e:
        print(f"[AUDIO ERROR] {e}")
    return "No se pudo enlazar el audio."

def get_calendar_service():
    if not GOOGLE_CREDS_RAW:
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDS_RAW)
        scopes = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return None

def buscar_en_internet(query):
    if not tavily_client:
        return "Buscador Tavily no configurado."
    try:
        respuesta = tavily_client.search(query=query, max_results=4, search_depth="basic")
        resultados = respuesta.get("results", [])
        if not resultados:
            return "No se encontraron resultados web."
        return "\n".join([f"• {r.get('title')}: {r.get('content')}" for r in resultados])
    except Exception as e:
        return f"Error en búsqueda: {e}"

def crear_evento_calendario(titulo, fecha_inicio_iso, fecha_fin_iso):
    calendar_service = get_calendar_service()
    if not calendar_service:
        return "Google Calendar no disponible."
    target_cal = CALENDAR_ID if CALENDAR_ID and CALENDAR_ID != "primary" else "primary"
    try:
        evento = {
            'summary': titulo,
            'start': {'dateTime': fecha_inicio_iso, 'timeZone': 'America/Hermosillo'},
            'end': {'dateTime': fecha_fin_iso, 'timeZone': 'America/Hermosillo'},
        }
        calendar_service.events().insert(calendarId=target_cal, body=evento).execute()
        return f"Evento '{titulo}' agendado con éxito."
    except Exception as e:
        return f"Error al agendar: {e}"

def consultar_agenda_calendario():
    calendar_service = get_calendar_service()
    if not calendar_service:
        return "Google Calendar no disponible."
    target_cal = CALENDAR_ID if CALENDAR_ID and CALENDAR_ID != "primary" else "primary"
    try:
        ahora = datetime.utcnow().isoformat() + 'Z'
        eventos_res = calendar_service.events().list(
            calendarId=target_cal, timeMin=ahora, maxResults=5, singleEvents=True, orderBy='startTime'
        ).execute()
        eventos = eventos_res.get('items', [])
        if not eventos:
            return "No tienes eventos pendientes."
        lista = [f"• {ev.get('summary', 'Sin título')} ({ev['start'].get('dateTime', ev['start'].get('date'))})" for ev in eventos]
        return "Próximos eventos:\n" + "\n".join(lista)
    except Exception as e:
        return f"Error al consultar agenda: {e}"

def _es_chat_telegram(chat_id) -> bool:
    if chat_id is None:
        return False
    return str(chat_id).strip().lstrip("-").isdigit()

def enviar_documento_telegram(chat_id, nombre_archivo, bytes_data, mime_type, caption=""):
    if not _es_chat_telegram(chat_id):
        return False
    try:
        url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        archivos = {'document': (nombre_archivo, bytes_data, mime_type)}
        data = {'chat_id': chat_id, 'caption': caption}
        httpx.post(url_tg, data=data, files=archivos, timeout=30.0)
        return True
    except Exception as e:
        print(f"[TELEGRAM FILE ERROR] {e}")
        return False

# ==========================================
# 5. LLAMADAS TELEFÓNICAS (BLAND.AI)
# ==========================================
def despachar_llamada_bland(telefono_limpio, destinatario, mensaje_objetivo, chat_id):
    if not BLAND_AI_API_KEY:
        return
    url = "https://api.bland.ai/v1/calls"
    headers = {"authorization": BLAND_AI_API_KEY, "Content-Type": "application/json"}
    prompt_mision = f"Eres Jarvis. Llamas a {destinatario}. Objetivo: {mensaje_objetivo}. Habla en español fluido."
    payload = {
        "phone_number": telefono_limpio,
        "task": prompt_mision,
        "voice": "mason",
        "language": "es",
        "temperature": 0.5,
        "wait_for_greeting": False,
        "reduce_latency": True,
        "webhook": f"{RENDER_APP_URL}/bland-webhook",
        "metadata": {"chat_id": str(chat_id), "destinatario": destinatario},
        "max_duration": 10
    }
    try:
        with httpx.Client(timeout=12.0) as client:
            client.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"[BLAND EXCEPTION] {e}")

def procesar_orden_llamada(telefono, destinatario, mensaje_objetivo, chat_id):
    tel_limpio = re.sub(r'[^\d+]', '', str(telefono).strip())
    if not tel_limpio.startswith("+"):
        tel_limpio = "+52" + tel_limpio if len(tel_limpio) == 10 else "+" + tel_limpio

    threading.Thread(target=despachar_llamada_bland, args=(tel_limpio, destinatario, mensaje_objetivo, chat_id), daemon=True).start()
    return f"Enlazando llamada a {destinatario} ({tel_limpio}). Te enviaré el reporte cuando termine."

def procesar_webhook_bland(data_bytes):
    try:
        data = json.loads(data_bytes.decode('utf-8'))
        metadata = data.get("metadata", {})
        chat_id = metadata.get("chat_id")
        destinatario = metadata.get("destinatario", "el contacto")
        resumen = data.get("summary", "Sin resumen.")
        duracion = data.get("call_length", 0)
        if _es_chat_telegram(chat_id):
            reporte = f"📞 *Llamada finalizada con {destinatario}*\n⏱️ *Duración:* {duracion:.1f} min\n📋 *Resumen:*\n{resumen}"
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            httpx.post(url, json={"chat_id": chat_id, "text": reporte, "parse_mode": "Markdown"}, timeout=10.0)

        transcripcion = data.get("concatenated_transcript") or data.get("transcript") or ""
        nota_llamada = (
            f"# Llamada finalizada con {destinatario}\n\n"
            f"- **Duración:** {duracion:.1f} min\n"
            f"- **Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"## Resumen\n\n{resumen}\n"
        )
        if transcripcion:
            nota_llamada += f"\n## Transcripción\n\n{transcripcion}\n"
        titulo_llamada = f"Llamada_{destinatario}_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
        save_to_obsidian(titulo_llamada, nota_llamada, tags=["llamada", "reporte", "transcripcion"])
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

# ==========================================
# 6. ENRUTAMIENTO RÁPIDO CON GROQ
# ==========================================
def procesar_con_ia(prompt_usuario, chat_id):
    ahora_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    system_prompt = f"""Eres Jarvis, asistente de alto rendimiento. Fecha actual: {ahora_str}.

Si el usuario solicita una investigación, ensayo, tarea, reporte, análisis financiero o de mercado:
- Acción obligatoria: "crear_doc"
- En "doc_titulo": Título técnico y claro (ej. "Analisis_NVIDIA_Valuacion")
- En "doc_tema": Tema exacto que solicitó

Acciones disponibles: "crear_doc" | "reproducir_musica" | "crear_sheet" | "llamada" | "buscar_web" | "crear_evento" | "ver_agenda" | "conversar"

Formato JSON obligatorio:
{{
  "accion": "<accion>",
  "parametros": {{
      "cancion_query": "<cancion>",
      "telefono": "<digitos>",
      "destinatario": "<persona>",
      "mensaje_llamada": "<mision>",
      "busqueda_query": "<palabras>",
      "evento_titulo": "<titulo>",
      "evento_inicio": "<YYYY-MM-DDTHH:MM:SS>",
      "evento_fin": "<YYYY-MM-DDTHH:MM:SS>",
      "doc_titulo": "<titulo>",
      "doc_tema": "<tema a redactar>"
  }},
  "respuesta_voz": "<Confirmación breve>"
}}
"""
    modelo = obtener_modelo_groq()
    try:
        completion = groq_client.chat.completions.create(
            model=modelo,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2000
        )
        data = json.loads(completion.choices[0].message.content)
        accion = data.get("accion", "conversar")
        params = data.get("parametros", {})
        resp_voz = data.get("respuesta_voz", "Entendido.")

        if accion == "crear_doc":
            titulo = params.get("doc_titulo") or "Analisis_Investigacion"
            tema = params.get("doc_tema") or prompt_usuario

            # Generar contenido profundo con Claude 3.5 Sonnet o modelo activo de Groq
            contenido_md = redactar_investigacion_profunda(titulo, tema)

            # 1. Nota Obsidian (.md) — Telegram solo si el origen es un chat real
            obsidian_bytes = formatear_para_obsidian(titulo, contenido_md)
            enviar_documento_telegram(chat_id, f"{titulo}.md", obsidian_bytes, 'text/markdown', f"🧠 *Nota lista para Obsidian:* `{titulo}.md`")

            # 2. Archivo HTML para visualización directa
            html_bytes = formatear_documento_html(titulo, contenido_md)
            enviar_documento_telegram(chat_id, f"{titulo}.html", html_bytes, 'text/html', f"📄 Documento HTML: `{titulo}.html`")

            threading.Thread(
                target=save_to_obsidian,
                args=(titulo, contenido_md, ["segundo_cerebro", "finanzas", "equity_research", "reporte"]),
                daemon=True,
            ).start()

            motor_usado = "Claude 3.5 Sonnet" if claude_client else "GPT-OSS / Groq"
            return f"{resp_voz} He completado el análisis con {motor_usado}. Te adjunto la nota para tu bóveda de Obsidian y el archivo HTML. También la sincronizo con tu repositorio."

        elif accion == "reproducir_musica":
            query = params.get("cancion_query") or prompt_usuario
            res = reproducir_en_spotify(query)
            if "no está configurado" in res.lower() and _es_chat_telegram(chat_id):
                res = buscar_y_enviar_audio(chat_id, query)
            return f"{resp_voz} {res}"

        elif accion == "llamada" and params.get("telefono"):
            return procesar_orden_llamada(params.get("telefono"), params.get("destinatario", "contacto"), params.get("mensaje_llamada", "Saludar"), chat_id)

        elif accion == "buscar_web" and params.get("busqueda_query"):
            return buscar_en_internet(params.get("busqueda_query"))

        elif accion == "crear_evento" and params.get("evento_titulo"):
            return crear_evento_calendario(params.get("evento_titulo"), params.get("evento_inicio"), params.get("evento_fin"))

        elif accion == "ver_agenda":
            return consultar_agenda_calendario()

        else:
            return resp_voz

    except Exception as e:
        return f"Error en procesamiento: {e}"

# ==========================================
# 7. API HTTP (FASTAPI) + SÍNTESIS DE VOZ
# ==========================================
KEYWORDS_LLAMADA = (
    "llama al", "llama a", "llámale", "llamale", "llámalo", "llamalo",
    "haz una llamada", "hacer una llamada", "hazle una llamada",
    "marca al", "marca a", "quiero que llames", "necesito que llames",
    "realiza una llamada", "realizar una llamada",
)
KEYWORDS_NOTA = (
    "nota", "notas", "resumen", "resúmenes", "resumenes",
    "análisis", "analisis", "analiza", "analizar",
    "reporte", "reporta", "investiga", "investigación", "investigacion",
    "ensayo", "guarda en obsidian", "sube a obsidian", "segundo cerebro",
)
KEYWORDS_MUSICA = (
    "reproduce", "reproducir", "pon la canción", "pon la cancion",
    "pon la pista", "pon música", "pon musica", "ponme",
    "quiero escuchar", "quiero oír", "quiero oir", "tócame", "tocame",
    "dale play", "play ",
)


def extraer_telefono(texto: str) -> Optional[str]:
    candidatos = re.findall(r"\+?\d[\d\s\-().]{7,18}\d", texto or "")
    for candidato in candidatos:
        if 10 <= len(re.sub(r"\D", "", candidato)) <= 15:
            return candidato
    return None


def parece_orden_llamada(prompt: str) -> bool:
    texto = (prompt or "").lower()
    if any(k in texto for k in KEYWORDS_LLAMADA):
        return True
    if extraer_telefono(prompt) and any(w in texto for w in ("llama", "llamada", "llame", "marcar", "marca")):
        return True
    return False


def parece_pedido_nota(prompt: str) -> bool:
    texto = (prompt or "").lower()
    return any(k in texto for k in KEYWORDS_NOTA)


def parece_orden_musica(prompt: str) -> bool:
    texto = (prompt or "").lower()
    return any(k in texto for k in KEYWORDS_MUSICA)


def extraer_query_cancion(prompt: str) -> str:
    texto = (prompt or "").strip()
    patrones = [
        r"(?i)(?:reproduce|reproducir|play)\s+(?:la\s+canci[oó]n\s+)?(.+)",
        r"(?i)pon(?:me)?\s+la\s+canci[oó]n\s+(.+)",
        r"(?i)pon(?:me)?\s+(?:la\s+pista\s+|m[uú]sica\s+(?:de\s+)?)(.+)",
        r"(?i)(?:quiero escuchar|quiero o[ií]r|t[oó]came|ponme)\s+(.+)",
        r"(?i)dale play\s+(?:a\s+)?(.+)",
    ]
    for patron in patrones:
        m = re.search(patron, texto)
        if m:
            return m.group(1).strip(" .¡!¿?")
    return texto


def extraer_contexto_llamada(prompt: str):
    destinatario = "contacto"
    mision = "Saludar"
    m_mision = re.search(
        r"(?:para|y dile que|dile que|decirle que|con el mensaje|objetivo[:\s])\s+(.+)$",
        prompt,
        re.IGNORECASE,
    )
    if m_mision:
        mision = m_mision.group(1).strip(" .")

    sin_tel = re.sub(r"\+?\d[\d\s\-().]{7,18}\d", " ", prompt)
    m_dest = re.search(
        r"(?:llama(?:r)?|llámale|llamale|llamada)\s+(?:a|al)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ][A-Za-zÁÉÍÓÚáéíóúñÑ\s]{1,40}?)(?:\s+(?:al|para|y|que)|$|,)",
        sin_tel,
        re.IGNORECASE,
    )
    if m_dest:
        nombre = m_dest.group(1).strip()
        if nombre.lower() not in {"el", "la", "al", "una", "un", "llamada", "numero", "número", "telefono", "teléfono"}:
            destinatario = nombre
    return destinatario, mision


def titulo_desde_prompt(prompt: str) -> str:
    limpio = re.sub(
        r"(?i)^(haz|genera|crea|redacta|escribe|dame|quiero|necesito)\s+(una?\s+)?"
        r"(nota|resumen|análisis|analisis|reporte|investigación|investigacion|ensayo)\s+"
        r"(sobre|de|del|acerca de)?\s*",
        "",
        prompt,
    ).strip(" .")
    return (limpio[:80] or "Nota_Jarvis")


def extraer_params_llamada_ia(prompt: str) -> dict:
    """Usa el enrutador Groq para completar teléfono/destinatario/misión si el regex no basta."""
    try:
        modelo = obtener_modelo_groq()
        completion = groq_client.chat.completions.create(
            model=modelo,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extrae parámetros de una orden de llamada telefónica. "
                        'Responde SOLO JSON: {"telefono":"","destinatario":"","mensaje_llamada":""}'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=300,
        )
        data = json.loads(completion.choices[0].message.content)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[ASK CALL PARSE ERROR] {e}")
        return {}


def procesar_prompt_api(prompt: str, chat_id=None) -> str:
    origen = chat_id if chat_id else "nexus"

    if parece_orden_llamada(prompt):
        telefono = extraer_telefono(prompt)
        destinatario, mision = extraer_contexto_llamada(prompt)
        if not telefono:
            extra = extraer_params_llamada_ia(prompt)
            telefono = extra.get("telefono") or telefono
            destinatario = extra.get("destinatario") or destinatario
            mision = extra.get("mensaje_llamada") or mision
        if telefono:
            return procesar_orden_llamada(telefono, destinatario, mision, origen)
        return "No pude identificar el número telefónico. Inclúyelo en el mensaje (ej. +52 662 123 4567)."

    if parece_orden_musica(prompt):
        return reproducir_en_spotify(extraer_query_cancion(prompt))

    if parece_pedido_nota(prompt):
        titulo = titulo_desde_prompt(prompt)
        contenido_md = redactar_investigacion_profunda(titulo, prompt)
        save_to_obsidian(
            titulo,
            contenido_md,
            tags=["nexus", "nota", "analisis", "segundo_cerebro"],
        )
        return f"Nota '{titulo}' generada y sincronizada con Obsidian.\n\n{contenido_md}"

    return procesar_con_ia(prompt, origen)


class AskRequest(BaseModel):
    prompt: Optional[str] = None
    message: Optional[str] = None
    chat_id: Optional[str] = None


api = FastAPI(title="Jarvis API")
# Starlette no permite allow_origins=["*"] junto con allow_credentials=True.
# NEXUS (localhost:3000) va explícito; el regex cubre el resto de orígenes HTTP(S).
api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/")
def health():
    return {"status": "ok", "service": "Jarvis 24/7 OK"}


@api.post("/ask")
def ask(body: AskRequest):
    prompt = (body.prompt or body.message or "").strip()
    if not prompt:
        return {"response": "Falta el campo 'prompt' o 'message'.", "status": "error"}
    try:
        respuesta = procesar_prompt_api(prompt, body.chat_id)
        return {"response": respuesta, "status": "ok"}
    except Exception as e:
        print(f"[ASK ERROR] {e}")
        return {"response": str(e), "status": "error"}


@api.post("/bland-webhook")
async def bland_webhook(request: Request):
    payload = await request.body()
    threading.Thread(target=procesar_webhook_bland, args=(payload,), daemon=True).start()
    return {"status": "ok"}


@api.get("/spotify/login")
def spotify_login():
    auth = get_spotify_oauth()
    if auth is None:
        return {"status": "error", "response": "Faltan SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET o SPOTIPY_REDIRECT_URI."}
    return RedirectResponse(auth.get_authorize_url())


@api.get("/spotify/callback")
def spotify_callback(code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return {"status": "error", "response": f"Spotify denegó el acceso: {error}"}
    if not code:
        return {"status": "error", "response": "Falta el código de autorización de Spotify."}
    auth = get_spotify_oauth()
    if auth is None:
        return {"status": "error", "response": "Spotify no está configurado."}
    try:
        auth.get_access_token(code, as_dict=True)
        reset_spotify_client()
        return {"status": "ok", "response": "Spotify autorizado. Ya puedes reproducir música desde NEXUS o /ask."}
    except Exception as e:
        print(f"[SPOTIFY AUTH ERROR] {e}")
        return {"status": "error", "response": str(e)}


async def generar_voz(texto: str, ruta_archivo: str):
    texto_audio = texto.split("🔗")[0].strip()
    if len(texto_audio) > 300:
        texto_audio = texto_audio[:280] + "..."
    comunicador = edge_tts.Communicate(texto_audio, "es-MX-JorgeNeural")
    await comunicador.save(ruta_archivo)


def iniciar_servidor():
    port = int(os.environ.get("PORT", 8080))
    config = uvicorn.Config(api, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()


threading.Thread(target=iniciar_servidor, daemon=True).start()

# ==========================================
# 8. BOT DE TELEGRAM
# ==========================================
async def responder_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    audio_in = f"in_{chat_id}.ogg"
    audio_out = f"out_{chat_id}.mp3"

    try:
        archivo_tg = await context.bot.get_file(update.message.voice.file_id)
        await archivo_tg.download_to_drive(audio_in)
        
        if not os.path.exists(audio_in) or os.path.getsize(audio_in) < 100:
            await update.message.reply_text("No se detectó audio en la grabación.")
            return

        await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")

        with open(audio_in, "rb") as f:
            transcripcion = groq_client.audio.transcriptions.create(
                file=(audio_in, f.read()),
                model="whisper-large-v3",
                language="es"
            ).text

        respuesta_texto = procesar_con_ia(transcripcion, chat_id)
        nota_voz = (
            f"# Transcripción de voz\n\n"
            f"## Usuario\n\n{transcripcion}\n\n"
            f"## Jarvis\n\n{respuesta_texto}\n"
        )
        titulo_voz = f"Transcripcion_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
        threading.Thread(
            target=save_to_obsidian,
            args=(titulo_voz, nota_voz, ["transcripcion", "voz"]),
            daemon=True,
        ).start()
        await generar_voz(respuesta_texto, audio_out)

        with open(audio_out, "rb") as voz:
            await update.message.reply_voice(
                voice=voz,
                caption=f"📝 _{transcripcion}_\n\n🤖 {respuesta_texto}",
                parse_mode="Markdown"
            )

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
    finally:
        for f in [audio_in, audio_out]:
            if os.path.exists(f):
                os.remove(f)

async def responder_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        respuesta = procesar_con_ia(update.message.text, chat_id)
        await update.message.reply_text(respuesta)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not GROQ_API_KEY:
        raise ValueError("Variables TELEGRAM_BOT_TOKEN o GROQ_API_KEY faltantes.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.VOICE, responder_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_texto))
    if GITHUB_TOKEN and GITHUB_REPO:
        print(f"Obsidian sync activo → {GITHUB_REPO}/{OBSIDIAN_FOLDER}")
    else:
        print("Obsidian sync inactivo: configura GITHUB_TOKEN y GITHUB_REPO en Render.")
    if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET and SPOTIPY_REDIRECT_URI:
        print("Spotify playback activo.")
    else:
        print("Spotify inactivo: configura SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET y SPOTIPY_REDIRECT_URI.")
    print("Jarvis conectado y listo.")
    app.run_polling(drop_pending_updates=True)