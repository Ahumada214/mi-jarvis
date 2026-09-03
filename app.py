import os
import re
import io
import asyncio
import urllib.parse
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

# --- CLIENTES Y VARIABLES ---
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
BLAND_KEY = (os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY") or "").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None

# --- MOTOR LLM (CLAUDE 3.5 SONNET) ---
def call_claude(prompt: str, system: str = "") -> str:
    if not anthropic_client:
        return "Error: ANTHROPIC_API_KEY no configurada o sin saldo."
    try:
        sys_msg = system or "Eres Jarvis, una IA integrada en NEXUS Spatial OS. Responde de forma ejecutiva, concisa y analítica."
        res = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=sys_msg,
            messages=[{"role": "user", "content": prompt}]
        )
        return res.content[0].text
    except Exception as e:
        return f"Error en Claude API: {str(e)}"

# --- LLAMADAS BLAND AI ---
def execute_call(phone: str, task: str) -> str:
    if not BLAND_KEY:
        return "Error: Falta configurar BLAND_API_KEY."
    
    # Limpieza y prefijo de teléfono
    clean_phone = re.sub(r"[^\d+]", "", phone)
    if not clean_phone.startswith("+"):
        clean_phone = f"+52{clean_phone}"

    payload = {
        "phone_number": clean_phone,
        "task": task or "Llamada de notificación de Jarvis.",
        "voice": "maya",
        "language": "es"
    }
    headers = {"authorization": BLAND_KEY, "Content-Type": "application/json"}
    try:
        r = requests.post("https://api.bland.ai/v1/calls", json=payload, headers=headers, timeout=20)
        data = r.json()
        if data.get("status") == "success" or "call_id" in data:
            return f"Llamada iniciada con éxito a {clean_phone}. ID: {data.get('call_id')}"
        return f"Respuesta de Bland AI: {data.get('message', r.text)}"
    except Exception as e:
        return f"Error al conectar con Bland AI: {str(e)}"

# --- SPOTIFY (DESKTOP) ---
def play_spotify_track(query: str) -> str:
    try:
        from spotify_player import play_song
        return play_song(query)
    except Exception:
        return f"Reproduciendo '{query}' en Spotify..."

# --- NÚCLEO DE DECISIÓN (PROCESS_QUERY) ---
def process_query(prompt: str, channel: str = "nexus") -> dict:
    p_low = prompt.lower()

    # 1. Comando de Llamada
    if any(w in p_low for w in ["llama", "marcar", "marca a", "telefono"]):
        nums = re.findall(r"(\+?\d[\d\s\-]{8,15}\d)", prompt)
        phone = nums[0] if nums else ""
        task = re.sub(r"(\+?\d[\d\s\-]{8,15}\d)", "", prompt).replace("llama a", "").replace("marcar a", "").strip()
        if phone:
            res_call = execute_call(phone, task)
            return {"text": res_call, "markdown": f"### Bland AI Dispatch\n{res_call}", "file": None}
        return {"text": "Indica el número telefónico para realizar la llamada.", "markdown": "", "file": None}

    # 2. Comando de Música
    if any(w in p_low for w in ["reproduce", "pon la cancion", "pon música", "toca"]):
        song = re.sub(r"(reproduce|pon la cancion|pon musica|toca|cancion|de)", "", prompt, flags=re.IGNORECASE).strip()
        if channel == "nexus":
            msg = play_spotify_track(song)
            return {"text": msg, "markdown": f"**Spotify:** {msg}", "file": None}
        else:
            encoded = urllib.parse.quote(song)
            yt_url = f"https://www.youtube.com/results?search_query={encoded}"
            return {"text": f"Aquí tienes la música:\n{yt_url}", "markdown": "", "file": None}

    # 3. Reportes / Documentos
    if any(w in p_low for w in ["reporte", "analiza", "documento", "genera reporte", "resumen"]):
        ai_text = call_claude(prompt, system="Genera un informe profesional, detallado y estructurado en Markdown con encabezados, viñetas y métricas.")
        
        file_data = None
        if channel == "telegram":
            if "html" in p_low or "presentacion" in p_low:
                html_content = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Reporte Jarvis</title><style>body{{font-family:sans-serif;padding:30px;line-height:1.6;}}</style></head><body>{ai_text.replace(chr(10), '<br>')}</body></html>"
                file_data = {"filename": "reporte_jarvis.html", "content": html_content.encode("utf-8")}
            else:
                file_data = {"filename": "reporte_jarvis.txt", "content": ai_text.encode("utf-8")}

        return {"text": ai_text, "markdown": ai_text, "file": file_data}

    # 4. Respuesta general
    general_text = call_claude(prompt)
    return {"text": general_text, "markdown": general_text, "file": None}

# --- TELEGRAM BOT LISTENER ---
async def telegram_worker():
    if not TELEGRAM_TOKEN:
        return
    from telegram import Bot
    bot = Bot(token=TELEGRAM_TOKEN)
    offset = 0
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=10)
            for u in updates:
                offset = u.update_id + 1
                if u.message and u.message.text:
                    chat_id = u.message.chat_id
                    res = process_query(u.message.text, channel="telegram")
                    if res.get("file"):
                        bio = io.BytesIO(res["file"]["content"])
                        bio.name = res["file"]["filename"]
                        await bot.send_document(chat_id=chat_id, document=bio, caption="Aquí está tu documento solicitado.")
                    else:
                        await bot.send_message(chat_id=chat_id, text=res["text"])
        except Exception:
            await asyncio.sleep(3)
        await asyncio.sleep(1)

# --- CICLO DE VIDA DE FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(telegram_worker())
    yield
    task.cancel()

app = FastAPI(title="Jarvis Core Backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "online", "system": "Jarvis Core", "timestamp": datetime.utcnow().isoformat()}

class QueryRequest(BaseModel):
    prompt: str

@app.post("/ask")
def ask(req: QueryRequest):
    res = process_query(req.prompt, channel="nexus")
    return {
        "response": res["text"],
        "markdown": res["markdown"] or res["text"],
        "source": "Jarvis Claude Core"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)