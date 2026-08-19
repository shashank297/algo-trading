# Orchestration

`TaskOrchestrator` persists `PENDING`, `RUNNING`, `WAITING`, `RETRYING`, `SUCCEEDED`, `FAILED`, and `CANCELLED` tasks. Each task has an optional parent, agent assignment, retry count, timeout record, input, output, and error log.

The first workflow validates data, obtains technical analysis, runs a deterministic experiment, obtains quant analysis, applies deterministic risk, and creates a research synthesis. Approval-gated tasks remain in `WAITING` until explicitly approved.

Agent calls execute only inside their persisted task lifecycle. Real OpenAI requests use the gateway HTTP timeout; the generic local callable timeout returns control but cannot forcibly terminate a Python thread, so timed callables must be idempotent and must not own broker or credential side effects.
