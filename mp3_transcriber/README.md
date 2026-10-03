# MP3 transcriber

Transcribeert met één klik alle (nieuwe) mp3-bestanden in een map, lokaal op je Mac
met [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Er gaat niets naar internet
behalve de eenmalige download van het model.

## Instellen (eenmalig)
1. Kopieer deze map naar je Mac.
2. Sluit je microfoon/recorder aan. Het script zoekt zelf naar een map `RECORD` op het
   apparaat (`/Volumes/<naam>/RECORD`). Wil je een andere map, vul dan `MP3_MAP` in
   `Transcribeer.command` in.
3. Dubbelklik `Transcribeer.command`. Krijg je een beveiligingsmelding: rechtsklik → *Open*.
   De eerste run installeert alles in `.venv` en downloadt het model.

## Gebruik
Dubbelklik `Transcribeer.command` wanneer je wilt. Transcripts komen in
`~/Documents/Transcripts/<naam>.txt` (instelbaar via `TRANSCRIPT_MAP`), dus niet op de
recorder zelf. Opnames (.mp3, .wav, .m4a) die al een transcript hebben worden overgeslagen.

Tips: `MODEL="medium"` of `"large-v3"` geeft betere kwaliteit maar is trager.
Tijdstempels nodig? Voeg `--timestamps` toe aan de regel met `transcribe.py`.
