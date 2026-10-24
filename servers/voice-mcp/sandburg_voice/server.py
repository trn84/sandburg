"""MCP server for speech synthesis (text-to-speech) and speech recognition (speech-to-text).

Tools:
  speak          Convert text to speech (Kokoro-82M)
  list_voices    List the available voices and languages
  transcribe     Convert audio/video to text and optionally subtitles (SRT) (Whisper)
  unload_models  Remove the models from GPU memory immediately

The models are only loaded on the first call and unloaded again after VOICE_IDLE_MINUTES
without a call, so ComfyUI and Blender can use the GPU memory.
Relative paths are resolved against SANDBURG_PROJECTS (default: /workspace/projects).
"""

from __future__ import annotations

import gc
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

PROJECTS = Path(os.environ.get("SANDBURG_PROJECTS", "/workspace/projects"))
AUDIO_DIR = PROJECTS / "audio"
IDLE_SECONDS = float(os.environ.get("VOICE_IDLE_MINUTES", "10")) * 60
WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "openai/whisper-large-v3-turbo")
KOKORO_REPO = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000
PAUSE_SECONDS = 0.4  # between paragraphs

# Kokoro language codes; the first letter of a voice name is its language code
LANGUAGES = {
    "en": ("a", "English (US)"), "en-us": ("a", "English (US)"), "en-gb": ("b", "English (UK)"),
    "es": ("e", "Spanish"), "fr": ("f", "French"), "hi": ("h", "Hindi"), "it": ("i", "Italian"),
    "pt": ("p", "Portuguese (BR)"), "zh": ("z", "Chinese"),
}
DEFAULT_VOICES = {
    "a": "af_heart", "b": "bf_emma", "e": "ef_dora", "f": "ff_siwis", "h": "hf_alpha",
    "i": "if_sara", "p": "pf_dora", "z": "zf_xiaobei",
}
VOICE_NAME = re.compile(r"^[abefhipz][fm]_[a-z]+$")

server = MCPServer(
    name="sandburg-voice",
    instructions=(
        "Speech synthesis and speech recognition on the Sandburg's GPU. Results end up under "
        "/workspace/projects/audio and can be fetched via the file server. The first call "
        "loads the models (the very first time including the download) and therefore takes longer."
    ),
)


class _Models:
    """Holds the models, loads them on demand and unloads them when idle."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.tts: Any = None
        self.pipelines: dict[str, Any] = {}
        self.asr: Any = None
        self.last_used = time.monotonic()
        threading.Thread(target=self._idle_watch, daemon=True).start()

    @staticmethod
    def device() -> str:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def get_pipeline(self, lang_code: str) -> Any:
        """Kokoro pipeline for one language; all languages share one model."""
        with self.lock:
            from kokoro import KModel, KPipeline

            if self.tts is None:
                self.tts = KModel(repo_id=KOKORO_REPO).to(self.device()).eval()
            if lang_code not in self.pipelines:
                self.pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=KOKORO_REPO,
                                                      model=self.tts)
            self.touch()
            return self.pipelines[lang_code]

    def get_asr(self) -> Any:
        with self.lock:
            if self.asr is None:
                import torch
                from transformers import pipeline

                device = self.device()
                self.asr = pipeline(
                    "automatic-speech-recognition",
                    model=WHISPER_MODEL,
                    dtype=torch.float16 if device == "cuda" else torch.float32,
                    device=device,
                )
            self.touch()
            return self.asr

    def unload(self) -> list[str]:
        with self.lock:
            unloaded = [name for name in ("tts", "asr") if getattr(self, name) is not None]
            self.tts = None
            self.pipelines = {}
            self.asr = None
            if unloaded:
                gc.collect()
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass
            return unloaded

    def _idle_watch(self) -> None:
        while True:
            time.sleep(30)
            if IDLE_SECONDS > 0 and time.monotonic() - self.last_used > IDLE_SECONDS:
                self.unload()


MODELS = _Models()


# --- Helpers ------------------------------------------------------------------


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECTS / p


def _existing(path: str) -> Path:
    p = _resolve(path)
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    return p


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-2000:]}")


def resolve_voice(voice: str | None, language: str | None) -> tuple[str, str]:
    """Return (voice, Kokoro language code) from the given voice and/or language."""
    lang_code = None
    if language:
        language = language.lower().strip()
        if language not in LANGUAGES:
            raise ValueError(f"language '{language}' is not supported. Supported: {', '.join(LANGUAGES)}")
        lang_code = LANGUAGES[language][0]
    if not voice:
        lang_code = lang_code or "a"
        return DEFAULT_VOICES[lang_code], lang_code
    # Several voices can be mixed: "af_bella,af_sky"
    names = voice.split(",")
    for name in names:
        if not VOICE_NAME.match(name):
            raise ValueError(f"unknown voice '{name}'. list_voices returns the available voices.")
    if lang_code is None:
        lang_code = names[0][0]
    return voice, lang_code


def _paragraphs(text: str) -> list[str]:
    return [p for p in (re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)) if p]


def _output_path(filename: str | None, ext: str) -> Path:
    if filename:
        p = _resolve(filename)
        if p.suffix.lower() != f".{ext}":
            p = p.with_suffix(f".{ext}")
        if not Path(filename).is_absolute() and len(Path(filename).parts) == 1:
            p = AUDIO_DIR / p.name  # just a file name: put it in the audio folder
    else:
        p = AUDIO_DIR / f"speech-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _srt_time(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(chunks: list[dict]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, 1):
        start, end = chunk.get("timestamp") or (None, None)
        start = start or 0.0
        end = end if end is not None else start + 2.0
        lines += [str(i), f"{_srt_time(start)} --> {_srt_time(end)}", chunk.get("text", "").strip(), ""]
    return "\n".join(lines)


# --- Tools --------------------------------------------------------------------


@server.tool()
def speak(
    text: str,
    language: str | None = None,
    voice: str | None = None,
    filename: str | None = None,
    format: Literal["wav", "mp3"] = "wav",
    speed: float = 1.0,
) -> dict:
    """Convert text to spoken language and save it as an audio file.

    Texts of any length are fine (whole chapters); paragraphs separated by a blank
    line get a short pause.

    Args:
        text: The text to speak.
        language: Language code: en (= en-us), en-gb, es, fr, hi, it, pt, zh.
                  If omitted, it follows from the voice (default: en).
        voice: Kokoro voice, e.g. "af_heart" or "bm_george"; mixes such as "af_bella,af_sky"
               are possible. list_voices returns all voices. If omitted, the language's
               default voice is used.
        filename: Destination file; a bare name ends up in /workspace/projects/audio/.
        format: "wav" or "mp3".
        speed: Speaking rate, 0.5 (slow) to 2.0 (fast).
    """
    voice, lang_code = resolve_voice(voice, language)
    paragraphs = _paragraphs(text)
    if not paragraphs:
        raise ValueError("no text given")
    out = _output_path(filename, format)

    import numpy as np
    import soundfile

    pipeline = MODELS.get_pipeline(lang_code)
    with MODELS.lock:
        pieces = []
        silence = np.zeros(int(SAMPLE_RATE * PAUSE_SECONDS), dtype=np.float32)
        for i, paragraph in enumerate(paragraphs):
            for result in pipeline(paragraph, voice=voice, speed=speed, split_pattern=None):
                if result.audio is not None:
                    pieces.append(result.audio.detach().cpu().numpy())
            if i < len(paragraphs) - 1:
                pieces.append(silence)
            MODELS.touch()
    if not pieces:
        raise RuntimeError("Kokoro produced no audio for this text")
    audio = np.concatenate(pieces)

    wav_path = out if format == "wav" else out.with_suffix(".tmp.wav")
    soundfile.write(str(wav_path), audio, SAMPLE_RATE)
    if format == "mp3":
        _ffmpeg("-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "2", str(out))
        wav_path.unlink(missing_ok=True)
    return {
        "output": str(out),
        "duration_s": round(len(audio) / SAMPLE_RATE, 2),
        "language": next(k for k, (code, _) in LANGUAGES.items() if code == lang_code),
        "voice": voice,
    }


@server.tool()
def list_voices() -> dict:
    """List the available Kokoro voices (grouped by language) and the supported languages.

    The voice name says language and gender: "af_heart" = American English, female.
    """
    from huggingface_hub import list_repo_files, snapshot_download

    try:
        files = list_repo_files(KOKORO_REPO)
    except Exception:  # offline: fall back to what is in the cache
        cache = Path(snapshot_download(KOKORO_REPO, local_files_only=True))
        files = [str(p.relative_to(cache)) for p in cache.glob("voices/*.pt")]
    voices = sorted(Path(f).stem for f in files if f.startswith("voices/") and f.endswith(".pt"))
    by_language: dict[str, list[str]] = {}
    for language, (code, _) in LANGUAGES.items():
        if language == "en-us":
            continue  # same as "en"
        by_language[language] = [v for v in voices if VOICE_NAME.match(v) and v[0] == code]
    return {
        "voices": by_language,
        "defaults": {lang: DEFAULT_VOICES[code] for lang, (code, _) in LANGUAGES.items()},
        "languages": {lang: name for lang, (_, name) in LANGUAGES.items()},
    }


@server.tool()
def transcribe(
    audio: str,
    language: str | None = None,
    subtitles: bool = False,
    output_dir: str | None = None,
) -> dict:
    """Convert an audio or video file to text, optionally with subtitles (SRT).

    Args:
        audio: Path to the file (WAV, MP3, M4A, MP4, MKV …).
        language: Language code such as "en"; if omitted, Whisper detects the language itself.
        subtitles: Also write an .srt file with timestamps.
        output_dir: Folder for .txt/.srt; default is /workspace/projects/audio/transcripts.
    """
    src = _existing(audio)
    out_dir = _resolve(output_dir) if output_dir else AUDIO_DIR / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        _ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav))
        asr = MODELS.get_asr()
        generate_kwargs: dict[str, Any] = {"task": "transcribe"}
        if language:
            generate_kwargs["language"] = language
        with MODELS.lock:
            result = asr(str(wav), return_timestamps=True, chunk_length_s=30,
                         batch_size=8, generate_kwargs=generate_kwargs)
            MODELS.touch()

    text = (result.get("text") or "").strip()
    txt_path = out_dir / f"{src.stem}.txt"
    txt_path.write_text(text + "\n", encoding="utf-8")
    answer: dict[str, Any] = {"text": text[:20000], "text_file": str(txt_path)}
    if len(text) > 20000:
        answer["note"] = "text truncated; full text in text_file"
    if subtitles:
        srt_path = out_dir / f"{src.stem}.srt"
        srt_path.write_text(to_srt(result.get("chunks") or []), encoding="utf-8")
        answer["subtitle_file"] = str(srt_path)
    return answer


@server.tool()
def unload_models() -> dict:
    """Remove the speech models from (GPU) memory immediately."""
    return {"unloaded": MODELS.unload()}


def main() -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is missing")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
