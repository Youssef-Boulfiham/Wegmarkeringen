#!/bin/bash
# Dubbelklik dit bestand (macOS) om alle nieuwe opnames te transcriberen.

# ---- Instellingen ---------------------------------------------------------
# Leeg = automatisch zoeken naar een aangesloten microfoon/recorder met een map RECORD.
# Of vul zelf een map in, bv. "$HOME/Documents/mp3".
MP3_MAP=""
TRANSCRIPT_MAP="$HOME/Documents/Transcripts"   # hier komen de .txt-bestanden
MODEL="small"                                    # tiny/base/small/medium/large-v3
TAAL="nl"                                        # leeg ("") = automatisch detecteren
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if [ -z "$MP3_MAP" ]; then
  for d in /Volumes/*/RECORD /Volumes/*/*/RECORD; do
    [ -d "$d" ] && MP3_MAP="$d" && break
  done
  if [ -z "$MP3_MAP" ]; then
    echo "Geen map RECORD gevonden op een aangesloten apparaat."
    echo "Aangesloten volumes:"; ls /Volumes
    read -r -p "Druk op Enter om te sluiten..."; exit 1
  fi
  echo "Microfoon gevonden: $MP3_MAP"
fi

if [ ! -d .venv ]; then
  echo "Eerste keer: omgeving installeren (duurt even)..."
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip faster-whisper || {
    echo "Installatie mislukt. Is Python 3 geinstalleerd? (https://www.python.org)"; read -r; exit 1; }
fi

.venv/bin/python transcribe.py "$MP3_MAP" --out "$TRANSCRIPT_MAP" --model "$MODEL" ${TAAL:+--language "$TAAL"}
echo; echo "Transcripts staan in: $TRANSCRIPT_MAP"
open "$TRANSCRIPT_MAP" 2>/dev/null
read -r -p "Druk op Enter om te sluiten..."
