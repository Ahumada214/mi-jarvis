"""Sincronización de notas y reportes hacia Obsidian vía GitHub API."""

import os
import re
from datetime import datetime
from typing import List, Optional

try:
    from github import Github, GithubException
except ImportError:
    Github = None
    GithubException = Exception

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
OBSIDIAN_FOLDER = os.environ.get("OBSIDIAN_FOLDER", "Jarvis_Notes").strip() or "Jarvis_Notes"


def sanitizar_titulo(title: str) -> str:
    """Convierte un título en un nombre de archivo .md válido."""
    if not title or not str(title).strip():
        return "nota_sin_titulo"

    limpio = str(title).strip()
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", limpio)
    limpio = re.sub(r"\s+", "_", limpio)
    limpio = re.sub(r"_+", "_", limpio)
    limpio = limpio.strip("._ ")
    return (limpio or "nota_sin_titulo")[:120]


def _normalizar_tags(tags: Optional[List[str]]) -> List[str]:
    if not tags:
        return ["jarvis"]

    normalizados = []
    for tag in tags:
        limpio = re.sub(r"[^a-zA-Z0-9_\-áéíóúñÁÉÍÓÚÑ]", "", str(tag).strip().replace(" ", "_"))
        if limpio:
            normalizados.append(limpio.lower())
    return normalizados or ["jarvis"]


def _construir_nota(title: str, content: str, tags: List[str]) -> str:
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M")
    titulo_yaml = str(title).replace('"', '\\"')
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    return (
        "---\n"
        f'title: "{titulo_yaml}"\n'
        f'date: "{fecha_actual}"\n'
        f'source: "Jarvis Backend"\n'
        "tags:\n"
        f"{tags_yaml}\n"
        "---\n\n"
        f"{content.rstrip()}\n"
    )


def save_to_obsidian(title: str, content: str, tags: Optional[List[str]] = None) -> bool:
    """Crea o actualiza una nota Markdown en el repositorio de Obsidian (GitHub)."""
    try:
        if Github is None:
            print("[OBSIDIAN] PyGithub no está instalado. Se omite la sincronización.")
            return False

        if not GITHUB_TOKEN or not GITHUB_REPO:
            print("[OBSIDIAN] Faltan GITHUB_TOKEN o GITHUB_REPO. Se omite la sincronización.")
            return False

        filename = sanitizar_titulo(title)
        ruta = f"{OBSIDIAN_FOLDER}/{filename}.md"
        nota = _construir_nota(title, content, _normalizar_tags(tags))

        cliente = Github(GITHUB_TOKEN)
        repo = cliente.get_repo(GITHUB_REPO)
        branch = repo.default_branch

        try:
            existente = repo.get_contents(ruta, ref=branch)
            repo.update_file(
                path=ruta,
                message=f"Jarvis: actualizar nota {filename}",
                content=nota,
                sha=existente.sha,
                branch=branch,
            )
            print(f"[OBSIDIAN] Nota actualizada en {GITHUB_REPO}:{ruta} (branch {branch})")
            return True
        except GithubException as e:
            if getattr(e, "status", None) != 404:
                raise
            repo.create_file(
                path=ruta,
                message=f"Jarvis: crear nota {filename}",
                content=nota,
                branch=branch,
            )
            print(f"[OBSIDIAN] Nota creada en {GITHUB_REPO}:{ruta} (branch {branch})")
            return True

    except GithubException as e:
        print(f"[OBSIDIAN ERROR] GitHub API ({getattr(e, 'status', '?')}): {e}")
        return False
    except Exception as e:
        print(f"[OBSIDIAN ERROR] No se pudo guardar '{title}': {e}")
        return False
