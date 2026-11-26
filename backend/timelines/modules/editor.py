"""Video Editing Engine: scene clips + narration mix -> final MP4, SRT, WAV, timeline JSON, FCP7 XML.

Timing model: scene i owns [start_i, end_i) on the output timeline. Each scene clip is rendered with a
tail handle equal to the next scene's transition length, so an FFmpeg xfade at offset start_{i+1}
always has picture on both sides.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from .. import config
from ..schemas import Timeline


def _xfade_name(kind: str) -> str:
    return {"crossfade": "fade", "dip_black": "fadeblack"}.get(kind, "fade")


def compose(timeline: Timeline, mix_wav: Path, out_mp4: Path, *, crf: int = 18) -> dict:
    clips = timeline.clips
    inputs, filt = [], []
    for i, c in enumerate(clips):
        inputs += ["-i", c.file]
        # Convert every input to limited-range BT.709 (Blender JPEG frames arrive as full-range yuvj420p).
        filt.append(f"[{i}:v]fps={timeline.fps},scale={timeline.width}:{timeline.height}:flags=lanczos:"
                    f"in_range=auto:out_range=tv:out_color_matrix=bt709,"
                    f"setsar=1,format=yuv420p,setparams=range=tv:colorspace=bt709:color_primaries=bt709:"
                    f"color_trc=bt709,settb=AVTB[v{i}]")
    last = "v0"
    for i in range(1, len(clips)):
        tr = clips[i].transition_in
        out = f"x{i}"
        if tr.type == "cut" or tr.duration_s <= 0:
            # hard cut: trim the running stream at the boundary and concatenate
            filt.append(f"[{last}]trim=0:{clips[i].start_s:.4f},setpts=PTS-STARTPTS[t{i}]")
            filt.append(f"[t{i}][v{i}]concat=n=2:v=1:a=0[{out}]")
        else:
            filt.append(f"[{last}][v{i}]xfade=transition={_xfade_name(tr.type)}:duration={tr.duration_s:.3f}:"
                        f"offset={clips[i].start_s:.4f}[{out}]")
        last = out
    filt.append(f"[{last}]trim=0:{timeline.duration_s:.4f},setpts=PTS-STARTPTS[vout]")
    k = len(clips)
    cmd = [config.ffmpeg_exe(), "-y", "-loglevel", "error", *inputs, "-i", str(mix_wav),
           "-filter_complex", ";".join(filt), "-map", "[vout]", "-map", f"{k}:a",
           "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(timeline.fps),
           "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart",
           "-t", f"{timeline.duration_s:.4f}", str(out_mp4)]
    subprocess.run(cmd, check=True)
    return {"file": str(out_mp4), "bytes": out_mp4.stat().st_size}


# ------------------------------------------------------------------ Premiere interchange (FCP7 XML)
def _file_url(path: str) -> str:
    p = Path(path).resolve().as_posix()
    return "file://localhost/" + quote(p, safe="/:")


def write_fcp7_xml(timeline: Timeline, mix_wav: Path, narration: list[dict], out_xml: Path) -> dict:
    """xmeml v4 sequence: V1 = scene clips (cuts at scene starts; crossfades are NOT exported),
    A1/A2 = final mix (stereo exploded), A3 = narration takes. Imports in Premiere via File > Import."""
    fps = timeline.fps

    def fr(t: float) -> int:
        return int(round(t * fps))

    def rate() -> str:
        return f"<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>"

    def fileblock(fid: str, path: str, dur_s: float, video: bool, audio_ch: int = 0) -> str:
        media = ""
        if video:
            media += (f"<video><samplecharacteristics>{rate()}<width>{timeline.width}</width>"
                      f"<height>{timeline.height}</height></samplecharacteristics></video>")
        if audio_ch:
            media += (f"<audio><samplecharacteristics><depth>24</depth><samplerate>48000</samplerate>"
                      f"</samplecharacteristics><channelcount>{audio_ch}</channelcount></audio>")
        return (f'<file id="{fid}"><name>{escape(Path(path).name)}</name><pathurl>{_file_url(path)}</pathurl>'
                f"{rate()}<duration>{fr(dur_s)}</duration><media>{media}</media></file>")

    vitems = []
    for i, c in enumerate(timeline.clips):
        start = fr(c.start_s)
        end = fr(timeline.clips[i + 1].start_s) if i + 1 < len(timeline.clips) else fr(timeline.duration_s)
        vitems.append(f'<clipitem id="v{i}"><name>{escape(c.scene_id)}</name><duration>{fr(c.duration_s)}</duration>'
                      f"{rate()}<start>{start}</start><end>{end}</end><in>0</in><out>{end - start}</out>"
                      f"{fileblock(f'fv{i}', c.file, c.duration_s, True)}</clipitem>")
    total = fr(timeline.duration_s)
    mix_items = []
    for ch in (1, 2):
        fid = "fmix" if ch == 1 else None
        fblock = fileblock("fmix", str(mix_wav), timeline.duration_s, False, 2) if ch == 1 else '<file id="fmix"/>'
        mix_items.append(f'<track><clipitem id="mix{ch}"><name>{escape(mix_wav.name)}</name>'
                         f"<duration>{total}</duration>{rate()}<start>0</start><end>{total}</end><in>0</in>"
                         f"<out>{total}</out>{fblock}<sourcetrack><mediatype>audio</mediatype>"
                         f"<trackindex>{ch}</trackindex></sourcetrack></clipitem></track>")
        _ = fid
    nitems = []
    for i, n in enumerate(narration):
        s, d = fr(n["start_s"]), fr(n["duration_s"])
        nitems.append(f'<clipitem id="n{i}"><name>{escape(Path(n["file"]).name)}</name><duration>{d}</duration>'
                      f"{rate()}<start>{s}</start><end>{s + d}</end><in>0</in><out>{d}</out>"
                      f"{fileblock(f'fn{i}', n['file'], n['duration_s'], False, 1)}"
                      f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="seq1">'
           f"<name>{escape(timeline.title)}</name><duration>{total}</duration>{rate()}"
           f"<media><video><format><samplecharacteristics>{rate()}<width>{timeline.width}</width>"
           f"<height>{timeline.height}</height><pixelaspectratio>square</pixelaspectratio></samplecharacteristics>"
           f"</format><track>{''.join(vitems)}</track></video>"
           f"<audio>{''.join(mix_items)}<track>{''.join(nitems)}</track></audio></media></sequence></xmeml>")
    out_xml.write_text(xml, "utf-8")
    return {"file": str(out_xml), "video_clips": len(vitems), "narration_clips": len(nitems),
            "limitations": "cuts only (crossfades not exported); verify by importing in Premiere"}


def write_timeline_json(timeline: Timeline, path: Path) -> None:
    path.write_text(json.dumps(json.loads(timeline.model_dump_json()), ensure_ascii=False, indent=2), "utf-8")
