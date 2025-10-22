# src/audio_service.py

import hashlib
import logging
from io import BytesIO
from pathlib import Path

try:
    from gtts import gTTS

    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    logging.warning("gTTS not installed. Audio generation will be disabled. Install with: pip install gTTS")

logger = logging.getLogger(__name__)


class AudioService:
    """Service for generating audio from text using Text-to-Speech"""

    def __init__(self, cache_dir: str = "data/audio_cache"):
        """
        Initialize audio service

        Args:
            cache_dir: Directory to cache generated audio files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        if not GTTS_AVAILABLE:
            logger.warning("gTTS is not available. Audio generation will be disabled.")

    def _get_cache_path(self, text: str, language: str = "en") -> Path:
        """Generate cache file path based on text hash"""
        text_hash = hashlib.md5(f"{text}:{language}".encode()).hexdigest()
        return self.cache_dir / f"{text_hash}.mp3"

    async def generate_audio(
        self, text: str, language: str = "en", use_cache: bool = True, max_length: int = 5000
    ) -> BytesIO | None:
        """
        Generate audio from text using gTTS

        Args:
            text: Text to convert to speech
            language: Language code (en, ru, etc.)
            use_cache: Whether to use cached audio if available
            max_length: Maximum text length (default 5000 chars)

        Returns:
            BytesIO buffer with MP3 audio data, or None if generation failed
        """
        if not GTTS_AVAILABLE:
            logger.error("Cannot generate audio: gTTS not installed")
            return None

        if not text or not text.strip():
            logger.error("Cannot generate audio: empty text")
            return None

        # Валидация длины текста
        if len(text) > max_length:
            logger.warning(f"Text too long for TTS: {len(text)} chars (max {max_length}). Truncating...")
            text = text[:max_length]

        # Check cache first
        cache_path = self._get_cache_path(text, language)
        if use_cache and cache_path.exists():
            logger.info(f"Using cached audio for text hash: {cache_path.name}")
            try:
                with open(cache_path, "rb") as f:
                    audio_buffer = BytesIO(f.read())
                    audio_buffer.seek(0)
                    return audio_buffer
            except Exception as e:
                logger.error(f"Failed to read cached audio: {e}")
                # Continue to regeneration

        # Generate new audio with retry
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    f"Generating audio for text ({len(text)} chars) in language: {language} "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )

                # Create gTTS object
                tts = gTTS(text=text, lang=language, slow=False)

                # Save to buffer
                audio_buffer = BytesIO()
                tts.write_to_fp(audio_buffer)
                audio_buffer.seek(0)

                # Cache the audio file
                if use_cache:
                    try:
                        with open(cache_path, "wb") as f:
                            f.write(audio_buffer.getvalue())
                        logger.info(f"Cached audio at: {cache_path}")
                        audio_buffer.seek(0)  # Reset after writing
                    except Exception as e:
                        logger.error(f"Failed to cache audio: {e}")
                        # Не критично, продолжаем

                return audio_buffer

            except ConnectionError as e:
                logger.warning(f"Network error generating audio (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    # Exponential backoff
                    import asyncio

                    await asyncio.sleep(2**attempt)
                    continue
                else:
                    logger.error(f"Failed to generate audio after {max_retries + 1} attempts")
                    return None
            except Exception as e:
                logger.error(f"Unexpected error generating audio: {e}", exc_info=True)
                return None

        return None

    def clear_cache(self, older_than_days: int | None = None):
        """
        Clear audio cache

        Args:
            older_than_days: If specified, only delete files older than this many days
        """
        if not self.cache_dir.exists():
            return

        import time

        deleted_count = 0
        for file_path in self.cache_dir.glob("*.mp3"):
            if older_than_days is not None:
                # Check file age
                file_age_days = (time.time() - file_path.stat().st_mtime) / 86400
                if file_age_days < older_than_days:
                    continue

            try:
                file_path.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete cached audio {file_path}: {e}")

        logger.info(f"Cleared {deleted_count} cached audio files")

    def get_cache_size(self) -> tuple[int, int]:
        """
        Get cache statistics

        Returns:
            Tuple of (number of files, total size in bytes)
        """
        if not self.cache_dir.exists():
            return (0, 0)

        files = list(self.cache_dir.glob("*.mp3"))
        total_size = sum(f.stat().st_size for f in files)

        return (len(files), total_size)


# Global instance
audio_service = AudioService()
