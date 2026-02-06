"""EL Voice Engine - Whisper STT + Bark TTS for human-like voice."""

import asyncio
import io
import logging
import tempfile
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger("el.voice")


class VoiceEngine:
    """Handles speech-to-text and text-to-speech for EL."""

    def __init__(self, stt_model: str = "base", tts_engine: str = "bark",
                 bark_speaker: str = "v2/en_speaker_6", sample_rate: int = 24000):
        self.stt_model = stt_model
        self.tts_engine = tts_engine
        self.bark_speaker = bark_speaker
        self.sample_rate = sample_rate
        self._whisper_model = None
        self._bark_loaded = False
        self._piper_voice = None

    async def initialize(self):
        """Lazy-load models to save memory until first use."""
        logger.info("Voice engine ready (models load on first use)")

    def _load_whisper(self):
        if self._whisper_model is None:
            import whisper
            logger.info(f"Loading Whisper model: {self.stt_model}")
            self._whisper_model = whisper.load_model(self.stt_model)
        return self._whisper_model

    def _load_bark(self):
        if not self._bark_loaded:
            from bark import preload_models
            logger.info("Loading Bark TTS models...")
            preload_models()
            self._bark_loaded = True

    async def speech_to_text(self, audio_path: str) -> str:
        """Convert voice message to text using Whisper."""
        def _transcribe():
            model = self._load_whisper()
            result = model.transcribe(audio_path)
            return result["text"].strip()

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _transcribe)
        logger.info(f"STT result: {text[:100]}...")
        return text

    async def text_to_speech(self, text: str, output_path: Optional[str] = None) -> str:
        """Convert text to speech using Bark or Piper."""
        if self.tts_engine == "bark":
            return await self._bark_tts(text, output_path)
        elif self.tts_engine == "piper":
            return await self._piper_tts(text, output_path)
        else:
            raise ValueError(f"Unknown TTS engine: {self.tts_engine}")

    async def _bark_tts(self, text: str, output_path: Optional[str] = None) -> str:
        """Generate speech using Bark - the most human-like TTS."""
        def _generate():
            self._load_bark()
            from bark import generate_audio, SAMPLE_RATE
            import numpy as np

            # Bark handles long text poorly, so chunk it
            chunks = self._chunk_text(text, max_chars=200)
            all_audio = []

            for chunk in chunks:
                audio_array = generate_audio(
                    chunk,
                    history_prompt=self.bark_speaker,
                )
                all_audio.append(audio_array)

            # Concatenate all chunks
            full_audio = np.concatenate(all_audio)

            # Save to WAV
            out = output_path or tempfile.mktemp(suffix=".wav")
            with wave.open(out, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((full_audio * 32767).astype(np.int16).tobytes())

            return out

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _generate)
        logger.info(f"TTS generated: {result}")
        return result

    async def _piper_tts(self, text: str, output_path: Optional[str] = None) -> str:
        """Generate speech using Piper - lighter weight alternative."""
        out = output_path or tempfile.mktemp(suffix=".wav")

        proc = await asyncio.create_subprocess_exec(
            "piper",
            "--model", "en_US-lessac-medium",
            "--output_file", out,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await proc.communicate(input=text.encode())

        if proc.returncode != 0:
            raise RuntimeError("Piper TTS failed")

        return out

    def _chunk_text(self, text: str, max_chars: int = 200) -> list[str]:
        """Split text into chunks for Bark processing."""
        sentences = text.replace("!", "!|").replace("?", "?|").replace(".", ".|").split("|")
        chunks = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current) + len(sentence) < max_chars:
                current += " " + sentence if current else sentence
            else:
                if current:
                    chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)

        return chunks or [text]


async def convert_ogg_to_wav(ogg_path: str) -> str:
    """Convert Telegram OGG voice message to WAV for Whisper."""
    wav_path = ogg_path.replace(".ogg", ".wav")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", wav_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg conversion failed")
    return wav_path
