import os
import json
import re
import io
import threading
import httpx
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import urllib.request

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
import edge_tts

# Integración Claude (Anthropic)
try:
    import anthropic
except ImportError:
    anthropic = None

# Integraciones de Google Calendar y búsqueda web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tavily import TavilyClient

# Integración local de Spotify
try:
    from spotify_player import play_song
except ImportError:
    play_song = None

# ==========================================
# 1. CREDENCIALES Y VARIABLES DE ENTORNO
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
BLAND_AI_API_KEY = (os.environ.get("BLAND_AI_API_KEY") or os.environ.get("BLAND_API_KEY") or "").strip()
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
GOOGLE_CREDS_RAW = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
RENDER_APP_URL = "https://mi-jarvis.onrender.com"

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (anthropic and ANTHROPIC_API_KEY) else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ==========================================
# 2. MOTOR DE REDACCIÓN (CLAUDE / GROQ)
# ==========================================
def obtener_modelo_groq():
    """Detecta el modelo disponible en la cuenta de Groq."""
    candidatos_validos = [
        "openai/gpt-oss-120b",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "mixtral-8x7b-32768"
    ]
    if not groq_client:
        return "openai/gpt-oss-120b"
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
    """Usa Claude 3.5 Sonnet si la API key existe y tiene saldo; si no, usa Groq."""
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

    if groq_client:
        try:
            modelo = obtener_modelo_groq()
            res = groq_client.chat.completions.create(
                model=modelo,
                messages=[{"role": "user", "content": prompt_redaccion}],
                max_tokens=3000,
                temperature=0.2
            )
            return res.choices[0].message.content
        except Exception as e:
            return f"Error al generar reporte: {e}"

    return "No hay motor de IA configurado para redactar el análisis."

# ==========================================
# 3. GENERADOR PARA OBSIDIAN (.MD) Y HTML
# ==========================================
def formatear_para_obsidian(titulo: str, contenido_md: str) -> bytes:
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
            if chat_id:
                url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                payload = {
                    'chat_id': chat_id,
                    'text': f"🎸 *Pista multimedia lista:*\n🎶 [Escuchar {query_cancion} en YouTube]({url_video})",
                    'parse_mode': 'Markdown'
                }
                httpx.post(url_tg, json=payload, timeout=20.0)
            return f"Pista activada: {url_video}"
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
        print(f"[CALENDAR AUTH ERROR] {e}")
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

def enviar_documento_telegram(chat_id, nombre_archivo, bytes_data, mime_type, caption=""):
    try:
        url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        archivos = {'document': (nombre_archivo, bytes_data, mime_type)}
        data = {'chat_id': chat_id, 'caption': caption[:1000]}
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
        "metadata": {"chat_id": str(chat_id) if chat_id else "", "destinatario": destinatario},
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
        if not chat_id:
            return
        resumen = data.get("summary", "Sin resumen.")
        duracion = data.get("call_length", 0)
        reporte = f"📞 *Llamada finalizada con {destinatario}*\n⏱️ *Duración:* {duracion:.1f} min\n📋 *Resumen:*\n{resumen}"
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": reporte, "parse_mode": "Markdown"}, timeout=10.0)
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

# ==========================================
# 6. ENRUTAMIENTO RÁPIDO (LLM)
# ==========================================
def procesar_con_ia(prompt_usuario, chat_id=None, channel="telegram"):
    ahora_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    system_prompt = f"""Eres Jarvis, asistente de alto rendimiento. Fecha actual: {ahora_str}.

Si el usuario solicita una investigación, ensayo, tarea, reporte, análisis financiero o de mercado:
- Acción obligatoria: "crear_doc"
- En "doc_titulo": Título técnico y claro (ej. "Analisis_NVIDIA_Valuacion")
- En "doc_tema": Tema exacto que solicitó

Acciones disponibles: "crear_doc" | "reproducir_musica" | "llamada" | "buscar_web" | "crear_evento" | "ver_agenda" | "conversar"

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
    try:
        # 1. Obtener decisión estructurada
        data = {}
        if claude_client:
            try:
                res = claude_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt_usuario}]
                )
                txt = res.content[0].text
                match = re.search(r'\{.*\}', txt, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
            except Exception as e:
                print(f"[CLAUDE PARSE ERROR] {e}")

        if not data and groq_client:
            modelo = obtener_modelo_groq()
            completion = groq_client.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_usuario}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1500
            )
            data = json.loads(completion.choices[0].message.content)

        accion = data.get("accion", "conversar")
        params = data.get("parametros", {})
        resp_voz = data.get("respuesta_voz", "Entendido.")

        if accion == "crear_doc":
            titulo = params.get("doc_titulo") or "Analisis_Investigacion"
            tema = params.get("doc_tema") or prompt_usuario
            contenido_md = redactar_investigacion_profunda(titulo, tema)

            if channel == "telegram" and chat_id:
                obsidian_bytes = formatear_para_obsidian(titulo, contenido_md)
                enviar_documento_telegram(chat_id, f"{titulo}.md", obsidian_bytes, 'text/markdown', f"🧠 *Nota lista para Obsidian:* `{titulo}.md`")

                html_bytes = formatear_documento_html(titulo, contenido_md)
                enviar_documento_telegram(chat_id, f"{titulo}.html", html_bytes, 'text/html', f"📄 Documento HTML: `{titulo}.html`")

            motor_usado = "Claude 3.5 Sonnet" if claude_client else "Groq"
            resumen = f"{resp_voz} He completado el análisis con {motor_usado}."
            return {"texto": resumen, "markdown": contenido_md}

        elif accion == "reproducir_musica":
            query = params.get("cancion_query") or prompt_usuario
            if channel == "nexus" and play_song:
                res = play_song(query)
                return {"texto": res, "markdown": f"**Spotify:** {res}"}
            else:
                res = buscar_y_enviar_audio(chat_id, query)
                return {"texto": f"{resp_voz} {res}", "markdown": f"**Música:** {res}"}

        elif accion == "llamada" and params.get("telefono"):
            msg = procesar_orden_llamada(params.get("telefono"), params.get("destinatario", "contacto"), params.get("mensaje_llamada", "Saludar"), chat_id)
            return {"texto": msg, "markdown": msg}

        elif accion == "buscar_web" and params.get("busqueda_query"):
            res = buscar_en_internet(params.get("busqueda_query"))
            return {"texto": res, "markdown": f"### Resultados Web\n{res}"}

        elif accion == "crear_evento" and params.get("evento_titulo"):
            res = crear_evento_calendario(params.get("evento_titulo"), params.get("evento_inicio"), params.get("evento_fin"))
            return {"texto": res, "markdown": res}

        elif accion == "ver_agenda":
            res = consultar_agenda_calendario()
            return {"texto": res, "markdown": f"### Agenda Personal\n{res}"}

        else:
            return {"texto": resp_voz, "markdown": resp_voz}

    except Exception as e:
        error_msg = f"Error en procesamiento: {e}"
        return {"texto": error_msg, "markdown": error_msg}

# ==========================================
# 7. SÍNTESIS DE VOZ Y SERVIDOR HTTP (NEXUS + WEBHOOK)
# ==========================================
async def generar_voz(texto: str, ruta_archivo: str):
    texto_audio = texto.split("🔗")[0].strip()
    if len(texto_audio) > 300:
        texto_audio = texto_audio[:280] + "..."
    comunicador = edge_tts.Communicate(texto_audio, "es-MX-JorgeNeural")
    await comunicador.save(ruta_archivo)

class WebServerHandler(BaseHTTPRequestHandler):
    def set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(200)
        self.set_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.set_cors_headers()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Jarvis 24/7 OK")

    def do_HEAD(self):
        self.send_response(200)
        self.set_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path == "/bland-webhook":
            longitud = int(self.headers.get('Content-Length', 0))
            payload = self.rfile.read(longitud)
            self.send_response(200)
            self.set_cors_headers()
            self.end_headers()
            self.wfile.write(b"OK")
            threading.Thread(target=procesar_webhook_bland, args=(payload,), daemon=True).start()

        elif self.path == "/ask":
            try:
                longitud = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(longitud).decode('utf-8')
                data = json.loads(body)
                prompt = data.get("prompt", "")

                resultado = procesar_con_ia(prompt, channel="nexus")

                response_payload = {
                    "response": resultado["texto"],
                    "markdown": resultado["markdown"],
                    "source": "Jarvis Core"
                }

                self.send_response(200)
                self.set_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(response_payload).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.set_cors_headers()
            self.end_headers()

    def log_message(self, format, *args):
        return

def iniciar_servidor():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), WebServerHandler)
    print(f"Servidor HTTP activo en el puerto {port}")
    server.serve_forever()

threading.Thread(target=iniciar_servidor, daemon=True).start()

# ==========================================
# 8. BOT DE TELEGRAM
# ==========================================
TELEGRAM_MAX_CHARS = 4000


async def enviar_texto_telegram(bot, chat_id, texto_respuesta: str):
    """Envía el texto en bloques de 4000 caracteres para evitar 'Message is too long'."""
    mensaje = texto_respuesta or "Sin respuesta."
    for i in range(0, len(mensaje), TELEGRAM_MAX_CHARS):
        await bot.send_message(chat_id=chat_id, text=mensaje[i:i + TELEGRAM_MAX_CHARS])


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

        resultado = procesar_con_ia(transcripcion, chat_id=chat_id, channel="telegram")
        respuesta_texto = resultado["texto"]
        
        await generar_voz(respuesta_texto, audio_out)

        caption_formateado = f"📝 _{transcripcion}_\n\n🤖 {respuesta_texto}"
        
        # Evitar el error 'Message caption is too long' (máximo 1024 caracteres en Telegram)
        if len(caption_formateado) <= 1000:
            with open(audio_out, "rb") as voz:
                await update.message.reply_voice(
                    voice=voz,
                    caption=caption_formateado,
                    parse_mode="Markdown"
                )
        else:
            with open(audio_out, "rb") as voz:
                await update.message.reply_voice(
                    voice=voz,
                    caption=f"📝 _{transcripcion[:200]}..._",
                    parse_mode="Markdown"
                )
            await enviar_texto_telegram(context.bot, chat_id, f"🤖 {respuesta_texto}")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
    finally:
        for f in [audio_in, audio_out]:
            if os.path.exists(f):
                os.remove(f)

async def responder_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        resultado = procesar_con_ia(update.message.text, chat_id=chat_id, channel="telegram")
        await enviar_texto_telegram(context.bot, chat_id, resultado["texto"])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise ValueError("Variable TELEGRAM_BOT_TOKEN faltante.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.VOICE, responder_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_texto))
    print("Jarvis conectado y listo.")
    app.run_polling(drop_pending_updates=True)