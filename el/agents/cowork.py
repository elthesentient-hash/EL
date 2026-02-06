"""EL Multi-Agent Cowork System - Parallel Claude Code sessions."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from el.core.brain import Brain

logger = logging.getLogger("el.agents")


@dataclass
class AgentTask:
    id: int
    name: str
    description: str
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None


class CoworkOrchestrator:
    """Manages multiple parallel Claude Code agents working together."""

    def __init__(self, brain: Brain, max_concurrent: int = 3):
        self.brain = brain
        self.max_concurrent = max_concurrent
        self.tasks: list[AgentTask] = []
        self._task_counter = 0
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def plan_tasks(self, goal: str) -> list[AgentTask]:
        """Break a complex goal into subtasks (synchronous planning)."""
        self.tasks = []
        self._task_counter = 0
        return self.tasks

    async def plan_tasks_with_ai(self, goal: str, user_id: str) -> list[AgentTask]:
        """Use Claude Code to break a complex goal into subtasks."""
        planning_prompt = (
            f"Break this goal into 2-5 independent subtasks that can be done in parallel. "
            f"Return ONLY a JSON array of objects with 'name' and 'description' fields. "
            f"No markdown, no explanation, just valid JSON.\n\n"
            f"Goal: {goal}"
        )

        result = await self.brain.think(user_id, planning_prompt)

        try:
            # Try to parse JSON from the response
            import json
            # Strip any markdown code blocks if present
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            tasks_data = json.loads(cleaned)

            self.tasks = []
            for item in tasks_data:
                self._task_counter += 1
                self.tasks.append(AgentTask(
                    id=self._task_counter,
                    name=item["name"],
                    description=item["description"],
                ))
            return self.tasks

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse task plan, creating single task: {e}")
            self._task_counter += 1
            task = AgentTask(
                id=self._task_counter,
                name="Execute goal",
                description=goal,
            )
            self.tasks = [task]
            return self.tasks

    async def _run_single_agent(self, task: AgentTask) -> AgentTask:
        """Run a single agent task with concurrency control."""
        async with self._semaphore:
            task.status = "running"
            logger.info(f"Agent [{task.id}] starting: {task.name}")

            try:
                result = await self.brain.execute_task(task.description)
                task.result = result
                task.status = "completed"
                logger.info(f"Agent [{task.id}] completed: {task.name}")
            except Exception as e:
                task.result = str(e)
                task.status = "failed"
                logger.error(f"Agent [{task.id}] failed: {task.name} - {e}")

            return task

    async def execute_all(self) -> list[AgentTask]:
        """Execute all planned tasks in parallel."""
        if not self.tasks:
            return []

        logger.info(f"Launching {len(self.tasks)} agents in parallel (max {self.max_concurrent} concurrent)")

        results = await asyncio.gather(
            *[self._run_single_agent(task) for task in self.tasks],
            return_exceptions=True,
        )

        # Handle any exceptions from gather
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.tasks[i].status = "failed"
                self.tasks[i].result = str(result)

        return self.tasks

    async def run_goal(self, goal: str, user_id: str) -> str:
        """Full pipeline: plan tasks, execute in parallel, summarize results."""
        # Plan
        tasks = await self.plan_tasks_with_ai(goal, user_id)
        task_list = "\n".join(f"  [{t.id}] {t.name}" for t in tasks)
        logger.info(f"Planned {len(tasks)} tasks:\n{task_list}")

        # Execute
        completed = await self.execute_all()

        # Summarize
        summary_parts = []
        for task in completed:
            status_icon = "done" if task.status == "completed" else "failed"
            summary_parts.append(f"[{status_icon}] {task.name}:\n{task.result[:500] if task.result else 'No output'}")

        return "\n\n".join(summary_parts)

    def get_status(self) -> str:
        """Get current status of all agents."""
        if not self.tasks:
            return "No active tasks."

        lines = []
        for task in self.tasks:
            lines.append(f"[{task.status}] {task.name}")
        return "\n".join(lines)
