#!/usr/bin/env python3.10
"""Comic Maker - Gradio-Oberfläche für eine Comic-Seite mit 4 bis 6 Panels.

Gedacht für einen MINT-Kurs mit Mädchen ab 12 Jahren. Die Oberfläche
führt in sechs Tabs durch den Ablauf:
Creator -> Characters -> Scene -> Script -> Page -> Export
"""

from __future__ import annotations

from typing import List

import gradio as gr

import config
import export_handler
import image_handler
import llm_handler
from llm_handler import Character, Panel

MAX_CHARACTERS = 3
PANEL_SLOTS = config.MAX_PANELS  # 6 vorbereitete Panel-Karten

TAB_CREATOR, TAB_CHARACTERS, TAB_SCENE, TAB_SCRIPT, TAB_PAGE, TAB_EXPORT = range(6)

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

def on_download_png(final_path):
    if not final_path:
        return None, _status("Es gibt noch kein Bild zum Speichern.", "warn")
    try:
        path = export_handler.export_png(final_path)
    except export_handler.ExportError as err:
        return None, _status(str(err), "error")
    return path, _status("PNG-Datei ist bereit - klicke auf den Datei-Namen zum Speichern.", "ok")


def on_download_pdf(final_path, comic_title, artist_name):
    if not final_path:
        return None, _status("Es gibt noch kein Bild zum Speichern.", "warn")
    try:
        path = export_handler.export_pdf(final_path, comic_title or "", artist_name or "")
    except export_handler.ExportError as err:
        return None, _status(str(err), "error")
    return path, _status("PDF-Datei ist bereit - klicke auf den Datei-Namen zum Speichern.", "ok")


def on_print(final_path, artist_name, acronym, comic_title, panel_count):
    ok, message = export_handler.send_to_print_server(
        final_path or "", artist_name or "", acronym or "", comic_title or "", int(panel_count or 0))
    return _status(message, "ok" if ok else "error")


# ------------------------------------------------------------- Oberfläche

CSS = """
.comic-title { text-align: center; }
.big-button button { font-size: 1.15rem !important; padding: 0.8rem !important; }
.status-box { min-height: 2.4rem; }
.hint { font-size: 0.95rem; opacity: 0.85; }
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
                gr.Markdown(
                    "<span class='hint'>Der Text wird von einem Sprachmodell (%s) "
                    "auf deinem eigenen Rechner geschrieben.</span>" % config.OLLAMA_MODEL)

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
                page_prompt = gr.Textbox(
                    label="Bild-Prompt (wird an den Zeichen-Server geschickt)", lines=12,
                    show_copy_button=True,
                    placeholder="Klicke im Tab 'Script' auf 'Weiter zu Page Generation'.")
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
                export_status = gr.Markdown(_status(
                    "Erzeuge zuerst im Tab 'Page' eine Comic-Seite.", "info"),
                    elem_classes=["status-box"])
                gr.Markdown("<span class='hint'>Druckserver: %s</span>"
                            % config.print_server_url())

        # ------------------------------------------------------- Verdrahtung

        btn_signature.click(
            fn=on_generate_signature,
            inputs=[acronym, artist_name],
            outputs=[signature_image, creator_status, st_signature],
        )

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

        btn_png.click(fn=on_download_png, inputs=[st_final_image],
                      outputs=[download_file, export_status])
        btn_pdf.click(fn=on_download_pdf, inputs=[st_final_image, comic_title, artist_name],
                      outputs=[download_file, export_status])
        btn_print.click(fn=on_print,
                        inputs=[st_final_image, artist_name, acronym, comic_title, panel_count],
                        outputs=[export_status])

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
