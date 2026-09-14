"""Zentrale Konfiguration für den Comic Maker.

Alle Werte kommen aus der .env-Datei (python-dotenv). So lässt sich das
Verhalten des Systems - inklusive der versteckten System-Prompts für
Ollama - ohne Code-Änderung anpassen.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


def _str(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is None:
        return default
    # \n aus der .env-Datei als echten Zeilenumbruch interpretieren
    return value.replace("\\n", "\n").strip()


def _int(key: str, default: int) -> int:
    try:
        return int(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


def _bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "ja", "on"}


# ---------------------------------------------------------------- Ollama
OLLAMA_HOST = _str("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = _str("OLLAMA_MODEL", "gemma4:latest")
OLLAMA_TIMEOUT = _float("OLLAMA_TIMEOUT", 300.0)
OLLAMA_TEMPERATURE = _float("OLLAMA_TEMPERATURE", 0.8)
OLLAMA_NUM_PREDICT = _int("OLLAMA_NUM_PREDICT", 1600)

# ------------------------------------------------------- ComfyUI / Krea2
COMFY_SERVER_URL = _str("COMFY_SERVER_URL", "http://127.0.0.1:8188").rstrip("/")
_workflow = _str("COMFY_WORKFLOW", "krea2.json")
COMFY_WORKFLOW = str(Path(_workflow) if Path(_workflow).is_absolute() else BASE_DIR / _workflow)
COMFY_TIMEOUT = _float("COMFY_TIMEOUT", 900.0)
# Erwartete Dauer eines Jobs - nur für die Fortschrittsanzeige
COMFY_EXPECTED_SECONDS = _float("COMFY_EXPECTED_SECONDS", 240.0)

COMFY_PAGE_ASPECT_RATIO = _str("COMFY_PAGE_ASPECT_RATIO", "3:4 (Portrait Standard)")
COMFY_PAGE_MEGAPIXELS = _float("COMFY_PAGE_MEGAPIXELS", 1.5)
COMFY_PAGE_STEPS = _int("COMFY_PAGE_STEPS", 8)

COMFY_SIGNATURE_ASPECT_RATIO = _str("COMFY_SIGNATURE_ASPECT_RATIO", "1:1 (Square)")
COMFY_SIGNATURE_MEGAPIXELS = _float("COMFY_SIGNATURE_MEGAPIXELS", 1.0)
COMFY_SIGNATURE_STEPS = _int("COMFY_SIGNATURE_STEPS", 8)

COMFY_ENABLE_LORA = _bool("COMFY_ENABLE_LORA", False)
COMFY_REFINE_PROMPT = _bool("COMFY_REFINE_PROMPT", False)

IMAGE_GEN_API_URL = _str("IMAGE_GEN_API_URL", "")

# ----------------------------------------------------------- Druckserver
PRINT_SERVER_SCHEME = _str("PRINT_SERVER_SCHEME", "http")
PRINT_SERVER_HOST = _str("PRINT_SERVER_HOST", "print-server.local")
PRINT_SERVER_PORT = _int("PRINT_SERVER_PORT", 80)
PRINT_SERVER_ENDPOINT = _str("PRINT_SERVER_ENDPOINT", "/api/v1/upload")
PRINT_SERVER_TIMEOUT = _float("PRINT_SERVER_TIMEOUT", 60.0)
_print_url = _str("PRINT_SERVER_URL", "")


def print_server_url() -> str:
    """Vollständige URL des Druckserver-Endpunkts."""
    if _print_url:
        return _print_url
    host = PRINT_SERVER_HOST
    default_port = 443 if PRINT_SERVER_SCHEME == "https" else 80
    netloc = host if PRINT_SERVER_PORT == default_port else "%s:%d" % (host, PRINT_SERVER_PORT)
    endpoint = PRINT_SERVER_ENDPOINT if PRINT_SERVER_ENDPOINT.startswith("/") else "/" + PRINT_SERVER_ENDPOINT
    return "%s://%s%s" % (PRINT_SERVER_SCHEME, netloc, endpoint)


# --------------------------------------------------------------- Ausgabe
OUTPUT_DIR = BASE_DIR / _str("OUTPUT_DIR", "output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- Gradio
GRADIO_SERVER_NAME = _str("GRADIO_SERVER_NAME", "127.0.0.1")
GRADIO_SERVER_PORT = _int("GRADIO_SERVER_PORT", 7861)
GRADIO_SHARE = _bool("GRADIO_SHARE", False)

# ------------------------------------------- Versteckter Kontext/Prompts
SYSTEM_PROMPT_GERMAN = _str(
    "SYSTEM_PROMPT_GERMAN",
    "Du bist ein kreativer Comic-Autor für Jugendliche. Schreibe ausschließlich "
    "auf Deutsch, in einfacher Sprache für 12-Jährige.",
)
PANEL_FORMAT_PROMPT = _str("PANEL_FORMAT_PROMPT", "")
IMAGE_STYLE_PROMPT = _str("IMAGE_STYLE_PROMPT", "clean modern comic book page, bright colors")
IMAGE_NEGATIVE_HINTS = _str("IMAGE_NEGATIVE_HINTS", "")
SIGNATURE_STYLE_PROMPT = _str("SIGNATURE_STYLE_PROMPT", "graffiti tag logo, spray paint style")

MIN_PANELS = 4
MAX_PANELS = 6
