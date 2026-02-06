"""EL Telegram Bot - Voice + text interface to EL."""

import asyncio
import logging
import tempfile
import os
from pathlib import Path
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from el.core.brain import Brain
from el.core.media import contains_youtube_url, download_youtube_video, extract_video_frames
from el.memory.store import Memory
from el.voice.engine import VoiceEngine, convert_ogg_to_wav
from el.agents.cowork import CoworkOrchestrator
from el.scheduler.proactive import ProactiveScheduler
from el.config.settings import ELConfig, EL_VOICE_CACHE

logger = logging.getLogger("el.telegram")


class ELBot:
    """Telegram bot interface for EL."""

    def __init__(self, config: ELConfig):
        self.config = config
        self.memory = Memory()
        self.brain = Brain(config, self.memory)
        self.voice = VoiceEngine(
            stt_model=config.voice.stt_model,
            tts_engine=config.voice.tts_engine,
            bark_speaker=config.voice.bark_speaker,
            sample_rate=config.voice.sample_rate,
        )
        self.cowork = CoworkOrchestrator(
            self.brain,
            max_concurrent=config.agents.max_concurrent_agents,
        )
        self.scheduler = ProactiveScheduler(
            self.brain,
            self.memory,
        )
        self.app: Application = None
        self._bot: Bot = None

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized to use EL."""
        allowed = self.config.telegram.allowed_user_ids
        return not allowed or user_id in allowed

    async def _send_notification(self, message: str):
        """Send a proactive notification to the first authorized user."""
        if self._bot and self.config.telegram.allowed_user_ids:
            user_id = self.config.telegram.allowed_user_ids[0]
            try:
                await self._bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Not authorized. Add your user ID to EL config.")
            return

        await update.message.reply_text(
            "Yo, EL here. I'm up and running.\n\n"
            "Just send me a message (text or voice) and I got you.\n\n"
            "Commands:\n"
            "/status - Check what's running\n"
            "/cowork <goal> - Spawn multiple agents on a task\n"
            "/schedule <time> <task> - Schedule a recurring task\n"
            "/voice on|off - Toggle voice responses\n"
            "/memory - See what I remember about you\n"
            "/forget - Clear conversation history"
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if not self._is_authorized(update.effective_user.id):
            return

        agent_status = self.cowork.get_status()
        job_count = len(self.scheduler.jobs)
        msg_count = len(self.memory.get_recent_messages(str(update.effective_user.id), 1000))

        await update.message.reply_text(
            f"EL Status:\n"
            f"- Memory: {msg_count} messages stored\n"
            f"- Scheduled jobs: {job_count}\n"
            f"- Agents: {agent_status}\n"
            f"- Voice: {'on' if self.config.voice.tts_engine else 'off'}"
        )

    async def cowork_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cowork command - spawn multi-agent task."""
        if not self._is_authorized(update.effective_user.id):
            return

        goal = " ".join(context.args) if context.args else None
        if not goal:
            await update.message.reply_text("Usage: /cowork <your goal here>")
            return

        user_id = str(update.effective_user.id)
        await update.message.reply_text(f"On it. Spinning up agents for: {goal}")

        result = await self.cowork.run_goal(goal, user_id)
        await update.message.reply_text(f"Done. Here's what the team got:\n\n{result[:4000]}")

    async def schedule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /schedule command - add a recurring task."""
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /schedule <interval> <task description>\n\n"
                "Intervals: hourly, daily, weekly, every_30m, every_2h, at_08:00\n\n"
                "Example: /schedule daily Check my GitHub notifications"
            )
            return

        interval = context.args[0]
        task_desc = " ".join(context.args[1:])

        job = self.scheduler.add_job(
            name=task_desc[:50],
            description=task_desc,
            cron_expr=interval,
        )

        await update.message.reply_text(
            f"Scheduled. I'll do this {interval}: {task_desc}"
        )

    async def voice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /voice command - toggle voice responses."""
        if not self._is_authorized(update.effective_user.id):
            return

        arg = context.args[0].lower() if context.args else "toggle"
        if arg == "on":
            self.config.telegram.voice_enabled = True
        elif arg == "off":
            self.config.telegram.voice_enabled = False
        else:
            self.config.telegram.voice_enabled = not self.config.telegram.voice_enabled

        status = "on" if self.config.telegram.voice_enabled else "off"
        await update.message.reply_text(f"Voice responses: {status}")

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /memory command - show what EL remembers."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)
        prefs = self.memory.get_all_preferences()
        ctx = self.memory.get_relevant_context(limit=5)
        msgs = self.memory.get_recent_messages(user_id, 5)

        parts = ["Here's what I remember:\n"]

        if prefs:
            parts.append("Preferences:")
            for k, v in prefs.items():
                parts.append(f"  - {k}: {v}")

        if ctx:
            parts.append("\nContext:")
            for c in ctx:
                parts.append(f"  - [{c['topic']}] {c['summary']}")

        if msgs:
            parts.append(f"\nLast {len(msgs)} messages in memory.")

        await update.message.reply_text("\n".join(parts))

    async def forget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /forget command - clear conversation history."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)
        self.memory.conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        self.memory.conn.commit()
        await update.message.reply_text("Done. Fresh start.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)
        message = update.message.text

        # Check for cowork trigger
        if message.lower().startswith("cowork:") or message.lower().startswith("team:"):
            goal = message.split(":", 1)[1].strip()
            await update.message.reply_text(f"Spinning up the team for: {goal}")
            result = await self.cowork.run_goal(goal, user_id)
            await update.message.reply_text(f"Team results:\n\n{result[:4000]}")
            return

        # Check for YouTube URL
        yt_url = contains_youtube_url(message)
        if yt_url:
            await self._handle_youtube(update, user_id, yt_url, message)
            return

        # Regular conversation
        response = await self.brain.think(user_id, message)

        # Send text response
        await update.message.reply_text(response[:4096])

    async def _handle_youtube(self, update: Update, user_id: str, url: str, original_message: str):
        """Handle a YouTube URL - download, extract frames, analyze."""
        await update.message.reply_text(f"Got the YouTube link. Downloading and analyzing...")

        work_dir = tempfile.mkdtemp(prefix="el_yt_", dir="/tmp")

        try:
            # Download video info, transcript, and video file
            yt_data = await download_youtube_video(url, work_dir)

            # Build context for Claude
            context_parts = []
            if yt_data["title"]:
                context_parts.append(f"Video title: {yt_data['title']}")
            if yt_data["description"]:
                context_parts.append(f"Description: {yt_data['description']}")
            if yt_data["duration"]:
                mins = yt_data["duration"] // 60
                secs = yt_data["duration"] % 60
                context_parts.append(f"Duration: {mins}m {secs}s")

            attachments = []

            # Extract frames if video was downloaded
            if yt_data["video_path"]:
                frame_dir = os.path.join(work_dir, "frames")
                os.makedirs(frame_dir, exist_ok=True)
                frames = await extract_video_frames(yt_data["video_path"], frame_dir)
                attachments.extend(frames)
                context_parts.append(f"({len(frames)} frames extracted from the video)")

            if yt_data["transcript"]:
                # Save transcript to a file so Claude can read it
                transcript_path = os.path.join(work_dir, "transcript.txt")
                with open(transcript_path, "w") as f:
                    f.write(yt_data["transcript"])
                attachments.append(transcript_path)
                context_parts.append("Transcript file attached.")

            # Remove the URL from the message to get the user's actual request
            user_request = original_message.replace(url, "").strip()
            if not user_request:
                user_request = "Analyze this YouTube video. Summarize what it's about, key points, and anything interesting."

            prompt = f"{user_request}\n\nYouTube video info:\n" + "\n".join(context_parts)

            if not attachments and not yt_data["transcript"]:
                # Nothing could be downloaded - let Claude try via web
                prompt = f"{user_request}\n\nYouTube URL: {url}\n\nI couldn't download this video directly. Use WebFetch or WebSearch to find information about this video and analyze it."

            response = await self.brain.think(user_id, prompt, attachments=attachments if attachments else None)
            await update.message.reply_text(response[:4096])

        except Exception as e:
            logger.error(f"YouTube handling error: {e}")
            # Fallback: just let Claude handle the URL via web tools
            fallback_prompt = f"{original_message}\n\nNote: Direct video download failed. Use WebFetch or WebSearch to find info about this YouTube video and answer the user's request."
            response = await self.brain.think(user_id, fallback_prompt)
            await update.message.reply_text(response[:4096])
        finally:
            # Cleanup work directory
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming photos/images."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)

        # Get the highest resolution photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir="/tmp") as tmp:
            img_path = tmp.name
            await file.download_to_drive(img_path)

        try:
            caption = update.message.caption or "What's in this image? Describe and analyze it."
            response = await self.brain.think(user_id, caption, attachments=[img_path])
            await update.message.reply_text(response[:4096])
        except Exception as e:
            logger.error(f"Photo handling error: {e}")
            await update.message.reply_text(f"Couldn't process that image: {str(e)[:200]}")
        finally:
            os.unlink(img_path)

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming videos - extract frames and analyze."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)

        video = update.message.video or update.message.video_note
        if not video:
            return

        await update.message.reply_text("Got the video. Analyzing it now...")

        file = await context.bot.get_file(video.file_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir="/tmp") as tmp:
            video_path = tmp.name
            await file.download_to_drive(video_path)

        frame_dir = tempfile.mkdtemp(prefix="el_frames_", dir="/tmp")
        frame_paths = []

        try:
            # Extract frames: 1 frame every 3 seconds
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", video_path,
                "-vf", "fps=1/3", "-frames:v", "10",
                "-q:v", "2",
                os.path.join(frame_dir, "frame_%03d.jpg"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            # Collect extracted frames
            for f in sorted(os.listdir(frame_dir)):
                if f.endswith(".jpg"):
                    frame_paths.append(os.path.join(frame_dir, f))

            if not frame_paths:
                await update.message.reply_text("Couldn't extract frames from the video.")
                return

            caption = update.message.caption or "Analyze this video. Describe what's happening in each frame and give an overall summary."
            caption += f"\n\n({len(frame_paths)} frames extracted from the video, 1 every 3 seconds)"

            response = await self.brain.think(user_id, caption, attachments=frame_paths)
            await update.message.reply_text(response[:4096])

        except Exception as e:
            logger.error(f"Video handling error: {e}")
            await update.message.reply_text(f"Had trouble with that video: {str(e)[:200]}")
        finally:
            os.unlink(video_path)
            for fp in frame_paths:
                try:
                    os.unlink(fp)
                except OSError:
                    pass
            try:
                os.rmdir(frame_dir)
            except OSError:
                pass

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming documents (PDFs, files, images sent as documents)."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)
        doc = update.message.document

        # Determine file extension
        file_name = doc.file_name or "file"
        suffix = os.path.splitext(file_name)[1] or ".bin"

        file = await context.bot.get_file(doc.file_id)

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as tmp:
            doc_path = tmp.name
            await file.download_to_drive(doc_path)

        try:
            caption = update.message.caption or f"Analyze this file ({file_name}). Summarize its contents."
            response = await self.brain.think(user_id, caption, attachments=[doc_path])
            await update.message.reply_text(response[:4096])
        except Exception as e:
            logger.error(f"Document handling error: {e}")
            await update.message.reply_text(f"Couldn't process that file: {str(e)[:200]}")
        finally:
            os.unlink(doc_path)

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming voice messages."""
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)

        # Download voice message
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            ogg_path = tmp.name
            await file.download_to_drive(ogg_path)

        try:
            # Convert OGG to WAV
            wav_path = await convert_ogg_to_wav(ogg_path)

            # Speech to text
            text = await self.voice.speech_to_text(wav_path)

            if not text:
                await update.message.reply_text("Couldn't catch that. Say again?")
                return

            # Think
            response = await self.brain.think(user_id, text)

            # Generate voice response
            audio_path = await self.voice.text_to_speech(response)

            # Send both text and voice
            await update.message.reply_text(f"[You said: {text}]\n\n{response[:3500]}")

            with open(audio_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file)

            # Cleanup
            os.unlink(audio_path)

        except Exception as e:
            logger.error(f"Voice handling error: {e}")
            await update.message.reply_text(
                f"Had trouble with that voice message: {str(e)[:200]}"
            )
        finally:
            os.unlink(ogg_path)
            if "wav_path" in locals():
                os.unlink(wav_path)

    async def run(self):
        """Start the Telegram bot and scheduler."""
        token = self.config.telegram.bot_token
        if not token:
            raise ValueError(
                "No Telegram bot token configured. "
                "Set it in ~/.el/config.json or run: el setup"
            )

        # Build the application
        self.app = Application.builder().token(token).build()
        self._bot = self.app.bot

        # Wire up the scheduler notification callback
        self.scheduler.notify = self._send_notification

        # Register handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("cowork", self.cowork_command))
        self.app.add_handler(CommandHandler("schedule", self.schedule_command))
        self.app.add_handler(CommandHandler("voice", self.voice_command))
        self.app.add_handler(CommandHandler("memory", self.memory_command))
        self.app.add_handler(CommandHandler("forget", self.forget_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, self.handle_video))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

        # Initialize voice engine
        await self.voice.initialize()

        logger.info("EL is online. Telegram bot starting...")

        # Start scheduler in background
        scheduler_task = asyncio.create_task(self.scheduler.run())

        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        logger.info("EL is live. Waiting for messages...")

        try:
            # Keep running
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down EL...")
        finally:
            self.scheduler.stop()
            scheduler_task.cancel()
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            self.memory.close()
