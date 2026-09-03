import os
import re
from typing import Optional

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


def es_comando_nota(text: str) -> bool:
    lower = (text or "").lower()
    return (
        lower.startswith("nota:")
        or lower.startswith("guardar nota")
        or "guarda en obsidian" in lower
        or "sube a obsidian" in lower
    )


@app.get("/")
def health_check():
    return {
        "status": "online",
        "system": "Jarvis Core",
        "spotify_auth_ready": bool(os.getenv("SPOTIFY_REFRESH_TOKEN")),
    }


@app.post("/ask", response_model=AskResponse)
async def ask_jarvis(request: AskRequest):
    prompt = (request.prompt or request.message or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Falta el campo 'prompt' o 'message'.")

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
        saved = save_to_obsidian("Nota Rápida", note_content, tags=["nexus", "nota"])
        msg = (
            "Nota sincronizada con Obsidian."
            if saved
            else "No pude guardar la nota. Revisa GITHUB_TOKEN y GITHUB_REPO."
        )
        return AskResponse(response=msg, status="ok", intent="obsidian")

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
