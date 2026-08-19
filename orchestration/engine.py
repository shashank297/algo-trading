"""Small local task runner with persisted state, retries, and approvals."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from orchestration.models import TaskState
from storage.duckdb_manager import DuckDBManager


class TaskOrchestrator:
    """Run trusted Python callables while persisting their lifecycle to DuckDB."""

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db

    def run_task(
        self,
        *,
        goal_id: str,
        task_name: str,
        executor: Callable[[], dict[str, Any]],
        assigned_agent: str | None = None,
        parent_task_id: str | None = None,
        max_retries: int = 0,
        timeout_seconds: int | None = None,
        requires_approval: bool = False,
        input_payload: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Execute a trusted task and store terminal state plus serialized output."""

        task_id = task_id or str(uuid.uuid4())
        self.db.create_research_task(
            {
                "task_id": task_id,
                "goal_id": goal_id,
                "parent_task_id": parent_task_id,
                "task_name": task_name,
                "assigned_agent": assigned_agent,
                "state": TaskState.WAITING.value if requires_approval else TaskState.PENDING.value,
                "max_retries": max_retries,
                "timeout_seconds": timeout_seconds,
                "input_json": json.dumps(input_payload or {}, default=str, sort_keys=True),
                "created_at": datetime.now(timezone.utc),
            },
        )
        if requires_approval:
            return task_id, None

        for attempt in range(max_retries + 1):
            self.db.update_research_task(
                task_id,
                state=TaskState.RUNNING.value,
                retry_count=attempt,
                started_at=datetime.now(timezone.utc),
            )
            try:
                output = self._execute_with_timeout(executor, timeout_seconds)
                self.db.update_research_task(
                    task_id,
                    state=TaskState.SUCCEEDED.value,
                    output_json=json.dumps(output, default=str, sort_keys=True),
                    finished_at=datetime.now(timezone.utc),
                )
                return task_id, output
            except Exception as exc:
                if attempt < max_retries:
                    self.db.update_research_task(task_id, state=TaskState.RETRYING.value, error_message=str(exc))
                    continue
                self.db.update_research_task(
                    task_id,
                    state=TaskState.FAILED.value,
                    error_message=str(exc),
                    finished_at=datetime.now(timezone.utc),
                )
                raise
        raise RuntimeError("Task retry loop ended unexpectedly.")

    @staticmethod
    def _execute_with_timeout(
        executor: Callable[[], dict[str, Any]],
        timeout_seconds: int | None,
    ) -> dict[str, Any]:
        if timeout_seconds is None:
            return executor()
        outcomes: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                outcomes.put((True, executor()))
            except BaseException as exc:
                outcomes.put((False, exc))

        worker = threading.Thread(target=run, name="bounded-research-task", daemon=True)
        worker.start()
        try:
            succeeded, value = outcomes.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(f"Task exceeded {timeout_seconds} seconds.") from exc
        if succeeded:
            return value
        raise value

    def approve_task(self, task_id: str) -> None:
        """Move an approval-gated task into the runnable state."""

        self._require_state(task_id, {TaskState.WAITING})
        self.db.update_research_task(task_id, state=TaskState.PENDING.value)

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task before any agent or execution tool can act on it."""

        self._require_state(task_id, {TaskState.PENDING, TaskState.WAITING, TaskState.RETRYING})
        self.db.update_research_task(task_id, state=TaskState.CANCELLED.value, finished_at=datetime.now(timezone.utc))

    def _require_state(self, task_id: str, allowed: set[TaskState]) -> None:
        row = self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()
        if row is None:
            raise ValueError(f"Unknown task: {task_id}")
        current = TaskState(str(row[0]))
        if current not in allowed:
            allowed_names = ", ".join(state.value for state in sorted(allowed, key=lambda value: value.value))
            raise ValueError(f"Task {task_id} is {current.value}; expected one of {allowed_names}.")
