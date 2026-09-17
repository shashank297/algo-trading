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
        self._active_tasks: dict[str, tuple[threading.Event, threading.Thread | None]] = {}
        self._lock = threading.Lock()

    def run_task(
        self,
        *,
        goal_id: str,
        task_name: str,
        executor: Callable[..., dict[str, Any]],
        assigned_agent: str | None = None,
        parent_task_id: str | None = None,
        max_retries: int = 0,
        timeout_seconds: int | None = None,
        requires_approval: bool = False,
        input_payload: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Execute a trusted task and store terminal state plus serialized output."""

        import inspect

        def _invoke_executor(fn: Callable[..., Any], token: threading.Event) -> Any:
            try:
                sig = inspect.signature(fn)
                if "cancellation_token" in sig.parameters:
                    return fn(cancellation_token=token)
                elif len(sig.parameters) >= 1:
                    return fn(token)
            except (ValueError, TypeError):
                pass
            return fn()

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

        active_worker: threading.Thread | None = None
        cancellation_token = threading.Event()
        for attempt in range(max_retries + 1):
            if active_worker is not None and active_worker.is_alive():
                # Enforce fail-closed non-overlapping retry invariant
                err_msg = (
                    f"Task '{task_name}' timed out and prior worker thread is still executing. "
                    f"Aborting subsequent retry to prevent concurrent side-effects."
                )
                self.db.update_research_task(
                    task_id,
                    state=TaskState.FAILED.value,
                    error_message=err_msg,
                    finished_at=datetime.now(timezone.utc),
                )
                raise RuntimeError(err_msg)

            self.db.update_research_task(
                task_id,
                state=TaskState.RUNNING.value,
                retry_count=attempt,
                started_at=datetime.now(timezone.utc),
            )
            if timeout_seconds is None:
                with self._lock:
                    self._active_tasks[task_id] = (cancellation_token, threading.current_thread())
                try:
                    output = _invoke_executor(executor, cancellation_token)
                    if cancellation_token.is_set():
                        self.db.update_research_task(
                            task_id,
                            state=TaskState.CANCELLED.value,
                            finished_at=datetime.now(timezone.utc),
                        )
                        return task_id, output
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.SUCCEEDED.value,
                        output_json=json.dumps(output, default=str, sort_keys=True),
                        finished_at=datetime.now(timezone.utc),
                    )
                    return task_id, output
                except Exception as exc:
                    if cancellation_token.is_set():
                        self.db.update_research_task(
                            task_id,
                            state=TaskState.CANCELLED.value,
                            finished_at=datetime.now(timezone.utc),
                        )
                        return task_id, None
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
                finally:
                    with self._lock:
                        self._active_tasks.pop(task_id, None)
            else:
                outcomes: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

                def run_fn() -> None:
                    try:
                        outcomes.put((True, _invoke_executor(executor, cancellation_token)))
                    except BaseException as exc:
                        outcomes.put((False, exc))

                active_worker = threading.Thread(target=run_fn, name="bounded-research-task", daemon=True)
                with self._lock:
                    self._active_tasks[task_id] = (cancellation_token, active_worker)
                active_worker.start()
                try:
                    succeeded, value = outcomes.get(timeout=timeout_seconds)
                except queue.Empty as exc:
                    # Worker thread is still alive and unterminated. Do not retry overlapping thread!
                    err_msg = (
                        f"Task '{task_name}' timed out after {timeout_seconds}s and worker thread remains active (TIMED_OUT_UNTERMINATED). "
                        f"Aborting retry to guarantee single-thread non-overlapping invariant."
                    )
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.FAILED.value,
                        error_message=err_msg,
                        finished_at=datetime.now(timezone.utc),
                    )
                    raise TimeoutError(err_msg) from exc
                finally:
                    with self._lock:
                        self._active_tasks.pop(task_id, None)

                if cancellation_token.is_set():
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.CANCELLED.value,
                        finished_at=datetime.now(timezone.utc),
                    )
                    return task_id, value if succeeded else None

                if succeeded:
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.SUCCEEDED.value,
                        output_json=json.dumps(value, default=str, sort_keys=True),
                        finished_at=datetime.now(timezone.utc),
                    )
                    return task_id, value
                else:
                    if attempt < max_retries:
                        self.db.update_research_task(task_id, state=TaskState.RETRYING.value, error_message=str(value))
                        continue
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.FAILED.value,
                        error_message=str(value),
                        finished_at=datetime.now(timezone.utc),
                    )
                    raise value
        raise RuntimeError("Task retry loop ended unexpectedly.")

    def approve_task(self, task_id: str) -> None:
        """Move an approval-gated task into the runnable state."""

        self._require_state(task_id, {TaskState.WAITING})
        self.db.update_research_task(task_id, state=TaskState.PENDING.value)

    def cancel_task(self, task_id: str, timeout_seconds: float = 2.0) -> None:
        """Cancel a task cooperatively, refusing to falsely report stopped execution while side effects can continue."""

        self._require_state(task_id, {TaskState.PENDING, TaskState.WAITING, TaskState.RETRYING, TaskState.RUNNING})
        with self._lock:
            active_task = self._active_tasks.get(task_id)

        if active_task is not None:
            token, worker = active_task
            token.set()
            if worker is not None and worker != threading.current_thread() and worker.is_alive():
                worker.join(timeout=timeout_seconds)
                if worker.is_alive():
                    err_msg = (
                        f"Task '{task_id}' was requested to cancel, but worker thread did not terminate within "
                        f"{timeout_seconds}s and remains actively executing (CANCELLATION_UNTERMINATED). "
                        f"Refusing to report stopped execution while worker can still perform side effects."
                    )
                    self.db.update_research_task(
                        task_id,
                        state=TaskState.RUNNING.value,
                        error_message=err_msg,
                    )
                    raise RuntimeError(err_msg)

        self.db.update_research_task(task_id, state=TaskState.CANCELLED.value, finished_at=datetime.now(timezone.utc))

    def _require_state(self, task_id: str, allowed: set[TaskState]) -> None:
        row = self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()
        if row is None:
            raise ValueError(f"Unknown task: {task_id}")
        current = TaskState(str(row[0]))
        if current not in allowed:
            allowed_names = ", ".join(state.value for state in sorted(allowed, key=lambda value: value.value))
            raise ValueError(f"Task {task_id} is {current.value}; expected one of {allowed_names}.")
