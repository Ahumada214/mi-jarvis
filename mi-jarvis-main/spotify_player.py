"""Reproducción de música en Spotify vía Spotipy (OAuth de usuario)."""

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
SPOTIPY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "").strip()
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
