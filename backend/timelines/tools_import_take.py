"""Move the newest ElevenLabs web download into a project's import folder as narr_<scene>.mp3."""
import shutil
import sys
from pathlib import Path

DL = Path.home() / "Downloads"


def main(video_dir: str, scene: str, lang: str = "en") -> None:
    cands = sorted(DL.glob("ElevenLabs_*.mp3"), key=lambda p: p.stat().st_mtime)
    if not cands:
        raise SystemExit("no ElevenLabs download found")
    src = cands[-1]
    dst = Path(video_dir) / "edit" / "audio" / lang / "import" / f"narr_{scene}.mp3"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), dst)
    (dst.parent / f"narr_{scene}.source.txt").write_text(src.name, "utf-8")   # provenance: original file name
    print(scene, "<-", src.name)


if __name__ == "__main__":
    main(*sys.argv[1:])
