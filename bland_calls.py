"""Llamadas telefónicas a través de Bland AI."""

import os
import re
from typing import Optional

import httpx

BLAND_API_URL = "https://api.bland.ai/v1/calls"
CODIGO_PAIS_DEFAULT = "+52"


def obtener_bland_api_key() -> str:
    return (os.getenv("BLAND_API_KEY") or "").strip()


def normalizar_telefono(telefono: str, codigo_pais: str = CODIGO_PAIS_DEFAULT) -> str:
    """Normaliza a E.164. Si falta '+', antepone +52 (México) en números de 10 dígitos."""
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


def extraer_telefono(texto: str) -> Optional[str]:
    candidatos = re.findall(r"\+?\d[\d\s\-().]{7,18}\d", texto or "")
    for candidato in candidatos:
        if 10 <= len(re.sub(r"\D", "", candidato)) <= 15:
            return candidato
    return None


def extraer_tarea_llamada(prompt: str, destinatario: str = "el contacto") -> str:
    mision = re.search(
        r"(?:para|y dile que|dile que|decirle que|con el mensaje|objetivo[:\s])\s+(.+)$",
        prompt or "",
        re.IGNORECASE,
    )
    if mision:
        return (
            f"Eres Jarvis. Llamas a {destinatario}. "
            f"Objetivo: {mision.group(1).strip(' .')}. Habla en español fluido."
        )
    return (
        f"Eres Jarvis. Llamas a {destinatario}. "
        f"Objetivo: {prompt}. Habla en español fluido."
    )


def extraer_destinatario(prompt: str) -> str:
    sin_tel = re.sub(r"\+?\d[\d\s\-().]{7,18}\d", " ", prompt or "")
    m_dest = re.search(
        r"(?:llama(?:r)?|llámale|llamale|llamada)\s+(?:a|al)\s+"
        r"([A-Za-zÁÉÍÓÚáéíóúñÑ][A-Za-zÁÉÍÓÚáéíóúñÑ\s]{1,40}?)"
        r"(?:\s+(?:al|para|y|que)|$|,)",
        sin_tel,
        re.IGNORECASE,
    )
    if not m_dest:
        return "el contacto"
    nombre = m_dest.group(1).strip()
    if nombre.lower() in {
        "el", "la", "al", "una", "un", "llamada",
        "numero", "número", "telefono", "teléfono",
    }:
        return "el contacto"
    return nombre


def _mensaje_error_bland(resp: httpx.Response) -> str:
    """Devuelve el error exacto del cuerpo de Bland para diagnóstico."""
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip() or f"HTTP {resp.status_code}"

    if isinstance(data, dict):
        if data.get("errors") not in (None, "", []):
            errors = data["errors"]
            if isinstance(errors, list):
                return " ".join(str(item) for item in errors)
            return str(errors)
        for key in ("message", "error", "msg"):
            if data.get(key):
                return str(data[key])
        return str(data)
    return str(data)


def hacer_llamada_bland(phone_number: str, prompt_or_task: str) -> str:
    """Dispara una llamada en Bland AI y reporta éxito o el error exacto de la API."""
    api_key = obtener_bland_api_key()
    if not api_key:
        return "Falta BLAND_API_KEY en las variables de entorno."

    phone_number = normalizar_telefono(phone_number)
    if not phone_number:
        return "No pude identificar un número telefónico válido."

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "phone_number": phone_number,
        "task": prompt_or_task,
        "voice": "nat",
        "reduce_latency": True,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(BLAND_API_URL, headers=headers, json=payload)

        if resp.status_code != 200:
            return _mensaje_error_bland(resp)

        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        estado = data.get("status") or "ok"
        return f"Enlazando llamada a {phone_number}. Estado Bland: {estado}."
    except Exception as e:
        print(f"[BLAND ERROR] {e}")
        return f"Error al contactar Bland AI: {e}"
