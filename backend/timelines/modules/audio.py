"""Voice & Audio Engine.

* TTS providers behind one interface (edge = Microsoft neural voices via edge-tts, default;
  elevenlabs / openai adapters need API keys). Generator audio is used as-is: no time-stretching
  (ultradedit lesson: stretched TTS sounds wrong); pacing comes from the text and the voice rate.
* Subtitle timing comes from the provider's word boundaries (exact), split into readable cues.
* Whisper (faster-whisper, CPU) re-transcribes each take for QC: missing / misread words are reported.
* Final mix: narration placed on the timeline, optional music bed with sidechain ducking,
  loudness normalised to -14 LUFS integrated / -1.5 dBTP.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config

SR = 48000


@dataclass
class Word:
    text: str
    start: float
    end: float


# ------------------------------------------------------------------ providers
class EdgeTTS:
    id = "edge"
    license_note = ("Microsoft Edge online neural voices via edge-tts: commercial-use terms for the free "
                    "service are not confirmed. For publication use Azure Speech, ElevenLabs or a licensed "
                    "human voice; QA flags this.")

    def synth(self, text: str, voice: str, out_mp3: Path, rate: str = "+0%") -> list[Word]:
        import edge_tts

        async def go():
            comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            words, audio = [], bytearray()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    s = chunk["offset"] / 1e7
                    words.append(Word(chunk["text"], s, s + chunk["duration"] / 1e7))
            out_mp3.write_bytes(bytes(audio))
            return words
        for attempt in range(3):
            try:
                return asyncio.run(go())
            except Exception:  # noqa: BLE001 - transient websocket errors
                if attempt == 2:
                    raise
        return []


class ElevenLabsTTS:
    id = "elevenlabs"
    license_note = ("ElevenLabs: commercial use requires a paid plan (the free plan is non-commercial and needs "
                    "attribution); record the plan used for this project.")
    API = "https://api.elevenlabs.io/v1"

    @staticmethod
    def _key() -> str:
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set (.env)")
        return key

    def voices(self) -> list[dict]:
        import httpx
        r = httpx.get(f"{self.API}/voices", headers={"xi-api-key": self._key()}, timeout=60)
        r.raise_for_status()
        return [{"voice_id": v["voice_id"], "name": v.get("name"), "category": v.get("category"),
                 "labels": v.get("labels") or {}, "preview_url": v.get("preview_url")}
                for v in r.json().get("voices", [])]

    def synth(self, text: str, voice: str, out_mp3: Path, rate: str = "+0%") -> list[Word]:
        """voice = ElevenLabs voice_id. `rate` is ignored: pacing comes from the voice and the text
        (no time-stretching). Model and voice settings come from settings['elevenlabs']."""
        import base64
        import httpx
        from .. import db
        cfg = db.get_setting("elevenlabs") or {}
        body = {"text": text, "model_id": cfg.get("model_id", "eleven_multilingual_v2")}
        if cfg.get("voice_settings"):
            body["voice_settings"] = cfg["voice_settings"]
        r = httpx.post(f"{self.API}/text-to-speech/{voice}/with-timestamps",
                       params={"output_format": "mp3_44100_192"},
                       headers={"xi-api-key": self._key()}, timeout=300, json=body)
        r.raise_for_status()
        data = r.json()
        out_mp3.write_bytes(base64.b64decode(data["audio_base64"]))
        al = data.get("alignment") or {}
        chars, starts, ends = al.get("characters", []), al.get("character_start_times_seconds", []), \
            al.get("character_end_times_seconds", [])
        words, cur, cs = [], "", None
        for ch, s, e in zip(chars, starts, ends):
            if ch.isspace():
                if cur:
                    words.append(Word(cur, cs, prev_e))
                cur, cs = "", None
                continue
            cur += ch
            cs = s if cs is None else cs
            prev_e = e
        if cur:
            words.append(Word(cur, cs, prev_e))
        return words


class ImportedTTS:
    """Narration generated elsewhere (e.g. the ElevenLabs web app): the user drops
    edit/audio/<lang>/import/narr_<scene_id>.(mp3|wav) and word timings come from Whisper."""
    id = "import"
    license_note = "Imported narration generated in the ElevenLabs web app on the user's paid plan (commercial use)."

    def synth(self, text: str, voice: str, out_mp3: Path, rate: str = "+0%") -> list[Word]:
        src_dir = out_mp3.parent / "import"
        name = out_mp3.stem
        src = next((p for ext in (".wav", ".mp3", ".m4a", ".flac") if (p := src_dir / f"{name}{ext}").exists()), None)
        if src is None:
            raise FileNotFoundError(f"put the take for this segment at {src_dir / (name + '.mp3')}")
        subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-c:a", "libmp3lame",
                        "-b:a", "192k", str(out_mp3)], check=True)
        return whisper_words(out_mp3)


def whisper_words(path: Path, language: str = "en") -> list[Word]:
    global _whisper
    from faster_whisper import WhisperModel
    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _whisper.transcribe(str(path), language=language, word_timestamps=True, vad_filter=False)
    return [Word(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or []) if w.word.strip()]


PROVIDERS = {"edge": EdgeTTS(), "elevenlabs": ElevenLabsTTS(), "import": ImportedTTS()}


# ------------------------------------------------------------------ helpers
def ffprobe_duration(path: Path) -> float:
    out = subprocess.run([config.ffprobe_exe(), "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def to_wav(src: Path, dst: Path) -> None:
    subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "1",
                    "-c:a", "pcm_s16le", str(dst)], check=True)


def synth_segment(text: str, voice: str, out_dir: Path, name: str, provider: str = "edge",
                  rate: str = "+0%") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3, wav = out_dir / f"{name}.mp3", out_dir / f"{name}.wav"
    words = PROVIDERS[provider].synth(text, voice, mp3, rate)
    to_wav(mp3, wav)
    mp3.unlink(missing_ok=True)
    dur = ffprobe_duration(wav)
    rec = {"file": str(wav), "duration_s": round(dur, 3), "text": text, "voice": voice, "provider": provider,
           "words": [w.__dict__ for w in words], "license_note": PROVIDERS[provider].license_note}
    (out_dir / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), "utf-8")
    return rec


# ------------------------------------------------------------------ subtitles
def cues_from_words(words: list[dict], offset: float, max_chars: int = 42, max_lines: int = 2,
                    max_dur: float = 6.0) -> list[dict]:
    """Group words into subtitle cues; break at sentence punctuation first, then by length."""
    cues, cur = [], []

    def flush():
        if cur:
            text = " ".join(w["text"] for w in cur)
            cues.append({"start": offset + cur[0]["start"], "end": offset + cur[-1]["end"], "text": text})
            cur.clear()
    for w in words:
        trial = " ".join(x["text"] for x in cur + [w])
        if cur and (len(trial) > max_chars * max_lines or w["end"] - cur[0]["start"] > max_dur):
            flush()
        cur.append(w)
        if re.search(r"[.!?;:]$", w["text"]) or (re.search(r",$", w["text"]) and len(trial) > max_chars):
            flush()
    flush()
    for c in cues:                                           # wrap to two balanced lines
        if len(c["text"]) > max_chars:
            parts = c["text"].split(" ")
            best = min(range(1, len(parts)), key=lambda i: abs(len(" ".join(parts[:i])) - len(" ".join(parts[i:]))))
            c["text"] = " ".join(parts[:best]) + "\n" + " ".join(parts[best:])
    for a, b in zip(cues, cues[1:]):                         # hold to next cue if the gap is short
        if b["start"] - a["end"] < 0.6:
            a["end"] = b["start"] - 0.04
        else:
            a["end"] += 0.35
    if cues:
        cues[-1]["end"] += 0.35
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[dict], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(c['start'])} --> {_srt_time(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines), "utf-8")


# ------------------------------------------------------------------ ASR verification
_whisper = None


def transcribe_check(wav: Path, expected: str, language: str = "en") -> dict:
    """Transcribe one take alone (no prompt with the expected text) and compare word sequences."""
    global _whisper
    from faster_whisper import WhisperModel
    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _whisper.transcribe(str(wav), language=language, beam_size=5, vad_filter=False)
    heard = " ".join(s.text.strip() for s in segs)

    def norm(s: str) -> list[str]:
        return re.findall(r"[a-z0-9']+", s.lower())
    a, b = norm(expected), norm(heard)
    sm = difflib.SequenceMatcher(a=a, b=b)
    missing = [" ".join(a[i1:i2]) for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace")]
    return {"heard": heard, "word_match": round(sm.ratio(), 3), "differences": missing[:20]}


# ------------------------------------------------------------------ mix
def mix(narration: list[dict], duration_s: float, out_wav: Path, music: Path | None = None,
        music_gain_db: float = -20.0) -> dict:
    """narration: [{file, start_s}] -> loudness-normalised stereo WAV of exactly duration_s."""
    inputs, filters, labels = [], [], []
    for i, n in enumerate(narration):
        inputs += ["-i", n["file"]]
        ms = int(round(n["start_s"] * 1000))
        filters.append(f"[{i}:a]aresample={SR},adelay={ms}|{ms},apad[n{i}]")
        labels.append(f"[n{i}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                   f"atrim=0:{duration_s:.3f}[voice]")
    out_label = "[voice]"
    if music:
        k = len(narration)
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(f"[{k}:a]aresample={SR},volume={music_gain_db}dB,atrim=0:{duration_s:.3f}[mus]")
        filters.append("[voice]asplit=2[v1][v2]")
        filters.append("[mus][v2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
        filters.append("[v1][duck]amix=inputs=2:normalize=0[mixed]")
        out_label = "[mixed]"
    filters.append(f"{out_label}aformat=channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11,"
                   f"aresample={SR},atrim=0:{duration_s:.3f},apad=whole_dur={duration_s:.3f}[out]")
    cmd = [config.ffmpeg_exe(), "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[out]", "-c:a", "pcm_s24le", str(out_wav)]
    subprocess.run(cmd, check=True)
    return {"file": str(out_wav), "duration_s": ffprobe_duration(out_wav)}


def loudness(path: Path) -> dict:
    out = subprocess.run([config.ffmpeg_exe(), "-hide_banner", "-i", str(path), "-af",
                          "loudnorm=I=-14:TP=-1.5:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    blob = out.stderr[out.stderr.rfind("{"):out.stderr.rfind("}") + 1]
    data = json.loads(blob)
    return {"integrated_lufs": float(data["input_i"]), "true_peak_db": float(data["input_tp"])}
