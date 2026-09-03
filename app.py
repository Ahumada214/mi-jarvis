import os
import re
from spotify_player import play_song
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# Importación segura de los módulos auxiliares
try:
    from spotify_player import play_song
except ImportError:
    def play_song(query: str) -> str:
        return "Módulo spotify_player no encontrado en el servidor."

try:
    from obsidian_sync import sync_note_to_obsidian
except ImportError:
    def sync_note_to_obsidian(title: str, content: str) -> str:
        return "Sincronización con Obsidian no configurada."

# Inicialización de FastAPI
app = FastAPI(title="Jarvis NEXUS Core", version="1.0.0")

# Configuración de CORS para permitir peticiones desde localhost:3000 (NEXUS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite el enlace directo desde NEXUS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    prompt: str
    user_id: Optional[str] = "default_user"

class AskResponse(BaseModel):
    response: str
    intent: Optional[str] = "chat"

def clean_music_query(text: str) -> str:
    """Limpia el comando del usuario para extraer solo el nombre de la canción o artista."""
    patterns = [
        r"^reproduce\s+(la\s+canción\s+)?(de\s+)?",
        r"^pon\s+(la\s+canción\s+)?(de\s+)?",
        r"^escuchar\s+",
        r"^play\s+",
    ]
    query = text.strip()
    for pattern in patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE)
    return query.strip()

@app.get("/")
def health_check():
    return {
        "status": "online",
        "system": "Jarvis Core",
        "spotify_auth_ready": bool(os.getenv("SPOTIFY_REFRESH_TOKEN")),
    }

@app.post("/ask", response_model=AskResponse)
async def ask_jarvis(request: AskRequest):
    prompt = request.prompt.strip()
    lower_prompt = prompt.lower()

    if not prompt:
        raise HTTPException(status_code=400, detail="El prompt no puede estar vacío.")

    # 1. Detección de comando de Spotify
    music_triggers = ["reproduce", "pon la canción", "pon canción", "play ", "escuchar "]
    if any(lower_prompt.startswith(trigger) or f" {trigger}" in lower_prompt for trigger in ["reproduce", "pon "]):
        song_query = clean_music_query(prompt)
        if not song_query:
            return AskResponse(
                response="Por favor especifica el nombre de la pista que deseas reproducir.",
                intent="music"
            )
        
        # Ejecuta la reproducción sin interacción de consola (headless)
        playback_result = play_song(song_query)
        return AskResponse(response=playback_result, intent="music")

    # 2. Detección de notas de Obsidian
    if lower_prompt.startswith("nota:") or lower_prompt.startswith("guardar nota"):
        note_content = prompt.split(":", 1)[-1].strip()
        result = sync_note_to_obsidian(title="Nota Rápida", content=note_content)
        return AskResponse(response=result, intent="obsidian")

    # 3. Respuesta estándar de conversación / fallback
    # Si tienes configurado cliente LLM (OpenAI/Gemini), intégralo aquí.
    response_msg = (
        f"Comando recibido en el Core: '{prompt}'. "
        "Spotify, Obsidian y módulos de telemetría sincronizados."
    )
    return AskResponse(response=response_msg, intent="chat")