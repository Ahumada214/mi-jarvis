import os
import re
import threading
import time
from datetime import datetime
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from spotify_player import play_song
except ImportError:
    def play_song(query: str) -> str:
        return "Módulo spotify_player no encontrado en el servidor."

try:
    from obsidian_sync import save_to_obsidian
except ImportError:
    def save_to_obsidian(title: str, content: str, tags=None) -> bool:
        return False


BLAND_KEY = os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY", "").strip()
BLAND_API_URL = "https://api.bland.ai/v1/calls"
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
RENDER_APP_URL = (
    os.getenv("RENDER_EXTERNAL_URL")
    or os.getenv("WEBHOOK_URL")
    or "https://mi-jarvis.onrender.com"
).rstrip("/")

app = FastAPI(title="Jarvis NEXUS Core", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    prompt: Optional[str] = None
    message: Optional[str] = None
    user_id: Optional[str] = "default_user"
    chat_id: Optional[str] = None


class AskResponse(BaseModel):
    response: str
    status: str = "ok"
    intent: Optional[str] = "chat"
    markdown: Optional[str] = None
    success: Optional[bool] = None
    call_id: Optional[str] = None


class GenerateNotesRequest(BaseModel):
    content: str
    title: str


class GenerateNotesResponse(BaseModel):
    success: bool
    markdown: str
    filename: str


MUSIC_TRIGGERS = (
    "reproduce",
    "reproducir",
    "pon la cancion",
    "pon la canción",
    "pon cancion",
    "pon canción",
    "pon musica",
    "pon música",
    "toca",
    "tocame",
    "tócame",
    "ponme",
    "play ",
)

CALL_TRIGGERS = (
    "llama a",
    "llama al",
    "marcar a",
    "marcar al",
    "marca al",
    "marca a",
    "llamada a",
    "haz una llamada",
)

REPORT_TRIGGERS = (
    "genera reporte",
    "crear reporte",
    "analiza y genera",
    "generar reporte",
    "crea reporte",
    "genera un reporte",
    "crea un reporte",
    "análisis",
    "analisis",
    "analiza",
    "generate notes",
    "genera notas",
    "generar notas",
)


def _contiene(texto: str, triggers: tuple) -> bool:
    lower = (texto or "").lower()
    return any(t in lower for t in triggers)


def clean_music_query(text: str) -> str:
    patterns = [
        r"^reproduce\s+(la\s+canci[oó]n\s+)?(de\s+)?",
        r"^reproducir\s+(la\s+canci[oó]n\s+)?(de\s+)?",
        r"^toca(?:me)?\s+(la\s+canci[oó]n\s+)?(de\s+)?",
        r"^pon(?:me)?\s+(la\s+canci[oó]n\s+|m[uú]sica\s+(?:de\s+)?)?",
        r"^play\s+",
    ]
    query = (text or "").strip()
    for pattern in patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE)
    return query.strip(" .¡!¿?")


def extraer_telefono_e164(texto: str) -> Optional[str]:
    match = re.search(r"(\+?\d[\d\s\-]{8,15}\d)", texto or "")
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw.startswith("+"):
        return "+52" + re.sub(r"\D", "", raw)
    return "+" + re.sub(r"\D", "", raw)


def extraer_titulo_reporte(prompt: str) -> str:
    limpio = re.sub(
        r"(?i)^(genera|generar|crea|crear|haz|redacta|analiza y genera)\s+(un\s+|el\s+|una\s+)?"
        r"(reporte|análisis|analisis|nota|notas)\s+(sobre|de|del|acerca de)?\s*",
        "",
        prompt or "",
    ).strip(" .")
    limpio = re.sub(r"(?i)^(analiza|analizar)\s+", "", limpio).strip(" .")
    return (limpio[:80] or "Reporte Jarvis")


def extraer_secciones_analisis(texto: str) -> tuple:
    limpio = (texto or "").strip()
    resumen_m = re.search(r"##\s*Resumen\s*\n+(.*?)(?=\n##\s|\Z)", limpio, re.IGNORECASE | re.DOTALL)
    contenido_m = re.search(r"##\s*Contenido\s*\n+(.*)\Z", limpio, re.IGNORECASE | re.DOTALL)
    if resumen_m:
        resumen = resumen_m.group(1).strip()
        contenido = contenido_m.group(1).strip() if contenido_m else re.sub(
            r"##\s*Resumen\s*\n+.*?(?=\n##\s|\Z)", "", limpio, flags=re.IGNORECASE | re.DOTALL
        ).strip()
        return resumen, contenido or limpio
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", limpio) if p.strip()]
    if not parrafos:
        return limpio, limpio
    return parrafos[0], limpio


def _prompt_analisis(tema: str) -> str:
    return (
        "Eres un analista e investigador sénior. Redacta un análisis completo, "
        f"técnico y detallado sobre: {tema}\n\n"
        "Estructura obligatoria en Markdown (sin frontmatter):\n"
        "## Resumen\n"
        "Resumen ejecutivo de 3 a 6 oraciones con la tesis principal.\n\n"
        "## Contenido\n"
        "Análisis profundo con subtítulos, contexto, datos, riesgos y conclusiones. "
        "Escribe en español, con formato Markdown limpio."
    )


def generar_markdown_reporte(title: str, content: str) -> str:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    titulo = (title or "Reporte Jarvis").strip() or "Reporte Jarvis"
    resumen, cuerpo = extraer_secciones_analisis(content)
    titulo_yaml = titulo.replace('"', '\\"')
    return (
        "---\n"
        f'title: "{titulo_yaml}"\n'
        f'date: "{fecha}"\n'
        f'source: "Jarvis Backend"\n'
        "tags:\n"
        "  - reporte\n"
        "  - jarvis\n"
        "---\n\n"
        f"# {titulo}\n\n"
        f"**Fecha:** {fecha}\n\n"
        "## Resumen\n\n"
        f"{resumen}\n\n"
        "## Contenido\n\n"
        f"{cuerpo}\n"
    )


def nombre_archivo_nota(title: str) -> str:
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "nota")
    limpio = re.sub(r"\s+", "_", limpio.strip()) or "nota"
    return f"{limpio[:80]}.md"


def _texto_gemini(res) -> Optional[str]:
    try:
        data = res.json()
    except Exception:
        return None
    if "candidates" in data and data["candidates"]:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    return None


def call_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "Error: GEMINI_API_KEY no configurada en las variables de entorno."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
    url_v1 = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        texto = _texto_gemini(res)
        if texto:
            return texto
        es_404 = res.status_code == 404
        try:
            data = res.json()
            codigo = (data.get("error") or {}).get("code")
            es_404 = es_404 or codigo == 404 or codigo == "404"
        except Exception:
            data = {}
        if es_404 or not texto:
            print(f"[GEMINI] Fallback a v1 tras {res.status_code}: {(res.text or '')[:300]}")
            res_v1 = requests.post(url_v1, headers=headers, json=payload, timeout=30)
            texto_v1 = _texto_gemini(res_v1)
            if texto_v1:
                return texto_v1
            try:
                data_v1 = res_v1.json()
            except Exception:
                return f"Respuesta inesperada de Gemini: {res_v1.text}"
            if "error" in data_v1:
                err = data_v1["error"]
                return f"Error API Gemini ({err.get('code')}): {err.get('message')}"
            return f"Respuesta inesperada de Gemini: {res_v1.text}"
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            return f"Error API Gemini ({err.get('code')}): {err.get('message')}"
        return f"Respuesta inesperada de Gemini: {res.text}"
    except Exception as e:
        try:
            res_v1 = requests.post(url_v1, headers=headers, json=payload, timeout=30)
            texto_v1 = _texto_gemini(res_v1)
            if texto_v1:
                return texto_v1
        except Exception as e2:
            return f"Error de conexión con Gemini: {str(e2)}"
        return f"Error de conexión con Gemini: {str(e)}"


def sincronizar_obsidian(title: str, markdown_text: str, tags=None) -> bool:
    """Sube el Markdown generado por Gemini al repo de Obsidian (GitHub)."""
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    repo = (os.getenv("GITHUB_REPO") or "").strip()
    if not token or not repo:
        print("[OBSIDIAN] Faltan GITHUB_TOKEN o GITHUB_REPO. No se hace commit.")
        return False
    try:
        ok = save_to_obsidian(title, markdown_text, tags=tags or ["reporte", "nexus", "gemini"])
        if ok:
            print(f"[OBSIDIAN] Commit listo: {title}")
        else:
            print(f"[OBSIDIAN] save_to_obsidian devolvió False para '{title}'")
        return ok
    except Exception as e:
        print(f"[OBSIDIAN ERROR] {e}")
        return False


def trigger_bland_call(phone_number: str, message_task: str):
    """Dispara una llamada Bland AI. Retorna (mensaje, call_id)."""
    api_key = os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY", "").strip()
    if not api_key:
        return "Falta BLAND_API_KEY o BLAND_AI_API_KEY en las variables de entorno.", None
    if not phone_number:
        return "No pude identificar un número telefónico válido.", None
    if not phone_number.startswith("+"):
        phone_number = "+52" + re.sub(r"\D", "", phone_number)

    try:
        resp = requests.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key},
            json={
                "phone_number": phone_number,
                "task": message_task,
                "voice": "maya",
                "language": "es",
            },
            timeout=20,
        )
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code != 200:
            if isinstance(data, dict):
                for key in ("errors", "message", "error", "msg"):
                    if data.get(key):
                        valor = data[key]
                        if isinstance(valor, list):
                            return " ".join(str(item) for item in valor), None
                        return str(valor), None
                return str(data), None
            return (resp.text or f"HTTP {resp.status_code}").strip(), None
        call_id = data.get("call_id") if isinstance(data, dict) else None
        confirmacion = f"Llamada iniciada hacia {phone_number}."
        if call_id:
            confirmacion = f"{confirmacion} call_id: {call_id}"
        return confirmacion, call_id
    except Exception as e:
        print(f"[BLAND ERROR] {e}")
        return f"Error al contactar Bland AI: {e}", None


def procesar_comando(prompt: str) -> dict:
    """Enrutador único para /ask y el bot de Telegram."""
    texto = (prompt or "").strip()
    if not texto:
        return {"response": "Falta el prompt.", "status": "error", "intent": "chat"}

    if _contiene(texto, MUSIC_TRIGGERS):
        cancion = clean_music_query(texto)
        if not cancion:
            return {
                "response": "Por favor especifica el nombre de la pista que deseas reproducir.",
                "status": "ok",
                "intent": "music",
            }
        return {"response": play_song(cancion), "status": "ok", "intent": "music"}

    if _contiene(texto, CALL_TRIGGERS):
        numero = extraer_telefono_e164(texto)
        if not numero:
            return {
                "response": "No pude identificar el número telefónico. Inclúyelo (ej. +521234567890).",
                "status": "ok",
                "intent": "call",
            }
        mensaje = re.sub(r"(?i)(haz una llamada|llama a|llama al|marcar a|marcar al|marca al|marca a|llamada a)", "", texto)
        mensaje = re.sub(r"\+?\d[\d\s\-]{8,15}\d", "", mensaje).strip() or texto
        resultado, call_id = trigger_bland_call(numero, mensaje)
        return {"response": resultado, "status": "ok", "intent": "call", "call_id": call_id}

    if _contiene(texto, REPORT_TRIGGERS):
        titulo = extraer_titulo_reporte(texto)
        analisis = call_gemini(_prompt_analisis(texto))
        if analisis.startswith("Error"):
            return {"response": analisis, "status": "error", "intent": "report", "success": False}
        markdown_text = generar_markdown_reporte(titulo, analisis)
        sincronizar_obsidian(titulo, markdown_text, tags=["reporte", "nexus", "gemini"])
        return {
            "response": markdown_text,
            "status": "ok",
            "intent": "report",
            "markdown": markdown_text,
            "success": True,
        }

    respuesta = call_gemini(texto)
    if respuesta.startswith("Error"):
        return {"response": respuesta, "status": "error", "intent": "chat"}
    return {"response": respuesta, "status": "ok", "intent": "chat"}


def _enviar_telegram(chat_id, texto: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": (texto or "Sin respuesta.")[:4000]},
            timeout=15,
        )
    except Exception as e:
        print(f"[TELEGRAM SEND] {e}")


def _configurar_webhook_telegram() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("[TELEGRAM] TELEGRAM_BOT_TOKEN no configurado. Bot inactivo.")
        return
    webhook_url = f"{RENDER_APP_URL}/telegram/webhook"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": webhook_url},
            timeout=10,
        )
        print(f"[TELEGRAM] Webhook → {webhook_url} ({resp.status_code})")
    except Exception as e:
        print(f"[TELEGRAM] No se pudo registrar el webhook: {e}")


def _telegram_poll_loop() -> None:
    """Polling de respaldo. Nunca deja subir una excepción al event loop de FastAPI."""
    offset = 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    print("[TELEGRAM] Polling en segundo plano.")
    while True:
        try:
            resp = requests.get(url, params={"offset": offset, "timeout": 25}, timeout=35)
            data = resp.json() if resp.status_code == 200 else {}
            for update in data.get("result") or []:
                offset = int(update.get("update_id", offset)) + 1
                message = update.get("message") or update.get("edited_message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                text = (message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                try:
                    resultado = procesar_comando(text)
                    _enviar_telegram(chat_id, resultado.get("response") or "Sin respuesta.")
                except Exception as inner:
                    print(f"[TELEGRAM POLL CMD] {inner}")
                    _enviar_telegram(chat_id, f"Error al procesar el comando: {inner}")
        except Exception as e:
            print(f"[TELEGRAM POLL] {e}")
            time.sleep(3)


@app.on_event("startup")
def iniciar_telegram():
    if not TELEGRAM_BOT_TOKEN:
        print("[TELEGRAM] TELEGRAM_BOT_TOKEN no configurado. Bot inactivo.")
        return
    if (os.getenv("TELEGRAM_USE_POLLING") or "").strip() in {"1", "true", "True"}:
        hilo = threading.Thread(target=_telegram_poll_loop, name="telegram-poll", daemon=True)
        hilo.start()
        return
    _configurar_webhook_telegram()


@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "online", "system": "Jarvis NEXUS Core"}


@app.post("/generate-notes", response_model=GenerateNotesResponse)
def generate_notes(request: GenerateNotesRequest):
    tema = f"{request.title}. {request.content}".strip()
    analisis = call_gemini(_prompt_analisis(tema))
    if analisis.startswith("Error"):
        raise HTTPException(status_code=502, detail=analisis)
    markdown_text = generar_markdown_reporte(request.title, analisis)
    filename = nombre_archivo_nota(request.title)
    sincronizar_obsidian(request.title, markdown_text, tags=["reporte", "nexus", "gemini"])
    return GenerateNotesResponse(success=True, markdown=markdown_text, filename=filename)


@app.post("/ask", response_model=AskResponse)
async def ask_jarvis(request: AskRequest):
    prompt = (request.prompt or request.message or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Falta el campo 'prompt' o 'message'.")
    return AskResponse(**procesar_comando(prompt))


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id and text:
            try:
                resultado = procesar_comando(text)
                _enviar_telegram(chat_id, resultado.get("response") or "Sin respuesta.")
            except Exception as inner:
                print(f"[TELEGRAM WEBHOOK CMD] {inner}")
                _enviar_telegram(chat_id, f"Error al procesar el comando: {inner}")
    except Exception as e:
        print(f"[TELEGRAM WEBHOOK] {e}")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
