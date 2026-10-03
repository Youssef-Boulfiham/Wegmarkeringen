"""Transcribeer alle mp3-bestanden in een map naar tekst.

Gebruik:  python transcribe.py /pad/naar/map [--model small] [--language nl]

- Schrijft voor elk bestand `naam.mp3` een `transcripts/naam.txt`.
- Bestanden met een bestaand transcript worden overgeslagen, dus je kunt het
  script zo vaak draaien als je wilt: alleen nieuwe mp3's worden verwerkt.
"""
import argparse
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def fmt(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("folder", type=Path)
    p.add_argument("--model", default="small",
                   help="tiny, base, small, medium, large-v3 (groter = beter maar trager)")
    p.add_argument("--language", default=None,
                   help="bv. 'nl' of 'en'; leeg = automatisch detecteren")
    p.add_argument("--timestamps", action="store_true", help="tijdstempels per zin")
    args = p.parse_args()

    folder = args.folder.expanduser()
    if not folder.is_dir():
        sys.exit(f"Map bestaat niet: {folder}")
    out_dir = folder / "transcripts"
    out_dir.mkdir(exist_ok=True)

    todo = [f for f in sorted(folder.rglob("*"))
            if f.suffix.lower() == ".mp3" and out_dir not in f.parents
            and not (out_dir / f.relative_to(folder).with_suffix(".txt")).exists()]
    if not todo:
        print("Niets nieuws om te transcriberen.")
        return

    print(f"{len(todo)} nieuw(e) bestand(en). Model '{args.model}' laden...")
    model = WhisperModel(args.model, device="auto", compute_type="int8")

    for i, mp3 in enumerate(todo, 1):
        target = out_dir / mp3.relative_to(folder).with_suffix(".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(todo)}] {mp3.name}", flush=True)
        try:
            segments, info = model.transcribe(str(mp3), language=args.language, vad_filter=True)
            lines = [(f"[{fmt(s.start)}] " if args.timestamps else "") + s.text.strip()
                     for s in segments]
        except Exception as e:  # beschadigd bestand: overslaan, volgende keer opnieuw
            print(f"   overgeslagen ({e})")
            continue
        # eerst naar .part schrijven zodat een afgebroken run geen half transcript achterlaat
        tmp = target.with_suffix(".part")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.rename(target)
        print(f"   -> {target.relative_to(folder)} ({info.language})")

    print("Klaar.")


if __name__ == "__main__":
    main()
