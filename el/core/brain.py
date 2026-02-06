"""EL Brain - Interface to Claude Code CLI."""

import asyncio
import subprocess
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
        self.claude_path = config.claude_code_path

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

    async def think(self, user_id: str, message: str) -> str:
        """Send a message to Claude Code and get a response."""
        system_prompt = self._build_system_prompt(user_id)

        self.memory.add_message(user_id, "user", message)

        try:
            result = await self._invoke_claude(system_prompt, message)
            self.memory.add_message(user_id, "assistant", result)
            return result
        except Exception as e:
            logger.error(f"Brain error: {e}")
            return "Yo, something glitched on my end. Give me a sec and try again."

    async def _invoke_claude(self, system_prompt: str, message: str) -> str:
        """Invoke Claude Code CLI in print mode."""
        full_prompt = f"{system_prompt}\n\nUser message: {message}"

        proc = await asyncio.create_subprocess_exec(
            self.claude_path,
            "--print",
            full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=120
        )

        if proc.returncode != 0:
            error = stderr.decode().strip()
            logger.error(f"Claude Code error: {error}")
            raise RuntimeError(f"Claude Code failed: {error}")

        return stdout.decode().strip()

    async def execute_task(self, task_description: str) -> str:
        """Execute a task using Claude Code with full tool access."""
        proc = await asyncio.create_subprocess_exec(
            self.claude_path,
            "--print",
            f"You are EL, an autonomous AI agent. Execute this task and report results concisely: {task_description}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=300
        )

        if proc.returncode != 0:
            return f"Task failed: {stderr.decode().strip()}"

        return stdout.decode().strip()
