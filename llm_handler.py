"""Ollama-Anbindung: erzeugt aus den Nutzereingaben ein Comic-Drehbuch.

Das Modell wird mit einem versteckten System-Prompt aus der .env-Datei
gesteuert und antwortet in einem festen Markdown-Format, das hier wieder
in einzelne Panel-Objekte zerlegt wird.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config


class LLMError(RuntimeError):
    """Fehler bei der Kommunikation mit dem Ollama-Server."""


# --------------------------------------------------------------- Datentypen

@dataclass
class Character:
    name: str = ""
    appearance: str = ""
    personality: str = ""

    @property
    def is_filled(self) -> bool:
        return bool(self.name.strip())

    def as_prompt_line(self) -> str:
        parts = [self.name.strip()]
        if self.appearance.strip():
            parts.append("Aussehen: %s" % self.appearance.strip())
        if self.personality.strip():
            parts.append("Eigenschaften: %s" % self.personality.strip())
        return " | ".join(parts)


@dataclass
class Panel:
    index: int = 0
    description: str = ""
    narration: str = ""
    dialogue: List[str] = field(default_factory=list)

    @property
    def dialogue_text(self) -> str:
        return "\n".join(self.dialogue)

    def to_markdown(self) -> str:
        lines = [
            "## Panel %d" % self.index,
            "**Bildbeschreibung:** %s" % self.description.strip(),
            "**Erzähler-Text:** %s" % self.narration.strip(),
            "**Sprechblasen:**",
        ]
        if self.dialogue:
            lines.extend("- %s" % d for d in self.dialogue)
        else:
            lines.append("- (keine)")
        return "\n".join(lines)


# ------------------------------------------------------------ Prompt-Aufbau

def build_user_prompt(
    panel_count: int,
    setting: str,
    story_start: str,
    story_goal: str,
    characters: List[Character],
    comic_title: str = "",
    artist_name: str = "",
) -> str:
    """Baut den sichtbaren Teil des Prompts für Ollama."""
    filled = [c for c in characters if c.is_filled]
    if filled:
        char_block = "\n".join("- %s" % c.as_prompt_line() for c in filled)
        names = ", ".join(c.name.strip() for c in filled)
    else:
        char_block = "- (keine Figuren angegeben, erfinde eine sympathische Hauptfigur)"
        names = "die Hauptfigur"

    lines = [
        "Schreibe das Drehbuch für EINE Comic-Seite mit genau %d Panels." % panel_count,
        "",
        "TITEL DES COMICS: %s" % (comic_title.strip() or "(kein Titel angegeben)"),
        "KUENSTLERIN / KUENSTLER: %s" % (artist_name.strip() or "(unbekannt)"),
        "",
        "FIGUREN (benutze genau diese Namen: %s):" % names,
        char_block,
        "",
        "ORT / UMGEBUNG:",
        setting.strip() or "(nicht angegeben - denke dir einen passenden MINT-Ort aus)",
        "",
        "ANFANG DER GESCHICHTE:",
        story_start.strip() or "(nicht angegeben)",
        "",
        "ZIEL / ENDE DER GESCHICHTE:",
        story_goal.strip() or "(nicht angegeben)",
        "",
        "Die Geschichte muss in genau %d Panels vom Anfang bis zum Ende erzählt werden." % panel_count,
        "Panel 1 zeigt den Anfang, Panel %d zeigt das Ende." % panel_count,
        "",
        config.PANEL_FORMAT_PROMPT,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- Ollama API

def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        raise LLMError("Ollama antwortet mit HTTP %s:\n%s" % (err.code, detail)) from err
    except urllib.error.URLError as err:
        raise LLMError(
            "Kein Kontakt zum Ollama-Server (%s): %s\n"
            "Läuft 'ollama serve' und ist das Modell '%s' installiert?"
            % (config.OLLAMA_HOST, err.reason, config.OLLAMA_MODEL)
        ) from err
    except json.JSONDecodeError as err:
        raise LLMError("Ollama hat keine gültige JSON-Antwort geliefert: %s" % err) from err


def call_ollama(user_prompt: str, system_prompt: Optional[str] = None) -> str:
    """Schickt den Prompt an /api/generate und liefert den Antworttext."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": user_prompt,
        "system": system_prompt if system_prompt is not None else config.SYSTEM_PROMPT_GERMAN,
        "stream": False,
        "options": {
            "temperature": config.OLLAMA_TEMPERATURE,
            "num_predict": config.OLLAMA_NUM_PREDICT,
        },
    }
    result = _post_json(config.OLLAMA_HOST + "/api/generate", payload, config.OLLAMA_TIMEOUT)
    text = (result.get("response") or "").strip()
    if not text:
        raise LLMError("Das Modell '%s' hat einen leeren Text zurückgegeben." % config.OLLAMA_MODEL)
    return text


def list_models() -> List[str]:
    """Verfügbare Modelle abfragen (für die Statusanzeige)."""
    try:
        with urllib.request.urlopen(config.OLLAMA_HOST + "/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


# ------------------------------------------------------------------- Parsing

_PANEL_RE = re.compile(r"^\s{0,3}#{0,4}\s*\**\s*panel\s*(\d+)", re.IGNORECASE)
_FIELD_RE = re.compile(
    r"^\s*[-*]?\s*\**\s*(bildbeschreibung|erz(?:ae|ä|a)hler[- _]?text|sprechblasen|"
    r"dialoge?|text|beschreibung)\s*\**\s*:?\s*\**\s*:?\s*(.*)$",
    re.IGNORECASE,
)

_FIELD_MAP = {
    "bildbeschreibung": "description",
    "erzahler-text": "narration",
    "erzahlertext": "narration",
    "dialoge": "dialogue",
    "beschreibung": "description",
    "erzaehler-text": "narration",
    "erzähler-text": "narration",
    "erzaehlertext": "narration",
    "erzählertext": "narration",
    "text": "narration",
    "sprechblasen": "dialogue",
    "dialog": "dialogue",
}


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\**\s*", "", text)
    text = re.sub(r"\s*\**$", "", text)
    return text.strip(" *_")


def parse_script(script: str, expected_panels: int = 0) -> List[Panel]:
    """Zerlegt das Markdown-Drehbuch in Panel-Objekte.

    Der Parser ist absichtlich tolerant: LLM-Ausgaben weichen gerne leicht
    vom vorgegebenen Format ab (fehlende Sterne, andere Überschriftenebene).
    """
    panels: List[Panel] = []
    current: Optional[Panel] = None
    field_name: Optional[str] = None

    for raw_line in (script or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        panel_match = _PANEL_RE.match(line)
        if panel_match:
            current = Panel(index=int(panel_match.group(1)))
            panels.append(current)
            field_name = None
            continue

        if current is None:
            continue

        field_match = _FIELD_RE.match(line)
        if field_match:
            key = field_match.group(1).lower().replace("_", "-").replace(" ", "-")
            field_name = _FIELD_MAP.get(key)
            rest = _clean(field_match.group(2))
            if field_name == "dialogue":
                if rest and not rest.lower().startswith("(keine"):
                    current.dialogue.append(rest)
            elif field_name == "description":
                current.description = rest
            elif field_name == "narration":
                current.narration = rest
            continue

        # Fortsetzungszeile des aktuellen Feldes
        content = _clean(re.sub(r"^\s*[-*•]\s*", "", line))
        if not content or content.lower().startswith("(keine"):
            continue
        if field_name == "dialogue":
            current.dialogue.append(content)
        elif field_name == "description":
            current.description = (current.description + " " + content).strip()
        elif field_name == "narration":
            current.narration = (current.narration + " " + content).strip()
        elif current.description:
            current.description = (current.description + " " + content).strip()
        else:
            current.description = content

    # Nummerierung normalisieren
    for i, panel in enumerate(panels, start=1):
        panel.index = i

    if expected_panels:
        panels = panels[:expected_panels]
        while len(panels) < expected_panels:
            panels.append(Panel(index=len(panels) + 1))

    return panels


def panels_to_markdown(panels: List[Panel]) -> str:
    """Baut aus den (evtl. editierten) Panels wieder ein Drehbuch."""
    return "\n\n".join(p.to_markdown() for p in panels)


def generate_script(
    panel_count: int,
    setting: str,
    story_start: str,
    story_goal: str,
    characters: List[Character],
    comic_title: str = "",
    artist_name: str = "",
) -> Dict[str, object]:
    """Kompletter Ablauf: Prompt bauen, Ollama fragen, Antwort parsen."""
    panel_count = max(config.MIN_PANELS, min(config.MAX_PANELS, int(panel_count)))
    prompt = build_user_prompt(
        panel_count, setting, story_start, story_goal, characters, comic_title, artist_name
    )
    raw = call_ollama(prompt)
    panels = parse_script(raw, expected_panels=panel_count)
    return {"raw": raw, "panels": panels, "prompt": prompt}
