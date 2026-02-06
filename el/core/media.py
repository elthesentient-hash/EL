"""EL Media Handler - YouTube downloads, URL fetching, media processing."""

import asyncio
import json
import logging
import os
import re
import tempfile

logger = logging.getLogger("el.media")

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]+'
)

URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')


def contains_youtube_url(text: str) -> str | None:
    """Extract a YouTube URL from text, or return None."""
    match = YOUTUBE_REGEX.search(text)
    return match.group(0) if match else None


def contains_url(text: str) -> str | None:
    """Extract any URL from text, or return None."""
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


async def download_youtube_video(url: str, output_dir: str) -> dict:
    """Download a YouTube video using yt-dlp with multiple fallback strategies.

    Returns dict with keys: video_path, title, description, duration, transcript
    """
    result = {
        "video_path": None,
        "title": "",
        "description": "",
        "duration": 0,
        "transcript": None,
    }

    # First, try to get video info
    info = await _get_video_info(url)
    if info:
        result["title"] = info.get("title", "")
        result["description"] = info.get("description", "")[:500]
        result["duration"] = info.get("duration", 0)

    # Try to get transcript/subtitles (works even when video download fails)
    transcript = await _get_transcript(url, output_dir)
    if transcript:
        result["transcript"] = transcript

    # Try to download the video with multiple strategies
    video_path = await _download_video(url, output_dir)
    if video_path:
        result["video_path"] = video_path

    return result


async def _get_video_info(url: str) -> dict | None:
    """Get video metadata without downloading."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--no-warnings",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode())
    except Exception as e:
        logger.warning(f"yt-dlp info failed: {e}")

    # Fallback: try with --cookies-from-browser
    for browser in ["chrome", "firefox", "chromium"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--no-warnings",
                "--cookies-from-browser", browser,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0 and stdout:
                return json.loads(stdout.decode())
        except Exception:
            continue

    return None


async def _get_transcript(url: str, output_dir: str) -> str | None:
    """Try to get video transcript/subtitles."""
    sub_path = os.path.join(output_dir, "subs")

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--convert-subs", "srt",
            "-o", sub_path,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)

        # Look for the subtitle file
        for ext in [".en.srt", ".srt", ".en.vtt", ".vtt"]:
            srt_file = sub_path + ext
            if os.path.exists(srt_file):
                with open(srt_file) as f:
                    raw = f.read()
                # Clean SRT formatting
                lines = []
                for line in raw.split("\n"):
                    line = line.strip()
                    if not line or line.isdigit() or "-->" in line:
                        continue
                    if line not in lines[-1:]:
                        lines.append(line)
                return " ".join(lines)[:3000]
    except Exception as e:
        logger.warning(f"Transcript extraction failed: {e}")

    return None


async def _download_video(url: str, output_dir: str) -> str | None:
    """Download video file with multiple fallback strategies."""
    output_path = os.path.join(output_dir, "video.mp4")

    # Strategy 1: Direct download, best quality under 50MB
    strategies = [
        [
            "yt-dlp",
            "-f", "best[filesize<50M]/worst",
            "-o", output_path,
            "--no-warnings",
            url,
        ],
        # Strategy 2: Audio only (smaller, still useful for analysis)
        [
            "yt-dlp",
            "-f", "worstaudio",
            "-o", output_path,
            "--no-warnings",
            url,
        ],
    ]

    for strategy in strategies:
        try:
            proc = await asyncio.create_subprocess_exec(
                *strategy,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0 and os.path.exists(output_path):
                return output_path

            # Check for bot detection
            err = stderr.decode()
            if "Sign in to confirm" in err or "bot" in err.lower():
                logger.warning("YouTube bot detection triggered, trying next strategy")
                continue

        except asyncio.TimeoutError:
            logger.warning("Video download timed out, trying next strategy")
            continue
        except Exception as e:
            logger.warning(f"Download strategy failed: {e}")
            continue

    return None


async def extract_video_frames(video_path: str, output_dir: str, interval: int = 3, max_frames: int = 10) -> list[str]:
    """Extract frames from a video using ffmpeg."""
    frame_paths = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{interval}", "-frames:v", str(max_frames),
            "-q:v", "2",
            os.path.join(output_dir, "frame_%03d.jpg"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)

        for f in sorted(os.listdir(output_dir)):
            if f.startswith("frame_") and f.endswith(".jpg"):
                frame_paths.append(os.path.join(output_dir, f))

    except Exception as e:
        logger.error(f"Frame extraction failed: {e}")

    return frame_paths
