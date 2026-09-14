# Comic-Werkstatt

Gradio-Oberflaeche fuer einen MINT-Kurs (Maedchen, 12 Jahre, Deutsch), in zwei
Reitern.

**Reiter „Figuren"** — Die Teilnehmerinnen beschreiben bis zu drei Figuren, das
Setting, die Startszene und das Ziel der Szene. Daraus erzeugt ein lokal
laufender Ollama-Server ein Skript fuer eine Comicseite mit 4 bis 6 Panels — pro
Panel eine Bildbeschreibung, den Erzaehltext der Textbox und den Dialog zwischen
den Figuren. Das Skript erscheint in einem grossen Textfeld und kann dort direkt
weiterbearbeitet werden.

**Reiter „Panels"** — Das Skript wird automatisch auf bis zu sechs Textboxen
verteilt, eine pro Panel. Jede Box ist bearbeitbar; der Knopf **generiere**
schickt die Beschreibung zusammen mit dem konfigurierten Bild-Kontext an einen
laufenden Fooocus-Server. Das fertige Bild erscheint neben der Textbox,
waehrend der Erzeugung wird der Fortschritt („Sampling step 12/30 …") angezeigt.

## Installation

```bash
python3 -m venv .venv          # Python 3.10 oder neuer
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## Starten

```bash
.venv/bin/python app.py
```

Die App oeffnet sich unter <http://127.0.0.1:7860>.

Voraussetzungen:

```bash
ollama serve            # Textmodell
ollama pull gemma4:latest
```

sowie ein laufender **Fooocus**-Server unter <http://127.0.0.1:7865/> (also mit
`--port 7865` gestartet) fuer die Bilder. Ob beides bereit ist, zeigen die
Statuszeilen in den Reitern „Figuren" und „Panels".

## Konfiguration

Alle Einstellungen stehen in `.env` (Vorlage: `.env.example`), gelesen mit
`python-dotenv`. Wichtig sind:

| Variable | Bedeutung |
| --- | --- |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Server und Modell |
| `OLLAMA_TEMPERATURE`, `OLLAMA_TOP_P`, `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TIMEOUT` | Generierungsparameter |
| `SYSTEM_CONTEXT` | **Der versteckte Kontext**: legt das allgemeine Verhalten fest (Sprache, Zielgruppe, Tonfall, Regeln). Wird als System-Nachricht vor jede Anfrage gesetzt und ist in der Oberflaeche nicht sichtbar. |
| `PROMPT_TEMPLATE` | Vorlage fuer die eigentliche Anfrage inkl. gewuenschtem Ausgabeformat |
| `CHARACTER_LINE_TEMPLATE` | Wie eine einzelne Figur in den Prompt geschrieben wird |
| `APP_TITLE`, `APP_SUBTITLE` | Ueberschriften der Oberflaeche |
| `MIN_PANELS`, `MAX_PANELS`, `DEFAULT_PANELS` | Bereich des Panel-Reglers |
| `SERVER_NAME`, `SERVER_PORT`, `SHARE` | Wo die App laeuft (`0.0.0.0` fuer das Kursnetz) |
| `FOOOCUS_URL`, `FOOOCUS_TIMEOUT` | Fooocus-Server und Wartezeit |
| `FOOOCUS_PROMPT_PREFIX`, `FOOOCUS_PROMPT_SUFFIX`, `FOOOCUS_NEGATIVE_PROMPT` | **Der versteckte Kontext fuer die Bildgenerierung**: wird vor bzw. hinter die Panel-Beschreibung gesetzt |
| `IMAGE_PROMPT_SECTION` | Welcher Abschnitt der Panel-Box als Bild-Prompt dient (`BILD`; leer = ganze Box) |
| `TRANSLATE_IMAGE_PROMPT`, `TRANSLATION_SYSTEM_PROMPT` | Deutsche Bildbeschreibung vor dem Zeichnen ins Englische uebersetzen |
| `FOOOCUS_STYLES`, `FOOOCUS_PERFORMANCE`, `FOOOCUS_ASPECT_RATIO`, `FOOOCUS_OUTPUT_FORMAT`, `FOOOCUS_IMAGE_NUMBER`, `FOOOCUS_SEED` | Fooocus-Einstellungen; leer = so lassen, wie im Fooocus-Fenster eingestellt |

Platzhalter in `PROMPT_TEMPLATE`: `{panel_count}`, `{characters}`,
`{character_names}`, `{setting}`, `{start_scene}`, `{goal}`.
In `CHARACTER_LINE_TEMPLATE`: `{name}`, `{description}`.
Unbekannte geschweifte Klammern bleiben unveraendert stehen.

Hinweise zum Format der `.env`: Mehrzeilige Werte in doppelte
Anfuehrungszeichen setzen und kein `$`-Zeichen verwenden (das wuerde als
Variable interpretiert).

## Zwei Hinweise zur Bildqualitaet

- **Sprache.** Bildmodelle verstehen praktisch nur Englisch. Deshalb uebersetzt
  das Ollama-Modell die Bildbeschreibung vor dem Zeichnen ins Englische
  (`TRANSLATE_IMAGE_PROMPT=true`). Ohne diesen Schritt hat das Bild oft nichts
  mit dem Panel zu tun.
- **Stil.** Ohne einen Comic-Stil in `FOOOCUS_STYLES` zeichnet Fooocus
  fotorealistisch, auch wenn im Prompt „comic book panel" steht. Voreingestellt
  ist deshalb `Fooocus V2, Fooocus Enhance, SAI Comic Book`.

## Dateien

- `app.py` — Oberflaeche, Prompt-Aufbau und Ollama-Anbindung
- `fooocus_client.py` — Anbindung an den Fooocus-Server
- `.env.example` — dokumentierte Vorlage der Konfiguration
- `requirements.txt` — Abhaengigkeiten

### Wie die Fooocus-Anbindung funktioniert

Fooocus hat keine REST-Schnittstelle, sondern ist selbst eine Gradio-Anwendung.
`fooocus_client.py` liest daher `GET /config`, uebernimmt daraus alle im
Fooocus-Fenster eingestellten Werte als Grundlage, ueberschreibt nur Prompt und
die in der `.env` gesetzten Optionen und ruft dann ueber das
Gradio-Queue-Protokoll (`ws /queue/join`) nacheinander `get_task` und
`generate_clicked` auf. Die Funktionsindizes werden dabei aus `/config`
ermittelt und nicht fest verdrahtet — die Anbindung ueberlebt also ein Update
von Fooocus.
