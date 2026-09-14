# Comic Maker

Gradio-App zum Erstellen **einer Comic-Seite mit 4 bis 6 Panels**.
Gedacht als einfache Oberfläche für einen MINT-Kurs mit Mädchen ab 12 Jahren.
Die komplette Oberfläche und alle generierten Texte sind auf Deutsch.

## Ablauf (6 Tabs)

| Tab | Name | Funktion |
|-----|------|----------|
| 1 | **Creator** | Künstlername, Kürzel, Comic-Titel; erzeugt ein Graffiti-Signatur-Logo (Krea2) |
| 2 | **Characters** | bis zu 3 Figuren mit Aussehen und Eigenschaften, Beispiel-Buttons |
| 3 | **Scene** | Umgebung, Anfang, Ziel der Geschichte, Panel-Anzahl (4-6); startet die Drehbuch-Generierung (Ollama) |
| 4 | **Script** | Gesamtes Skript als Text plus editierbare Panel-Karten (Bildbeschreibung, Erzähler-Text, Sprechblasen) |
| 5 | **Page** | Style-Eingabe, Bild-Prompt-Vorschau, Zeichnen der Seite (ComfyUI / Krea2), Neuversuch |
| 6 | **Export** | Seite mit Signatur-Fußleiste, Download als PNG/PDF, Upload an den Druckserver |

## Dateien

| Datei | Inhalt |
|-------|--------|
| `app.py` | Gradio-Oberfläche (6 Tabs) und Verdrahtung der Ereignisse |
| `llm_handler.py` | Ollama-Anbindung, Prompt-Aufbau, Parser für das Drehbuch |
| `image_handler.py` | ComfyUI/Krea2-Anbindung (Signatur und Comic-Seite), Bild-Prompt-Synthese |
| `export_handler.py` | Signatur-Stempel, PNG/PDF-Export, POST an den Druckserver |
| `config.py` | liest alle Einstellungen und System-Prompts aus `.env` |
| `.env` | Server-Adressen und **versteckte System-Prompts** (nicht im Code!) |
| `.env.example` | Vorlage ohne die ausformulierten Prompts |
| `krea2.json` | ComfyUI-Workflow im API-Format |
| `comfy_krea2.py` | Referenz-Skript für den ComfyUI-Aufruf (Vorlage für `image_handler.py`) |
| `output/` | erzeugte Bilder, PNG- und PDF-Exporte |

## Installation (Python 3.10)

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Start

```bash
.venv/bin/python app.py
# oder
./run.sh
```

Die App laeuft standardmäßig auf <http://127.0.0.1:7861>
(anpassbar mit `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` in der `.env`).

## Voraussetzungen zur Laufzeit

* **Ollama** mit dem Modell aus `OLLAMA_MODEL` (Standard `gemma4:latest`)

  ```bash
  ollama serve
  ollama pull gemma4:latest
  ```

* **ComfyUI** mit dem Krea2-Workflow, erreichbar unter `COMFY_SERVER_URL`
  (Standard `http://127.0.0.1:8188`). Die Modelle aus `krea2.json`
  (`krea2_turbo_int8_convrot.safetensors`, `qwen3vl_4b_fp8_scaled.safetensors`,
  `qwen_image_vae.safetensors`) muessen installiert sein.

* **Druckserver** mit `POST /api/v1/upload`. Ohne laufenden Druckserver
  funktioniert die App weiter - der Export-Tab zeigt dann eine
  Fehlermeldung an, PNG- und PDF-Download bleiben nutzbar.

## Konfiguration (`.env`)

Alle Einstellungen liegen in der `.env`-Datei, damit das Verhalten ohne
Code-Änderung angepasst werden kann.

| Schlüssel | Bedeutung |
|------------|-----------|
| `OLLAMA_HOST`, `OLLAMA_MODEL` | Adresse und Modell des Textmodells |
| `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TIMEOUT` | Generierungs-Parameter |
| `COMFY_SERVER_URL`, `COMFY_WORKFLOW`, `COMFY_TIMEOUT` | ComfyUI-Server und Workflow-Datei |
| `COMFY_PAGE_ASPECT_RATIO`, `COMFY_PAGE_MEGAPIXELS`, `COMFY_PAGE_STEPS` | Format der Comic-Seite (Standard Hochformat 3:4, 1.5 MP) |
| `COMFY_EXPECTED_SECONDS` | erwartete Dauer eines Bild-Jobs, nur für den Fortschrittsbalken |
| `COMFY_SIGNATURE_*` | Format des Signatur-Logos |
| `COMFY_ENABLE_LORA`, `COMFY_REFINE_PROMPT` | Schalter im Krea2-Workflow |
| `PRINT_SERVER_SCHEME/HOST/PORT/ENDPOINT` | Adresse des Druckservers (oder komplett `PRINT_SERVER_URL`) |
| `OUTPUT_DIR` | Ordner für Bilder und Exporte |
| `GRADIO_SERVER_NAME/PORT/SHARE` | Adresse der Weboberflaeche |

### Versteckter Kontext für das Sprachmodell

| Schlüssel | Bedeutung |
|------------|-----------|
| `SYSTEM_PROMPT_GERMAN` | Grundverhalten: nur Deutsch, einfache Sprache für 12-Jährige, Namenskonsistenz, kurze Texte, positive Inhalte |
| `PANEL_FORMAT_PROMPT` | erzwingt das parsebare Markdown-Format pro Panel |
| `IMAGE_STYLE_PROMPT` | Grundstil für die Bildgenerierung |
| `IMAGE_NEGATIVE_HINTS` | unerwuenschte Bildinhalte |
| `SIGNATURE_STYLE_PROMPT` | Stil des Graffiti-Logos |

`\n` in diesen Werten wird als echter Zeilenumbruch interpretiert.

## Format des Drehbuchs

Das Sprachmodell wird auf dieses Format festgelegt; `llm_handler.parse_script()`
liest es wieder ein (tolerant gegenüber kleinen Abweichungen):

```markdown
## Panel 1
**Bildbeschreibung:** Lina steht vor der Tafel und schaut überrascht.
**Erzähler-Text:** Im Labor leuchtet eine seltsame Formel.
**Sprechblasen:**
- Lina: "Was ist das denn?"
- Robo-X: "Unbekanntes Zeichen entdeckt!"
```

Im Tab **Script** kann in beide Richtungen umgeschaltet werden:
*Text in die Panel-Karten übernehmen* (parsen) und
*Panel-Karten in den Text übernehmen* (neu zusammenbauen).

## Laufzeiten

Gemessen auf einem Mac mit lokalem Ollama und lokalem ComfyUI:

| Schritt | Dauer |
|---------|-------|
| Drehbuch (Ollama, `gemma4:latest`) | ca. 30–40 s |
| Signatur-Logo (1.0 MP) | ca. 1 min (erster Aufruf länger, die Modelle werden geladen) |
| Comic-Seite (1.5 MP) | ca. 3–5 min |

Die 1.5 Megapixel der Seite sind nötig, damit die Schrift in den Sprechblasen
lesbar wird. Wer schneller arbeiten will, kann `COMFY_PAGE_MEGAPIXELS`
verkleinern - dann wird der Text im Bild aber unschärfer.

## Hinweise für den Kurs

* Die Beispiel-Buttons (**Beispiel laden**, **Alle Beispiel-Figuren laden**,
  **Beispiel-Szene laden**) fuellen alle Felder mit MINT-Beispielen -
  praktisch für einen schnellen ersten Durchlauf.
* Erzähler-Text max. ca. 15 Wörter, Sprechblasen max. ca. 12 Wörter,
  sonst passt der Text im Bild nicht in die Blasen.
* Je genauer das Aussehen der Figuren beschrieben ist, desto ähnlicher
  sehen sie auf den einzelnen Panels aus.
