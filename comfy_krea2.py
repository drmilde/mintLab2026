#!/usr/bin/env python3
"""Schickt den Workflow aus krea2.json an einen laufenden ComfyUI-Server.

Aufruf:
    python3 comfy_krea2.py "ein roter Drache ueber Fulda" drache.png

Es wird nur die Python-Standardbibliothek benutzt.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# Node-IDs aus krea2.json
NODE_USER_PROMPT = "30:19"   # PrimitiveStringMultiline (Text String (User Prompt))
NODE_SAVE_IMAGE = "29"       # SaveImage
NODE_KSAMPLER = "30:3"       # KSampler
NODE_RESOLUTION = "49"       # ResolutionSelector
NODE_LATENT = "30:5"         # EmptyLatentImage
NODE_ENABLE_LORA = "30:23"   # Boolean (Enable LoRA?)
NODE_REFINE_PROMPT = "30:24" # Boolean (Refine Prompt?)

ASPECT_RATIOS = [
    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
    "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
]

WORKFLOW_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krea2.json")


def http_json(url, payload=None):
    """GET (payload=None) oder POST eines JSON-Requests."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def snap_size(value, name):
    """Auf ein Vielfaches von 8 runden und auf den erlaubten Bereich pruefen."""
    if not 16 <= value <= 16384:
        sys.exit("%s muss zwischen 16 und 16384 Pixeln liegen (angegeben: %d)." % (name, value))
    snapped = max(16, int(round(value / 8.0)) * 8)
    if snapped != value:
        print("Hinweis: %s %d -> %d (Vielfaches von 8)." % (name, value, snapped))
    return snapped


def build_workflow(args):
    """Workflow laden und Prompt / Dateiname / Seed einsetzen."""
    with open(args.workflow, "r", encoding="utf-8") as fh:
        wf = json.load(fh)

    wf[NODE_USER_PROMPT]["inputs"]["value"] = args.prompt

    # SaveImage kennt nur ein Prefix; ComfyUI haengt _00001_.png an.
    prefix = os.path.splitext(os.path.basename(args.outfile))[0]
    wf[NODE_SAVE_IMAGE]["inputs"]["filename_prefix"] = prefix

    seed = args.seed if args.seed is not None else random.randint(0, 2**63 - 1)
    wf[NODE_KSAMPLER]["inputs"]["seed"] = seed
    if args.steps is not None:
        wf[NODE_KSAMPLER]["inputs"]["steps"] = args.steps
    if args.width is not None or args.height is not None:
        if args.width is None or args.height is None:
            sys.exit("--width und --height bitte gemeinsam angeben "
                     "(oder stattdessen --aspect-ratio / --megapixels benutzen).")
        # Feste Masse: die Links auf den ResolutionSelector durch Zahlen ersetzen.
        wf[NODE_LATENT]["inputs"]["width"] = snap_size(args.width, "Breite")
        wf[NODE_LATENT]["inputs"]["height"] = snap_size(args.height, "Hoehe")
        wf.pop(NODE_RESOLUTION, None)  # Node wird nicht mehr gebraucht
    else:
        if args.aspect_ratio is not None:
            wf[NODE_RESOLUTION]["inputs"]["aspect_ratio"] = args.aspect_ratio
        if args.megapixels is not None:
            wf[NODE_RESOLUTION]["inputs"]["megapixels"] = args.megapixels

    wf[NODE_ENABLE_LORA]["inputs"]["value"] = bool(args.lora)
    wf[NODE_REFINE_PROMPT]["inputs"]["value"] = bool(args.refine)

    return wf, seed


def queue_prompt(server, workflow, client_id):
    """Workflow in die Warteschlange stellen, prompt_id zurueckgeben."""
    try:
        result = http_json(server + "/prompt", {"prompt": workflow, "client_id": client_id})
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        sys.exit("ComfyUI hat den Workflow abgelehnt (HTTP %s):\n%s" % (err.code, detail))
    except urllib.error.URLError as err:
        sys.exit("Kein Kontakt zu %s: %s" % (server, err.reason))
    return result["prompt_id"]


def wait_for_result(server, prompt_id, timeout, poll=1.0):
    """Auf /history warten, bis der Job fertig ist."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = http_json("%s/history/%s" % (server, prompt_id))
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False:
                messages = status.get("messages", [])
                sys.exit("Fehler bei der Ausfuehrung:\n%s" % json.dumps(messages, indent=2))
            return entry
        time.sleep(poll)
    sys.exit("Timeout: nach %s s war der Job %s nicht fertig." % (timeout, prompt_id))


def download_images(server, entry, outfile):
    """Erzeugte Bilder holen und lokal speichern."""
    images = []
    for node_output in entry.get("outputs", {}).values():
        images.extend(node_output.get("images", []))
    images = [img for img in images if img.get("type") != "temp"]
    if not images:
        sys.exit("Der Job lieferte kein Bild zurueck.")

    root, ext = os.path.splitext(outfile)
    if not ext:
        ext = ".png"

    saved = []
    for index, img in enumerate(images):
        query = urllib.parse.urlencode({
            "filename": img["filename"],
            "subfolder": img.get("subfolder", ""),
            "type": img.get("type", "output"),
        })
        with urllib.request.urlopen("%s/view?%s" % (server, query), timeout=60) as resp:
            data = resp.read()
        target = outfile if index == 0 else "%s_%d%s" % (root, index + 1, ext)
        with open(target, "wb") as fh:
            fh.write(data)
        saved.append(target)
    return saved


def main():
    parser = argparse.ArgumentParser(
        description="Bild mit dem krea2-Workflow auf einem ComfyUI-Server erzeugen.")
    parser.add_argument("prompt", help="Bildbeschreibung (User-Prompt)")
    parser.add_argument("outfile", help="Dateiname des erzeugten Bildes, z.B. bild.png")
    parser.add_argument("--server", default="http://127.0.0.1:8188",
                        help="Adresse des ComfyUI-Servers (Default: %(default)s)")
    parser.add_argument("--workflow", default=WORKFLOW_DEFAULT,
                        help="Workflow-JSON im API-Format (Default: krea2.json)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fester Seed; ohne Angabe wird er zufaellig gewaehlt")
    parser.add_argument("--steps", type=int, default=None, help="Sampler-Schritte (Default: 8)")
    parser.add_argument("--width", type=int, default=None,
                        help="Bildbreite in Pixeln (Vielfaches von 8, 16-16384)")
    parser.add_argument("--height", type=int, default=None,
                        help="Bildhoehe in Pixeln (Vielfaches von 8, 16-16384)")
    parser.add_argument("--aspect-ratio", default=None, choices=ASPECT_RATIOS,
                        help="Seitenverhaeltnis statt fester Masse (Default: 1:1 (Square))")
    parser.add_argument("--megapixels", type=float, default=None,
                        help="Zielgroesse in Megapixeln fuer --aspect-ratio (Default: 1.0)")
    parser.add_argument("--lora", action="store_true", help="LoRA krea2_darkbrush aktivieren")
    parser.add_argument("--refine", action="store_true",
                        help="Prompt vorher vom Textmodell ausformulieren lassen")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="Maximale Wartezeit in Sekunden (Default: %(default)s)")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    workflow, seed = build_workflow(args)

    prompt_id = queue_prompt(server, workflow, str(uuid.uuid4()))
    print("Job %s in der Warteschlange (seed=%d) ..." % (prompt_id, seed))

    entry = wait_for_result(server, prompt_id, args.timeout)
    for path in download_images(server, entry, args.outfile):
        print("Gespeichert: %s" % path)


if __name__ == "__main__":
    main()
