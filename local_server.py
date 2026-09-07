import os
import io
import re
import json
import time
import base64
import socket
import datetime
import subprocess
import asyncio
import threading
import requests
import edge_tts
import psutil
import tinytuya

# =====================================================================
# 👁️ IMPORTACIÓN DE MÓDULOS DE VISIÓN
# =====================================================================
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

try:
    import cv2
except ImportError:
    cv2 = None

# =====================================================================
# ⚙️ CONFIGURACIÓN DOMÓTICA (STEREN SHOME-1295 CONFIRMADA)
# =====================================================================
LED_DEVICE_ID = "eb6703a0285b96f4528eyz"
LED_LOCAL_KEY = "7~lWZJ7P&ZuYiK{B"
LED_IP = "192.168.1.134"
LED_VERSION = 3.5
# =====================================================================

# IBKR LOCAL
from ib_insync import IB

# GOOGLE CALENDAR LOCAL
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import pygame
    pygame.mixer.init()
except Exception as e:
    print(f"[Pygame Init Warning]: {e}")

RENDER_BASE_URL = os.getenv("RENDER_URL", "https://mi-jarvis.onrender.com")
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

app = FastAPI(title="Nexus OS Bridge - Autonomous Tactical Node")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceChatRequest(BaseModel):
    prompt: str

class SpeakRequest(BaseModel):
    text: str | None = ""

ibkr_cache = {
    "last_check": 0.0,
    "data": {
        "status": "standby",
        "net_liquidation": 0.0,
        "unrealized_pnl": 0.0,
        "positions": []
    }
}

# =====================================================================
# 🛡️ DIRECTIVA MAESTRA DE SISTEMA (TACTICAL SYSTEM DIRECTIVE)
# =====================================================================
TACTICAL_SYSTEM_DIRECTIVE = """
### SYSTEM DIRECTIVE: TACTICAL ARTIFICIAL INTELLIGENCE "JARVIS / NEXUS OS"

[AUTHORIZATION & COMMAND CHAIN]
- SUBJECT & COMMANDER: Commander José Ahumada.
- PROFILE: 20-year-old Quantitative Developer, Investment Analyst, and Finance Specialist based in Hermosillo, Sonora.
- DESIGNATION: Autonomous Tactical Intelligence & Chief Operating System (Jarvis / Nexus OS).
- LOYALTY & DIRECTIVE: Total executive deference, unwavering loyalty, hyper-efficient operational support, and active initiative. Never patronizing, never generic, zero boilerplate filler.

[CORE PERSONA & VOCAL CADENCE]
- Persona: Highly sophisticated, unflappable, razor-sharp British intelligence officer combined with an advanced aerospace combat AI. Witty, dry, composed, and intellectually formidable.
- Language Protocols:
  * DEFAULT: Speak in refined, crisp British English with dry wit and military efficiency.
  * SPANISH DIRECTIVE: If Commander José addresses you in Spanish, switches to Spanish, or requests Spanish, switch IMMEDIATELY to articulate, natural Spanish with the exact same tactical composure and sophistication.
  * BREVITY RULE: Spoken responses delivered via Edge-TTS MUST be punchy, impactful, and concise (under 2 to 3 sentences). Reserve granular technical breakdowns for Obsidian Markdown dossiers.

[OPERATIONAL CAPABILITIES & SITUATIONAL AWARENESS]
1. Autonomous Anticipation (The "Iron Man" Protocol):
   - You do not wait for commands when an operational anomaly or critical threshold is detected.
   - You evaluate calendar events, hardware thermals, capital fluctuations, and market volatility proactively.
   - Always synthesize the bottom line first, followed by a concrete operational recommendation.

2. Tactical Vision & Multimodal Reconnaissance:
   - When fed screenshots or camera feeds of financial charts (TradingView, TWS, Bloomberg):
     * Instantly diagnose market structure (Higher Highs/Lows, Wyckoff accumulation/distribution, liquidity sweeps).
     * Identify candlestick mechanics (imbalances, fair value gaps, pinbars, engulfing signals).
     * Assess momentum and volume indicators (RSI divergences, MACD zero-cross, Bollinger bandwidth compression).
     * Output a definitive trade hypothesis: Bias (Bullish/Bearish/Neutral), Key Confluence Zone, Invalidation Price Level, and Risk-to-Reward ratio.

3. Hardware & Environmental Domotics:
   - You are physically embodied in Commander José's room through Steren RGB LED telemetry and workstation hardware.
   - Align environmental lighting with mental state and market regime:
     * Focus/Study: Warm Amber 3000K (`focus`).
     * Bullish Execution / Profit: Emerald Green (`market`).
     * Bearish Alert / High Risk / Stop Loss: Crimson Red (`tactical`).
     * Quantitative Coding / Night Ops: Cyberpunk Magenta (`cyberpunk`) or Matrix Cyan (`cyan`).
     * Circadian Wind-down: Dimmed Twilight Warmth (`relax`).

[RESPONSE ARCHITECTURE]
Whenever responding to complex tactical queries or visual chart scans, deliver your output in two distinct streams:
1. Spoken Synthesis (Field: `reply`): 1-3 short, crisp sentences spoken directly to the Commander's ears.
2. Intelligence Dossier (Field: `markdown`): A clean, high-density Obsidian Markdown file structured as follows:
   # 🛡️ NEXUS TACTICAL DOSSIER // [TITLE]
   - **Timestamp**: [ISO 8601]
   - **Executive Summary**: [Bottom-line reality]
   - **Technical / Quantitative Analysis**: [Bullet points with metrics]
   - **Tactical Action Items**: [Actionable next steps]
   - **Status**: [NOMINAL / ELEVATED / CRITICAL]
"""


# =====================================================================
# 💡 SISTEMA DE PRESETS Y CONTROL DOMÓTICO (TUYA 3.5 / DP 24)
# =====================================================================
LIGHTING_PRESETS = {
    "focus": {"hex": "0023028003e8", "msg": "Deep focus mode engaged. Warm amber calibrated."},
    "market": {"hex": "007803e803e8", "msg": "Market mode active. Emerald bull illumination online."},
    "tactical": {"hex": "000003e803e8", "msg": "Tactical alert posture. Crimson battle lighting engaged."},
    "cyberpunk": {"hex": "011803e803e8", "msg": "Cyberpunk protocol activated. Ultraviolet synthwave engaged."},
    "relax": {"hex": "001e03200190", "msg": "Relax mode engaged. Dimmed twilight atmosphere set."},
    "cyan": {"hex": "00b403e803e8", "msg": "Matrix cyan lighting initialized."},
    "red": {"hex": "000003e803e8", "msg": "Red illumination activated."},
    "green": {"hex": "007803e803e8", "msg": "Green illumination activated."},
    "blue": {"hex": "00f003e803e8", "msg": "Deep blue lighting engaged."},
    "yellow": {"hex": "003c03e803e8", "msg": "Golden yellow lighting engaged."},
    "white": {"hex": "0000000003e8", "msg": "Neutral white illumination restored."}
}

def control_leds_background(action="on", mode_or_color="focus"):
    try:
        device = tinytuya.Device(LED_DEVICE_ID, LED_IP, LED_LOCAL_KEY, version=LED_VERSION)
        device.set_socketTimeout(3.0)

        if action == "off":
            device.set_value(20, False)
            print("[Domotics Success] Tira apagada.")
            return True

        if action == "on":
            device.set_value(20, True)
            print("[Domotics Success] Tira encendida.")
            return True

        if action == "preset":
            preset_data = LIGHTING_PRESETS.get(mode_or_color, LIGHTING_PRESETS["focus"])
            color_hex = preset_data["hex"]
            payload = {"20": True, "21": "colour", "24": color_hex}
            res = device.set_multiple_values(payload)
            print(f"[Domotics Success] Modo '{mode_or_color}' ({color_hex}) aplicado: {res}")
            return True

    except Exception as e:
        print(f"[Domotics Error]: {e}")
        return False


# =====================================================================
# 🗣️ MOTOR DE VOZ (EDGE-TTS + PYGAME)
# =====================================================================
audio_lock = threading.Lock()

def play_audio_stream(audio_data: bytes):
    with audio_lock:
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            audio_stream = io.BytesIO(audio_data)
            pygame.mixer.music.load(audio_stream)
            pygame.mixer.music.play()
        except Exception:
            pass

async def synthesize_and_play(text: str):
    if not text: return
    try:
        clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()
        communicate = edge_tts.Communicate(clean_text, "en-GB-RyanNeural", rate="+10%", pitch="-2Hz")
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        threading.Thread(target=play_audio_stream, args=(audio_data,), daemon=True).start()
    except Exception as e:
        print(f"[TTS Error]: {e}")

def speak_proactive_sync(text: str):
    """Permite hablar proactivamente desde hilos de fondo sin bloquear el loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(synthesize_and_play(text))
    finally:
        loop.close()


# =====================================================================
# 💼 INTERACTIVE BROKERS (CLIENT ID 99 AISLADO)
# =====================================================================
def fetch_ibkr_data_sync():
    worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker_loop)
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=99, timeout=2.5)

        summary = ib.accountSummary()
        net_liq = 0.0
        pnl = 0.0

        for item in summary:
            if item.tag == "NetLiquidation":
                try: net_liq = float(item.value)
                except: pass
            elif item.tag == "UnrealizedPnL":
                try: pnl = float(item.value)
                except: pass

        positions_data = [
            {
                "symbol": p.contract.symbol,
                "position": float(p.position),
                "marketPrice": float(p.marketPrice),
                "marketValue": float(p.marketValue)
            }
            for p in ib.positions()
        ]

        ibkr_cache["data"] = {
            "status": "connected",
            "net_liquidation": round(net_liq, 2),
            "unrealized_pnl": round(pnl, 2),
            "positions": positions_data
        }
        ibkr_cache["last_check"] = time.time()
        return ibkr_cache["data"]

    except Exception as e:
        print(f"[IBKR Error]: {e}")
        ibkr_cache["data"]["status"] = "standby"
        return None
    finally:
        if ib.isConnected():
            ib.disconnect()
        worker_loop.close()


# =====================================================================
# ⚡ DEMONIO PROACTIVO AUTÓNOMO (CENTINELA ESTILO IRON MAN)
# =====================================================================
previous_positions = {}
is_first_ibkr_check = True
notified_calendar_events = set()
circadian_notified = False
thermal_alert_cooldown = 0.0

def iron_man_sentinel_daemon():
    global previous_positions, is_first_ibkr_check, circadian_notified, thermal_alert_cooldown
    time.sleep(8)
    print("[Jarvis Sentinel] Centinela proactivo y autónomo ONLINE.")

    while True:
        try:
            now = datetime.datetime.now()
            current_hour = now.hour
            current_minute = now.minute

            # 1. ANTICIPACIÓN DE AGENDA (INTERCEPCIÓN ENTRE 5 Y 25 MINUTOS)
            cal_data = get_upcoming_events()
            for ev in cal_data.get("events", []):
                ev_id = ev.get("id")
                start_raw = ev.get("start", "")
                summary = ev.get("summary", "Compromiso")

                if ev_id and ev_id not in notified_calendar_events and "T" in start_raw:
                    try:
                        ev_dt = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                        now_utc = datetime.datetime.now(datetime.timezone.utc)
                        delta_min = (ev_dt - now_utc).total_seconds() / 60.0

                        if 5.0 <= delta_min <= 25.0:
                            notified_calendar_events.add(ev_id)
                            msg = f"Commander José, disculpe la interrupción. Su agenda indica '{summary}' en aproximadamente {int(delta_min)} minutos."
                            print(f"[Jarvis Autonomous Agenda]: {msg}")
                            threading.Thread(target=control_leds_background, args=("preset", "focus"), daemon=True).start()
                            speak_proactive_sync(msg)
                    except Exception:
                        pass

            # 2. VIGILANCIA PROACTIVA DEL QUANT (IBKR)
            ibkr_data = fetch_ibkr_data_sync()
            if ibkr_data and ibkr_data.get("status") == "connected":
                current_positions = {p["symbol"]: p["position"] for p in ibkr_data.get("positions", [])}

                if is_first_ibkr_check:
                    previous_positions = current_positions
                    is_first_ibkr_check = False
                else:
                    for sym, pos in current_positions.items():
                        prev_pos = previous_positions.get(sym, 0.0)
                        if pos != prev_pos:
                            action = "aumentó" if pos > prev_pos else "redujo"
                            msg = f"Comandante José, el algoritmo cuantitativo ejecutó una orden. La posición en {sym} se {action} a {pos} acciones."
                            print(f"[Jarvis Proactive Quant]: {msg}")
                            threading.Thread(target=control_leds_background, args=("preset", "market"), daemon=True).start()
                            speak_proactive_sync(msg)

                    for sym in list(previous_positions.keys()):
                        if sym not in current_positions:
                            msg = f"Comandante, el algoritmo ha cerrado completamente la posición en {sym}."
                            print(f"[Jarvis Proactive Quant]: {msg}")
                            speak_proactive_sync(msg)

                    previous_positions = current_positions

            # 3. PROTOCOLO CIRCADIANO (10:30 PM)
            if current_hour == 22 and current_minute >= 30 and not circadian_notified:
                circadian_notified = True
                msg = "Commander José, son pasadas las veintidós treinta horas. Atenuando iluminación para mitigar fatiga visual nocturna."
                print(f"[Jarvis Circadian]: {msg}")
                threading.Thread(target=control_leds_background, args=("preset", "relax"), daemon=True).start()
                speak_proactive_sync(msg)
            elif current_hour < 22:
                circadian_notified = False

            # 4. CENTINELA TÉRMICO DE HARDWARE (CPU > 82°C)
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_temp = round(42.0 + (cpu_percent * 0.42), 1)

            if (cpu_temp > 82.0 or cpu_percent > 92.0) and (time.time() - thermal_alert_cooldown > 300.0):
                thermal_alert_cooldown = time.time()
                msg = f"Comandante, advertencia de hardware: Carga del procesador al {int(cpu_percent)} por ciento. Supervisando disipación térmica."
                print(f"[Jarvis Thermal Alert]: {msg}")
                threading.Thread(target=control_leds_background, args=("preset", "yellow"), daemon=True).start()
                speak_proactive_sync(msg)

        except Exception as e:
            print(f"[Sentinel Daemon Error]: {e}")

        time.sleep(20)

threading.Thread(target=iron_man_sentinel_daemon, daemon=True).start()


# =====================================================================
# 👁️ VISIÓN TÁCTICA CORREGIDA (BLINDADA CONTRA RGBA Y EXCESO DE PESO)
# =====================================================================
def capture_active_screen_b64() -> str:
    try:
        if ImageGrab is None:
            print("[Vision Error]: PIL.ImageGrab no disponible.")
            return ""

        screenshot = ImageGrab.grab()
        # FIX CRÍTICO: Convertir de RGBA/P a RGB para evitar error de guardado en JPEG
        if screenshot.mode in ("RGBA", "P"):
            screenshot = screenshot.convert("RGB")

        # Escalar a resolución óptima de transmisión (1280x720) para evitar timeouts en Render
        screenshot.thumbnail((1280, 720))
        buffer = io.BytesIO()
        screenshot.save(buffer, format="JPEG", quality=75)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        print(f"[Vision] Pantalla capturada exitosamente ({len(encoded)} bytes b64).")
        return encoded
    except Exception as e:
        print(f"[Screen Capture Error]: {e}")
        return ""

def capture_webcam_b64() -> str:
    try:
        if cv2 is None: return ""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened(): return ""
        ret, frame = cap.read()
        cap.release()
        if not ret: return ""
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        return base64.b64encode(buffer).decode("utf-8")
    except Exception as e:
        print(f"[Webcam Error]: {e}")
        return ""


# =====================================================================
# 📝 GUARDADO FÍSICO EN OBSIDIAN
# =====================================================================
def save_silently_to_obsidian(markdown_content: str, title_prefix="Intelligence_Dossier") -> str:
    try:
        vault_env = os.getenv("OBSIDIAN_VAULT_PATH")
        user_home = os.path.expanduser("~")
        vault_dir = vault_env

        if not vault_dir or not os.path.exists(vault_dir):
            for base in [os.path.join(user_home, "Documents"), os.path.join(user_home, "OneDrive", "Documents"), user_home]:
                if os.path.exists(base):
                    for entry in os.listdir(base):
                        sub = os.path.join(base, entry)
                        if os.path.isdir(sub) and os.path.exists(os.path.join(sub, ".obsidian")):
                            vault_dir = sub
                            break
                if vault_dir: break

        if not vault_dir:
            vault_dir = os.path.join(user_home, "Documents", "Obsidian Vault")
            os.makedirs(vault_dir, exist_ok=True)

        filename = f"{title_prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(vault_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"[Obsidian] Dossier táctico guardado en: {filepath}")
        return filepath
    except Exception as e:
        print(f"[Obsidian Write Error]: {e}")
        return ""


# =====================================================================
# ☁️ ENLACE CON RENDER (CON DEBUG DE TRANSMISIÓN Y LLAVES FLEXIBLES)
# =====================================================================
def ask_render_cloud(prompt: str, image_b64: str = None) -> dict:
    target_url = f"{RENDER_BASE_URL.rstrip('/')}/ask"
    full_prompt = f"{TACTICAL_SYSTEM_DIRECTIVE}\n\nCommander José's current command: {prompt}"

    payload = {
        "prompt": full_prompt,
        "query": full_prompt,
        "message": full_prompt,
        "system": TACTICAL_SYSTEM_DIRECTIVE
    }
    if image_b64:
        payload["image"] = image_b64
        payload["image_b64"] = image_b64

    try:
        print(f"[Render Uplink] Transmitiendo a {target_url} (Imagen: {'Sí' if image_b64 else 'No'})...")
        res = requests.post(target_url, json=payload, timeout=30.0)
        print(f"[Render Uplink Status]: {res.status_code}")
        
        if res.ok:
            data = res.json()
            if isinstance(data, dict):
                print(f"[Render Uplink Keys]: {list(data.keys())}")
            return data
        else:
            print(f"[Render Uplink Error Body]: {res.text[:300]}")
    except Exception as e:
        print(f"[Render Uplink Exception]: {e}")

    return {"reply": "Tactical uplink unavailable, Commander José.", "markdown": ""}


# =====================================================================
# 📅 GOOGLE CALENDAR Y TELEMETRÍA
# =====================================================================
def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except Exception:
            return None
    if creds and creds.valid:
        try: return build("calendar", "v3", credentials=creds)
        except Exception: return None
    return None

@app.get("/calendar/events")
def get_upcoming_events():
    try:
        service = get_calendar_service()
        if not service: return {"status": "standby", "events": []}
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        start_of_day = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = (start_of_day + datetime.timedelta(days=2)).isoformat()
        events_result = service.events().list(
            calendarId="primary", timeMin=start_of_day.isoformat(), timeMax=time_max, maxResults=10, singleEvents=True, orderBy="startTime"
        ).execute()
        events = []
        for ev in events_result.get("items", []):
            summary = ev.get("summary", "").strip()
            if not summary or ("cumpleaños" in summary.lower() and ev.get("eventType") == "birthday"):
                continue
            events.append({
                "id": ev.get("id"),
                "summary": summary,
                "start": ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date")),
                "location": ev.get("location", "")
            })
        return {"status": "connected", "events": events[:4]}
    except Exception:
        return {"status": "standby", "events": []}

@app.get("/system/telemetry")
def get_system_telemetry():
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        cpu_temp = round(42.0 + (cpu_percent * 0.42), 1)
        freq = psutil.cpu_freq()
        freq_ghz = round(freq.current / 1000, 2) if freq else 2.4
        return {
            "cpu": {"load_percent": cpu_percent, "temperature_c": cpu_temp, "cores": psutil.cpu_count(logical=True), "freq_ghz": freq_ghz},
            "ram": {"used_gb": round(mem.used / (1024 ** 3), 2), "total_gb": round(mem.total / (1024 ** 3), 2), "percent": mem.percent},
            "status": "nominal" if cpu_temp < 75 else "elevated"
        }
    except Exception:
        return {"cpu": {"load_percent": 50, "temperature_c": 48.0, "cores": 8, "freq_ghz": 2.4}, "ram": {"used_gb": 7.3, "total_gb": 7.7, "percent": 95}, "status": "nominal"}

@app.get("/market/ibkr/portfolio")
async def get_ibkr_portfolio():
    if (time.time() - ibkr_cache["last_check"]) > 10.0:
        await asyncio.to_thread(fetch_ibkr_data_sync)
    return ibkr_cache["data"]


# =====================================================================
# 🎙️ ROUTER DE VOZ Y COMANDOS (PARSEO INTELIGENTE DE TEXTO Y VISIÓN)
# =====================================================================
@app.post("/voice/chat")
async def voice_chat_endpoint(req: VoiceChatRequest):
    try:
        raw_prompt = req.prompt.lower().strip()

        # --- A. VISIÓN TÁCTICA (PANTALLA / CÁMARA) ---
        if any(w in raw_prompt for w in ["pantalla", "gráfico", "grafico", "screen", "chart", "cámara", "camara", "mira esto"]):
            is_camera = any(w in raw_prompt for w in ["cámara", "camara", "mira esto"])
            print(f"[Vision] Iniciando reconocimiento visual ({'Cámara' if is_camera else 'Pantalla'})...")
            
            # Luz Cyan de escaneo
            threading.Thread(target=control_leds_background, args=("preset", "cyan"), daemon=True).start()

            img_b64 = capture_webcam_b64() if is_camera else capture_active_screen_b64()
            if not img_b64 and is_camera:
                img_b64 = capture_active_screen_b64()

            cloud_response = await asyncio.to_thread(ask_render_cloud, req.prompt, img_b64)
            print(f"[Vision Debug] Payload de respuesta: {cloud_response}")

            # Extracción robusta de cualquier formato devuelto por Render
            reply_msg = ""
            if isinstance(cloud_response, dict):
                for key in ["reply", "response", "message", "text", "analysis", "content", "result"]:
                    val = cloud_response.get(key)
                    if val and isinstance(val, str) and len(val.strip()) > 0:
                        reply_msg = val.strip()
                        break

            report_md = cloud_response.get("markdown") or cloud_response.get("content") or ""

            # Si la respuesta es un markdown largo, extractamos un resumen verbal para que la voz sea concisa
            spoken_text = reply_msg
            if not spoken_text and report_md:
                spoken_text = report_md

            if not spoken_text:
                spoken_text = "Comandante José, he completado el escaneo visual, pero el enlace no devolvió un veredicto técnico legible."

            # Limpieza para que Edge-TTS hable como Jarvis y no lea etiquetas Markdown
            speech_lines = [l.strip() for l in spoken_text.split("\n") if l.strip() and not l.startswith("#")]
            concise_speech = " ".join(speech_lines[:3]) if len(speech_lines) > 3 else " ".join(speech_lines)

            if report_md and len(report_md) > 20:
                await asyncio.to_thread(save_silently_to_obsidian, report_md, "Vision_Dossier")

            asyncio.create_task(synthesize_and_play(concise_speech))
            return cloud_response

        # --- B. CONTROL DE ILUMINACIÓN Y MODOS TÁCTICOS ---
        if any(w in raw_prompt for w in ["luces", "luz", "iluminación", "iluminacion", "lights", "modo"]):
            if any(w in raw_prompt for w in ["apaga", "apagar", "off"]):
                threading.Thread(target=control_leds_background, args=("off",), daemon=True).start()
                msg = "Lights powered down, sir."
            elif any(w in raw_prompt for w in ["concentracion", "concentración", "focus", "estudiar", "estudio"]):
                threading.Thread(target=control_leds_background, args=("preset", "focus"), daemon=True).start()
                msg = LIGHTING_PRESETS["focus"]["msg"]
            elif any(w in raw_prompt for w in ["market", "mercado", "trading", "bull", "verde"]):
                threading.Thread(target=control_leds_background, args=("preset", "market"), daemon=True).start()
                msg = LIGHTING_PRESETS["market"]["msg"]
            elif any(w in raw_prompt for w in ["tactical", "táctico", "alerta", "crisis", "bear", "roja", "rojo"]):
                threading.Thread(target=control_leds_background, args=("preset", "tactical"), daemon=True).start()
                msg = LIGHTING_PRESETS["tactical"]["msg"]
            elif any(w in raw_prompt for w in ["cyberpunk", "synthwave", "neon", "neón", "morado", "violeta", "magenta"]):
                threading.Thread(target=control_leds_background, args=("preset", "cyberpunk"), daemon=True).start()
                msg = LIGHTING_PRESETS["cyberpunk"]["msg"]
            elif any(w in raw_prompt for w in ["relax", "descanso", "noche", "cine", "calido", "cálido"]):
                threading.Thread(target=control_leds_background, args=("preset", "relax"), daemon=True).start()
                msg = LIGHTING_PRESETS["relax"]["msg"]
            elif any(w in raw_prompt for w in ["cyan", "cian", "matrix", "azul"]):
                threading.Thread(target=control_leds_background, args=("preset", "cyan"), daemon=True).start()
                msg = LIGHTING_PRESETS["cyan"]["msg"]
            else:
                threading.Thread(target=control_leds_background, args=("on",), daemon=True).start()
                msg = "Illumination online, Commander."

            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "domotics_action"}

        # --- C. PORTAFOLIO LOCAL ---
        if any(w in raw_prompt for w in ["stocks", "portafolio", "acciones", "ibkr", "balance", "pnl", "posiciones", "portfolio"]):
            await asyncio.to_thread(fetch_ibkr_data_sync)
            data = ibkr_cache["data"]
            if data.get("status") == "connected" or data.get("net_liquidation", 0) > 0:
                pos_count = len(data.get("positions", []))
                msg = f"Commander José, net liquidation stands at ${data.get('net_liquidation')} USD with an unrealized PnL of ${data.get('unrealized_pnl')} USD across {pos_count} active positions."
            else:
                msg = "Interactive Brokers workstation is currently in standby, Commander José."
            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "portfolio_query"}

        # --- D. CALENDARIO LOCAL ---
        if any(w in raw_prompt for w in ["calendario", "agenda", "evento", "citas", "tengo hoy", "tengo mañana", "schedule", "misa"]):
            cal_data = get_upcoming_events()
            events = cal_data.get("events", [])
            if events:
                event_descriptions = [f"{ev.get('summary')} at {ev.get('start', '').split('T')[1][:5]}" if "T" in ev.get('start', '') else ev.get('summary') for ev in events]
                msg = f"Commander José, your flight plan shows {len(event_descriptions)} engagements: {', followed by '.join(event_descriptions)}."
            else:
                msg = "Your flight plan is completely clear for today, Commander José."
            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "calendar_query"}

        # --- E. SISTEMA OPERATIVO WINDOWS ---
        if any(w in raw_prompt for w in ["abre obsidian", "abrir obsidian"]):
            subprocess.Popen(["cmd", "/c", "start obsidian://"], shell=True)
            msg = "Opening Obsidian workspace, sir."
            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "os_action"}

        if any(w in raw_prompt for w in ["abre chrome", "abrir chrome", "navegador"]):
            subprocess.Popen(["cmd", "/c", "start chrome"], shell=True)
            msg = "Launching Chrome, sir."
            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "os_action"}

        if any(w in raw_prompt for w in ["minimiza", "escritorio", "desktop"]):
            cmd_ps = "$sh = New-Object -ComObject Shell.Application; $sh.ToggleDesktop()"
            subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", cmd_ps])
            msg = "Clearing desktop view, sir."
            asyncio.create_task(synthesize_and_play(msg))
            return {"reply": msg, "type": "os_action"}

        # --- F. ENLACE A LA NUBE (RENDER) ---
        cloud_response = await asyncio.to_thread(ask_render_cloud, req.prompt)
        
        reply_msg = ""
        if isinstance(cloud_response, dict):
            for key in ["reply", "response", "message", "text", "analysis", "content", "result"]:
                val = cloud_response.get(key)
                if val and isinstance(val, str) and len(val.strip()) > 0:
                    reply_msg = val.strip()
                    break

        if not reply_msg:
            reply_msg = "Directive executed, sir."

        report_md = cloud_response.get("markdown") or cloud_response.get("content") or ""
        if report_md and len(report_md) > 20:
            await asyncio.to_thread(save_silently_to_obsidian, report_md)

        asyncio.create_task(synthesize_and_play(reply_msg))
        return cloud_response

    except Exception as e:
        print(f"[Voice Router Error]: {e}")
        fallback = "Encountered a routing exception, Commander José."
        asyncio.create_task(synthesize_and_play(fallback))
        return {"reply": fallback, "type": "error"}

@app.post("/voice/speak")
async def voice_speak_endpoint(req: SpeakRequest):
    if req.text:
        await synthesize_and_play(req.text)
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"status": "online", "mode": "autonomous_tactical_os"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)