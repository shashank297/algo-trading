"""Small local task runner with persisted state, retries, and approvals."""

from __future__ import annotations

import json
import inspect
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from orchestration.models import TaskState
from storage.duckdb_manager import DuckDBManager
from loguru import logger


class TaskCancellation(Exception):
    """Raised by a cooperative task when its cancellation token is set."""


class CancellationToken:
    """Thread-safe cancellation signal exposed to task executors."""

    def __init__(self, event: threading.Event) -> None:
        self._event = event

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancellation("TASK_CANCELLED")


class TaskOrchestrator:
    """Run trusted Python callables while persisting their lifecycle to DuckDB."""

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db
        self._cancellation_events: dict[str, threading.Event] = {}
        self._cancellation_lock = threading.Lock()

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
        cancellation_event = threading.Event()
        with self._cancellation_lock:
            self._cancellation_events[task_id] = cancellation_event
        token = CancellationToken(cancellation_event)
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
            with self._cancellation_lock:
                self._cancellation_events.pop(task_id, None)
            return task_id, None

        active_worker: threading.Thread | None = None
        try:
            for attempt in range(max_retries + 1):
                token.raise_if_cancelled()
                if active_worker is not None and active_worker.is_alive():
                    err_msg = (
                        f"Task '{task_name}' timed out and prior worker thread is still executing. "
                        f"Aborting subsequent retry to prevent concurrent side-effects."
                    )
                    self.db.update_research_task(
                        task_id, state=TaskState.FAILED.value, error_message=err_msg,
                        finished_at=datetime.now(timezone.utc),
                        preserve_cancelled=True,
                    )
                    raise RuntimeError(err_msg)

                self.db.update_research_task(
                    task_id, state=TaskState.RUNNING.value, retry_count=attempt,
                    started_at=datetime.now(timezone.utc),
                    preserve_cancelled=True,
                )
                self._raise_if_task_cancelled(task_id)
                if timeout_seconds is None:
                    try:
                        output = self._invoke_executor(executor, token)
                        token.raise_if_cancelled()
                        self._raise_if_task_cancelled(task_id)
                        self.db.update_research_task(
                            task_id, state=TaskState.SUCCEEDED.value,
                            output_json=json.dumps(output, default=str, sort_keys=True),
                            finished_at=datetime.now(timezone.utc),
                            preserve_cancelled=True,
                        )
                        self._raise_if_task_cancelled(task_id)
                        return task_id, output
                    except TaskCancellation:
                        raise
                    except Exception as exc:
                        if attempt < max_retries:
                            self.db.update_research_task(
                                task_id, state=TaskState.RETRYING.value, error_message=str(exc),
                                preserve_cancelled=True,
                            )
                            continue
                        self.db.update_research_task(
                            task_id, state=TaskState.FAILED.value, error_message=str(exc),
                            finished_at=datetime.now(timezone.utc),
                            preserve_cancelled=True,
                        )
                        raise
                outcomes: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
                timed_out = threading.Event()

                def run_fn() -> None:
                    try:
                        value = self._invoke_executor(executor, token)
                        if timed_out.is_set():
                            try:
                                self.db.update_research_task(
                                    task_id,
                                    state=TaskState.CANCELLED.value if cancellation_event.is_set() else TaskState.FAILED.value,
                                    error_message="TASK_CANCELLED" if cancellation_event.is_set() else "TIMED_OUT_WORKER_TERMINATED",
                                    finished_at=datetime.now(timezone.utc),
                                    preserve_cancelled=True,
                                )
                            except Exception as db_exc:
                                logger.warning("Could not persist timed worker terminal state for {}: {}", task_id, db_exc)
                        outcomes.put((True, value))
                    except BaseException as exc:
                        if timed_out.is_set():
                            try:
                                self.db.update_research_task(
                                    task_id,
                                    state=TaskState.CANCELLED.value if cancellation_event.is_set() else TaskState.FAILED.value,
                                    error_message=str(exc),
                                    finished_at=datetime.now(timezone.utc),
                                    preserve_cancelled=True,
                                )
                            except Exception as db_exc:
                                logger.warning("Could not persist timed worker terminal state for {}: {}", task_id, db_exc)
                        try:
                            outcomes.put((False, exc), timeout=0.1)
                        except queue.Full:
                            pass

                active_worker = threading.Thread(target=run_fn, name="bounded-research-task", daemon=True)
                active_worker.start()
                try:
                    succeeded, value = outcomes.get(timeout=timeout_seconds)
                except queue.Empty as exc:
                    timed_out.set()
                    cancellation_event.set()
                    err_msg = (
                        f"Task '{task_name}' timed out after {timeout_seconds}s and worker thread remains active (TIMED_OUT_UNTERMINATED). "
                        f"Aborting retry to guarantee single-thread non-overlapping invariant."
                    )
                    # Do not report a terminal state while the worker can
                    # still perform side effects.  The worker marks FAILED or
                    # CANCELLED only after it actually returns.
                    self.db.update_research_task(
                        task_id, error_message=err_msg, preserve_cancelled=True,
                    )
                    raise TimeoutError(err_msg) from exc

                if succeeded:
                    token.raise_if_cancelled()
                    self._raise_if_task_cancelled(task_id)
                    self.db.update_research_task(
                        task_id, state=TaskState.SUCCEEDED.value,
                        output_json=json.dumps(value, default=str, sort_keys=True),
                        finished_at=datetime.now(timezone.utc),
                        preserve_cancelled=True,
                    )
                    self._raise_if_task_cancelled(task_id)
                    return task_id, value
                if isinstance(value, TaskCancellation):
                    raise value
                if attempt < max_retries:
                    self.db.update_research_task(
                        task_id, state=TaskState.RETRYING.value, error_message=str(value),
                        preserve_cancelled=True,
                    )
                    continue
                self.db.update_research_task(
                    task_id, state=TaskState.FAILED.value, error_message=str(value),
                    finished_at=datetime.now(timezone.utc),
                    preserve_cancelled=True,
                )
                raise value
            raise RuntimeError("Task retry loop ended unexpectedly.")
        except TaskCancellation as exc:
            self.db.update_research_task(
                task_id, state=TaskState.CANCELLED.value,
                error_message=str(exc), finished_at=datetime.now(timezone.utc),
            )
            raise
        finally:
            with self._cancellation_lock:
                self._cancellation_events.pop(task_id, None)

    @staticmethod
    def _invoke_executor(executor: Callable[..., dict[str, Any]], token: CancellationToken) -> dict[str, Any]:
        """Call legacy zero-argument executors or new token-aware executors."""
        try:
            signature = inspect.signature(executor)
            accepts_token = len(signature.parameters) > 0
        except (TypeError, ValueError):
            accepts_token = False
        return executor(token) if accepts_token else executor()

    def approve_task(self, task_id: str) -> None:
        """Move an approval-gated task into the runnable state."""

        self._require_state(task_id, {TaskState.WAITING})
        self.db.update_research_task(task_id, state=TaskState.PENDING.value)

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task before or during execution."""

        self._require_state(task_id, {TaskState.PENDING, TaskState.WAITING, TaskState.RETRYING, TaskState.RUNNING})
        row = self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()
        current_state = TaskState(str(row[0])) if row is not None else TaskState.CANCELLED
        with self._cancellation_lock:
            event = self._cancellation_events.get(task_id)
            if event is not None:
                event.set()
        if current_state == TaskState.RUNNING:
            self.db.update_research_task(
                task_id,
                error_message="CANCEL_REQUESTED; waiting for worker termination",
                preserve_cancelled=True,
            )
        else:
            self.db.update_research_task(
                task_id, state=TaskState.CANCELLED.value, finished_at=datetime.now(timezone.utc),
            )

    def _raise_if_task_cancelled(self, task_id: str) -> None:
        row = self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()
        if row is not None and str(row[0]) == TaskState.CANCELLED.value:
            raise TaskCancellation("TASK_CANCELLED")

    def _require_state(self, task_id: str, allowed: set[TaskState]) -> None:
        row = self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()
        if row is None:
            raise ValueError(f"Unknown task: {task_id}")
        current = TaskState(str(row[0]))
        if current not in allowed:
            allowed_names = ", ".join(state.value for state in sorted(allowed, key=lambda value: value.value))
            raise ValueError(f"Task {task_id} is {current.value}; expected one of {allowed_names}.")
