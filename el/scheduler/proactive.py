"""EL Proactive Scheduler - Wake up and do things autonomously."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Callable, Optional
from el.memory.store import Memory
from el.core.brain import Brain

logger = logging.getLogger("el.scheduler")


class ScheduledJob:
    """A single scheduled job."""

    def __init__(self, name: str, description: str, cron_expr: str,
                 callback: Optional[Callable] = None):
        self.name = name
        self.description = description
        self.cron_expr = cron_expr
        self.callback = callback
        self.last_run: Optional[float] = None

    def should_run(self) -> bool:
        """Simple cron-like check. Supports: hourly, daily, weekly, and interval formats."""
        now = datetime.now()

        if self.cron_expr == "hourly":
            if self.last_run is None:
                return True
            return (time.time() - self.last_run) >= 3600

        elif self.cron_expr == "daily":
            if self.last_run is None:
                return True
            return (time.time() - self.last_run) >= 86400

        elif self.cron_expr == "weekly":
            if self.last_run is None:
                return True
            return (time.time() - self.last_run) >= 604800

        elif self.cron_expr.startswith("every_"):
            # Format: every_30m, every_2h, every_1d
            interval_str = self.cron_expr[6:]
            multipliers = {"m": 60, "h": 3600, "d": 86400}
            unit = interval_str[-1]
            value = int(interval_str[:-1])
            interval = value * multipliers.get(unit, 60)

            if self.last_run is None:
                return True
            return (time.time() - self.last_run) >= interval

        elif self.cron_expr.startswith("at_"):
            # Format: at_08:00, at_17:30
            target_time = self.cron_expr[3:]
            hour, minute = map(int, target_time.split(":"))
            if now.hour == hour and now.minute == minute:
                if self.last_run is None:
                    return True
                return (time.time() - self.last_run) >= 3600  # Don't re-run within the hour
            return False

        return False


class ProactiveScheduler:
    """Runs scheduled tasks and proactive actions for EL."""

    def __init__(self, brain: Brain, memory: Memory, notify_callback: Callable = None):
        self.brain = brain
        self.memory = memory
        self.notify = notify_callback  # Function to send messages to user via Telegram
        self.jobs: list[ScheduledJob] = []
        self._running = False
        self._check_interval = 60  # Check every 60 seconds

    def add_job(self, name: str, description: str, cron_expr: str,
                callback: Callable = None) -> ScheduledJob:
        """Add a scheduled job."""
        job = ScheduledJob(name, description, cron_expr, callback)
        self.jobs.append(job)

        # Also persist to memory
        self.memory.add_scheduled_task(name, description, cron_expr)
        logger.info(f"Scheduled job added: {name} ({cron_expr})")
        return job

    def load_jobs_from_memory(self):
        """Load previously saved scheduled tasks from memory."""
        tasks = self.memory.get_scheduled_tasks(enabled_only=True)
        for task in tasks:
            existing = [j for j in self.jobs if j.name == task["name"]]
            if not existing:
                self.jobs.append(ScheduledJob(
                    name=task["name"],
                    description=task["description"],
                    cron_expr=task["cron_expr"],
                    callback=None,
                ))
        logger.info(f"Loaded {len(tasks)} scheduled tasks from memory")

    async def _execute_job(self, job: ScheduledJob):
        """Execute a single scheduled job."""
        logger.info(f"Running scheduled job: {job.name}")
        job.last_run = time.time()

        try:
            if job.callback:
                result = await job.callback()
            else:
                # Use Claude Code to execute the task
                result = await self.brain.execute_task(job.description)

            # Notify user of results via Telegram
            if self.notify:
                message = f"[Scheduled] {job.name}\n\n{result[:1000]}"
                await self.notify(message)

            logger.info(f"Job completed: {job.name}")

        except Exception as e:
            logger.error(f"Job failed: {job.name} - {e}")
            if self.notify:
                await self.notify(f"[Scheduled] {job.name} failed: {str(e)[:200]}")

    async def run(self):
        """Main scheduler loop - runs forever."""
        self._running = True
        self.load_jobs_from_memory()
        logger.info(f"Scheduler started with {len(self.jobs)} jobs")

        while self._running:
            for job in self.jobs:
                if job.should_run():
                    asyncio.create_task(self._execute_job(job))

            await asyncio.sleep(self._check_interval)

    def stop(self):
        """Stop the scheduler loop."""
        self._running = False
        logger.info("Scheduler stopped")

    def add_default_jobs(self):
        """Add some useful default proactive jobs."""
        defaults = [
            {
                "name": "morning_briefing",
                "description": "Give me a brief morning summary: what's on my calendar today, any important notifications, weather outlook. Keep it short and casual.",
                "cron_expr": "at_08:00",
            },
            {
                "name": "pr_check",
                "description": "Check my GitHub for any PRs that need review or have new comments. Only report if there's something actionable.",
                "cron_expr": "every_2h",
            },
        ]

        for d in defaults:
            existing = [j for j in self.jobs if j.name == d["name"]]
            if not existing:
                self.add_job(**d)
