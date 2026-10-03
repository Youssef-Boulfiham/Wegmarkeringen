# MP3 transcriber

Transcribeert met één klik alle (nieuwe) mp3-bestanden in een map, lokaal op je Mac
met [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Er gaat niets naar internet
behalve de eenmalige download van het model.

## Instellen (eenmalig)
1. Kopieer deze map naar je Mac.
2. Open `Transcribeer.command` in een teksteditor en zet `MP3_MAP` op jouw map met mp3's.
3. Dubbelklik `Transcribeer.command`. Krijg je een beveiligingsmelding: rechtsklik → *Open*.
   De eerste run installeert alles in `.venv` en downloadt het model.

## Gebruik
Dubbelklik `Transcribeer.command` wanneer je wilt. Transcripts komen in
`<MP3_MAP>/transcripts/<naam>.txt`; bestanden die al een transcript hebben worden overgeslagen.

Tips: `MODEL="medium"` of `"large-v3"` geeft betere kwaliteit maar is trager.
Tijdstempels nodig? Voeg `--timestamps` toe aan de regel met `transcribe.py`.
