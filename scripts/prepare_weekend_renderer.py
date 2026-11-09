"""Create a reviewed weekend-capable sibling of the saved v2 renderer; no rendering."""

import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.reports.weekend_media_contract import MAX_BYTES,adapted_renderer


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer",required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        source=args.renderer.resolve()
        if source.stat().st_size>MAX_BYTES:raise ValueError("Renderer exceeds the inspection bound")
        text=adapted_renderer(source.read_text(encoding="utf-8-sig"))
        target=source.with_name("weekend_render_episode.py")
        if target==source:raise ValueError("Choose the original render_episode.py")
        if target.exists():
            if target.read_text(encoding="utf-8-sig")!=text:raise ValueError("Existing weekend renderer differs; preserve and review that file")
            print("Already prepared: "+str(target));return 0
        with target.open("x",encoding="utf-8",newline="\n") as file:file.write(text)
        print("Prepared sibling: "+str(target))
        print("Original daily renderer preserved. No speech, render or upload was started.")
        return 0
    except (OSError,ValueError) as error:
        print("HOLD: "+str(error),file=sys.stderr);return 1


if __name__=="__main__":raise SystemExit(main())
