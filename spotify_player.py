"""Reproducción de música en Spotify vía Spotipy (OAuth de usuario / Headless Refresh Token)."""
from spotify_player import play_song
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
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()


def get_spotify_client() -> Optional["spotipy.Spotify"]:
    """Obtiene un cliente de Spotipy autenticado mediante el refresh token configurado."""
    if not spotipy or not SpotifyOAuth:
        return None

    if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        return None

    auth_manager = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=False,
    )

    if SPOTIFY_REFRESH_TOKEN:
        try:
            token_info = auth_manager.refresh_access_token(SPOTIFY_REFRESH_TOKEN)
            return spotipy.Spotify(auth=token_info["access_token"])
        except Exception as e:
            print(f"[Spotify] Error al renovar access token con refresh token: {e}")
            return None

    return None


def play_song(query: str) -> str:
    """Busca una pista y la reproduce en el dispositivo activo de Spotify."""
    sp = get_spotify_client()
    if not sp:
        return "Configuración de Spotify incompleta o error al renovar el token en el servidor."

    try:
        # 1. Buscar la pista
        results = sp.search(q=query, limit=1, type="track")
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return f"No encontré la canción '{query}' en Spotify."

        track = tracks[0]
        track_uri = track["uri"]
        track_name = track["name"]
        artist_name = track["artists"][0]["name"] if track["artists"] else "Desconocido"

        # 2. Obtener dispositivo activo o primer dispositivo disponible
        devices_data = sp.devices()
        devices = devices_data.get("devices", [])
        if not devices:
            return f"Encontré '{track_name}' de {artist_name}, pero no hay dispositivos de Spotify abiertos. Abre Spotify en tu PC."

        active_device = next((d for d in devices if d.get("is_active")), None)
        target_device_id = active_device["id"] if active_device else devices[0]["id"]

        # 3. Lanzar reproducción
        sp.start_playback(device_id=target_device_id, uris=[track_uri])
        return f"Reproduciendo {track_name} de {artist_name} en Spotify."

    except SpotifyException as se:
        if "NO_ACTIVE_DEVICE" in str(se):
            return "Abre Spotify en tu PC y dale reproducir a cualquier canción para activar la sesión."
        if "PREMIUM_REQUIRED" in str(se):
            return "El control remoto de reproducción requiere una cuenta de Spotify Premium."
        return f"Error en API de Spotify: {str(se)}"
    except Exception as e:
        return f"Error al reproducir en Spotify: {str(e)}"
SPOTIFY_CACHE_PATH = os.environ.get("SPOTIFY_CACHE_PATH", ".spotify_token_cache").strip() or ".spotify_token_cache"

_sp_client = None


def spotify_configurado() -> bool:
    return bool(spotipy and SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET and SPOTIPY_REDIRECT_URI)


def get_spotify_oauth() -> Optional["SpotifyOAuth"]:
    if not spotify_configurado():
        return None
    auth = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        cache_path=SPOTIFY_CACHE_PATH,
        open_browser=False,
    )
    refresh = os.environ.get("SPOTIPY_REFRESH_TOKEN", "").strip()
    if refresh and not auth.get_cached_token():
        try:
            auth.refresh_access_token(refresh)
        except Exception as e:
            print(f"[SPOTIFY] No se pudo usar SPOTIPY_REFRESH_TOKEN: {e}")
    return auth


def reset_spotify_client():
    global _sp_client
    _sp_client = None


def get_spotify_client():
    """Cliente Spotipy con SpotifyOAuth. Reutiliza el token en caché."""
    global _sp_client
    if _sp_client is not None:
        return _sp_client
    if spotipy is None:
        print("[SPOTIFY] spotipy no está instalado.")
        return None
    auth_manager = get_spotify_oauth()
    if auth_manager is None:
        print("[SPOTIFY] Faltan SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET o SPOTIPY_REDIRECT_URI.")
        return None
    _sp_client = spotipy.Spotify(auth_manager=auth_manager)
    return _sp_client


def _sin_dispositivo_activo(exc: Exception) -> bool:
    texto = str(exc).lower()
    reason = str(getattr(exc, "reason", "") or "").upper()
    if reason == "NO_ACTIVE_DEVICE":
        return True
    return "no active device" in texto or "no_active_device" in texto


def reproducir_en_spotify(cancion: str) -> str:
    """Busca un track y lo reproduce en el dispositivo Spotify activo."""
    query = (cancion or "").strip()
    if not query:
        return "Dime qué canción quieres reproducir."

    try:
        sp = get_spotify_client()
        if sp is None:
            return (
                "Spotify no está configurado. Define SPOTIPY_CLIENT_ID, "
                "SPOTIPY_CLIENT_SECRET y SPOTIPY_REDIRECT_URI en Render."
            )

        dispositivos = (sp.devices() or {}).get("devices") or []
        activos = [d for d in dispositivos if d.get("is_active")]
        if not dispositivos or not activos:
            print("[SPOTIFY] No hay dispositivo activo.")
            return (
                "No hay un dispositivo de Spotify activo. "
                "Abre Spotify en tu PC (o en el teléfono) y vuelve a intentarlo."
            )

        resultado = sp.search(q=query, limit=1, type="track")
        items = ((resultado or {}).get("tracks") or {}).get("items") or []
        if not items:
            return f"No encontré '{query}' en Spotify."

        track = items[0]
        track_uri = track.get("uri")
        nombre = track.get("name") or query
        artistas = track.get("artists") or []
        artista = artistas[0].get("name") if artistas else "artista desconocido"

        sp.start_playback(uris=[track_uri])
        print(f"[SPOTIFY] Reproduciendo {nombre} de {artista} ({track_uri})")
        return f"Reproduciendo {nombre} de {artista} en Spotify."

    except SpotifyException as e:
        print(f"[SPOTIFY ERROR] HTTP {getattr(e, 'http_status', '?')}: {e}")
        if _sin_dispositivo_activo(e):
            return (
                "No hay un dispositivo de Spotify activo. "
                "Abre Spotify en tu PC (o en el teléfono) y vuelve a intentarlo."
            )
        if getattr(e, "http_status", None) == 403:
            return "Spotify rechazó la reproducción. Se necesita una cuenta Premium y autorización de la app."
        if getattr(e, "http_status", None) in (401, 403):
            return "Spotify no está autorizado. Abre /spotify/login para vincular tu cuenta."
        return f"No pude controlar Spotify: {e}"
    except Exception as e:
        print(f"[SPOTIFY ERROR] {e}")
        texto = str(e).lower()
        if "no active device" in texto or "authorization" in texto:
            if "no active device" in texto:
                return (
                    "No hay un dispositivo de Spotify activo. "
                    "Abre Spotify en tu PC (o en el teléfono) y vuelve a intentarlo."
                )
            return "Spotify no está autorizado. Abre /spotify/login para vincular tu cuenta."
        return f"Error al reproducir en Spotify: {e}"
