"""Find when every script line is spoken in the narration.

1. Whisper (faster-whisper or openai-whisper, whichever is installed)
   transcribes the narration with word-level timestamps.
2. The transcript is aligned to the script word by word, so recognition
   mistakes do not matter: the script text is the truth, the audio only
   provides the clock.
3. Each line gets start/end times plus the times of its own words, which the
   renderer uses to move the pen while those words are spoken.

Without Whisper, timings can come from an SRT file or be estimated from the
narration length (useful for a first preview).
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .project import Project, ScriptLine, audio_duration
from .textnorm import normalize_token, tokenize

Progress = Callable[[str, float], None]


@dataclass
class Word:
    text: str
    start: float
    end: float


# ──────────────────────────────────────────────────────────────
# Transcription
# ──────────────────────────────────────────────────────────────
def whisper_backends() -> list[str]:
    found = []
    try:
        import faster_whisper  # noqa: F401
        found.append("faster-whisper")
    except Exception:
        pass
    try:
        import whisper  # noqa: F401
        if hasattr(whisper, "load_model"):
            found.append("openai-whisper")
    except Exception:
        pass
    return found


def _prompt_from_script(lines: list[ScriptLine]) -> str:
    # Whisper's prompt window is small; the opening words help it pick the
    # right spelling of names and the right language.
    text = " ".join(ln.text for ln in lines)
    return text[:600]


def transcribe(audio: Path, language: str | None, model_name: str, prompt: str = "",
               progress: Progress | None = None) -> list[Word]:
    backends = whisper_backends()
    if not backends:
        raise RuntimeError(
            "Whisper is not installed. Install it with `pip install faster-whisper` "
            "(or `pip install openai-whisper`), or import an SRT file instead."
        )
    lang = language if language in ("en", "fa") else None
    if model_name.endswith(".en") and lang not in (None, "en"):
        model_name = model_name[:-3]
    total = max(audio_duration(audio), 0.001)

    if backends[0] == "faster-whisper":
        from faster_whisper import WhisperModel

        if progress:
            progress(f"Loading Whisper model '{model_name}'", 0.02)
        model = WhisperModel(model_name, device="auto", compute_type="default")
        segments, _info = model.transcribe(
            str(audio), language=lang, word_timestamps=True,
            initial_prompt=prompt or None, vad_filter=False, beam_size=5,
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(w.word.strip(), float(w.start), float(w.end)))
            if progress:
                progress("Transcribing narration", min(0.98, seg.end / total))
        return words

    import whisper

    if progress:
        progress(f"Loading Whisper model '{model_name}'", 0.02)
    model = whisper.load_model(model_name)
    if progress:
        progress("Transcribing narration (openai-whisper reports no progress)", 0.1)
    result = model.transcribe(str(audio), language=lang, word_timestamps=True,
                              initial_prompt=prompt or None, verbose=None)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append(Word(w["word"].strip(), float(w["start"]), float(w["end"])))
    return words


# ──────────────────────────────────────────────────────────────
# SRT import
# ──────────────────────────────────────────────────────────────
_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        rows = [r for r in block.split("\n") if r.strip()]
        for i, row in enumerate(rows):
            m = _SRT_TIME.search(row)
            if m:
                g = m.groups()
                body = " ".join(rows[i + 1:]).strip()
                body = re.sub(r"<[^>]+>", "", body)
                cues.append((_ts(*g[:4]), _ts(*g[4:]), body))
                break
    return cues


def words_from_srt(text: str) -> list[Word]:
    """Spread each cue's time over its words (by length) to get pseudo word timings."""
    words: list[Word] = []
    for start, end, body in parse_srt(text):
        toks = tokenize(body)
        if not toks:
            continue
        weights = [len(t) + 1 for t in toks]
        total = sum(weights)
        t = start
        for tok, wgt in zip(toks, weights):
            dur = (end - start) * wgt / total
            words.append(Word(tok, t, t + dur))
            t += dur
    return words


# ──────────────────────────────────────────────────────────────
# Alignment
# ──────────────────────────────────────────────────────────────
def align_words(lines: list[ScriptLine], words: list[Word], duration: float) -> list[dict]:
    """Give every script word a time, using the transcript as the clock."""
    script: list[tuple[int, str, str]] = []  # (line index, display word, normalized)
    for li, ln in enumerate(lines):
        for w in tokenize(ln.text):
            script.append((li, w, normalize_token(w)))

    s_norm = [s[2] for s in script]
    t_norm = [normalize_token(w.text) for w in words]
    times: list[tuple[float, float] | None] = [None] * len(script)

    if words:
        sm = difflib.SequenceMatcher(None, s_norm, t_norm, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    tw = words[j1 + k]
                    times[i1 + k] = (tw.start, tw.end)
            elif tag == "replace":
                # Misheard or re-spelled words: spread the script words over
                # the time Whisper spent on its own version of them.
                span_s, span_e = words[j1].start, words[j2 - 1].end
                weights = [len(script[i][1]) + 1 for i in range(i1, i2)]
                total = sum(weights)
                t = span_s
                for i, wgt in zip(range(i1, i2), weights):
                    d = (span_e - span_s) * wgt / total
                    times[i] = (t, t + d)
                    t += d

    _fill_gaps(script, times, duration)
    return [
        {"line": script[i][0], "w": script[i][1], "s": round(times[i][0], 3), "e": round(times[i][1], 3)}
        for i in range(len(script))
    ]


def _fill_gaps(script, times, duration: float) -> None:
    """Interpolate words that were not heard (or when there is no transcript)."""
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else duration
        if right < left:
            right = left
        weights = [len(script[k][1]) + 1 for k in range(i, j)]
        total = sum(weights)
        t = left
        for k, wgt in zip(range(i, j), weights):
            d = (right - left) * wgt / total
            times[k] = (t, t + d)
            t += d
        i = j
    # Keep the word clock monotonic.
    last = 0.0
    for k in range(n):
        s, e = times[k]
        s = max(s, last)
        e = max(e, s)
        times[k] = (s, e)
        last = s


def build_timeline(lines: list[ScriptLine], word_times: list[dict], duration: float, source: str) -> dict:
    per_line: list[list[dict]] = [[] for _ in lines]
    for wt in word_times:
        per_line[wt["line"]].append({"w": wt["w"], "s": wt["s"], "e": wt["e"]})
    out_lines = []
    for ln, ws in zip(lines, per_line):
        start = ws[0]["s"] if ws else 0.0
        end = ws[-1]["e"] if ws else start
        out_lines.append({"id": ln.id, "text": ln.text, "start": start, "end": end, "words": ws})
    return {"version": 1, "source": source, "duration": round(duration, 3), "lines": out_lines}


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────
def align_project(project: Project, method: str = "whisper", srt_text: str | None = None,
                  progress: Progress | None = None, reuse_transcript: bool = True) -> dict:
    """Create timeline.json for a project.

    method: "whisper" (transcribe the narration), "srt" (use srt_text) or
    "estimate" (spread lines over the narration by length).
    """
    lines = project.lines()
    if not lines:
        raise ValueError("The script is empty.")
    narration = project.narration_path()
    if narration is None:
        raise ValueError("Upload the narration audio first.")
    duration = audio_duration(narration)

    if method == "whisper":
        words: list[Word]
        cached = project.transcript_path
        if reuse_transcript and cached.exists():
            data = json.loads(cached.read_text(encoding="utf-8"))
            words = [Word(**w) for w in data["words"]]
            if progress:
                progress("Using saved transcript", 0.9)
        else:
            words = transcribe(narration, project.language(), project.settings.get("whisper_model", "small"),
                               _prompt_from_script(lines), progress)
            cached.write_text(json.dumps({"words": [asdict(w) for w in words]}, ensure_ascii=False),
                              encoding="utf-8")
    elif method == "srt":
        if not srt_text:
            raise ValueError("No SRT text given.")
        words = words_from_srt(srt_text)
    elif method == "estimate":
        words = []  # align_words spreads the words evenly over the narration
    else:
        raise ValueError(f"Unknown alignment method: {method}")

    word_times = align_words(lines, words, duration)
    timeline = build_timeline(lines, word_times, duration, method)
    project.save_timeline(timeline)
    if progress:
        progress("Timeline ready", 1.0)
    return timeline
