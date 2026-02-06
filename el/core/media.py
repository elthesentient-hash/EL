"""EL Media Handler - YouTube downloads, URL fetching, media processing."""

import asyncio
import json
import logging
import os
import re
import tempfile

from el.config.settings import EL_COOKIES_FILE

logger = logging.getLogger("el.media")

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]+'
)

URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# Browser-like user agent to avoid bot detection
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# yt-dlp base args that help bypass bot detection
YTDLP_BASE = [
    "yt-dlp",
    "--user-agent", USER_AGENT,
    "--referer", "https://www.youtube.com/",
    "--no-warnings",
    "--no-check-certificates",
]

# Player client strategies - these use different YouTube API endpoints
# that are less likely to trigger bot detection on cloud servers
PLAYER_CLIENTS = [
    "android_creator",
    "mediaconnect",
    "android",
    "ios",
]


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'youtube\.com/watch\?v=([\w\-]+)',
        r'youtu\.be/([\w\-]+)',
        r'youtube\.com/shorts/([\w\-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def contains_youtube_url(text: str) -> str | None:
    """Extract a YouTube URL from text, or return None."""
    match = YOUTUBE_REGEX.search(text)
    return match.group(0) if match else None


def contains_url(text: str) -> str | None:
    """Extract any URL from text, or return None."""
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


def _get_cookies_args() -> list[str]:
    """Return yt-dlp cookie arguments if cookies.txt exists."""
    if EL_COOKIES_FILE.exists():
        return ["--cookies", str(EL_COOKIES_FILE)]
    return []


def _get_client_args() -> list[str]:
    """Return extractor args for alternative player clients."""
    clients = ",".join(PLAYER_CLIENTS)
    return ["--extractor-args", f"youtube:player_client={clients}"]


async def download_youtube_video(url: str, output_dir: str) -> dict:
    """Download a YouTube video using yt-dlp with multiple fallback strategies."""
    result = {
        "video_path": None,
        "title": "",
        "description": "",
        "duration": 0,
        "transcript": None,
    }

    # Try to get video info
    info = await _get_video_info(url)
    if info:
        result["title"] = info.get("title", "")
        result["description"] = info.get("description", "")[:500]
        result["duration"] = info.get("duration", 0)

    # Try transcript via multiple methods
    transcript = await _get_transcript(url, output_dir)
    if not transcript:
        transcript = await _get_transcript_api(url)
    if transcript:
        result["transcript"] = transcript

    # Try to download the actual video
    video_path = await _download_video(url, output_dir)
    if video_path:
        result["video_path"] = video_path

    return result


async def _get_video_info(url: str) -> dict | None:
    """Get video metadata without downloading."""
    cookies = _get_cookies_args()
    client_args = _get_client_args()

    # Strategy 1: yt-dlp with alternative player clients + cookies
    try:
        cmd = YTDLP_BASE + ["--dump-json", "--no-download"] + client_args + cookies + [url]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode())
        else:
            logger.warning(f"yt-dlp info failed: {stderr.decode()[:200]}")
    except Exception as e:
        logger.warning(f"yt-dlp info exception: {e}")

    # Strategy 2: noembed API (always works, limited info)
    video_id = _extract_video_id(url)
    if video_id:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-A", USER_AGENT,
                f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0 and stdout:
                data = json.loads(stdout.decode())
                if "title" in data:
                    return {"title": data.get("title", ""), "description": "", "duration": 0}
        except Exception:
            pass

    return None


async def _get_transcript(url: str, output_dir: str) -> str | None:
    """Try to get video transcript via yt-dlp subtitles."""
    sub_path = os.path.join(output_dir, "subs")
    cookies = _get_cookies_args()
    client_args = _get_client_args()

    try:
        cmd = YTDLP_BASE + [
            "--skip-download",
            "--write-auto-sub", "--write-sub",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--convert-subs", "srt",
            "-o", sub_path,
        ] + client_args + cookies + [url]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)

        for ext in [".en.srt", ".srt", ".en.vtt", ".vtt"]:
            srt_file = sub_path + ext
            if os.path.exists(srt_file):
                with open(srt_file) as f:
                    raw = f.read()
                lines = []
                for line in raw.split("\n"):
                    line = line.strip()
                    if not line or line.isdigit() or "-->" in line:
                        continue
                    if line not in lines[-1:]:
                        lines.append(line)
                return " ".join(lines)[:5000]
    except Exception as e:
        logger.warning(f"yt-dlp transcript failed: {e}")

    return None


async def _get_transcript_api(url: str) -> str | None:
    """Fallback: try youtube-transcript-api Python package."""
    video_id = _extract_video_id(url)
    if not video_id:
        return None

    try:
        loop = asyncio.get_event_loop()

        def _fetch():
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
                text = " ".join([entry["text"] for entry in transcript_list])
                return text[:5000]
            except Exception:
                return None

        result = await loop.run_in_executor(None, _fetch)
        if result:
            logger.info("Got transcript via youtube-transcript-api")
            return result
    except Exception as e:
        logger.warning(f"youtube-transcript-api failed: {e}")

    return None


async def _download_video(url: str, output_dir: str) -> str | None:
    """Download video file using alternative player clients to bypass bot detection."""
    output_path = os.path.join(output_dir, "video.mp4")
    cookies = _get_cookies_args()
    client_args = _get_client_args()

    strategies = [
        # Strategy 1: Alt player clients + best quality under 50MB
        YTDLP_BASE + ["-f", "best[filesize<50M]/worst", "-o", output_path]
        + client_args + cookies + [url],

        # Strategy 2: Alt player clients + worst quality (smallest file)
        YTDLP_BASE + ["-f", "worstvideo+worstaudio/worst", "-o", output_path]
        + client_args + cookies + [url],

        # Strategy 3: Individual player clients one at a time
        YTDLP_BASE + ["-f", "best[filesize<50M]/worst", "-o", output_path,
                       "--extractor-args", "youtube:player_client=android_creator"]
        + cookies + [url],

        YTDLP_BASE + ["-f", "best[filesize<50M]/worst", "-o", output_path,
                       "--extractor-args", "youtube:player_client=mediaconnect"]
        + cookies + [url],

        # Strategy 4: Audio only with alt clients
        YTDLP_BASE + ["-f", "worstaudio", "-o", output_path]
        + client_args + cookies + [url],
    ]

    for i, strategy in enumerate(strategies):
        try:
            # Remove old file if exists from a previous failed attempt
            if os.path.exists(output_path):
                os.unlink(output_path)

            proc = await asyncio.create_subprocess_exec(
                *strategy,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0 and os.path.exists(output_path):
                logger.info(f"Video downloaded with strategy {i+1}")
                return output_path

            err = stderr.decode()
            if "Sign in to confirm" in err or "bot" in err.lower():
                logger.warning(f"YouTube bot detection on strategy {i+1}")
                continue
            elif err.strip():
                logger.warning(f"Strategy {i+1} error: {err[:200]}")

        except asyncio.TimeoutError:
            logger.warning(f"Strategy {i+1} timed out")
            continue
        except Exception as e:
            logger.warning(f"Strategy {i+1} failed: {e}")
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
