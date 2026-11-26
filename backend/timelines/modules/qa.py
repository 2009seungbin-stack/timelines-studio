"""Quality Assurance Engine. Measures the OUTPUT files (not the pipeline's own logs).

Technical checks decide `technical_pass`; editorial, legal and disclosure items are listed in
`human_review_required`. Automatic QC is never recorded as human viewing or user approval.
Inspection frames go to <video>/evidence/qc_tmp and are removed by ultradedit qc_cleanup after a pass.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from .. import config
from ..schemas import QCCheck, QCReport, ResearchDossier, Script, Storyboard, Timeline
from . import audio

TECHNICAL = {"container", "duration", "black_frames", "audio_present", "silence", "loudness", "subtitles",
             "narration_asr", "duplicate_scenes"}


def _probe(path: Path) -> dict:
    out = subprocess.run([config.ffprobe_exe(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                          str(path)], capture_output=True, text=True)
    return json.loads(out.stdout)


def _ff_filter(path: Path, vf: str | None = None, af: str | None = None) -> str:
    cmd = [config.ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path)]
    cmd += ["-vf", vf] if vf else ["-vn"]
    cmd += ["-af", af] if af else ["-an"]
    cmd += ["-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr


def _dhash(img: Image.Image) -> int:
    g = np.asarray(img.convert("L").resize((17, 16), Image.BILINEAR), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def run_qc(project_id: str, video_dir: Path, final_mp4: Path, timeline: Timeline, script: Script,
           storyboard: Storyboard, dossier: ResearchDossier | None, narration: list[dict], srt: Path,
           extra: dict | None = None) -> QCReport:
    checks: list[QCCheck] = []
    review: list[str] = []
    info = _probe(final_mp4)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])

    ok = v is not None and v["width"] * 9 == v["height"] * 16 and v.get("pix_fmt") == "yuv420p"
    checks.append(QCCheck(id="container", name="Container / aspect / pixel format", status="pass" if ok else "fail",
                          details=f"{v and v['width']}x{v and v['height']} {v and v.get('pix_fmt')} "
                                  f"{v and v.get('r_frame_rate')}"))
    diff = abs(dur - timeline.duration_s)
    checks.append(QCCheck(id="duration", name="Duration matches timeline", status="pass" if diff < 0.15 else "fail",
                          details=f"file {dur:.2f}s vs timeline {timeline.duration_s:.2f}s",
                          data={"file_s": dur, "timeline_s": timeline.duration_s}))

    blk = _ff_filter(final_mp4, vf="blackdetect=d=0.4:pix_th=0.08:pic_th=0.98")
    spans = [(float(s), float(e)) for s, e in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", blk)]
    bad = [s for s in spans if not (s[0] > dur - 1.2)]           # allow the closing fade
    checks.append(QCCheck(id="black_frames", name="Unintended black frames", status="fail" if bad else "pass",
                          details=f"{len(bad)} black spans" + (f": {bad[:5]}" if bad else ""), data={"spans": spans}))

    checks.append(QCCheck(id="audio_present", name="Audio stream present",
                          status="pass" if a is not None else "fail",
                          details=f"{a and a['codec_name']} {a and a.get('sample_rate')} Hz {a and a.get('channels')} ch"))
    sil = _ff_filter(final_mp4, af="silencedetect=noise=-45dB:d=2.5")
    silent = [(float(s), float(e)) for s, e in zip(re.findall(r"silence_start: ([\d.]+)", sil),
                                                   re.findall(r"silence_end: ([\d.]+)", sil))]
    checks.append(QCCheck(id="silence", name="Silent stretches >= 2.5 s",
                          status="warn" if silent else "pass",
                          details=f"{len(silent)} stretches {silent[:6]} (no music bed: check pacing by ear)",
                          data={"spans": silent}))
    if silent:
        review.append(f"Listen to {len(silent)} silent stretch(es) >= 2.5 s: {silent[:6]}")

    loud = audio.loudness(final_mp4)
    lok = abs(loud["integrated_lufs"] + 14) <= 1.0 and loud["true_peak_db"] <= -1.0
    checks.append(QCCheck(id="loudness", name="Loudness -14 LUFS / TP <= -1 dBTP", status="pass" if lok else "fail",
                          details=json.dumps(loud), data=loud))

    # subtitles ---------------------------------------------------
    cues = _read_srt(srt)
    problems = []
    for c, nxt in zip(cues, cues[1:] + [None]):
        d = c["end"] - c["start"]
        chars = len(c["text"].replace("\n", ""))
        if d < 0.8:
            problems.append(f"#{c['i']} too short {d:.2f}s")
        if chars / max(d, 0.01) > 21:
            problems.append(f"#{c['i']} {chars / d:.1f} chars/s")
        if any(len(line) > 46 for line in c["text"].split("\n")):
            problems.append(f"#{c['i']} line too long")
        if nxt and nxt["start"] < c["end"]:
            problems.append(f"#{c['i']} overlaps next")
        if c["end"] > dur + 0.05:
            problems.append(f"#{c['i']} ends after video")
    checks.append(QCCheck(id="subtitles", name="Subtitle timing and readability",
                          status="fail" if any("overlap" in p or "after video" in p for p in problems)
                          else ("warn" if problems else "pass"),
                          details=f"{len(cues)} cues; " + ("; ".join(problems[:8]) or "ok")))

    # narration takes transcribed alone ------------------------------
    asr = []
    for n in narration:
        res = audio.transcribe_check(Path(n["file"]), n["text"])
        asr.append({"scene_id": n["scene_id"], **res})
    low = [x for x in asr if x["word_match"] < 0.9]
    checks.append(QCCheck(id="narration_asr", name="Narration matches script (ASR of each take)",
                          status="fail" if any(x["word_match"] < 0.75 for x in asr) else ("warn" if low else "pass"),
                          details=f"min match {min((x['word_match'] for x in asr), default=1):.2f}; "
                                  + "; ".join(f"{x['scene_id']}: {x['differences'][:3]}" for x in low[:5]),
                          data={"takes": asr}))
    if low:
        review.append("Listen to narration takes with low ASR match: " + ", ".join(x["scene_id"] for x in low))

    # duplicate scenes (frames sampled from the output) --------------------
    tmp = video_dir / "evidence" / "qc_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    hashes = []
    for c in timeline.clips:
        mid = c.start_s + min(c.duration_s, 4) / 2 + 0.5
        f = tmp / f"qc_frame_{c.scene_id}.png"
        subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{mid:.2f}", "-i", str(final_mp4),
                        "-frames:v", "1", "-vf", "scale=480:-1", str(f)], check=True)
        hashes.append((c.scene_id, _dhash(Image.open(f))))
    dups = [(a_[0], b_[0]) for i, a_ in enumerate(hashes) for b_ in hashes[i + 1:]
            if bin(a_[1] ^ b_[1]).count("1") < 12]
    checks.append(QCCheck(id="duplicate_scenes", name="Repeated / duplicate scene pictures",
                          status="warn" if dups else "pass", details=f"near-identical pairs: {dups}"))

    # editorial: sources, fact classes ---------------------------------
    claims = {c.id: c for c in (dossier.claims if dossier else [])}
    unsourced, unknown, flagged = [], [], []
    for seg in script.segments:
        if seg.classification in ("FACT", "INTERPRETATION"):
            if not seg.claim_ids:
                unsourced.append(seg.scene_id)
            for cid in seg.claim_ids:
                if cid not in claims:
                    unknown.append(f"{seg.scene_id}:{cid}")
                elif claims[cid].needs_review:
                    flagged.append(f"{seg.scene_id}:{cid}")
    st = "fail" if unsourced or unknown else ("manual" if flagged else "pass")
    checks.append(QCCheck(id="sources", name="Every factual segment cites dossier claims", status=st,
                          details=f"unsourced {unsourced}; unknown {unknown}; needs_review {flagged}"))
    if flagged:
        review.append(f"Re-check claims marked needs_review before publishing: {flagged}")

    mismatch = []
    sb = {s.scene_id: s for s in storyboard.scenes}
    for seg in script.segments:
        scene = sb.get(seg.scene_id)
        if scene is None or (seg.classification == "SPECULATION") != (scene.classification == "SPECULATION"):
            mismatch.append(seg.scene_id)
    checks.append(QCCheck(id="speculation_labels", name="Alternate-history scenes carry the HYPOTHETICAL badge",
                          status="fail" if mismatch else "pass", details=f"mismatched scenes: {mismatch}"))

    # licenses / rights / disclosure --------------------------------------
    lic = (extra or {}).get("licenses", [])
    unclear = [x for x in lic if x.get("commercial_use") not in ("yes", True)]
    checks.append(QCCheck(id="licenses", name="Commercial-use licenses of every input",
                          status="manual" if unclear else "pass",
                          details=f"{len(lic)} inputs; unclear: {[x['item'] for x in unclear]}", data={"inputs": lic}))
    if unclear:
        review.append("Resolve unclear licenses: " + "; ".join(f"{x['item']} ({x.get('note', '')[:80]})" for x in unclear))
    checks.append(QCCheck(id="ai_disclosure", name="Synthetic / altered content disclosure", status="manual",
                          details="Synthetic narration voice and computer-generated reconstructions are used. "
                                  "Decide the YouTube 'altered or synthetic content' setting and say in the "
                                  "description that reconstructions are approximate and the scenario is fictional."))
    review.append("Decide YouTube synthetic-content disclosure (TTS narration, CG reconstructions)")
    review.append("Watch and listen to the full video once (automatic QC is not human viewing)")

    technical_pass = all(c.status != "fail" for c in checks if c.id in TECHNICAL) and \
        all(c.status != "fail" for c in checks if c.id in ("sources", "speculation_labels"))
    return QCReport(project_id=project_id, output=str(final_mp4), created_at=datetime.now(timezone.utc).isoformat(),
                    checks=checks, technical_pass=technical_pass, human_review_required=review)


def _read_srt(path: Path) -> list[dict]:
    blocks = path.read_text("utf-8").strip().split("\n\n")
    out = []

    def t(s):
        h, m, rest = s.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
    for b in blocks:
        lines = b.splitlines()
        if len(lines) < 3:
            continue
        s, e = lines[1].split(" --> ")
        out.append({"i": int(lines[0]), "start": t(s), "end": t(e), "text": "\n".join(lines[2:])})
    return out


def cleanup_inspection_frames(video_dir: Path, report_path: Path) -> dict:
    """ultradedit standing rule: remove disposable qc_tmp frames automatically after a passing QC."""
    sys.path.insert(0, str(config.RESEARCH))
    from qc_cleanup import cleanup_after_qc  # type: ignore
    return cleanup_after_qc(video_dir, report_path, "technical_pass")
