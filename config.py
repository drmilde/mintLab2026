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


# ============================================================
#  Laufzeit-Konfiguration (Tab "Config" in der Oberfläche)
# ============================================================
#
#  Alle hier gelisteten Schlüssel lassen sich in der Oberfläche
#  anzeigen, zur Laufzeit übernehmen und zurück in die .env-Datei
#  schreiben. Die Handler lesen ihre Werte über ``config.<NAME>``,
#  darum wirkt ein Übernehmen sofort - ohne Neustart.

#: Schlüssel -> Datentyp ("text" = mehrzeilig, sonst wie der Name sagt)
SETTING_TYPES = {
    # System-Prompts Text
    "SYSTEM_PROMPT_GERMAN": "text",
    "PANEL_FORMAT_PROMPT": "text",
    # System-Prompts Bild
    "IMAGE_STYLE_PROMPT": "text",
    "IMAGE_NEGATIVE_HINTS": "text",
    "SIGNATURE_STYLE_PROMPT": "text",
    # Sprachmodell
    "OLLAMA_HOST": "str",
    "OLLAMA_MODEL": "str",
    "OLLAMA_TIMEOUT": "float",
    "OLLAMA_TEMPERATURE": "float",
    "OLLAMA_NUM_PREDICT": "int",
    # Bild-Server
    "COMFY_SERVER_URL": "str",
    "COMFY_WORKFLOW": "str",
    "COMFY_TIMEOUT": "float",
    "COMFY_EXPECTED_SECONDS": "float",
    "COMFY_ENABLE_LORA": "bool",
    "COMFY_REFINE_PROMPT": "bool",
    # Bildformate
    "COMFY_PAGE_ASPECT_RATIO": "str",
    "COMFY_PAGE_MEGAPIXELS": "float",
    "COMFY_PAGE_STEPS": "int",
    "COMFY_SIGNATURE_ASPECT_RATIO": "str",
    "COMFY_SIGNATURE_MEGAPIXELS": "float",
    "COMFY_SIGNATURE_STEPS": "int",
    # Druckserver
    "PRINT_SERVER_SCHEME": "str",
    "PRINT_SERVER_HOST": "str",
    "PRINT_SERVER_PORT": "int",
    "PRINT_SERVER_ENDPOINT": "str",
    "PRINT_SERVER_TIMEOUT": "float",
    "PRINT_SERVER_URL": "str",
    # Ausgabe / Oberfläche
    "OUTPUT_DIR": "str",
    "GRADIO_SERVER_NAME": "str",
    "GRADIO_SERVER_PORT": "int",
    "GRADIO_SHARE": "bool",
}

#: Diese Werte greifen erst nach einem Neustart der Anwendung.
RESTART_KEYS = {"GRADIO_SERVER_NAME", "GRADIO_SERVER_PORT", "GRADIO_SHARE"}


def _format_number(value: float, as_int: bool) -> str:
    if as_int:
        return str(int(round(value)))
    text = ("%f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def format_value(key: str, value) -> str:
    """Einen Wert aus der Oberfläche in seine .env-Schreibweise bringen."""
    kind = SETTING_TYPES.get(key, "str")
    if value is None:
        return ""
    if kind == "bool":
        if isinstance(value, str):
            return "true" if value.strip().lower() in {"1", "true", "yes", "ja", "on"} else "false"
        return "true" if value else "false"
    if kind in ("int", "float"):
        if isinstance(value, str):
            raw = value.strip().replace(",", ".")
            if not raw:
                raise ValueError("'%s' braucht eine Zahl." % key)
            try:
                number = float(raw)
            except ValueError:
                raise ValueError("'%s': '%s' ist keine Zahl." % (key, value)) from None
        else:
            number = float(value)
        return _format_number(number, kind == "int")
    return str(value).replace("\r\n", "\n")


def parse_value(key: str, raw: str):
    """Eine .env-Schreibweise in den passenden Python-Wert umwandeln."""
    kind = SETTING_TYPES.get(key, "str")
    text = "" if raw is None else str(raw)
    if kind == "bool":
        return text.strip().lower() in {"1", "true", "yes", "ja", "on"}
    if kind == "int":
        return int(round(float(text.strip().replace(",", ".") or 0)))
    if kind == "float":
        return float(text.strip().replace(",", ".") or 0)
    return text.replace("\\n", "\n").strip()


def _short_path(value) -> str:
    """Pfade innerhalb des Projektordners kurz (relativ) anzeigen."""
    path = Path(str(value))
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def current_values() -> dict:
    """Aktuell gültige Werte als Text - genau so, wie sie in der .env stehen."""
    values = {}
    for key, kind in SETTING_TYPES.items():
        if key == "PRINT_SERVER_URL":
            current = _print_url
        elif key in ("OUTPUT_DIR", "COMFY_WORKFLOW"):
            current = _short_path(globals()[key])
        else:
            current = globals().get(key, "")
        if kind == "bool":
            values[key] = "true" if current else "false"
        elif kind in ("int", "float"):
            values[key] = _format_number(float(current or 0), kind == "int")
        else:
            values[key] = str(current)
    return values


def apply_settings(values: dict) -> list:
    """Werte prüfen und sofort für alle Handler gültig machen.

    Gibt eine Liste mit Hinweisen zurück (z. B. "Neustart nötig").
    Bei ungültigen Zahlen wird ein ``ValueError`` ausgelöst.
    """
    global _print_url, OUTPUT_DIR, COMFY_WORKFLOW

    parsed = {}
    for key, raw in values.items():
        if key not in SETTING_TYPES:
            continue
        try:
            parsed[key] = parse_value(key, raw)
        except (TypeError, ValueError):
            raise ValueError("'%s': '%s' ist keine gültige Zahl." % (key, raw)) from None

    previous = current_values()
    changed = {key for key, value in parsed.items()
               if previous.get(key) != format_value(key, value)}

    notes = []
    for key, value in parsed.items():
        if key in ("OLLAMA_HOST", "COMFY_SERVER_URL"):
            globals()[key] = str(value).rstrip("/")
        elif key == "PRINT_SERVER_URL":
            _print_url = str(value)
        elif key == "COMFY_WORKFLOW":
            path = Path(str(value))
            COMFY_WORKFLOW = str(path if path.is_absolute() else BASE_DIR / path)
            if not Path(COMFY_WORKFLOW).is_file():
                notes.append("Workflow-Datei nicht gefunden: %s" % COMFY_WORKFLOW)
        elif key == "OUTPUT_DIR":
            path = Path(str(value))
            new_dir = path if path.is_absolute() else BASE_DIR / path
            new_dir.mkdir(parents=True, exist_ok=True)
            OUTPUT_DIR = new_dir
            if key in changed:
                notes.append("Neue Dateien landen in %s." % OUTPUT_DIR)
        else:
            globals()[key] = value
        # Kindprozesse / ein späteres Neuladen sollen denselben Stand sehen
        os.environ[key] = format_value(key, value)

    if RESTART_KEYS & changed:
        notes.append("Die geänderten Gradio-Einstellungen greifen erst nach einem "
                     "Neustart der App.")
    return notes


def _env_literal(value: str) -> str:
    """Wert so escapen, dass python-dotenv ihn wieder korrekt einliest."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r\n", "\n").replace("\n", "\\n")
    return '"%s"' % escaped


def save_settings(values: dict) -> Path:
    """Werte in die .env-Datei schreiben (Kommentare bleiben erhalten).

    Vor dem Überschreiben wird eine Sicherungskopie ``.env.bak`` angelegt.
    """
    pending = {key: format_value(key, value)
               for key, value in values.items() if key in SETTING_TYPES}

    original = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    if original:
        (ENV_PATH.parent / ".env.bak").write_text(original, encoding="utf-8")

    lines = original.splitlines()
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                out.append("%s=%s" % (key, _env_literal(pending.pop(key))))
                continue
        out.append(line)

    if pending:
        out.append("")
        out.append("# ---------- von der Config-Oberfläche ergänzt ----------")
        for key, value in pending.items():
            out.append("%s=%s" % (key, _env_literal(value)))

    ENV_PATH.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return ENV_PATH


def reload_settings() -> dict:
    """.env erneut einlesen, anwenden und die neuen Werte zurückgeben."""
    load_dotenv(ENV_PATH, override=True)
    raw = {key: os.getenv(key, "") for key in SETTING_TYPES}
    apply_settings(raw)
    return current_values()
