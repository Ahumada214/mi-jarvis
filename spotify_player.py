"""Reproducción de música en Spotify vía Spotipy (OAuth headless con refresh token)."""

import os
from typing import Optional

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    from spotipy.exceptions import SpotifyException
except ImportError:
    spotipy = None
    SpotifyOAuth = None
    SpotifyException = Exception

SPOTIFY_SCOPE = "user-modify-playback-state user-read-playback-state"
SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "").strip()
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "").strip()
SPOTIPY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8080").strip()
SPOTIFY_CACHE_PATH = os.environ.get("SPOTIFY_CACHE_PATH", ".spotify_token_cache").strip() or ".spotify_token_cache"


def get_spotify_oauth() -> Optional["SpotifyOAuth"]:
    """Crea SpotifyOAuth headless. Nunca abre el navegador ni pide input()."""
    if not spotipy or not SpotifyOAuth:
        return None
    if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        return None
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=False,
        cache_path=SPOTIFY_CACHE_PATH,
    )


def get_spotify_client() -> Optional["spotipy.Spotify"]:
    """Cliente autenticado solo con SPOTIFY_REFRESH_TOKEN. Cero interacción de consola."""
    if not spotipy or not SpotifyOAuth:
        print("[SPOTIFY] spotipy no está instalado.")
        return None

    if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        print("[SPOTIFY] Faltan SPOTIPY_CLIENT_ID o SPOTIPY_CLIENT_SECRET.")
        return None

    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        print("[SPOTIFY] Falta SPOTIFY_REFRESH_TOKEN. No se inicia OAuth interactivo.")
        return None

    auth_manager = get_spotify_oauth()
    if auth_manager is None:
        return None

    try:
        token_info = auth_manager.refresh_access_token(os.environ["SPOTIFY_REFRESH_TOKEN"])
        return spotipy.Spotify(auth=token_info["access_token"])
    except Exception as e:
        print(f"[SPOTIFY] Error al renovar access token con refresh token: {e}")
        return None


def _sin_dispositivo_activo(exc: Exception) -> bool:
    texto = str(exc).lower()
    reason = str(getattr(exc, "reason", "") or "").upper()
    if reason == "NO_ACTIVE_DEVICE":
        return True
    return "no active device" in texto or "no_active_device" in texto


def play_song(query: str) -> str:
    """Busca una pista y la reproduce en el dispositivo activo de Spotify."""
    cancion = (query or "").strip()
    if not cancion:
        return "Dime qué canción quieres reproducir."

    try:
        sp = get_spotify_client()
        if not sp:
            return (
                "Spotify no está autorizado en el servidor. "
                "Configura SPOTIFY_REFRESH_TOKEN, SPOTIPY_CLIENT_ID y SPOTIPY_CLIENT_SECRET en Render."
            )

        results = sp.search(q=cancion, limit=1, type="track")
        tracks = ((results or {}).get("tracks") or {}).get("items") or []
        if not tracks:
            return f"No encontré la canción '{cancion}' en Spotify."

        track = tracks[0]
        track_uri = track.get("uri")
        track_name = track.get("name") or cancion
        artists = track.get("artists") or []
        artist_name = artists[0].get("name") if artists else "Desconocido"

        devices = ((sp.devices() or {}).get("devices")) or []
        if not devices:
            return (
                f"Encontré '{track_name}' de {artist_name}, pero no hay un dispositivo de Spotify activo. "
                "Abre Spotify en tu PC e inténtalo de nuevo."
            )

        active_device = next((d for d in devices if d.get("is_active")), None)
        target_device_id = (active_device or devices[0]).get("id")

        sp.start_playback(device_id=target_device_id, uris=[track_uri])
        print(f"[SPOTIFY] Reproduciendo {track_name} de {artist_name} ({track_uri})")
        return f"Reproduciendo {track_name} de {artist_name} en Spotify."

    except SpotifyException as se:
        print(f"[SPOTIFY ERROR] HTTP {getattr(se, 'http_status', '?')}: {se}")
        if _sin_dispositivo_activo(se) or "NO_ACTIVE_DEVICE" in str(se):
            return (
                "No hay un dispositivo de Spotify activo. "
                "Abre Spotify en tu PC y vuelve a intentarlo."
            )
        if "PREMIUM_REQUIRED" in str(se) or getattr(se, "http_status", None) == 403:
            return "El control remoto de reproducción requiere una cuenta de Spotify Premium."
        return f"Error en API de Spotify: {se}"
    except Exception as e:
        print(f"[SPOTIFY ERROR] {e}")
        texto = str(e).lower()
        if "eof when reading a line" in texto:
            return (
                "Spotify no puede autenticarse en Render sin SPOTIFY_REFRESH_TOKEN. "
                "Añade ese token en las variables de entorno."
            )
        if "no active device" in texto:
            return (
                "No hay un dispositivo de Spotify activo. "
                "Abre Spotify en tu PC y vuelve a intentarlo."
            )
        return f"Error al reproducir en Spotify: {e}"


def reproducir_en_spotify(cancion: str) -> str:
    """Alias usado por el enrutador de /ask."""
    return play_song(cancion)
