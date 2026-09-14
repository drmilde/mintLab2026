#!/usr/bin/env python3.10
"""Comic Maker - Gradio-Oberfläche für eine Comic-Seite mit 4 bis 6 Panels.

Gedacht für einen MINT-Kurs mit Mädchen ab 12 Jahren. Die Oberfläche
führt in sechs Tabs durch den Ablauf:
Creator -> Characters -> Scene -> Script -> Page -> Export

Ein siebter Tab "Config" macht die Einstellungen aus der .env-Datei
direkt in der Oberfläche editierbar.
"""

from __future__ import annotations

import contextlib
import urllib.parse
from pathlib import Path
from typing import List

import gradio as gr

import config
import export_handler
import image_handler
import llm_handler
from llm_handler import Character, Panel

MAX_CHARACTERS = 3
PANEL_SLOTS = config.MAX_PANELS  # 6 vorbereitete Panel-Karten

(TAB_CREATOR, TAB_CHARACTERS, TAB_SCENE, TAB_SCRIPT, TAB_PAGE, TAB_EXPORT,
 TAB_CONFIG) = range(7)

# ------------------------------------------------------------- Beispieldaten

CHARACTER_PRESETS = [
    ("Lina",
     "12 Jahre, braune Zöpfe, blauer Laborkittel, gelbe Schutzbrille auf der Stirn, "
     "Tablet unter dem Arm",
     "neugierige Forscherin, probiert alles selbst aus"),
    ("Robo-X",
     "kleiner runder Roboter, mint-grünes Metall, ein großes Kameraauge, "
     "Räder statt Beine, kleine Greifarme",
     "hilfsbereiter Roboter, rechnet blitzschnell"),
    ("Yara",
     "13 Jahre, schwarze Locken mit rotem Stirnband, Jeanslatzhose voller Werkzeug, "
     "Lupe an einer Kette",
     "mutige Technikerin, baut und repariert gerne"),
]

SCENE_PRESET = (
    "Ein modernes Schul-Labor mit bunten Flüssigkeiten, Mikroskopen und Computern. "
    "Durch die großen Fenster fällt Nachmittagssonne.",
    "Lina entdeckt eine seltsame leuchtende Formel an der Tafel, die niemand "
    "geschrieben hat.",
    "Lina, Robo-X und Yara lösen gemeinsam das Rätsel und starten das Experiment "
    "erfolgreich - es leuchtet in allen Farben.",
)

STYLE_PRESET = (
    "freundlicher moderner Comic-Stil, klare schwarze Konturen, leuchtende Farben, "
    "große ausdrucksstarke Augen, saubere Sprechblasen mit gut lesbarer Schrift"
)

WELCOME = """
# Willkommen beim Comic Maker!

Erstelle deine eigene Comic-Seite in **6 einfachen Schritten**:

| Schritt | Tab | Was passiert hier? |
|---|---|---|
| 1 | **Creator** | Dein Künstlername, dein Kürzel und dein Signatur-Logo |
| 2 | **Characters** | Wer kommt in deinem Comic vor? |
| 3 | **Scene** | Wo spielt die Geschichte, wie fängt sie an, wie endet sie? |
| 4 | **Script** | Der Computer schreibt das Drehbuch - du darfst alles ändern |
| 5 | **Page** | Deine Comic-Seite wird gezeichnet |
| 6 | **Export** | Speichern und ausdrucken |

Du kannst jederzeit zurückgehen und etwas ändern. Viel Spaß!

*Im Tab **⚙️ Config** stellt die Kursleitung ein, wie der Computer arbeitet.*
"""


# ---------------------------------------------------------------- Hilfsteile

def _characters_from_fields(values: List[str]) -> List[Character]:
    """Aus den 3x3 Textfeldern eine Liste von Figuren bauen."""
    chars: List[Character] = []
    for i in range(MAX_CHARACTERS):
        name, appearance, personality = values[i * 3:i * 3 + 3]
        chars.append(Character(name or "", appearance or "", personality or ""))
    return chars


def _panels_from_fields(values: List[str], count: int) -> List[Panel]:
    """Aus den Panel-Karten (je 3 Felder) Panel-Objekte bauen."""
    panels: List[Panel] = []
    for i in range(min(count, PANEL_SLOTS)):
        description, narration, dialogue = values[i * 3:i * 3 + 3]
        lines = [ln.strip(" -") for ln in (dialogue or "").splitlines() if ln.strip(" -")]
        panels.append(Panel(index=i + 1,
                            description=description or "",
                            narration=narration or "",
                            dialogue=lines))
    return panels


def _panel_visibility(count: int) -> list:
    count = int(count)
    return [gr.update(visible=(i < count)) for i in range(PANEL_SLOTS)]


def _panel_field_updates(panels: List[Panel]) -> list:
    """18 Updates (6 Panels x 3 Felder) für die Panel-Karten."""
    updates = []
    for i in range(PANEL_SLOTS):
        if i < len(panels):
            panel = panels[i]
            updates.extend([
                gr.update(value=panel.description),
                gr.update(value=panel.narration),
                gr.update(value=panel.dialogue_text),
            ])
        else:
            updates.extend([gr.update(value=""), gr.update(value=""), gr.update(value="")])
    return updates


PROMPT_PREVIEW_EMPTY = ("*Hier erscheint dein Bild-Prompt, sobald du im Tab 'Script' "
                        "auf 'Weiter zu Page Generation' geklickt hast.*")


def _render_prompt(text: str) -> str:
    """Den Prompt-Text als Markdown in der Vorschau anzeigen."""
    return (text or "").strip() or PROMPT_PREVIEW_EMPTY


def _status(text: str, kind: str = "info") -> str:
    icons = {"info": "ℹ️", "ok": "✅", "warn": "⚠️", "error": "❌", "work": "⏳"}
    return "%s %s" % (icons.get(kind, "ℹ️"), text)


# ------------------------------------------------------------ Tab 1: Creator

def on_generate_signature(acronym: str, artist_name: str, progress=gr.Progress()):
    tag = (acronym or "").strip()
    if not tag:
        return None, _status("Bitte gib zuerst dein Kürzel ein (2 bis 4 Buchstaben).", "warn"), None
    if len(tag) > 6:
        return None, _status("Das Kürzel ist zu lang - nimm 2 bis 4 Buchstaben.", "warn"), None

    progress(0.02, desc="Signatur wird vorbereitet ...")

    def report(fraction: float, message: str) -> None:
        progress(fraction, desc=message)

    try:
        path = image_handler.generate_signature(tag, artist_name or "", progress=report)
    except image_handler.ImageError as err:
        return None, _status(str(err), "error"), None
    return path, _status("Fertig! Das ist deine Signatur '%s'." % tag, "ok"), path


# --------------------------------------------------------- Tab 2: Characters

def on_load_character_preset(slot: int):
    name, appearance, personality = CHARACTER_PRESETS[slot]
    return name, appearance, personality


def on_load_all_presets():
    values = []
    for preset in CHARACTER_PRESETS:
        values.extend(preset)
    return values


# -------------------------------------------------------------- Tab 3: Scene

def on_generate_script(
    panel_count, setting, story_start, story_goal, comic_title, artist_name, *char_values,
    progress=gr.Progress(),
):
    characters = _characters_from_fields(list(char_values))
    missing = []
    if not any(c.is_filled for c in characters):
        missing.append("mindestens eine Figur im Tab 'Characters'")
    if not (setting or "").strip():
        missing.append("die Umgebung")
    if not (story_start or "").strip():
        missing.append("den Anfang der Geschichte")
    if not (story_goal or "").strip():
        missing.append("das Ziel der Geschichte")

    if missing:
        message = _status("Da fehlt noch etwas: %s." % ", ".join(missing), "warn")
        return ["", message, *_panel_field_updates([]), *_panel_visibility(panel_count),
                gr.update(), gr.update(value=message)]

    progress(0.1, desc="Der Geschichten-Computer denkt nach ...")
    try:
        result = llm_handler.generate_script(
            int(panel_count), setting or "", story_start or "", story_goal or "",
            characters, comic_title or "", artist_name or "",
        )
    except llm_handler.LLMError as err:
        message = _status(str(err), "error")
        return ["", message, *_panel_field_updates([]),
                *_panel_visibility(panel_count), gr.update(), gr.update(value=message)]

    panels: List[Panel] = result["panels"]
    progress(0.95, desc="Drehbuch wird sortiert ...")
    ok_message = _status(
        "Dein Drehbuch mit %d Panels ist fertig! Schau im Tab 'Script' nach und "
        "ändere alles, was dir nicht gefällt." % len(panels), "ok")
    return [result["raw"], ok_message, *_panel_field_updates(panels),
            *_panel_visibility(panel_count), gr.update(selected=TAB_SCRIPT),
            gr.update(value=ok_message)]


def on_load_scene_preset():
    return SCENE_PRESET


# ------------------------------------------------------------- Tab 4: Script

def on_reparse_script(script_text, panel_count):
    """Text aus dem großen Editor wieder in die Panel-Karten übernehmen."""
    panels = llm_handler.parse_script(script_text or "", expected_panels=int(panel_count))
    return [*_panel_field_updates(panels), *_panel_visibility(panel_count),
            _status("Die Panel-Karten wurden aus dem Text neu eingelesen.", "ok")]


def on_sync_from_cards(panel_count, *panel_values):
    """Panel-Karten zurück in den großen Text-Editor schreiben."""
    panels = _panels_from_fields(list(panel_values), int(panel_count))
    return (llm_handler.panels_to_markdown(panels),
            _status("Der Skript-Text wurde aus den Panel-Karten aktualisiert.", "ok"))


def on_build_prompt(panel_count, style, comic_title, acronym, *values):
    """Bild-Prompt aus Panel-Karten und Figuren zusammensetzen."""
    char_values = list(values[:MAX_CHARACTERS * 3])
    panel_values = list(values[MAX_CHARACTERS * 3:])
    characters = _characters_from_fields(char_values)
    panels = _panels_from_fields(panel_values, int(panel_count))

    if not any(p.description.strip() for p in panels):
        return ("", _status("Es gibt noch keine Bildbeschreibungen. Erzeuge zuerst im Tab "
                            "'Scene' ein Drehbuch.", "warn"), gr.update())

    prompt = image_handler.build_page_prompt(
        panels, characters, style or "", comic_title or "", acronym or "")
    return (prompt,
            _status("Der Bild-Prompt ist fertig. Weiter im Tab 'Page'!", "ok"),
            gr.update(selected=TAB_PAGE))


def on_rebuild_prompt(panel_count, style, comic_title, acronym, *values):
    """Wie on_build_prompt, aber ohne Tab-Wechsel (Button im Tab 'Page')."""
    prompt, message, _ = on_build_prompt(panel_count, style, comic_title, acronym, *values)
    return prompt, message


# --------------------------------------------------------------- Tab 5: Page

def on_draw_page(prompt, comic_title, acronym, progress=gr.Progress()):
    if not (prompt or "").strip():
        return (None, _status("Der Bild-Prompt ist leer. Gehe zurück zum Tab 'Script' und "
                              "klicke auf 'Weiter zu Page Generation'.", "warn"), None)

    progress(0.02, desc="Verbindung zum Zeichen-Server ...")

    def report(fraction: float, message: str) -> None:
        progress(fraction, desc=message)

    try:
        path = image_handler.generate_comic_page(
            prompt, comic_title or "", acronym or "", progress=report)
    except image_handler.ImageError as err:
        return None, _status(str(err), "error"), None
    return (path,
            _status("Deine Comic-Seite ist fertig gezeichnet! Weiter zum Tab 'Export'.", "ok"),
            path)


def on_page_to_export(image_path, artist_name, acronym, comic_title, signature_path):
    """Fertige Seite mit Künstler-Fußleiste in den Export-Tab übernehmen."""
    if not image_path:
        return (None, None,
                _status("Es gibt noch keine gezeichnete Seite.", "warn"),
                gr.update())
    try:
        stamped = export_handler.stamp_signature(
            image_path, artist_name or "", acronym or "", comic_title or "", signature_path)
    except export_handler.ExportError as err:
        return None, None, _status(str(err), "error"), gr.update()
    return (stamped, stamped,
            _status("Deine Seite ist bereit zum Speichern und Drucken.", "ok"),
            gr.update(selected=TAB_EXPORT))


# ------------------------------------------------------------- Tab 6: Export

try:  # Gradio 5 serviert Dateien unter /gradio_api/file=...
    from gradio.route_utils import API_PREFIX as _GRADIO_API_PREFIX
except ImportError:  # pragma: no cover - ältere Gradio-Versionen
    _GRADIO_API_PREFIX = ""

#: Legt die eben erzeugte Datei direkt in den Download-Ordner des Browsers -
#: die Schülerin muss den Datei-Namen nicht mehr anklicken.
AUTO_DOWNLOAD_JS = """
(url) => {
    if (!url) { return; }
    const link = document.createElement("a");
    link.href = url;
    link.download = decodeURIComponent(url.split("/").pop());
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
}
"""


def _download_url(path) -> str:
    """Adresse, unter der Gradio die erzeugte Datei ausliefert."""
    if not path:
        return ""
    quoted = urllib.parse.quote(str(Path(path).resolve()))
    return "%s/file=%s" % (_GRADIO_API_PREFIX, quoted)


def on_download_png(final_path):
    if not final_path:
        return None, _status("Es gibt noch kein Bild zum Speichern.", "warn"), ""
    try:
        path = export_handler.export_png(final_path)
    except export_handler.ExportError as err:
        return None, _status(str(err), "error"), ""
    return (path,
            _status("Die PNG-Datei wird gespeichert - schau in deinen Download-Ordner. "
                    "Falls nichts passiert, klicke unten auf den Datei-Namen.", "ok"),
            _download_url(path))


def on_download_pdf(final_path, comic_title, artist_name):
    if not final_path:
        return None, _status("Es gibt noch kein Bild zum Speichern.", "warn"), ""
    try:
        path = export_handler.export_pdf(final_path, comic_title or "", artist_name or "")
    except export_handler.ExportError as err:
        return None, _status(str(err), "error"), ""
    return (path,
            _status("Die PDF-Datei wird gespeichert - schau in deinen Download-Ordner. "
                    "Falls nichts passiert, klicke unten auf den Datei-Namen.", "ok"),
            _download_url(path))


def on_print(final_path, artist_name, acronym, comic_title, panel_count):
    ok, message = export_handler.send_to_print_server(
        final_path or "", artist_name or "", acronym or "", comic_title or "", int(panel_count or 0))
    return _status(message, "ok" if ok else "error")


# ------------------------------------------------------------- Tab 7: Config

# Aufbau des Config-Tabs. Pro Gruppe: (Titel, offen?, Erklärung, Zeilen).
# Eine Zeile enthält ein oder mehrere Felder, die nebeneinander stehen.
# Ein Feld ist: (Schlüssel aus der .env, Art, Beschriftung, Hilfetext, Extra)
#   Art: "prompt"/"text" = mehrzeilig (Extra = Zeilenzahl), "line" = einzeilig,
#        "int"/"num" = Zahl, "bool" = Haken, "choice" = Auswahl (Extra = Liste)

CONFIG_GROUPS = [
    ("🧠 System-Prompt für das Sprachmodell (Text)", True,
     "Diese Texte sieht die Schülerin nie. Sie bestimmen, wie das Sprachmodell "
     "das Drehbuch schreibt.",
     [
         [("SYSTEM_PROMPT_GERMAN", "prompt", "Rolle & Regeln für das Sprachmodell",
           "Wer ist das Modell, für wen schreibt es, welche Regeln gelten "
           "(Sprache, Satzlänge, keine Gewalt ...)?", 14)],
         [("PANEL_FORMAT_PROMPT", "prompt", "Ausgabeformat der Panels",
           "Legt fest, wie das Drehbuch aufgebaut sein muss. Achtung: Die "
           "Panel-Karten im Tab 'Script' lesen genau dieses Format ein.", 12)],
     ]),

    ("🎨 System-Prompts für die Bildgenerierung", True,
     "Diese Bausteine hängen automatisch an jedem Bild-Prompt.",
     [
         [("IMAGE_STYLE_PROMPT", "prompt", "Stil der Comic-Seite",
           "Grundstil jeder Seite - wird mit dem Style-Feld aus Tab 'Page' "
           "kombiniert. Englisch funktioniert hier meist am besten.", 6)],
         [("IMAGE_NEGATIVE_HINTS", "text", "Unerwünschtes (Negativ-Hinweise)",
           "Was auf keinen Fall im Bild vorkommen soll.", 3)],
         [("SIGNATURE_STYLE_PROMPT", "prompt", "Stil des Signatur-Logos",
           "Aussehen des Künstler-Tags aus Tab 'Creator'.", 5)],
     ]),

    ("🤖 Sprachmodell (Ollama)", False,
     "Adresse und Verhalten des Text-Modells auf deinem Rechner.",
     [
         [("OLLAMA_HOST", "line", "Server-Adresse", "z. B. http://localhost:11434", None),
          ("OLLAMA_MODEL", "line", "Modell", "z. B. gemma4:latest", None)],
         [("OLLAMA_TEMPERATURE", "num", "Kreativität (temperature)",
           "0.0 = sehr brav, 1.0 = sehr verspielt", None),
          ("OLLAMA_NUM_PREDICT", "int", "Maximale Textlänge (Tokens)",
           "Mehr Tokens = längeres Drehbuch, aber langsamer", None),
          ("OLLAMA_TIMEOUT", "num", "Zeitlimit (Sekunden)",
           "Wie lange auf das Modell gewartet wird", None)],
     ]),

    ("🖼️ Bild-Server (ComfyUI / Krea2)", False,
     "Wohin die Bild-Aufträge geschickt werden.",
     [
         [("COMFY_SERVER_URL", "line", "Server-Adresse", "z. B. http://127.0.0.1:8188", None),
          ("COMFY_WORKFLOW", "line", "Workflow-Datei (API-Format)",
           "Dateiname im Projektordner oder kompletter Pfad", None)],
         [("COMFY_TIMEOUT", "num", "Zeitlimit (Sekunden)",
           "Abbruch, wenn der Bild-Auftrag länger dauert", None),
          ("COMFY_EXPECTED_SECONDS", "num", "Erwartete Dauer (Sekunden)",
           "Nur für den Fortschrittsbalken", None)],
         [("COMFY_ENABLE_LORA", "bool", "LoRA 'krea2_darkbrush' benutzen",
           "Zusätzlicher Stil-Baustein im Workflow", None),
          ("COMFY_REFINE_PROMPT", "bool", "Prompt im Workflow ausformulieren lassen",
           "Das Textmodell im Workflow verfeinert den Prompt - dauert länger", None)],
     ]),

    ("📐 Bildformate (Seite & Signatur)", False,
     "Links die Comic-Seite, rechts das kleine Signatur-Logo.",
     [
         [("COMFY_PAGE_ASPECT_RATIO", "choice", "Seite: Seitenverhältnis",
           "Comic-Seiten sind meist hochformatig", image_handler.ASPECT_RATIOS),
          ("COMFY_SIGNATURE_ASPECT_RATIO", "choice", "Signatur: Seitenverhältnis",
           "Für ein Logo passt ein Quadrat gut", image_handler.ASPECT_RATIOS)],
         [("COMFY_PAGE_MEGAPIXELS", "num", "Seite: Megapixel",
           "Mehr Megapixel = mehr Details, aber langsamer", None),
          ("COMFY_SIGNATURE_MEGAPIXELS", "num", "Signatur: Megapixel",
           "Für das Logo reicht wenig", None)],
         [("COMFY_PAGE_STEPS", "int", "Seite: Schritte (steps)",
           "Rechenschritte pro Bild", None),
          ("COMFY_SIGNATURE_STEPS", "int", "Signatur: Schritte (steps)",
           "Rechenschritte pro Logo", None)],
     ]),

    ("🖨️ Druckserver", False,
     "Wohin die fertige Seite zum Drucken geschickt wird.",
     [
         [("PRINT_SERVER_SCHEME", "choice", "Protokoll", "http oder https", ["http", "https"]),
          ("PRINT_SERVER_HOST", "line", "Host", "z. B. print-server.local", None),
          ("PRINT_SERVER_PORT", "int", "Port", "z. B. 80", None)],
         [("PRINT_SERVER_ENDPOINT", "line", "Endpunkt (Pfad)", "z. B. /api/v1/upload", None),
          ("PRINT_SERVER_TIMEOUT", "num", "Zeitlimit (Sekunden)", "", None)],
         [("PRINT_SERVER_URL", "line", "Kompletter URL (optional)",
           "Wenn gesetzt, überschreibt dieser Wert Protokoll, Host, Port und Endpunkt.",
           None)],
     ]),

    ("💾 Ausgabe & Oberfläche", False,
     "Speicherort der Bilder und Start-Einstellungen von Gradio.",
     [
         [("OUTPUT_DIR", "line", "Ausgabe-Ordner",
           "Ordner im Projekt oder kompletter Pfad - wird bei Bedarf angelegt", None)],
         [("GRADIO_SERVER_NAME", "line", "Gradio: Adresse",
           "127.0.0.1 = nur dieser Rechner, 0.0.0.0 = im ganzen Netz (Neustart nötig)",
           None),
          ("GRADIO_SERVER_PORT", "int", "Gradio: Port", "Neustart nötig", None),
          ("GRADIO_SHARE", "bool", "Gradio: öffentlicher Link",
           "Erzeugt beim Start einen share-Link (Neustart nötig)", None)],
     ]),
]

#: Reihenfolge der Felder - genau so werden sie ein- und ausgelesen.
CONFIG_KEYS = [field[0]
               for _title, _open, _info, rows in CONFIG_GROUPS
               for row in rows for field in row]
#: Schlüssel -> Art des Bedienelements
CONFIG_KINDS = {field[0]: field[1]
                for _title, _open, _info, rows in CONFIG_GROUPS
                for row in rows for field in row}

CONFIG_INTRO = """
## Einstellungen

Hier stehen alle Werte aus der Datei `.env`. Ganz oben die **System-Prompts** -
der versteckte Auftrag an das Sprachmodell und an die Bildgenerierung.

* **Übernehmen** - gilt sofort, aber nur bis zum Beenden der App.
* **Speichern** - schreibt die Werte in die `.env` (eine Sicherungskopie
  landet in `.env.bak`).
* **Verwerfen** - liest die `.env` wieder neu ein.
"""


def _config_component(field, values):
    """Ein Bedienelement für einen .env-Schlüssel bauen."""
    key, kind, label, info, extra = field
    raw = values.get(key, "")
    if kind in ("prompt", "text"):
        return gr.Textbox(label=label, info=info, value=raw, lines=extra or 4,
                          show_copy_button=True)
    if kind == "line":
        return gr.Textbox(label=label, info=info, value=raw, max_lines=1)
    if kind == "int":
        return gr.Number(label=label, info=info, value=config.parse_value(key, raw),
                         precision=0)
    if kind == "num":
        return gr.Number(label=label, info=info, value=config.parse_value(key, raw))
    if kind == "bool":
        return gr.Checkbox(label=label, info=info, value=config.parse_value(key, raw))
    if kind == "choice":
        return gr.Dropdown(label=label, info=info, value=raw, choices=list(extra or []),
                           allow_custom_value=True)
    raise ValueError("Unbekannte Feld-Art '%s' für '%s'" % (kind, key))


def _build_config_fields() -> list:
    """Alle Gruppen aufklappbar untereinander anlegen."""
    components = []
    values = config.current_values()
    for title, is_open, description, rows in CONFIG_GROUPS:
        with gr.Accordion(title, open=is_open):
            if description:
                gr.Markdown("<span class='hint'>%s</span>" % description)
            for row in rows:
                context = gr.Row() if len(row) > 1 else contextlib.nullcontext()
                with context:
                    for field in row:
                        components.append(_config_component(field, values))
    return components


def _model_hint() -> str:
    return ("<span class='hint'>Der Text wird von einem Sprachmodell (%s) "
            "auf deinem eigenen Rechner geschrieben.</span>" % config.OLLAMA_MODEL)


def _print_hint() -> str:
    return "<span class='hint'>Druckserver: %s</span>" % config.print_server_url()


def _config_hints() -> tuple:
    """Die beiden Hinweiszeilen in den Tabs 'Scene' und 'Export' auffrischen."""
    return gr.update(value=_model_hint()), gr.update(value=_print_hint())


def _config_dict(values) -> dict:
    return dict(zip(CONFIG_KEYS, values))


def on_config_apply(*values):
    try:
        notes = config.apply_settings(_config_dict(values))
    except ValueError as err:
        return (_status(str(err), "error"), *_config_hints())
    text = "Die Einstellungen gelten ab sofort - aber nur bis zum Beenden der App."
    return (_status(" ".join([text, *notes]), "ok"), *_config_hints())


def on_config_save(*values):
    data = _config_dict(values)
    try:
        notes = config.apply_settings(data)
        path = config.save_settings(data)
    except ValueError as err:
        return (_status(str(err), "error"), *_config_hints())
    except OSError as err:
        return (_status("Die Datei %s konnte nicht geschrieben werden: %s"
                        % (config.ENV_PATH.name, err), "error"), *_config_hints())
    text = ("Gespeichert in %s - die alte Fassung liegt als .env.bak daneben."
            % path.name)
    return (_status(" ".join([text, *notes]), "ok"), *_config_hints())


def on_config_reload():
    try:
        values = config.reload_settings()
    except (OSError, ValueError) as err:
        message = _status("Die Datei %s konnte nicht gelesen werden: %s"
                          % (config.ENV_PATH.name, err), "error")
        return [*[gr.update() for _ in CONFIG_KEYS], message, *_config_hints()]

    updates = []
    for key in CONFIG_KEYS:
        raw = values.get(key, "")
        if CONFIG_KINDS[key] in ("int", "num", "bool"):
            updates.append(gr.update(value=config.parse_value(key, raw)))
        else:
            updates.append(gr.update(value=raw))
    return [*updates,
            _status("Die Werte aus der %s sind wieder eingelesen."
                    % config.ENV_PATH.name, "ok"),
            *_config_hints()]


# ------------------------------------------------------------- Oberfläche

CSS = """
.comic-title { text-align: center; }
.big-button button { font-size: 1.15rem !important; padding: 0.8rem !important; }
.status-box { min-height: 2.4rem; }
.hint { font-size: 0.95rem; opacity: 0.85; }
.prompt-preview {
    border: 1px solid var(--border-color-primary);
    border-radius: 8px;
    padding: 0.4rem 0.9rem;
    max-height: 460px;
    overflow-y: auto;
    background: var(--block-background-fill);
}
.prompt-preview h1 { font-size: 1.15rem; margin-top: 0.4rem; }
.prompt-preview h2 { font-size: 1.02rem; }
.prompt-preview h3 { font-size: 0.95rem; }
.prompt-preview li { margin: 0.1rem 0; }
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Comic Maker", theme=gr.themes.Soft(), css=CSS) as demo:
        # --- Zustand
        st_signature = gr.State(None)
        st_page_image = gr.State(None)
        st_final_image = gr.State(None)

        gr.Markdown("# 🎨 Comic Maker - deine eigene Comic-Seite",
                    elem_classes=["comic-title"])

        with gr.Tabs() as tabs:
            # ============================================== TAB 1: CREATOR
            with gr.Tab("1. Creator", id=TAB_CREATOR):
                gr.Markdown(WELCOME)
                with gr.Row():
                    with gr.Column(scale=3):
                        artist_name = gr.Textbox(
                            label="Künstlername", placeholder="z. B. Lina M. oder StarPainter",
                            info="So heißt du als Comic-Zeichnerin.")
                        acronym = gr.Textbox(
                            label="Kürzel (2–4 Buchstaben)", placeholder="z. B. LNA",
                            max_lines=1, info="Kommt als Signatur in die Ecke der Seite.")
                        comic_title = gr.Textbox(
                            label="Comic-Titel (optional)",
                            placeholder="z. B. Das Rätsel im Labor")
                        btn_signature = gr.Button("✒️ Signature generieren", variant="primary",
                                                  elem_classes=["big-button"])
                        creator_status = gr.Markdown(_status(
                            "Trage deinen Namen ein und erzeuge dein Signatur-Logo.", "info"),
                            elem_classes=["status-box"])
                    with gr.Column(scale=2):
                        signature_image = gr.Image(
                            label="Dein Signatur-Logo", type="filepath",
                            height=320, interactive=False, show_download_button=True)

            # =========================================== TAB 2: CHARACTERS
            with gr.Tab("2. Characters", id=TAB_CHARACTERS):
                gr.Markdown(
                    "## Wer kommt in deinem Comic vor?\n"
                    "Beschreibe **1 bis 3 Figuren**. Je genauer du das Aussehen beschreibst, "
                    "desto besser sehen die Figuren auf jedem Panel gleich aus.")
                btn_all_presets = gr.Button("🎁 Alle Beispiel-Figuren laden")

                char_fields: List[gr.Textbox] = []
                preset_buttons = []
                for slot in range(MAX_CHARACTERS):
                    open_default = slot == 0
                    with gr.Accordion("Figur %d%s" % (slot + 1,
                                      "" if open_default else " (optional)"),
                                      open=open_default):
                        c_name = gr.Textbox(label="Name der Figur",
                                            placeholder="z. B. Lina, Robot-X")
                        c_look = gr.Textbox(
                            label="Aussehen & Kleidung", lines=3,
                            placeholder="Haarfarbe, Kleidung, MINT-Ausrüstung "
                                        "(Laborkittel, Schutzbrille, Lupe ...)")
                        c_traits = gr.Textbox(
                            label="Eigenschaften",
                            placeholder="z. B. neugierige Forscherin, hilfsbereiter Roboter")
                        btn_preset = gr.Button("Beispiel laden", size="sm")
                        btn_preset.click(
                            fn=(lambda s=slot: on_load_character_preset(s)),
                            outputs=[c_name, c_look, c_traits])
                        preset_buttons.append(btn_preset)
                        char_fields.extend([c_name, c_look, c_traits])

                btn_to_scene = gr.Button("➡️ Szene beschreiben", variant="primary",
                                         elem_classes=["big-button"])

                btn_all_presets.click(fn=on_load_all_presets, outputs=char_fields)

            # ================================================ TAB 3: SCENE
            with gr.Tab("3. Scene", id=TAB_SCENE):
                gr.Markdown(
                    "## Wo spielt deine Geschichte?\n"
                    "Benutze die **Namen deiner Figuren** aus Schritt 2, damit sie in der "
                    "Geschichte richtig vorkommen.")
                setting = gr.Textbox(
                    label="Umgebung / Ort", lines=3,
                    placeholder="z. B. Ein modernes Schul-Labor mit bunten Flüssigkeiten "
                                "und Computern")
                story_start = gr.Textbox(
                    label="Anfang der Geschichte", lines=3,
                    placeholder="z. B. Lina entdeckt eine seltsame leuchtende Formel an der Tafel")
                story_goal = gr.Textbox(
                    label="Ziel / Ende der Geschichte", lines=3,
                    placeholder="z. B. Sie lösen gemeinsam das Rätsel und starten das "
                                "Experiment erfolgreich")
                panel_count = gr.Slider(
                    label="Anzahl der Panels", minimum=config.MIN_PANELS,
                    maximum=config.MAX_PANELS, step=1, value=config.MIN_PANELS)
                with gr.Row():
                    btn_scene_preset = gr.Button("🎁 Beispiel-Szene laden")
                    btn_script = gr.Button("📝 Script generieren", variant="primary",
                                           elem_classes=["big-button"])
                scene_status = gr.Markdown(_status(
                    "Fülle die drei Felder aus und klicke auf 'Script generieren'. "
                    "Das dauert einen Moment.", "info"), elem_classes=["status-box"])
                scene_model_hint = gr.Markdown(_model_hint())

                btn_scene_preset.click(fn=on_load_scene_preset,
                                       outputs=[setting, story_start, story_goal])

            # =============================================== TAB 4: SCRIPT
            with gr.Tab("4. Script", id=TAB_SCRIPT):
                gr.Markdown(
                    "## Dein Drehbuch\n"
                    "Hier steht, was auf jedem Panel passiert. **Du darfst alles ändern!**")
                gr.Markdown(
                    "> **Wichtig:** Halte die Texte kurz und einfach. "
                    "Erzähler-Text: höchstens ca. 15 Wörter. "
                    "Sprechblasen: höchstens ca. 12 Wörter - sonst passt der Text "
                    "nicht in die Blase.")
                master_script = gr.Textbox(
                    label="Gesamtes Skript", lines=18, show_copy_button=True,
                    placeholder="Hier erscheint das Drehbuch, nachdem du im Tab 'Scene' "
                                "auf 'Script generieren' geklickt hast.")
                with gr.Row():
                    btn_reparse = gr.Button("⬇️ Text in die Panel-Karten übernehmen")
                    btn_sync = gr.Button("⬆️ Panel-Karten in den Text übernehmen")

                panel_groups = []
                panel_fields: List[gr.Textbox] = []
                for slot in range(PANEL_SLOTS):
                    with gr.Group(visible=slot < config.MIN_PANELS) as group:
                        gr.Markdown("### Panel %d" % (slot + 1))
                        p_desc = gr.Textbox(
                            label="Bildbeschreibung", lines=3,
                            placeholder="Was sieht man im Bild? z. B. Lina blickt überrascht "
                                        "auf das Mikroskop")
                        p_narr = gr.Textbox(
                            label="Erzähler-Text (max. ~15 Wörter)", lines=2,
                            placeholder="Kurzer Text im Kästchen oben im Panel")
                        p_dial = gr.Textbox(
                            label="Sprechblasen (eine Zeile pro Blase)", lines=3,
                            placeholder='Lina: "Das gibt\'s doch gar nicht!"')
                    panel_groups.append(group)
                    panel_fields.extend([p_desc, p_narr, p_dial])

                script_status = gr.Markdown("", elem_classes=["status-box"])
                btn_to_page = gr.Button("➡️ Weiter zu Page Generation", variant="primary",
                                        elem_classes=["big-button"])

            # ================================================= TAB 5: PAGE
            with gr.Tab("5. Page", id=TAB_PAGE):
                gr.Markdown("## Deine Comic-Seite zeichnen")
                style = gr.Textbox(
                    label="Style (wie soll die Seite aussehen?)", lines=3, value=STYLE_PRESET,
                    info="Beschreibe den Zeichenstil - Farben, Linien, Stimmung.")
                with gr.Row():
                    with gr.Column(scale=1):
                        page_prompt = gr.Textbox(
                            label="Bild-Prompt (wird an den Zeichen-Server geschickt)",
                            lines=20, show_copy_button=True,
                            info="Markdown - du darfst hier alles ändern.",
                            placeholder="Klicke im Tab 'Script' auf "
                                        "'Weiter zu Page Generation'.")
                    with gr.Column(scale=1):
                        gr.Markdown("**Vorschau des Prompts**")
                        prompt_preview = gr.Markdown(
                            PROMPT_PREVIEW_EMPTY, elem_classes=["prompt-preview"])
                with gr.Row():
                    btn_rebuild_prompt = gr.Button("🔄 Prompt neu zusammenbauen")
                    btn_draw = gr.Button("🖍️ Comic-Seite zeichnen", variant="primary",
                                         elem_classes=["big-button"])
                    btn_redraw = gr.Button("🎲 Nochmal zeichnen (neuer Versuch)")
                page_status = gr.Markdown(_status(
                    "Wenn der Prompt gut aussieht, klicke auf 'Comic-Seite zeichnen'. "
                    "Das kann ein bis zwei Minuten dauern.", "info"),
                    elem_classes=["status-box"])
                page_image = gr.Image(
                    label="Deine Comic-Seite", type="filepath", height=760,
                    interactive=False, show_download_button=True)
                btn_to_export = gr.Button("➡️ Weiter zum Export", variant="primary",
                                          elem_classes=["big-button"])

            # =============================================== TAB 6: EXPORT
            with gr.Tab("6. Export", id=TAB_EXPORT):
                gr.Markdown(
                    "## Speichern und drucken\n"
                    "Unten siehst du deine fertige Seite mit deiner Signatur-Zeile.")
                final_image = gr.Image(
                    label="Fertige Comic-Seite", type="filepath", height=760,
                    interactive=False, show_download_button=True)
                with gr.Row():
                    btn_png = gr.Button("💾 Als PNG speichern")
                    btn_pdf = gr.Button("📄 Als PDF speichern")
                    btn_print = gr.Button("🖨️ Drucken / Absenden", variant="primary",
                                          elem_classes=["big-button"])
                download_file = gr.File(label="Deine Datei", interactive=False)
                # Traegt die Adresse der fertigen Datei zum Browser - unsichtbar,
                # weil sie nur den automatischen Download ausloest.
                download_url = gr.Textbox(visible=False)
                export_status = gr.Markdown(_status(
                    "Erzeuge zuerst im Tab 'Page' eine Comic-Seite.", "info"),
                    elem_classes=["status-box"])
                export_print_hint = gr.Markdown(_print_hint())

            # =============================================== TAB 7: CONFIG
            with gr.Tab("⚙️ Config", id=TAB_CONFIG):
                gr.Markdown(CONFIG_INTRO)
                with gr.Row():
                    btn_config_apply = gr.Button("✔️ Übernehmen", variant="primary",
                                                 elem_classes=["big-button"])
                    btn_config_save = gr.Button("💾 In .env speichern", variant="primary",
                                                elem_classes=["big-button"])
                    btn_config_reload = gr.Button("↩️ Änderungen verwerfen")
                config_status = gr.Markdown(_status(
                    "Die Werte kommen aus der Datei %s." % config.ENV_PATH.name, "info"),
                    elem_classes=["status-box"])
                config_fields = _build_config_fields()

        # ------------------------------------------------------- Verdrahtung

        btn_signature.click(
            fn=on_generate_signature,
            inputs=[acronym, artist_name],
            outputs=[signature_image, creator_status, st_signature],
        )

        btn_to_scene.click(fn=lambda: gr.update(selected=TAB_SCENE), outputs=[tabs])

        panel_count.change(fn=_panel_visibility, inputs=[panel_count], outputs=panel_groups)

        btn_script.click(
            fn=on_generate_script,
            inputs=[panel_count, setting, story_start, story_goal, comic_title, artist_name,
                    *char_fields],
            outputs=[master_script, scene_status, *panel_fields, *panel_groups, tabs,
                     script_status],
        )

        btn_reparse.click(
            fn=on_reparse_script,
            inputs=[master_script, panel_count],
            outputs=[*panel_fields, *panel_groups, script_status],
        )

        btn_sync.click(
            fn=on_sync_from_cards,
            inputs=[panel_count, *panel_fields],
            outputs=[master_script, script_status],
        )

        btn_to_page.click(
            fn=on_build_prompt,
            inputs=[panel_count, style, comic_title, acronym, *char_fields, *panel_fields],
            outputs=[page_prompt, script_status, tabs],
        )

        btn_rebuild_prompt.click(
            fn=on_rebuild_prompt,
            inputs=[panel_count, style, comic_title, acronym, *char_fields, *panel_fields],
            outputs=[page_prompt, page_status],
        )

        page_prompt.change(fn=_render_prompt, inputs=[page_prompt],
                           outputs=[prompt_preview])

        for button in (btn_draw, btn_redraw):
            button.click(
                fn=on_draw_page,
                inputs=[page_prompt, comic_title, acronym],
                outputs=[page_image, page_status, st_page_image],
            )

        btn_to_export.click(
            fn=on_page_to_export,
            inputs=[st_page_image, artist_name, acronym, comic_title, st_signature],
            outputs=[final_image, st_final_image, export_status, tabs],
        )

        btn_png.click(
            fn=on_download_png, inputs=[st_final_image],
            outputs=[download_file, export_status, download_url],
        ).then(fn=None, inputs=[download_url], js=AUTO_DOWNLOAD_JS)

        btn_pdf.click(
            fn=on_download_pdf, inputs=[st_final_image, comic_title, artist_name],
            outputs=[download_file, export_status, download_url],
        ).then(fn=None, inputs=[download_url], js=AUTO_DOWNLOAD_JS)
        btn_print.click(fn=on_print,
                        inputs=[st_final_image, artist_name, acronym, comic_title, panel_count],
                        outputs=[export_status])

        btn_config_apply.click(
            fn=on_config_apply,
            inputs=config_fields,
            outputs=[config_status, scene_model_hint, export_print_hint],
        )

        btn_config_save.click(
            fn=on_config_save,
            inputs=config_fields,
            outputs=[config_status, scene_model_hint, export_print_hint],
        )

        btn_config_reload.click(
            fn=on_config_reload,
            outputs=[*config_fields, config_status, scene_model_hint, export_print_hint],
        )

    return demo


def main() -> None:
    demo = build_ui()
    demo.queue().launch(
        server_name=config.GRADIO_SERVER_NAME,
        server_port=config.GRADIO_SERVER_PORT,
        share=config.GRADIO_SHARE,
        show_error=True,
        allowed_paths=[str(config.OUTPUT_DIR)],
    )


if __name__ == "__main__":
    main()
