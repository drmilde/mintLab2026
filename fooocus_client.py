"""
Anbindung an einen laufenden Fooocus-Server.

Fooocus stellt keine eigene REST-Schnittstelle bereit, sondern ist selbst eine
Gradio-Anwendung (Version 3.x). Dieses Modul spricht deshalb direkt das
Gradio-Queue-Protokoll:

1.  ``GET /config``          liefert alle Bedienelemente inklusive ihrer aktuell
                             eingestellten Werte. Daraus wird die Argumentliste
                             fuer den Generieren-Knopf zusammengebaut, so dass
                             alle Einstellungen des Fooocus-Servers uebernommen
                             werden und nur Prompt, Stil usw. ueberschrieben
                             werden muessen.
2.  ``ws /queue/join`` (1)   ruft ``get_task`` auf und legt den Auftrag an.
3.  ``ws /queue/join`` (2)   ruft ``generate_clicked`` auf, meldet zwischendurch
                             den Fortschritt und liefert am Ende die Pfade der
                             erzeugten Bilder.

Beide Aufrufe teilen sich denselben ``session_hash`` - nur dann findet der
zweite Aufruf den im ersten Schritt angelegten Auftrag.
"""

from __future__ import annotations

import os
import re
import json
import uuid
import tempfile
from dataclasses import dataclass, field
from urllib.parse import urlparse, quote

import requests
from websockets.sync.client import connect as ws_connect

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env(name, str(default))).strip())
    except ValueError:
        return default


DEFAULT_PROMPT_PREFIX = (
    "comic book panel, clean bold line art, bright friendly colors, "
    "cheerful all-ages illustration,"
)
DEFAULT_PROMPT_SUFFIX = "highly detailed, dynamic composition, no text, no speech bubbles"
DEFAULT_NEGATIVE_PROMPT = (
    "text, letters, words, speech bubbles, watermark, signature, "
    "blurry, deformed hands, extra limbs, scary, gore, nsfw"
)


@dataclass
class FooocusConfig:
    url: str = field(default_factory=lambda: _env("FOOOCUS_URL", "http://127.0.0.1:7865/"))
    timeout: int = field(default_factory=lambda: _env_int("FOOOCUS_TIMEOUT", 900))

    # Versteckter Kontext fuer die Bildgenerierung
    prompt_prefix: str = field(default_factory=lambda: _env("FOOOCUS_PROMPT_PREFIX", DEFAULT_PROMPT_PREFIX))
    prompt_suffix: str = field(default_factory=lambda: _env("FOOOCUS_PROMPT_SUFFIX", DEFAULT_PROMPT_SUFFIX))
    negative_prompt: str = field(default_factory=lambda: _env("FOOOCUS_NEGATIVE_PROMPT", DEFAULT_NEGATIVE_PROMPT))

    # Optionale Ueberschreibungen der Fooocus-Einstellungen ("" = so lassen, wie
    # es im Fooocus-Fenster eingestellt ist)
    styles: str = field(default_factory=lambda: _env("FOOOCUS_STYLES", ""))
    performance: str = field(default_factory=lambda: _env("FOOOCUS_PERFORMANCE", ""))
    aspect_ratio: str = field(default_factory=lambda: _env("FOOOCUS_ASPECT_RATIO", ""))
    output_format: str = field(default_factory=lambda: _env("FOOOCUS_OUTPUT_FORMAT", ""))
    image_number: int = field(default_factory=lambda: _env_int("FOOOCUS_IMAGE_NUMBER", 1))
    seed: str = field(default_factory=lambda: _env("FOOOCUS_SEED", ""))

    # Welcher Abschnitt der Panel-Beschreibung wird als Bild-Prompt verwendet?
    # Leer lassen, um den gesamten Text der Textbox zu verwenden.
    prompt_section: str = field(default_factory=lambda: _env("IMAGE_PROMPT_SECTION", "BILD"))


class FooocusError(RuntimeError):
    """Fehler bei der Kommunikation mit dem Fooocus-Server."""


# ---------------------------------------------------------------------------
# Prompt-Aufbau
# ---------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")


def extract_section(text: str, section: str) -> str:
    """Holt z.B. den ``BILD:``-Abschnitt aus einer Panel-Beschreibung.

    Der Abschnitt endet bei der naechsten Zeile, die mit einem Schluesselwort in
    Grossbuchstaben und Doppelpunkt beginnt (TEXT:, DIALOG:, ...). Wird der
    Abschnitt nicht gefunden, kommt der komplette Text zurueck.
    """
    if not section:
        return text.strip()
    pattern = re.compile(
        rf"^[ \t]*{re.escape(section)}[ \t]*:[ \t]*(.*?)(?=^[ \t]*[A-ZÄÖÜ][A-ZÄÖÜ ]{{1,20}}:|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return text.strip()
    return " ".join(match.group(1).split()).strip()


def wrap_prompt(core: str, config: FooocusConfig) -> str:
    """Legt den in der .env konfigurierten versteckten Kontext um eine Beschreibung."""
    parts = [config.prompt_prefix.strip(), core.strip(), config.prompt_suffix.strip()]
    return " ".join(part for part in parts if part).strip()


def build_image_prompt(panel_text: str, config: FooocusConfig) -> str:
    """Panel-Beschreibung plus den in der .env konfigurierten versteckten Kontext."""
    return wrap_prompt(extract_section(panel_text, config.prompt_section), config)


# ---------------------------------------------------------------------------
# Gradio-Protokoll
# ---------------------------------------------------------------------------


def _ws_url(http_url: str) -> str:
    parsed = urlparse(http_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/queue/join"


def _progress_text(html) -> str:
    """Macht aus dem Fortschritts-HTML von Fooocus einen kurzen Text."""
    if isinstance(html, dict):  # Gradio schickt Updates als {"value": ..., "__type__": "update"}
        html = html.get("value")
    if not isinstance(html, str):
        return ""
    match = re.search(r"<span>(.*?)</span>", html, re.DOTALL)
    text = match.group(1) if match else _TAGS.sub(" ", html)
    return " ".join(text.split())


def _call(ws_url: str, fn_index: int, data: list, session_hash: str, timeout: int, on_progress=None):
    """Ein Aufruf ueber die Gradio-Warteschlange. Gibt die Ausgabedaten zurueck."""
    try:
        connection = ws_connect(ws_url, max_size=None, open_timeout=30, close_timeout=5)
    except OSError as error:
        raise FooocusError(f"Keine Verbindung zum Fooocus-Server: {error}") from error

    with connection as socket:
        while True:
            try:
                message = json.loads(socket.recv(timeout=timeout))
            except TimeoutError as error:
                raise FooocusError("Zeitueberschreitung beim Warten auf Fooocus.") from error

            kind = message.get("msg")
            if kind == "send_hash":
                socket.send(json.dumps({"fn_index": fn_index, "session_hash": session_hash}))
            elif kind == "send_data":
                socket.send(
                    json.dumps(
                        {
                            "fn_index": fn_index,
                            "data": data,
                            "session_hash": session_hash,
                            "event_data": None,
                            "trigger_id": None,
                        }
                    )
                )
            elif kind == "estimation":
                rank = message.get("rank")
                if on_progress and rank:
                    on_progress(f"In der Warteschlange, Platz {rank + 1} ...")
            elif kind == "process_starts":
                if on_progress:
                    on_progress("Fooocus hat angefangen zu zeichnen ...")
            elif kind == "process_generating":
                output = message.get("output") or {}
                if output.get("error"):
                    raise FooocusError(str(output["error"]))
                if on_progress:
                    values = output.get("data") or []
                    text = _progress_text(values[0] if values else "")
                    if text:
                        on_progress(text)
            elif kind == "process_completed":
                output = message.get("output") or {}
                if output.get("error"):
                    raise FooocusError(str(output["error"]))
                return output.get("data") or []
            elif kind == "queue_full":
                raise FooocusError("Die Warteschlange von Fooocus ist voll. Bitte kurz warten.")


def _load_layout(config: FooocusConfig) -> tuple:
    """Liest /config und ermittelt Argumentliste und Funktionsindizes."""
    url = config.url.rstrip("/") + "/config"
    try:
        raw = requests.get(url, timeout=15).json()
    except requests.RequestException as error:
        raise FooocusError(f"Fooocus unter {config.url} ist nicht erreichbar ({error}).") from error
    except ValueError as error:
        raise FooocusError(f"Unerwartete Antwort von {url}.") from error

    components = {c["id"]: c for c in raw.get("components", [])}
    dependencies = raw.get("dependencies", [])

    # get_task: die Funktion mit den meisten Eingaben.
    # generate_clicked: die darauffolgende Funktion, die eine Gallery ausgibt.
    task_index = max(
        range(len(dependencies)),
        key=lambda i: len(dependencies[i].get("inputs", [])),
        default=-1,
    )
    if task_index < 0 or len(dependencies[task_index].get("inputs", [])) < 20:
        raise FooocusError("Auf dem Server unter dieser Adresse wurde keine Fooocus-Oberflaeche gefunden.")

    generate_index = None
    for i in range(task_index + 1, len(dependencies)):
        outputs = dependencies[i].get("outputs", [])
        types = [components.get(o, {}).get("type") for o in outputs]
        if types.count("gallery") >= 1 and "html" in types:
            generate_index = i
            break
    if generate_index is None:
        raise FooocusError("Der Generieren-Knopf von Fooocus konnte nicht gefunden werden.")

    inputs = dependencies[task_index]["inputs"]
    specs = [components.get(cid, {}) for cid in inputs]
    args = [None if s.get("type") == "state" else s.get("props", {}).get("value") for s in specs]
    return specs, args, task_index, generate_index


def _find(specs: list, label: str) -> int:
    for index, spec in enumerate(specs):
        if spec.get("props", {}).get("label") == label:
            return index
    return -1


def _match_choice(choices, wanted: str):
    """Findet einen Auswahlwert, auch wenn er HTML enthaelt (Aspect Ratios)."""

    def normalise(value: str) -> str:
        value = _TAGS.sub(" ", str(value))
        value = value.replace("×", "x").replace("*", "x").replace("∣", "|")
        return " ".join(value.split()).lower()

    target = normalise(wanted)
    for choice in choices or []:
        value = choice[1] if isinstance(choice, (list, tuple)) and len(choice) == 2 else choice
        current = normalise(value)
        if current == target or current.startswith(target):
            return value
    return None


def _apply_overrides(specs: list, args: list, prompt: str, config: FooocusConfig) -> list:
    """Setzt Prompt und die in der .env gewuenschten Einstellungen."""
    negative_index = _find(specs, "Negative Prompt")
    if negative_index < 1:
        raise FooocusError("Das Prompt-Feld von Fooocus konnte nicht gefunden werden.")
    args[negative_index - 1] = prompt
    args[negative_index] = config.negative_prompt

    def set_value(label: str, value):
        index = _find(specs, label)
        if index >= 0:
            args[index] = value

    def set_choice(label: str, wanted: str):
        index = _find(specs, label)
        if index < 0 or not wanted:
            return
        choices = specs[index].get("props", {}).get("choices")
        match = _match_choice(choices, wanted)
        if match is not None:
            args[index] = match

    if config.image_number > 0:
        set_value("Image Number", config.image_number)
    if config.seed.strip():
        seed_index = _find(specs, "Seed")
        if seed_index >= 0:
            args[seed_index] = config.seed.strip()
            # Zufallszahl abschalten, sonst wird der Seed ignoriert
            random_index = _find(specs, "Random")
            if random_index >= 0:
                args[random_index] = False
    if config.styles.strip():
        set_value("Selected Styles", [s.strip() for s in config.styles.split(",") if s.strip()])
    set_choice("Performance", config.performance)
    set_choice("Aspect Ratios", config.aspect_ratio)
    set_choice("Output Format", config.output_format)
    return args


def _local_path(entry, config: FooocusConfig) -> str:
    """Macht aus einem Gallery-Eintrag einen lokal lesbaren Dateipfad."""
    if isinstance(entry, dict):
        path = entry.get("name") or entry.get("path") or ""
    else:
        path = str(entry or "")
    if not path:
        raise FooocusError("Fooocus hat kein Bild zurueckgeliefert.")
    if os.path.exists(path):
        return path
    # Fooocus laeuft auf einem anderen Rechner: Bild ueber /file= holen
    url = config.url.rstrip("/") + "/file=" + quote(path)
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as error:
        raise FooocusError(f"Das Bild konnte nicht geladen werden: {error}") from error
    suffix = os.path.splitext(path)[1] or ".png"
    handle, target = tempfile.mkstemp(prefix="comic_panel_", suffix=suffix)
    with os.fdopen(handle, "wb") as file:
        file.write(response.content)
    return target


# ---------------------------------------------------------------------------
# Oeffentliche Schnittstelle
# ---------------------------------------------------------------------------


def generate_image(prompt: str, config: FooocusConfig, on_progress=None) -> str:
    """Erzeugt ein Bild und gibt den Pfad zur Bilddatei zurueck."""
    specs, args, task_index, generate_index = _load_layout(config)
    args = _apply_overrides(specs, args, prompt, config)

    ws_url = _ws_url(config.url)
    session_hash = str(uuid.uuid4())

    if on_progress:
        on_progress("Auftrag wird an Fooocus uebergeben ...")
    _call(ws_url, task_index, args, session_hash, config.timeout, on_progress)
    data = _call(ws_url, generate_index, [None], session_hash, config.timeout, on_progress)

    gallery = data[-1] if data else None
    if isinstance(gallery, dict):
        gallery = gallery.get("value")
    if not gallery:
        raise FooocusError("Fooocus hat kein Bild zurueckgeliefert (wurde die Erzeugung abgebrochen?).")
    return _local_path(gallery[0], config)


def check_server(config: FooocusConfig) -> str:
    """Kurzer Statustext fuer die Oberflaeche."""
    try:
        _load_layout(config)
    except FooocusError as error:
        return f"Fooocus: {error}"
    return f"Fooocus ist bereit unter {config.url}"
