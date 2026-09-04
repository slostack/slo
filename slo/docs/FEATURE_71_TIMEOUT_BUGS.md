# Feature 71: Detached Workflow Timeout Bugs

## Changes

- Branch `feature-71-timeout-bugs` is relative to merge-base `d6985b3`, with feature commit `d8fc80f` (`feat(orchestration): harden detached workflow supervision`) and a merge change of 61 files (+7,962/-890).
- Adds durable detached-workflow state through a canonical layout and atomic private writes: `orchestrator.json`, `fleet.json`, a durable abort request, and `children/<id>/status.json`.
- Uses flock-protected mutations, fresh-status-first reconciliation with PID fallback, and lifecycle and terminal projections.
- Hardens watchdog, heartbeat, control-loop, abort, and cleanup behavior: cooperative durable abort, SIGTERM and parent-death handling, pool sealing/draining, SIGTERM → grace → SIGKILL → reap, terminal-fact persistence, cleanup accounting, and PID identity verification before signalling.
- Adds recovery and diagnostics: `/workflows resume <id>` is limited to stalled or failed handles and reuses original history; launching becomes running only after fresh evidence. TUI and visualizer display orchestrator rows, fleet/liveness/cleanup/selected diagnostics, and incremental stdout JSONL tails.
- Tests and documentation cover atomic state, reconciliation, reaping and PID reuse, timeout/watchdog behavior, terminal drain, relaunch, slash routing, and the visualizer; documentation and changelog are updated.

## Fix addresses

- Prevents false child cancellation caused by stale heartbeat telemetry. Heartbeats are advisory (`healthy`, `degraded`, or `silent`); only `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` cancels a child for stdout inactivity.
- Replaces stale, ambiguous, or unrecoverable detached state after failures with verified durable evidence.
- Avoids orphaned or incorrect child cleanup and signals to recycled PIDs, while improving detached-workflow observability.
