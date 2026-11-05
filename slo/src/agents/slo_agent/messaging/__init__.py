"""Session-owned durable message delivery (feature 96, sub-spec A.1).

This package introduces the shared messaging vocabulary and the
session-owned admission, ordering and recovery components:

- ``dao.py`` — strict immutable boundary records and safe internal errors.
- ``ownership.py`` — single-owner execution lease for one session.
- ``store.py`` — the only SQLite owner for session messaging state.
- ``queue.py`` — serialized admission, selection and wake/yield signals.
- ``delivery.py`` — the narrow seam between session-owned claims and
  agent-owned context.
- ``client.py`` — the bound local messaging client used by trusted
  composition.

These types are added privately and stay inactive until the complete
local cutover in sub-spec A.1 Change 9. No constructor in this package
starts tasks, opens connections or publishes readiness.
"""
