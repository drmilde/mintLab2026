"""
Comic-Skript-Generator
======================

Eine kleine Gradio-Oberflaeche fuer den MINT-Kurs, in zwei Schritten:

Reiter "Figuren"  Die Teilnehmerinnen beschreiben bis zu drei Figuren, das
                  Setting, die Startszene und das Ziel der Szene. Daraus erzeugt
                  ein lokal laufender Ollama-Server ein Skript fuer eine
                  Comicseite mit 4 bis 6 Panels.
Reiter "Panels"   Das Skript wird auf einzelne Panel-Textboxen verteilt. Jedes
                  Panel kann bearbeitet und ueber einen laufenden Fooocus-Server
                  in ein Bild verwandelt werden.

Das Verhalten der beiden Server (der "versteckte Kontext") wird komplett ueber
die .env-Datei konfiguriert, siehe .env.example.
"""

from __future__ import annotations

import os
import re
import json
import queue
import threading
from dataclasses import dataclass, field

import gradio as gr
import requests
from dotenv import load_dotenv

import fooocus_client

# ---------------------------------------------------------------------------
# Konfiguration aus .env
# ---------------------------------------------------------------------------

load_dotenv()  # laedt .env aus dem Arbeitsverzeichnis, ueberschreibt keine echten ENV-Variablen


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env(name, str(default))).strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(_env(name, str(default))).strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return str(_env(name, str(default))).strip().lower() in {"1", "true", "yes", "ja", "on"}


DEFAULT_SYSTEM_CONTEXT = """\
Du bist eine erfahrene Comic-Autorin und schreibst gemeinsam mit Maedchen im \
Alter von 12 Jahren ein Comic-Skript. Du antwortest ausschliesslich auf Deutsch, \
in einfacher, lebendiger und altersgerechter Sprache.

Regeln:
- Die Geschichte ist freundlich, mutmachend und altersgerecht (keine Gewalt, \
keine Angst machenden oder unpassenden Inhalte, keine Werbung, keine Romantik).
- Du erfindest nur Figuren, die vorgegeben wurden, und nennst sie immer bei ihrem Namen.
- Die Bildbeschreibungen sind konkret und zeichenbar: Bildausschnitt (z.B. Nahaufnahme, \
Totale), Ort, Handlung, Mimik, Farben und Stimmung.
- Die Erzaehltexte sind kurz (maximal zwei Saetze) und treiben die Geschichte voran.
- Die Dialoge sind kurz, natuerlich und passen zur jeweiligen Figur.
- Das Panel 1 zeigt die Startszene, das letzte Panel erreicht das Ziel der Szene.
- Du gibst nur das fertige Skript aus, keine Erklaerungen, keine Einleitung, \
keine Rueckfragen und keine Markdown-Codebloecke.\
"""

DEFAULT_PROMPT_TEMPLATE = """\
Schreibe ein Skript fuer EINE Comicseite mit genau {panel_count} Panels.

FIGUREN:
{characters}

SETTING (Ort, Zeit, Stimmung):
{setting}

STARTSZENE (so beginnt die Seite):
{start_scene}

ZIEL DER SZENE (so endet die Seite):
{goal}

Gib das Ergebnis exakt in diesem Format aus, fuer jedes Panel von 1 bis {panel_count}:

PANEL <Nummer>
BILD: <ausfuehrliche Beschreibung des Bildes>
TEXT: <Erzaehltext der Textbox, 1-2 Saetze>
DIALOG:
<Figurenname>: <was die Figur sagt>
<Figurenname>: <was die Figur sagt>

Wenn in einem Panel niemand spricht, schreibe unter DIALOG die Zeile "(kein Dialog)".
Verwende zwischen den Panels eine Leerzeile.\
"""

DEFAULT_CHARACTER_LINE = "- {name}: {description}"

DEFAULT_TRANSLATION_PROMPT = """\
Du uebersetzt Bildbeschreibungen aus einem Comic-Skript vom Deutschen ins Englische, \
damit ein Bildgenerator sie versteht. Behalte alle Namen, Details, Farben, Kameraeinstellungen \
und Stimmungen bei. Antworte ausschliesslich mit der englischen Uebersetzung - ohne \
Anfuehrungszeichen, ohne Einleitung und ohne Erklaerung.\
"""


@dataclass
class Config:
    """Alle Einstellungen, die ueber die .env-Datei gesteuert werden."""

    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434"))
    model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "gemma4:latest"))
    timeout: int = field(default_factory=lambda: _env_int("OLLAMA_TIMEOUT", 300))
    temperature: float = field(default_factory=lambda: _env_float("OLLAMA_TEMPERATURE", 0.8))
    top_p: float = field(default_factory=lambda: _env_float("OLLAMA_TOP_P", 0.9))
    num_ctx: int = field(default_factory=lambda: _env_int("OLLAMA_NUM_CTX", 8192))
    num_predict: int = field(default_factory=lambda: _env_int("OLLAMA_NUM_PREDICT", 2048))

    # Der "versteckte Kontext": Systemprompt + Vorlage fuer die eigentliche Anfrage.
    system_context: str = field(default_factory=lambda: _env("SYSTEM_CONTEXT", DEFAULT_SYSTEM_CONTEXT))
    prompt_template: str = field(default_factory=lambda: _env("PROMPT_TEMPLATE", DEFAULT_PROMPT_TEMPLATE))
    character_line: str = field(default_factory=lambda: _env("CHARACTER_LINE_TEMPLATE", DEFAULT_CHARACTER_LINE))

    # Bildbeschreibungen vor der Bildgenerierung ins Englische uebersetzen.
    # Bildmodelle verstehen Deutsch kaum, ohne diesen Schritt passt das Bild
    # meist nicht zum Panel.
    translate_image_prompt: bool = field(
        default_factory=lambda: _env_bool("TRANSLATE_IMAGE_PROMPT", True)
    )
    translation_system_prompt: str = field(
        default_factory=lambda: _env("TRANSLATION_SYSTEM_PROMPT", DEFAULT_TRANSLATION_PROMPT)
    )

    # Oberflaeche
    app_title: str = field(default_factory=lambda: _env("APP_TITLE", "Comic-Werkstatt"))
    app_subtitle: str = field(
        default_factory=lambda: _env(
            "APP_SUBTITLE",
            "Erfinde deine Figuren, beschreibe die Szene - und lass dein Comic-Skript schreiben!",
        )
    )
    min_panels: int = field(default_factory=lambda: _env_int("MIN_PANELS", 4))
    max_panels: int = field(default_factory=lambda: _env_int("MAX_PANELS", 6))
    default_panels: int = field(default_factory=lambda: _env_int("DEFAULT_PANELS", 5))

    # Server
    server_name: str = field(default_factory=lambda: _env("SERVER_NAME", "127.0.0.1"))
    server_port: int = field(default_factory=lambda: _env_int("SERVER_PORT", 7860))
    share: bool = field(default_factory=lambda: _env_bool("SHARE", False))


CONFIG = Config()
FOOOCUS = fooocus_client.FooocusConfig()

MAX_CHARACTERS = 3


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def fill_template(template: str, values: dict) -> str:
    """Ersetzt {platzhalter} in einer Vorlage.

    Bewusst nicht str.format(): unbekannte geschweifte Klammern in der Vorlage
    (z.B. in einem Beispielformat) bleiben unveraendert stehen, statt einen
    Fehler auszuloesen.
    """

    def replace(match: re.Match) -> str:
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)

    return _PLACEHOLDER.sub(replace, template)


def clean_output(text: str) -> str:
    """Entfernt Denk-Bloecke und Markdown-Codefences aus der Modellantwort."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^\s*```[a-zA-Z]*\s*\n", "", text)
    text = re.sub(r"\n\s*```\s*$", "", text)
    return text.strip()


def build_character_block(characters: list) -> str:
    """Baut den Figuren-Abschnitt fuer den Prompt. characters: [(name, beschreibung), ...]"""
    lines = []
    for name, description in characters:
        name = (name or "").strip()
        description = (description or "").strip()
        if not name:
            continue
        if not description:
            description = "keine weitere Beschreibung"
        lines.append(fill_template(CONFIG.character_line, {"name": name, "description": description}))
    return "\n".join(lines)


def build_prompt(characters: list, setting: str, start_scene: str, goal: str, panel_count: int) -> str:
    """Setzt den sichtbaren Teil der Anfrage aus den Eingaben der Kinder zusammen."""
    names = [n.strip() for n, _ in characters if (n or "").strip()]
    return fill_template(
        CONFIG.prompt_template,
        {
            "panel_count": panel_count,
            "characters": build_character_block(characters),
            "character_names": ", ".join(names),
            "setting": (setting or "").strip(),
            "start_scene": (start_scene or "").strip(),
            "goal": (goal or "").strip(),
        },
    )


def validate(characters: list, setting: str, start_scene: str, goal: str) -> list:
    """Gibt eine Liste von Fehlermeldungen in deutscher Sprache zurueck."""
    errors = []
    if not any((n or "").strip() for n, _ in characters):
        errors.append("Bitte gib mindestens einer Figur einen Namen.")
    for index, (name, description) in enumerate(characters, start=1):
        if (description or "").strip() and not (name or "").strip():
            errors.append(f"Figur {index} hat eine Beschreibung, aber keinen Namen.")
    if not (setting or "").strip():
        errors.append("Bitte beschreibe das Setting der Szene.")
    if not (start_scene or "").strip():
        errors.append("Bitte beschreibe die Startszene.")
    if not (goal or "").strip():
        errors.append("Bitte beschreibe das Ziel der Szene.")
    return errors


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def stream_ollama(system_context: str, prompt: str):
    """Ruft /api/chat auf und liefert die Antwort stueckweise (Generator)."""
    payload = {
        "model": CONFIG.model,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "options": {
            "temperature": CONFIG.temperature,
            "top_p": CONFIG.top_p,
            "num_ctx": CONFIG.num_ctx,
            "num_predict": CONFIG.num_predict,
        },
    }

    url = CONFIG.ollama_url.rstrip("/") + "/api/chat"
    with requests.post(url, json=payload, stream=True, timeout=CONFIG.timeout) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            yield chunk.get("message", {}).get("content", "")
            if chunk.get("done"):
                break


def ask_ollama(system_context: str, prompt: str) -> str:
    """Einzelner Aufruf ohne Streaming, z.B. fuer die Uebersetzung."""
    payload = {
        "model": CONFIG.model,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": CONFIG.num_ctx},
    }
    url = CONFIG.ollama_url.rstrip("/") + "/api/chat"
    response = requests.post(url, json=payload, timeout=CONFIG.timeout)
    response.raise_for_status()
    return clean_output(response.json().get("message", {}).get("content", ""))


def check_ollama() -> str:
    """Kurzer Statustext fuer die Oberflaeche."""
    url = CONFIG.ollama_url.rstrip("/") + "/api/tags"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        models = [m.get("name", "") for m in response.json().get("models", [])]
    except requests.RequestException:
        return f"Ollama ist unter {CONFIG.ollama_url} nicht erreichbar."
    if CONFIG.model in models:
        return f"Bereit - Modell `{CONFIG.model}` laeuft auf {CONFIG.ollama_url}."
    return (
        f"Ollama laeuft, aber das Modell `{CONFIG.model}` wurde nicht gefunden. "
        f"Verfuegbar sind z.B.: {', '.join(models[:5]) or 'keine'}."
    )


# ---------------------------------------------------------------------------
# Callback fuer den Button
# ---------------------------------------------------------------------------


def generate_script(
    name1, desc1, name2, desc2, name3, desc3, setting, start_scene, goal, panel_count
):
    characters = [(name1, desc1), (name2, desc2), (name3, desc3)]
    panel_count = int(panel_count)

    errors = validate(characters, setting, start_scene, goal)
    if errors:
        yield "", "Da fehlt noch etwas:\n\n" + "\n".join(f"- {e}" for e in errors)
        return

    prompt = build_prompt(characters, setting, start_scene, goal, panel_count)

    yield "", f"Das Skript wird geschrieben ... (Modell: {CONFIG.model})"

    collected = ""
    try:
        for piece in stream_ollama(CONFIG.system_context, prompt):
            collected += piece
            yield clean_output(collected), "Das Skript wird geschrieben ..."
    except requests.exceptions.ConnectionError:
        yield "", f"Der Ollama-Server unter {CONFIG.ollama_url} ist nicht erreichbar."
        return
    except requests.exceptions.Timeout:
        yield clean_output(collected), "Zeitueberschreitung - der Server hat zu lange gebraucht."
        return
    except requests.exceptions.HTTPError as error:
        detail = ""
        if error.response is not None:
            detail = error.response.text[:300]
        yield "", f"Fehler vom Ollama-Server: {error}. {detail}"
        return
    except (requests.RequestException, RuntimeError) as error:
        yield clean_output(collected), f"Fehler bei der Verbindung zu Ollama: {error}"
        return

    result = clean_output(collected)
    if not result:
        yield "", "Das Modell hat leider nichts geliefert. Bitte versuche es noch einmal."
        return

    yield result, "Fertig! Du kannst das Skript jetzt lesen und direkt im Textfeld aendern."


# ---------------------------------------------------------------------------
# Reiter "Panels": Skript zerlegen und Bilder erzeugen
# ---------------------------------------------------------------------------

_PANEL_HEADING = re.compile(r"^[ \t]*[*#_]*[ \t]*PANEL[ \t]*\d+.*$", re.IGNORECASE | re.MULTILINE)


def split_panels(script: str, max_panels: int) -> list:
    """Zerlegt ein Skript in die einzelnen Panel-Abschnitte."""
    script = (script or "").strip()
    if not script:
        return []

    starts = [match.start() for match in _PANEL_HEADING.finditer(script)]
    if len(starts) >= 2:
        bounds = starts + [len(script)]
        blocks = [script[bounds[i]:bounds[i + 1]].strip() for i in range(len(starts))]
    else:
        # Kein erkennbarer PANEL-Kopf: notfalls an Leerzeilen trennen
        blocks = [block.strip() for block in re.split(r"\n[ \t]*\n", script) if block.strip()]

    return blocks[:max_panels]


def distribute_to_panels(script: str):
    """Fuellt die Panel-Textboxen, blendet nicht benoetigte Zeilen aus und
    entfernt die Bilder der vorherigen Geschichte."""
    count = CONFIG.max_panels
    blocks = split_panels(script, count)
    values = [blocks[i] if i < len(blocks) else "" for i in range(count)]
    visibility = [gr.update(visible=i < len(blocks)) for i in range(count)]
    if blocks:
        note = (
            f"{len(blocks)} Panels aus dem Skript uebernommen. "
            "Du kannst die Texte hier aendern und dann Bilder erzeugen."
        )
    else:
        note = "Es gibt noch kein Skript. Schreibe zuerst im Reiter **Figuren** ein Skript."
    return values + visibility + [note] + [None] * count + [""] * count


def clear_panels():
    return distribute_to_panels("")


def generate_panel_image(panel_index: int, panel_text: str):
    """Schickt eine Panel-Beschreibung an Fooocus und liefert das fertige Bild."""
    if not (panel_text or "").strip():
        yield "Diese Textbox ist noch leer.", gr.update()
        return

    core = fooocus_client.extract_section(panel_text, FOOOCUS.prompt_section)
    hint = ""
    if CONFIG.translate_image_prompt:
        yield f"Panel {panel_index}: Beschreibung wird fuer das Bildmodell uebersetzt ...", gr.update()
        try:
            translated = ask_ollama(CONFIG.translation_system_prompt, core)
            if translated:
                core = translated
        except (requests.RequestException, ValueError) as error:
            hint = (
                f"\n\n<sub>Hinweis: Die Uebersetzung ins Englische hat nicht geklappt "
                f"({error}). Es wurde der deutsche Text verwendet.</sub>"
            )

    prompt = fooocus_client.wrap_prompt(core, FOOOCUS)

    messages: queue.Queue = queue.Queue()
    result: dict = {}

    def worker():
        try:
            result["path"] = fooocus_client.generate_image(prompt, FOOOCUS, on_progress=messages.put)
        except Exception as error:  # noqa: BLE001 - alles wird als Text angezeigt
            result["error"] = error
        finally:
            messages.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    yield f"Panel {panel_index}: Bild wird erzeugt ...", gr.update()
    while True:
        message = messages.get()
        if message is None:
            break
        yield f"Panel {panel_index}: {message}", gr.update()
    thread.join()

    if "error" in result:
        yield f"Fehler: {result['error']}", gr.update()
        return

    yield f"Fertig. Bild-Prompt: _{prompt}_{hint}", result["path"]


def reset_all():
    return (
        "", "", "", "", "", "",           # Figuren
        "", "", "",                        # Setting, Start, Ziel
        CONFIG.default_panels,             # Panel-Anzahl
        "",                                # Skript
        "Alles zurueckgesetzt. Los geht's!",
    )


# ---------------------------------------------------------------------------
# Oberflaeche
# ---------------------------------------------------------------------------

CSS = """
.big-script textarea {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    font-size: 15px !important;
    line-height: 1.55 !important;
}
"""


def make_panel_handler(panel_index: int):
    """Erzeugt den Klick-Handler fuer den 'generiere'-Knopf eines Panels."""

    def handler(panel_text):
        yield from generate_panel_image(panel_index, panel_text)

    return handler


def build_ui() -> gr.Blocks:
    with gr.Blocks(title=CONFIG.app_title, theme=gr.themes.Soft(), css=CSS) as demo:
        gr.Markdown(f"# {CONFIG.app_title}\n{CONFIG.app_subtitle}")

        with gr.Tabs():
            # -----------------------------------------------------------------
            # Reiter 1: Figuren und Skript
            # -----------------------------------------------------------------
            with gr.Tab("Figuren"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("## 1. Deine Figuren\nDu kannst bis zu drei Figuren erfinden.")

                        character_inputs = []
                        for index in range(1, MAX_CHARACTERS + 1):
                            with gr.Accordion(f"Figur {index}", open=(index == 1)):
                                name = gr.Textbox(
                                    label="Name",
                                    placeholder="z.B. Lina",
                                    max_lines=1,
                                )
                                description = gr.Textbox(
                                    label="Beschreibung",
                                    placeholder="Wie sieht die Figur aus? Wie alt ist sie? "
                                    "Was kann sie besonders gut? Was mag sie?",
                                    lines=4,
                                )
                                character_inputs.extend([name, description])

                        gr.Markdown("## 2. Die Szene")
                        setting = gr.Textbox(
                            label="Setting - wo und wann spielt die Szene?",
                            placeholder="z.B. In einer Werkstatt voller Roboter, spaet am Abend. "
                            "Draussen regnet es.",
                            lines=3,
                        )
                        start_scene = gr.Textbox(
                            label="Startszene - wie faengt es an?",
                            placeholder="z.B. Lina findet einen kaputten Roboter unter einer Decke.",
                            lines=3,
                        )
                        goal = gr.Textbox(
                            label="Ziel - wie soll es ausgehen?",
                            placeholder="z.B. Der Roboter laeuft wieder und bedankt sich bei Lina.",
                            lines=3,
                        )

                        panel_count = gr.Slider(
                            minimum=CONFIG.min_panels,
                            maximum=CONFIG.max_panels,
                            value=CONFIG.default_panels,
                            step=1,
                            label="Wie viele Panels soll die Seite haben?",
                        )

                        with gr.Row():
                            generate_button = gr.Button("Skript schreiben", variant="primary", scale=3)
                            reset_button = gr.Button("Zuruecksetzen", scale=1)

                    with gr.Column(scale=1):
                        gr.Markdown("## 3. Dein Comic-Skript")
                        status = gr.Markdown(check_ollama())
                        script = gr.Textbox(
                            label="Skript (du kannst hier alles aendern)",
                            lines=32,
                            max_lines=60,
                            show_copy_button=True,
                            elem_classes="big-script",
                            placeholder="Hier erscheint dein Skript, sobald du auf "
                            "'Skript schreiben' klickst.",
                        )

                inputs = character_inputs + [setting, start_scene, goal, panel_count]

                gr.Examples(
                    examples=[
                        [
                            "Lina", "12 Jahre alt, kurze rote Locken, Latzhose voller Werkzeug, "
                            "bastelt am liebsten an Maschinen.",
                            "Bolt", "Ein kleiner runder Roboter mit einem verbeulten Arm und "
                            "einem leuchtenden blauen Auge. Er piepst statt zu sprechen.",
                            "", "",
                            "Eine alte Fahrradwerkstatt, die Lina zur Roboter-Werkstatt umgebaut hat. "
                            "Abends, warmes Lampenlicht, ueberall Schrauben und Kabel.",
                            "Lina zieht eine staubige Decke von einem alten Roboter und entdeckt, "
                            "dass er noch ganz leise summt.",
                            "Lina repariert Bolts Arm und die beiden werden Freunde.",
                            5,
                        ],
                    ],
                    inputs=inputs,
                    label="Beispiel zum Ausprobieren",
                )

            # -----------------------------------------------------------------
            # Reiter 2: Panels und Bilder
            # -----------------------------------------------------------------
            with gr.Tab("Panels"):
                gr.Markdown(
                    "## Deine Panels\n"
                    "Hier steht jedes Panel deines Skripts in einer eigenen Textbox. "
                    "Aendere den Text, wenn du moechtest, und klicke dann auf **generiere**, "
                    "um ein Bild dazu zeichnen zu lassen."
                )
                with gr.Row():
                    take_over_button = gr.Button("Skript in die Panels uebernehmen", scale=2)
                    fooocus_status = gr.Markdown(fooocus_client.check_server(FOOOCUS))

                panel_note = gr.Markdown(
                    "Es gibt noch kein Skript. Schreibe zuerst im Reiter **Figuren** ein Skript."
                )

                panel_rows, panel_boxes, panel_images, panel_notes = [], [], [], []
                for index in range(1, CONFIG.max_panels + 1):
                    with gr.Row(visible=False, equal_height=True) as row:
                        with gr.Column(scale=3):
                            box = gr.Textbox(
                                label=f"Panel {index}",
                                lines=12,
                                max_lines=24,
                                elem_classes="big-script",
                            )
                            panel_button = gr.Button(
                                f"generiere Bild fuer Panel {index}", variant="primary"
                            )
                            panel_message = gr.Markdown("")
                        with gr.Column(scale=2):
                            image = gr.Image(
                                label=f"Bild zu Panel {index}",
                                type="filepath",
                                height=420,
                                show_download_button=True,
                                interactive=False,
                            )
                    panel_rows.append(row)
                    panel_boxes.append(box)
                    panel_images.append(image)
                    panel_notes.append(panel_message)

                    panel_button.click(
                        fn=make_panel_handler(index),
                        inputs=[box],
                        outputs=[panel_message, image],
                    )

        # ---------------------------------------------------------------------
        # Verdrahtung
        # ---------------------------------------------------------------------
        panel_outputs = panel_boxes + panel_rows + [panel_note] + panel_images + panel_notes

        generate_button.click(
            fn=generate_script,
            inputs=inputs,
            outputs=[script, status],
        ).then(
            fn=distribute_to_panels,
            inputs=[script],
            outputs=panel_outputs,
        )

        reset_button.click(
            fn=reset_all,
            inputs=None,
            outputs=inputs + [script, status],
        ).then(
            fn=clear_panels,
            inputs=None,
            outputs=panel_outputs,
        )

        take_over_button.click(
            fn=distribute_to_panels,
            inputs=[script],
            outputs=panel_outputs,
        )

        gr.Markdown(
            f"<sub>Text: `{CONFIG.model}` auf {CONFIG.ollama_url} &middot; "
            f"Bilder: Fooocus auf {FOOOCUS.url} &middot; "
            "Einstellungen und Verhalten werden in der Datei `.env` festgelegt.</sub>"
        )

    return demo


if __name__ == "__main__":
    build_ui().queue().launch(
        server_name=CONFIG.server_name,
        server_port=CONFIG.server_port,
        share=CONFIG.share,
        inbrowser=True,
    )
