"""Bildgenerierung über einen ComfyUI-Server mit dem Krea2-Workflow.

Die Kommunikation folgt dem Referenz-Skript comfy_krea2.py: Workflow aus
krea2.json laden, Prompt/Seed/Größe einsetzen, in die Warteschlange
stellen, auf /history warten und das Bild über /view herunterladen.
Es wird nur die Standardbibliothek benutzt.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import config
from llm_handler import Character, Panel

# Node-IDs aus krea2.json (siehe comfy_krea2.py)
NODE_USER_PROMPT = "30:19"   # PrimitiveStringMultiline (User Prompt)
NODE_SAVE_IMAGE = "29"       # SaveImage
NODE_KSAMPLER = "30:3"       # KSampler
NODE_RESOLUTION = "49"       # ResolutionSelector
NODE_LATENT = "30:5"         # EmptyLatentImage
NODE_ENABLE_LORA = "30:23"   # Boolean (Enable LoRA?)
NODE_REFINE_PROMPT = "30:24"  # Boolean (Refine Prompt?)

ASPECT_RATIOS = [
    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
    "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
]

# Panel-Anzahl -> Beschreibung des Seitenlayouts für den Bild-Prompt
PANEL_LAYOUTS = {
    4: "page layout: 2x2 grid, four equally sized rectangular panels",
    5: "page layout: two wide panels in the top rows and a row of three smaller panels, five panels total",
    6: "page layout: 3 rows x 2 columns grid, six equally sized rectangular panels",
}


class ImageError(RuntimeError):
    """Fehler bei der Kommunikation mit dem ComfyUI-Server."""


# ------------------------------------------------------------- HTTP-Helfer

def _http_json(url: str, payload: Optional[dict] = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def server_online() -> bool:
    """Kurzer Check, ob der ComfyUI-Server erreichbar ist."""
    try:
        _http_json(config.COMFY_SERVER_URL + "/system_stats", timeout=4.0)
        return True
    except Exception:
        return False


# ------------------------------------------------------------- Prompt-Bau

def _sentence(text: str) -> str:
    """Text saeubern: Leerzeichen und ein abschliessender Punkt entfernen.

    So entstehen beim Zusammensetzen des Prompts keine doppelten Punkte.
    """
    return (text or "").strip().rstrip(".").strip()


def _character_sheet(characters: List[Character]) -> str:
    filled = [c for c in characters if c.is_filled]
    if not filled:
        return ""
    parts = []
    for c in filled:
        desc = c.appearance.strip() or c.personality.strip() or "young curious character"
        parts.append("%s (%s)" % (c.name.strip(), desc))
    return "consistent recurring characters on every panel: " + "; ".join(parts)


def build_page_prompt(
    panels: List[Panel],
    characters: List[Character],
    style: str = "",
    comic_title: str = "",
    artist_acronym: str = "",
) -> str:
    """Setzt den kompletten Bild-Prompt für die Comic-Seite zusammen."""
    usable = [p for p in panels if p.description.strip() or p.narration.strip() or p.dialogue]
    if not usable:
        usable = panels
    count = max(config.MIN_PANELS, min(config.MAX_PANELS, len(usable) or config.MIN_PANELS))

    lines: List[str] = []
    lines.append("A single comic book page in German with exactly %d panels." % count)
    layout = PANEL_LAYOUTS.get(count, PANEL_LAYOUTS[config.MIN_PANELS])
    lines.append(layout + ", white gutters between the panels, thin black panel borders.")

    if comic_title.strip():
        lines.append('Title banner at the top of the page, it reads exactly: "%s"'
                     % comic_title.strip())

    style_text = style.strip() or config.IMAGE_STYLE_PROMPT
    lines.append("Style: " + style_text)
    if style.strip() and config.IMAGE_STYLE_PROMPT:
        lines.append("Also: " + config.IMAGE_STYLE_PROMPT)

    sheet = _character_sheet(characters)
    if sheet:
        lines.append(sheet + ".")

    lines.append("")
    lines.append("Panel content (top-left to bottom-right, reading order):")
    for i, panel in enumerate(usable[:count], start=1):
        block = ["Panel %d: %s" % (i, _sentence(panel.description) or "the story continues")]
        if panel.narration.strip():
            block.append('caption box at the top reads: "%s"' % _sentence(panel.narration))
        for line in panel.dialogue:
            block.append("speech balloon: %s" % _sentence(line))
        lines.append(". ".join(block) + ".")

    if artist_acronym.strip():
        lines.append("")
        lines.append('Small artist signature "%s" in the bottom right corner of the page.'
                     % artist_acronym.strip())
    if config.IMAGE_NEGATIVE_HINTS:
        lines.append(config.IMAGE_NEGATIVE_HINTS)

    return "\n".join(lines)


def build_signature_prompt(acronym: str, artist_name: str = "") -> str:
    """Prompt für das Graffiti-Signatur-Logo."""
    tag = (acronym or artist_name or "ART").strip()
    parts = ['A graffiti signature logo showing the letters "%s".' % tag,
             config.SIGNATURE_STYLE_PROMPT]
    if artist_name.strip() and artist_name.strip().lower() != tag.lower():
        parts.append('The tag stands for the artist "%s".' % artist_name.strip())
    parts.append("only these letters, no other text, no watermark")
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------- Workflow-Bau

def _load_workflow() -> dict:
    path = Path(config.COMFY_WORKFLOW)
    if not path.is_file():
        raise ImageError("Workflow-Datei nicht gefunden: %s" % path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_workflow(
    prompt: str,
    filename_prefix: str,
    aspect_ratio: str,
    megapixels: float,
    steps: int,
    seed: Optional[int] = None,
    enable_lora: Optional[bool] = None,
    refine_prompt: Optional[bool] = None,
) -> tuple:
    wf = _load_workflow()
    wf[NODE_USER_PROMPT]["inputs"]["value"] = prompt
    wf[NODE_SAVE_IMAGE]["inputs"]["filename_prefix"] = filename_prefix

    used_seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
    wf[NODE_KSAMPLER]["inputs"]["seed"] = used_seed
    if steps:
        wf[NODE_KSAMPLER]["inputs"]["steps"] = int(steps)

    if aspect_ratio:
        if aspect_ratio not in ASPECT_RATIOS:
            raise ImageError(
                "Unbekanntes Seitenverhältnis '%s'. Erlaubt: %s"
                % (aspect_ratio, ", ".join(ASPECT_RATIOS))
            )
        wf[NODE_RESOLUTION]["inputs"]["aspect_ratio"] = aspect_ratio
    if megapixels:
        wf[NODE_RESOLUTION]["inputs"]["megapixels"] = float(megapixels)

    lora = config.COMFY_ENABLE_LORA if enable_lora is None else enable_lora
    refine = config.COMFY_REFINE_PROMPT if refine_prompt is None else refine_prompt
    wf[NODE_ENABLE_LORA]["inputs"]["value"] = bool(lora)
    wf[NODE_REFINE_PROMPT]["inputs"]["value"] = bool(refine)
    return wf, used_seed


# -------------------------------------------------------------- Job-Ablauf

def _queue_prompt(workflow: dict, client_id: str) -> str:
    try:
        result = _http_json(
            config.COMFY_SERVER_URL + "/prompt",
            {"prompt": workflow, "client_id": client_id},
            timeout=60.0,
        )
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:800]
        raise ImageError("ComfyUI hat den Workflow abgelehnt (HTTP %s):\n%s" % (err.code, detail)) from err
    except urllib.error.URLError as err:
        raise ImageError(
            "Kein Kontakt zum ComfyUI-Server (%s): %s"
            % (config.COMFY_SERVER_URL, err.reason)
        ) from err
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise ImageError("ComfyUI hat keine prompt_id zurückgegeben: %s" % result)
    return prompt_id


def _wait_for_result(
    prompt_id: str,
    timeout: float,
    poll: float = 1.0,
    progress: Optional[Callable[[float, str], None]] = None,
    expected: Optional[float] = None,
) -> dict:
    deadline = time.time() + timeout
    start = time.time()
    while time.time() < deadline:
        try:
            history = _http_json("%s/history/%s" % (config.COMFY_SERVER_URL, prompt_id), timeout=30.0)
        except (urllib.error.URLError, json.JSONDecodeError):
            history = {}
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False:
                messages = json.dumps(status.get("messages", []), indent=2)[:1200]
                raise ImageError("Fehler bei der Ausführung des Workflows:\n%s" % messages)
            return entry
        if progress is not None:
            waited = time.time() - start
            # Fortschritt gegen die erwartete Dauer schaetzen, nicht gegen den Timeout
            share = min(1.0, waited / max(expected or config.COMFY_EXPECTED_SECONDS, 1.0))
            progress(0.1 + 0.8 * share,
                     "Der Zeichen-Server arbeitet ... (%d s)" % int(waited))
        time.sleep(poll)
    raise ImageError("Timeout: der Job %s war nach %.0f s nicht fertig." % (prompt_id, timeout))


def _download_images(entry: dict, outfile: Path) -> List[str]:
    images = []
    for node_output in entry.get("outputs", {}).values():
        images.extend(node_output.get("images", []))
    images = [img for img in images if img.get("type") != "temp"]
    if not images:
        raise ImageError("Der Job lieferte kein Bild zurück.")

    saved: List[str] = []
    root, ext = os.path.splitext(str(outfile))
    ext = ext or ".png"
    for index, img in enumerate(images):
        query = urllib.parse.urlencode({
            "filename": img["filename"],
            "subfolder": img.get("subfolder", ""),
            "type": img.get("type", "output"),
        })
        with urllib.request.urlopen(
            "%s/view?%s" % (config.COMFY_SERVER_URL, query), timeout=120
        ) as resp:
            data = resp.read()
        target = Path(str(outfile) if index == 0 else "%s_%d%s" % (root, index + 1, ext))
        target.write_bytes(data)
        saved.append(str(target))
    return saved


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe(text: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (text or "").strip())
    return cleaned.strip("_") or fallback


def generate_image(
    prompt: str,
    filename_prefix: str,
    aspect_ratio: str,
    megapixels: float,
    steps: int,
    seed: Optional[int] = None,
    progress: Optional[Callable[[float, str], None]] = None,
    expected_seconds: Optional[float] = None,
) -> str:
    """Bild erzeugen und lokalen Pfad zurückgeben."""
    if progress:
        progress(0.05, "Workflow wird vorbereitet ...")
    workflow, seed_used = _build_workflow(
        prompt, filename_prefix, aspect_ratio, megapixels, steps, seed
    )
    if progress:
        progress(0.1, "Auftrag wird an den Zeichen-Server geschickt ...")
    prompt_id = _queue_prompt(workflow, str(uuid.uuid4()))
    entry = _wait_for_result(prompt_id, config.COMFY_TIMEOUT, progress=progress,
                             expected=expected_seconds)
    if progress:
        progress(0.95, "Bild wird geladen ...")
    outfile = config.OUTPUT_DIR / ("%s_%s_seed%d.png" % (filename_prefix, _timestamp(), seed_used))
    saved = _download_images(entry, outfile)
    return saved[0]


def generate_signature(
    acronym: str,
    artist_name: str = "",
    progress: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Graffiti-Signatur aus dem Kürzel erzeugen."""
    tag = (acronym or artist_name or "").strip()
    if not tag:
        raise ImageError("Bitte zuerst ein Kürzel (2-4 Buchstaben) eingeben.")
    prompt = build_signature_prompt(acronym, artist_name)
    prefix = "signature_%s" % _safe(tag, "tag")
    return generate_image(
        prompt,
        prefix,
        config.COMFY_SIGNATURE_ASPECT_RATIO,
        config.COMFY_SIGNATURE_MEGAPIXELS,
        config.COMFY_SIGNATURE_STEPS,
        progress=progress,
    )


def generate_comic_page(
    prompt: str,
    comic_title: str = "",
    artist_acronym: str = "",
    seed: Optional[int] = None,
    progress: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Comic-Seite aus dem fertigen Prompt zeichnen."""
    if not (prompt or "").strip():
        raise ImageError("Der Bild-Prompt ist leer. Bitte zuerst das Skript erzeugen.")
    prefix = "comic_%s_%s" % (_safe(artist_acronym, "anon"), _safe(comic_title, "seite"))
    return generate_image(
        prompt,
        prefix,
        config.COMFY_PAGE_ASPECT_RATIO,
        config.COMFY_PAGE_MEGAPIXELS,
        config.COMFY_PAGE_STEPS,
        seed=seed,
        progress=progress,
    )
