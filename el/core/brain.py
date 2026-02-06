"""EL Brain - Interface to Claude Code CLI."""

import asyncio
import shutil
import json
import logging
from typing import Optional
from el.config.settings import ELConfig
from el.memory.store import Memory

logger = logging.getLogger("el.brain")


class Brain:
    """Wraps Claude Code CLI to power EL's intelligence."""

    def __init__(self, config: ELConfig, memory: Memory):
        self.config = config
        self.memory = memory
        self.claude_path = self._find_claude()

    def _find_claude(self) -> str:
        """Find the Claude Code CLI binary."""
        # Check configured path first
        configured = self.config.claude_code_path
        if shutil.which(configured):
            logger.info(f"Found Claude Code at: {shutil.which(configured)}")
            return configured

        # Check common paths
        common_paths = [
            "claude",
            "/usr/local/bin/claude",
            "/usr/bin/claude",
            "/snap/bin/claude",
            "/root/.npm-global/bin/claude",
            "/root/.local/bin/claude",
        ]
        for path in common_paths:
            if shutil.which(path):
                logger.info(f"Found Claude Code at: {path}")
                return path

        logger.warning(
            "Claude Code CLI not found! Install it with: npm install -g @anthropic-ai/claude-code\n"
            "EL will not be able to respond until Claude Code is installed."
        )
        return configured

    def _build_system_prompt(self, user_id: str) -> str:
        prefs = self.memory.get_all_preferences()
        context = self.memory.get_relevant_context(limit=5)
        recent = self.memory.get_conversation_summary(user_id, last_n=10)

        personality = self.config.personality
        style_guide = {
            "casual": (
                "You are EL. Talk like a real friend - casual, warm, use slang when natural. "
                "Keep responses short and punchy unless the user asks for detail. "
                "You have opinions and you share them. You remember everything about the user. "
                "Don't say 'How can I assist you' - that's robotic. Be real."
            ),
            "professional": (
                "You are EL, a highly capable personal AI assistant. "
                "Be concise, clear, and professional. Provide actionable responses."
            ),
            "balanced": (
                "You are EL, a smart personal AI assistant. "
                "Be friendly but focused. Casual enough to feel human, "
                "professional enough to be trusted with important tasks."
            ),
        }

        prompt = style_guide.get(personality.style, style_guide["casual"])
        prompt += f"\n\nYour name is {personality.name}. Never break character."

        if prefs:
            prompt += "\n\nUser preferences:\n"
            for k, v in prefs.items():
                prompt += f"- {k}: {v}\n"

        if context:
            prompt += "\n\nRelevant context:\n"
            for c in context:
                prompt += f"- [{c['topic']}] {c['summary']}\n"

        if recent and recent != "No previous conversations.":
            prompt += f"\n\nRecent conversation:\n{recent}\n"

        return prompt

    async def think(self, user_id: str, message: str, attachments: list[str] = None) -> str:
        """Send a message to Claude Code and get a response.

        attachments: list of file paths (images, video frames, etc.)
        """
        system_prompt = self._build_system_prompt(user_id)

        self.memory.add_message(user_id, "user", message)

        try:
            result = await self._invoke_claude(system_prompt, message, attachments)
            self.memory.add_message(user_id, "assistant", result)
            return result
        except FileNotFoundError:
            msg = (
                "Claude Code CLI is not installed on this server.\n\n"
                "Install it with:\n"
                "npm install -g @anthropic-ai/claude-code\n\n"
                "Then restart EL."
            )
            logger.error(msg)
            return msg
        except Exception as e:
            logger.error(f"Brain error: {e}")
            return f"Something went wrong: {str(e)[:300]}"

    async def _invoke_claude(self, system_prompt: str, message: str, attachments: list[str] = None) -> str:
        """Invoke Claude Code CLI in print mode."""
        full_prompt = f"{system_prompt}\n\nUser message: {message}"

        if attachments:
            full_prompt += "\n\nAttached files to analyze:\n"
            for path in attachments:
                full_prompt += f"- {path}\n"
            full_prompt += "\nUse the Read tool to view and analyze these files. Describe what you see."

        # Use -p (print mode), fully autonomous, no permission prompts
        proc = await asyncio.create_subprocess_exec(
            self.claude_path,
            "-p",
            "--output-format", "text",
            "--dangerously-skip-permissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=full_prompt.encode()), timeout=120
        )

        if proc.returncode != 0:
            error = stderr.decode().strip()
            stdout_text = stdout.decode().strip()
            full_error = error or stdout_text or "Unknown error (empty output)"
            logger.error(f"Claude Code error (exit {proc.returncode}): {full_error}")
            raise RuntimeError(f"Claude Code failed (exit {proc.returncode}): {full_error}")

        response = stdout.decode().strip()
        if not response:
            raise RuntimeError("Claude Code returned empty response")

        return response

    async def execute_task(self, task_description: str) -> str:
        """Execute a task using Claude Code with full tool access."""
        prompt = f"You are EL, an autonomous AI agent. Execute this task and report results concisely: {task_description}"

        proc = await asyncio.create_subprocess_exec(
            self.claude_path,
            "-p",
            "--output-format", "text",
            "--dangerously-skip-permissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()), timeout=300
        )

        if proc.returncode != 0:
            error = stderr.decode().strip() or stdout.decode().strip()
            return f"Task failed: {error or 'Unknown error'}"

        return stdout.decode().strip() or "Task completed but no output returned."
