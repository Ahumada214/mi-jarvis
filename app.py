import os
import re
from datetime import datetime
from typing import Optional

import httpx
import requests
from fastapi import FastAPI, HTTPException
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

try:
    from bland_calls import extraer_destinatario, extraer_telefono, extraer_tarea_llamada, normalizar_telefono
except ImportError:
    def extraer_telefono(texto: str):
        candidatos = re.findall(r"\+?\d[\d\s\-().]{7,18}\d", texto or "")
        for candidato in candidatos:
            if 10 <= len(re.sub(r"\D", "", candidato)) <= 15:
                return candidato
        return None

    def extraer_destinatario(prompt: str) -> str:
        return "el contacto"

    def extraer_tarea_llamada(prompt: str, destinatario: str = "el contacto") -> str:
        return prompt

    def normalizar_telefono(telefono: str, codigo_pais: str = "+52") -> str:
        raw = (telefono or "").strip()
        if not raw:
            return ""
        tiene_plus = raw.startswith("+")
        digitos = re.sub(r"\D", "", raw)
        if not digitos:
            return ""
        if tiene_plus:
            return f"+{digitos}"
        if digitos.startswith("52") and len(digitos) >= 12:
            return f"+{digitos}"
        if len(digitos) == 10:
            return f"{codigo_pais}{digitos}"
        return f"+{digitos}"


BLAND_API_KEY = os.getenv("BLAND_API_KEY")
BLAND_API_URL = "https://api.bland.ai/v1/calls"

app = FastAPI(title="Jarvis NEXUS Core", version="1.0.0")

# Starlette no permite allow_origins=["*"] con allow_credentials=True.
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
    "pon la canción",
    "pon la cancion",
    "pon canción",
    "pon cancion",
    "pon música",
    "pon musica",
    "ponme",
    "play ",
    "escuchar ",
    "quiero escuchar",
    "dale play",
)

REPORT_TRIGGERS = (
    "genera reporte",
    "generar reporte",
    "crea reporte",
    "crear reporte",
    "genera un reporte",
    "crea un reporte",
    "haz un reporte",
    "genera el reporte",
    "crea el reporte",
)


def clean_music_query(text: str) -> str:
    """Limpia el comando del usuario para extraer solo el nombre de la canción o artista."""
    patterns = [
        r"^reproduce\s+(la\s+canción\s+)?(de\s+)?",
        r"^reproducir\s+(la\s+canción\s+)?(de\s+)?",
        r"^pon(?:me)?\s+(la\s+canción\s+)?(de\s+)?",
        r"^escuchar\s+",
        r"^quiero escuchar\s+",
        r"^dale play\s+(a\s+)?",
        r"^play\s+",
    ]
    query = (text or "").strip()
    for pattern in patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE)
    return query.strip(" .¡!¿?")


def es_comando_musica(text: str) -> bool:
    lower = (text or "").lower()
    return any(trigger in lower for trigger in MUSIC_TRIGGERS)


def es_comando_llamada(text: str) -> bool:
    lower = (text or "").lower()
    return "llama a" in lower or "marcar a" in lower or "marca a" in lower or "llama al" in lower or "marcar al" in lower


def es_comando_reporte(text: str) -> bool:
    lower = (text or "").lower()
    return any(trigger in lower for trigger in REPORT_TRIGGERS)


def es_comando_nota(text: str) -> bool:
    lower = (text or "").lower()
    return (
        lower.startswith("nota:")
        or lower.startswith("guardar nota")
        or "guarda en obsidian" in lower
        or "sube a obsidian" in lower
    )


def extraer_titulo_reporte(prompt: str) -> str:
    limpio = re.sub(
        r"(?i)^(genera|generar|crea|crear|haz|redacta)\s+(un\s+|el\s+)?reporte\s+"
        r"(sobre|de|del|acerca de)?\s*",
        "",
        prompt or "",
    ).strip(" .")
    return (limpio[:80] or "Reporte Jarvis")


def generar_markdown_reporte(title: str, content: str) -> str:
    """Markdown limpio con metadatos para descarga en el frontend."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    titulo = (title or "Reporte Jarvis").strip() or "Reporte Jarvis"
    cuerpo = (content or "").strip() or "Sin contenido."
    resumen = re.sub(r"\s+", " ", cuerpo).strip()[:280]
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


def extraer_telefono_e164(texto: str) -> Optional[str]:
    """Extrae un teléfono y lo normaliza a E.164, anteponiendo +52 si falta el código."""
    match = re.search(r"(\+?\d[\d\s\-().]{7,18}\d)", texto or "")
    if not match:
        return None
    raw = match.group(1).strip()
    digitos = re.sub(r"\D", "", raw)
    if not digitos:
        return None
    if raw.startswith("+"):
        return f"+{digitos}"
    if digitos.startswith("52") and len(digitos) >= 12:
        return f"+{digitos}"
    if len(digitos) == 10:
        return f"+52{digitos}"
    return f"+{digitos}"


def nombre_archivo_nota(title: str) -> str:
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "nota")
    limpio = re.sub(r"\s+", "_", limpio.strip()) or "nota"
    return f"{limpio[:80]}.md"


def trigger_bland_call(phone_number: str, message_task: str) -> str:
    """Dispara una llamada Bland AI y retorna el estado o el error de la API."""
    api_key = os.getenv("BLAND_API_KEY") or ""
    if not api_key:
        return "Falta BLAND_API_KEY en las variables de entorno."
    if not phone_number:
        return "No pude identificar un número telefónico válido."

    try:
        resp = requests.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key, "Content-Type": "application/json"},
            json={"phone_number": phone_number, "task": message_task},
            timeout=20,
        )
        if resp.status_code != 200:
            try:
                data = resp.json()
            except Exception:
                return (resp.text or f"HTTP {resp.status_code}").strip()
            if isinstance(data, dict):
                if data.get("errors"):
                    errors = data["errors"]
                    if isinstance(errors, list):
                        return " ".join(str(item) for item in errors)
                    return str(errors)
                for key in ("message", "error", "msg"):
                    if data.get(key):
                        return str(data[key])
                return str(data)
            return str(data)
        return f"Llamada iniciada hacia {phone_number}."
    except Exception as e:
        print(f"[BLAND ERROR] {e}")
        return f"Error al contactar Bland AI: {e}"


def make_call(phone_number: str, task: str) -> str:
    """Inicia una llamada en Bland AI y devuelve el estado o el error exacto."""
    api_key = os.getenv("BLAND_API_KEY") or ""
    if not api_key:
        return "Falta BLAND_API_KEY en las variables de entorno."

    phone_number = normalizar_telefono(phone_number)
    if not phone_number:
        return "No pude identificar un número telefónico válido."

    headers = {"authorization": api_key}
    payload = {"phone_number": phone_number, "task": task}

    try:
        resp = httpx.post(BLAND_API_URL, headers=headers, json=payload, timeout=20.0)
        if resp.status_code != 200:
            try:
                data = resp.json()
            except Exception:
                return (resp.text or f"HTTP {resp.status_code}").strip()
            if isinstance(data, dict):
                if data.get("errors"):
                    errors = data["errors"]
                    if isinstance(errors, list):
                        return " ".join(str(item) for item in errors)
                    return str(errors)
                for key in ("message", "error", "msg"):
                    if data.get(key):
                        return str(data[key])
                return str(data)
            return str(data)
        return f"Llamada iniciada hacia {phone_number}."
    except Exception as e:
        print(f"[BLAND ERROR] {e}")
        return f"Error al contactar Bland AI: {e}"


@app.get("/")
def health_check():
    return {
        "status": "online",
        "system": "Jarvis Core",
        "spotify_auth_ready": bool(os.getenv("SPOTIFY_REFRESH_TOKEN")),
        "bland_ready": bool(os.getenv("BLAND_API_KEY")),
    }


@app.post("/generate-notes", response_model=GenerateNotesResponse)
def generate_notes(request: GenerateNotesRequest):
    markdown_text = generar_markdown_reporte(request.title, request.content)
    filename = nombre_archivo_nota(request.title)
    try:
        save_to_obsidian(request.title, request.content, tags=["reporte", "nexus"])
    except Exception as e:
        print(f"[OBSIDIAN] No se pudo sincronizar la nota: {e}")
    return GenerateNotesResponse(success=True, markdown=markdown_text, filename=filename)


@app.post("/ask", response_model=AskResponse)
async def ask_jarvis(request: AskRequest):
    prompt = (request.prompt or request.message or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Falta el campo 'prompt' o 'message'.")

    lower_prompt = prompt.lower()
    if any(k in lower_prompt for k in ("llama a", "marcar a", "marca al")):
        phone_number = extraer_telefono_e164(prompt)
        if not phone_number:
            return AskResponse(
                response="No pude identificar el número telefónico. Inclúyelo en formato internacional (ej. +521234567890).",
                status="ok",
                intent="call",
            )
        message_task = re.sub(r"(?i)(llama a|marcar a|marca al)", "", prompt)
        message_task = re.sub(r"\+?\d[\d\s\-().]{7,18}\d", "", message_task).strip() or prompt
        resultado = trigger_bland_call(phone_number, message_task)
        return AskResponse(response=resultado, status="ok", intent="call")

    if es_comando_llamada(prompt):
        telefono = extraer_telefono(prompt)
        if not telefono:
            return AskResponse(
                response="No pude identificar el número telefónico. Inclúyelo con lada (ej. +521234567890 o 6621234567).",
                status="ok",
                intent="call",
            )
        phone_number = normalizar_telefono(telefono)
        destinatario = extraer_destinatario(prompt)
        task = extraer_tarea_llamada(prompt, destinatario)
        resultado = make_call(phone_number, task)
        return AskResponse(response=resultado, status="ok", intent="call")

    if es_comando_reporte(prompt):
        titulo = extraer_titulo_reporte(prompt)
        markdown_text = generar_markdown_reporte(titulo, prompt)
        try:
            save_to_obsidian(titulo, prompt, tags=["reporte", "nexus"])
        except Exception as e:
            print(f"[OBSIDIAN] No se pudo sincronizar el reporte: {e}")
        return AskResponse(
            response=markdown_text,
            status="ok",
            intent="report",
            markdown=markdown_text,
            success=True,
        )

    if es_comando_musica(prompt):
        song_query = clean_music_query(prompt)
        if not song_query:
            return AskResponse(
                response="Por favor especifica el nombre de la pista que deseas reproducir.",
                status="ok",
                intent="music",
            )
        playback_result = play_song(song_query)
        return AskResponse(response=playback_result, status="ok", intent="music")

    if es_comando_nota(prompt):
        note_content = prompt.split(":", 1)[-1].strip() or prompt
        markdown_text = generar_markdown_reporte("Nota Rápida", note_content)
        saved = save_to_obsidian("Nota Rápida", note_content, tags=["nexus", "nota"])
        msg = markdown_text if saved else (
            markdown_text + "\n\n> No pude sincronizar con Obsidian. Revisa GITHUB_TOKEN y GITHUB_REPO."
        )
        return AskResponse(
            response=msg,
            status="ok",
            intent="obsidian",
            markdown=markdown_text,
            success=True,
        )

    return AskResponse(
        response=(
            f"Comando recibido en el Core: '{prompt}'. "
            "Spotify, Obsidian y módulos de telemetría sincronizados."
        ),
        status="ok",
        intent="chat",
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
