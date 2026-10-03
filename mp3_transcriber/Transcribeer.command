#!/bin/bash
# Dubbelklik dit bestand (macOS) om alle nieuwe mp3's in MP3_MAP te transcriberen.

# ---- Instellingen ---------------------------------------------------------
MP3_MAP="$HOME/Documents/mp3"      # <-- pas aan naar jouw map
MODEL="small"                       # tiny/base/small/medium/large-v3
TAAL="nl"                           # leeg laten ("") = automatisch detecteren
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "Eerste keer: omgeving installeren (duurt even)..."
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip faster-whisper || {
    echo "Installatie mislukt. Is Python 3 geinstalleerd? (https://www.python.org)"; read -r; exit 1; }
fi

.venv/bin/python transcribe.py "$MP3_MAP" --model "$MODEL" ${TAAL:+--language "$TAAL"}
echo; echo "Transcripts staan in: $MP3_MAP/transcripts"
read -r -p "Druk op Enter om te sluiten..."
