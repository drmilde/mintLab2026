"""Export der fertigen Comic-Seite: PNG, PDF und Upload zum Druckserver."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

import config


class ExportError(RuntimeError):
    """Fehler beim Export oder beim Upload zum Druckserver."""


# --------------------------------------------------------------- Hilfsmittel

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _safe(text: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (text or "").strip())
    return cleaned.strip("_") or fallback


def _stamp_text(artist_name: str, acronym: str, comic_title: str, timestamp: str) -> str:
    left = comic_title.strip() or "Comic-Seite"
    who = artist_name.strip() or "unbekannt"
    if acronym.strip():
        who = "%s (%s)" % (who, acronym.strip())
    return "%s  -  %s  -  %s" % (left, who, timestamp)


# ------------------------------------------------------------------- Stempel

def stamp_signature(
    image_path: str,
    artist_name: str = "",
    acronym: str = "",
    comic_title: str = "",
    signature_path: Optional[str] = None,
) -> str:
    """Setzt eine Fußleiste mit Künstler-Daten unter die Comic-Seite.

    Optional wird das generierte Graffiti-Logo klein mit eingeblendet.
    Rückgabe: Pfad der neuen PNG-Datei.
    """
    src = Path(image_path or "")
    if not src.is_file():
        raise ExportError("Es gibt noch kein Bild zum Exportieren.")

    page = Image.open(src).convert("RGB")
    bar_height = max(48, page.height // 18)
    canvas = Image.new("RGB", (page.width, page.height + bar_height), "white")
    canvas.paste(page, (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.line([(0, page.height), (page.width, page.height)], fill=(0, 0, 0), width=2)

    timestamp = datetime.now().strftime("%d.%m.%Y")
    text = _stamp_text(artist_name, acronym, comic_title, timestamp)
    font = _load_font(max(14, bar_height // 3))
    draw.text((16, page.height + bar_height // 2), text, fill=(20, 20, 20), font=font, anchor="lm")

    if signature_path and Path(signature_path).is_file():
        try:
            logo = Image.open(signature_path).convert("RGB")
            side = bar_height - 12
            logo.thumbnail((side, side))
            canvas.paste(logo, (page.width - logo.width - 12, page.height + (bar_height - logo.height) // 2))
        except OSError:
            pass  # Ein fehlerhaftes Logo soll den Export nicht blockieren

    target = config.OUTPUT_DIR / ("final_%s_%s.png" % (
        _safe(acronym or artist_name, "anon"), datetime.now().strftime("%Y%m%d-%H%M%S")))
    canvas.save(target, "PNG")
    return str(target)


# ------------------------------------------------------------ Datei-Exporte

def export_png(image_path: str) -> str:
    """Liefert eine PNG-Kopie im Ausgabeordner (für den Download-Button)."""
    src = Path(image_path or "")
    if not src.is_file():
        raise ExportError("Es gibt noch kein Bild zum Exportieren.")
    target = config.OUTPUT_DIR / ("download_%s.png" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    Image.open(src).convert("RGB").save(target, "PNG")
    return str(target)


def export_pdf(image_path: str, comic_title: str = "", artist_name: str = "") -> str:
    """Wandelt die Seite in eine PDF-Datei (DIN-A4-freundlich, 150 dpi)."""
    src = Path(image_path or "")
    if not src.is_file():
        raise ExportError("Es gibt noch kein Bild zum Exportieren.")
    image = Image.open(src).convert("RGB")
    target = config.OUTPUT_DIR / ("comic_%s_%s.pdf" % (
        _safe(comic_title, "seite"), datetime.now().strftime("%Y%m%d-%H%M%S")))
    image.save(
        target,
        "PDF",
        resolution=150.0,
        title=comic_title.strip() or "Comic-Seite",
        author=artist_name.strip() or "",
    )
    return str(target)


# --------------------------------------------------------------- Druckserver

def build_metadata(
    artist_name: str,
    acronym: str,
    comic_title: str,
    panel_count: int = 0,
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    meta: Dict[str, object] = {
        "artist_name": artist_name.strip(),
        "artist_acronym": acronym.strip(),
        "title": comic_title.strip() or "Comic-Seite",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": "comicmaker",
    }
    if panel_count:
        meta["panel_count"] = int(panel_count)
    if extra:
        meta.update(extra)
    return meta


def send_to_print_server(
    image_path: str,
    artist_name: str = "",
    acronym: str = "",
    comic_title: str = "",
    panel_count: int = 0,
) -> Tuple[bool, str]:
    """POST der Datei plus Metadaten an den Druckserver.

    Rückgabe: (erfolgreich, Meldung in deutscher Sprache).
    """
    src = Path(image_path or "")
    if not src.is_file():
        return False, "Es gibt noch kein Bild zum Drucken. Erzeuge zuerst eine Comic-Seite."

    url = config.print_server_url()
    metadata = build_metadata(artist_name, acronym, comic_title, panel_count)

    try:
        with src.open("rb") as fh:
            response = requests.post(
                url,
                files={"file": (src.name, fh, "image/png")},
                data={"metadata": json.dumps(metadata, ensure_ascii=False), **{
                    k: str(v) for k, v in metadata.items()
                }},
                timeout=config.PRINT_SERVER_TIMEOUT,
            )
    except requests.exceptions.ConnectionError:
        return False, ("Der Druckserver ist nicht erreichbar (%s). "
                       "Bitte prüfe die Adresse in der .env-Datei oder frag die Kursleitung." % url)
    except requests.exceptions.Timeout:
        return False, "Der Druckserver hat zu lange gebraucht (Timeout). Bitte noch einmal versuchen."
    except requests.exceptions.RequestException as err:
        return False, "Fehler beim Senden an den Druckserver: %s" % err

    if 200 <= response.status_code < 300:
        return True, ("Super! Deine Comic-Seite wurde erfolgreich an den Drucker gesendet! "
                      "(Server-Antwort: HTTP %d)" % response.status_code)
    return False, ("Der Druckserver hat die Seite abgelehnt (HTTP %d): %s"
                   % (response.status_code, (response.text or "")[:300]))
