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


BLAND_API_KEY = os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY", "").strip()
BLAND_API_URL = "https://api.bland.ai/v1/calls"
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
JARVIS_SYSTEM_PROMPT = (
    "Eres Jarvis, una IA integrada en NEXUS Spatial OS. "
    "Responde de forma concisa y analítica."
)

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
    "análisis",
    "analisis",
    "analiza",
    "analizar",
    "genera notas",
    "generar notas",
    "genera una nota",
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


CALL_TRIGGERS = ("haz una llamada", "llama a", "llama al", "marcar a", "marcar al", "marca al", "marca a")


def es_comando_llamada(text: str) -> bool:
    lower = (text or "").lower()
    return any(trigger in lower for trigger in CALL_TRIGGERS)


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


def _llamar_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY no está configurada.")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.5,
        },
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text or f"HTTP {resp.status_code}")
    texto = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    if not texto:
        raise RuntimeError("Groq devolvió una respuesta vacía.")
    print("[LLM] Respuesta generada con Groq (llama3-8b-8192)")
    return texto


def _llamar_anthropic(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY no está configurada.")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text or f"HTTP {resp.status_code}")
    partes = resp.json().get("content") or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict)).strip()
    if not texto:
        raise RuntimeError("Anthropic devolvió una respuesta vacía.")
    print("[LLM] Respuesta generada con Anthropic")
    return texto


def llamar_llm(prompt: str) -> str:
    """Usa Groq (GROQ_API_KEY) o Anthropic (ANTHROPIC_API_KEY), las keys de Render."""
    errores = []
    if GROQ_API_KEY:
        try:
            return _llamar_groq(prompt)
        except Exception as e:
            errores.append(f"Groq: {e}")
            print(f"[LLM GROQ] {e}")
    if ANTHROPIC_API_KEY:
        try:
            return _llamar_anthropic(prompt)
        except Exception as e:
            errores.append(f"Anthropic: {e}")
            print(f"[LLM ANTHROPIC] {e}")
    detalle = " | ".join(errores) if errores else "Faltan GROQ_API_KEY y ANTHROPIC_API_KEY."
    raise RuntimeError(f"No se pudo generar texto con el LLM. {detalle}")


def generar_analisis_llm(tema: str) -> str:
    """Genera un análisis enriquecido con Groq o Anthropic. Nunca devuelve el prompt crudo."""
    return llamar_llm(_prompt_analisis(tema))


def responder_chat_llm(prompt: str) -> str:
    """Respuesta de conversación con el mismo LLM de Render."""
    return llamar_llm(prompt)



def extraer_secciones_analisis(texto: str) -> tuple:
    """Separa ## Resumen y ## Contenido del texto del LLM."""
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


def extraer_titulo_reporte(prompt: str) -> str:
    limpio = re.sub(
        r"(?i)^(genera|generar|crea|crear|haz|redacta)\s+(un\s+|el\s+|una\s+)?"
        r"(reporte|análisis|analisis|nota|notas)\s+"
        r"(sobre|de|del|acerca de)?\s*",
        "",
        prompt or "",
    ).strip(" .")
    limpio = re.sub(r"(?i)^(analiza|analizar)\s+", "", limpio).strip(" .")
    return (limpio[:80] or "Reporte Jarvis")


def generar_markdown_reporte(title: str, content: str) -> str:
    """Arma el .md con el texto enriquecido del LLM en Resumen y Contenido."""
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


def construir_reporte_llm(title: str, tema: str) -> str:
    """Pide el análisis al LLM y lo formatea. No usa el prompt crudo como cuerpo."""
    analisis = generar_analisis_llm(tema)
    return generar_markdown_reporte(title, analisis)


def extraer_telefono_e164(texto: str) -> Optional[str]:
    """Extrae un teléfono con el regex E.164 pedido y antepone +52 si falta '+'."""
    match = re.search(r"(\+?\d[\d\s\-]{8,15}\d)", texto or "")
    if not match:
        return None
    raw = match.group(1).strip()
    if raw.startswith("+"):
        return "+" + re.sub(r"\D", "", raw)
    return "+52" + re.sub(r"\D", "", raw)


def nombre_archivo_nota(title: str) -> str:
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "nota")
    limpio = re.sub(r"\s+", "_", limpio.strip()) or "nota"
    return f"{limpio[:80]}.md"


def trigger_bland_call(phone_number: str, message_task: str):
    """Dispara una llamada Bland AI. Retorna (mensaje, call_id)."""
    api_key = BLAND_API_KEY or os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY", "").strip()
    if not api_key:
        return "Falta BLAND_API_KEY o BLAND_AI_API_KEY en las variables de entorno.", None
    if not phone_number:
        return "No pude identificar un número telefónico válido.", None

    try:
        resp = requests.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key},
            json={"phone_number": phone_number, "task": message_task},
            timeout=20,
        )
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code != 200:
            if isinstance(data, dict):
                if data.get("errors"):
                    errors = data["errors"]
                    if isinstance(errors, list):
                        return " ".join(str(item) for item in errors), None
                    return str(errors), None
                for key in ("message", "error", "msg"):
                    if data.get(key):
                        return str(data[key]), None
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


def make_call(phone_number: str, task: str) -> str:
    """Inicia una llamada en Bland AI y devuelve el estado o el error exacto."""
    api_key = BLAND_API_KEY or os.getenv("BLAND_API_KEY") or os.getenv("BLAND_AI_API_KEY", "").strip()
    if not api_key:
        return "Falta BLAND_API_KEY o BLAND_AI_API_KEY en las variables de entorno."

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
        "bland_ready": bool(BLAND_API_KEY),
        "llm_ready": bool(GROQ_API_KEY or ANTHROPIC_API_KEY),
    }


@app.post("/generate-notes", response_model=GenerateNotesResponse)
def generate_notes(request: GenerateNotesRequest):
    tema = f"{request.title}. {request.content}".strip()
    try:
        analisis = generar_analisis_llm(tema)
        markdown_text = generar_markdown_reporte(request.title, analisis)
    except Exception as e:
        print(f"[LLM] {e}")
        raise HTTPException(status_code=502, detail=str(e))
    filename = nombre_archivo_nota(request.title)
    try:
        save_to_obsidian(request.title, analisis, tags=["reporte", "nexus"])
    except Exception as e:
        print(f"[OBSIDIAN] No se pudo sincronizar la nota: {e}")
    return GenerateNotesResponse(success=True, markdown=markdown_text, filename=filename)


@app.post("/ask", response_model=AskResponse)
async def ask_jarvis(request: AskRequest):
    prompt = (request.prompt or request.message or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Falta el campo 'prompt' o 'message'.")

    if es_comando_llamada(prompt):
        phone_number = extraer_telefono_e164(prompt)
        if not phone_number:
            return AskResponse(
                response="No pude identificar el número telefónico. Inclúyelo en formato internacional (ej. +521234567890).",
                status="ok",
                intent="call",
            )
        tarea = re.sub(r"(?i)(haz una llamada|llama a|llama al|marcar a|marcar al|marca al|marca a)", "", prompt)
        tarea = re.sub(r"\+?\d[\d\s\-]{8,15}\d", "", tarea).strip() or prompt
        resultado, call_id = trigger_bland_call(phone_number, tarea)
        return AskResponse(response=resultado, status="ok", intent="call", call_id=call_id)

    if es_comando_reporte(prompt) or es_comando_nota(prompt):
        titulo = extraer_titulo_reporte(prompt) if es_comando_reporte(prompt) else "Nota Jarvis"
        if es_comando_nota(prompt) and prompt.lower().startswith("nota:"):
            titulo = "Nota Jarvis"
        try:
            analisis = generar_analisis_llm(prompt)
            markdown_text = generar_markdown_reporte(titulo, analisis)
        except Exception as e:
            print(f"[LLM] {e}")
            return AskResponse(response=str(e), status="error", intent="report", success=False)
        try:
            save_to_obsidian(titulo, analisis, tags=["reporte", "nexus"])
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

    try:
        respuesta = responder_chat_llm(prompt)
    except Exception as e:
        print(f"[LLM CHAT] {e}")
        return AskResponse(response=str(e), status="error", intent="chat")
    return AskResponse(response=respuesta, status="ok", intent="chat")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
