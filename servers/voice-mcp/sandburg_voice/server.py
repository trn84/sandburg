"""MCP server for speech synthesis (text-to-speech) and speech recognition (speech-to-text).

Tools:
  speak          Convert text to speech (Chatterbox Multilingual, 23 languages)
  clone_voice    Store a reference recording as a named voice
  list_voices    List the stored voices
  transcribe     Convert audio/video to text and optionally subtitles (SRT) (Whisper)
  unload_models  Remove the models from GPU memory immediately

The models are only loaded on the first call and unloaded again after VOICE_IDLE_MINUTES
without a call, so ComfyUI and Blender can use the GPU memory.
Relative paths are resolved against SANDBURG_PROJECTS (default: /workspace/projects).
"""

from __future__ import annotations

import gc
import json
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
VOICES_DIR = AUDIO_DIR / "voices"
IDLE_SECONDS = float(os.environ.get("VOICE_IDLE_MINUTES", "10")) * 60
WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "openai/whisper-large-v3-turbo")
MAX_CHUNK_CHARS = int(os.environ.get("VOICE_MAX_CHUNK_CHARS", "280"))
PAUSE_SECONDS = 0.25

# Languages supported by Chatterbox Multilingual
LANGUAGES = {
    "ar": "Arabic", "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "ms": "Malay",
    "nl": "Dutch", "no": "Norwegian", "pl": "Polish", "pt": "Portuguese",
    "ru": "Russian", "sv": "Swedish", "sw": "Swahili", "tr": "Turkish", "zh": "Chinese",
}
VOICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

server = MCPServer(
    name="sandburg-voice",
    instructions=(
        "Speech synthesis and speech recognition on the Sandburg's GPU. Results end up under "
        "/workspace/projects/audio and can be fetched via the file server. The first call "
        "loads the models (the very first time including the download) and therefore takes longer. "
        "Only clone voices with the consent of the person."
    ),
)


class _Models:
    """Holds the models, loads them on demand and unloads them when idle."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.tts: Any = None
        self.asr: Any = None
        self.last_used = time.monotonic()
        threading.Thread(target=self._idle_watch, daemon=True).start()

    @staticmethod
    def device() -> str:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def get_tts(self) -> Any:
        with self.lock:
            if self.tts is None:
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS

                self.tts = ChatterboxMultilingualTTS.from_pretrained(device=self.device())
            self.touch()
            return self.tts

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


def _duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return round(float(json.loads(proc.stdout)["format"]["duration"]), 2)
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text at sentence boundaries into chunks the model speaks reliably."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…;:])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # Split overlong sentences further at commas, or at spaces if necessary
        parts = [sentence]
        if len(sentence) > max_chars:
            parts = re.split(r"(?<=,)\s+", sentence)
        for part in parts:
            while len(part) > max_chars:
                cut = part.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(part[:cut].strip())
                part = part[cut:].strip()
            if current and len(current) + 1 + len(part) > max_chars:
                chunks.append(current)
                current = part
            else:
                current = f"{current} {part}".strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _voice_path(voice: str | None) -> Path | None:
    if not voice:
        return None
    if VOICE_NAME.match(voice) and (VOICES_DIR / f"{voice}.wav").is_file():
        return VOICES_DIR / f"{voice}.wav"
    p = _resolve(voice)
    if p.is_file():
        return p
    raise ValueError(f"voice '{voice}' not found. list_voices returns the available voices.")


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
    language: str = "en",
    voice: str | None = None,
    filename: str | None = None,
    format: Literal["wav", "mp3"] = "wav",
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
) -> dict:
    """Convert text to spoken language and save it as an audio file.

    Long texts are split at sentence boundaries and joined with short pauses.

    Args:
        text: The text to speak.
        language: Language code, e.g. "en", "de", "fr" (23 languages, see the error message for an invalid code).
        voice: Name of a voice created with clone_voice, or path to a reference WAV.
               If omitted, the model's default voice is used.
        filename: Destination file; a bare name ends up in /workspace/projects/audio/.
        format: "wav" or "mp3".
        exaggeration: Expressiveness, 0.25 (calm) to 1.0 (very emphatic).
        cfg_weight: Adherence to the reference voice/pace, 0.3 (looser, faster) to 0.7.
    """
    language = language.lower().strip()
    if language not in LANGUAGES:
        raise ValueError(f"language '{language}' is not supported. Supported: {', '.join(sorted(LANGUAGES))}")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("no text given")
    prompt = _voice_path(voice)
    out = _output_path(filename, format)

    import torch
    import torchaudio

    model = MODELS.get_tts()
    with MODELS.lock:
        pieces = []
        silence = torch.zeros(1, int(model.sr * PAUSE_SECONDS))
        for i, chunk in enumerate(chunks):
            kwargs: dict[str, Any] = {
                "language_id": language,
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
            }
            if prompt is not None:
                kwargs["audio_prompt_path"] = str(prompt)
            wav = model.generate(chunk, **kwargs).detach().cpu()
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            pieces.append(wav)
            if i < len(chunks) - 1:
                pieces.append(silence)
        audio = torch.cat(pieces, dim=1)
        MODELS.touch()

    wav_path = out if format == "wav" else out.with_suffix(".tmp.wav")
    torchaudio.save(str(wav_path), audio, model.sr)
    if format == "mp3":
        _ffmpeg("-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "2", str(out))
        wav_path.unlink(missing_ok=True)
    return {
        "output": str(out),
        "duration_s": round(audio.shape[1] / model.sr, 2),
        "language": language,
        "voice": voice or "default",
        "chunks": len(chunks),
    }


@server.tool()
def clone_voice(reference: str, name: str) -> dict:
    """Store a reference recording as a named voice for speak().

    Ideally 10–20 seconds of cleanly spoken speech without music or reverb. At least
    5 seconds; longer recordings are trimmed to 30 seconds. Audio and video
    (e.g. MP3, M4A, MP4) are accepted. Only use with the consent of the person.

    Args:
        reference: Path to the recording, e.g. after uploading it via the file server.
        name: Name of the voice (letters, digits, - and _), e.g. "narrator".
    """
    if not VOICE_NAME.match(name):
        raise ValueError("invalid name: only letters, digits, - and _ (max. 64 characters)")
    src = _existing(reference)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    dst = VOICES_DIR / f"{name}.wav"
    # Mono, 24 kHz, max. 30 s – what the model expects as a reference
    _ffmpeg("-i", str(src), "-t", "30", "-ac", "1", "-ar", "24000", str(dst))
    duration = _duration(dst)
    if 0 < duration < 5:
        dst.unlink(missing_ok=True)
        raise ValueError(f"the recording is only {duration} s long; at least 5 seconds are required.")
    return {"voice": name, "path": str(dst), "duration_s": duration}


@server.tool()
def list_voices() -> dict:
    """List the stored voices and supported languages."""
    voices = []
    if VOICES_DIR.is_dir():
        for f in sorted(VOICES_DIR.glob("*.wav")):
            voices.append({"name": f.stem, "path": str(f), "duration_s": _duration(f)})
    return {"voices": voices, "languages": LANGUAGES}


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
