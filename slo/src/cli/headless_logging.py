"""Logging isolation for headless ``slo run`` invocations.

In headless mode stdout is reserved exclusively for ``AgentStreamEventDAO``
JSONL records.  Any logging line that leaks to stdout would corrupt the
stream.  This module provides a context manager that:

  1. Snapshots the root logger's current handlers.
  2. Replaces them with a file-only sink at ``SLO_HOME/logs/app.log``
     (best-effort; falls back to a NullHandler if the file cannot be created).
  3. Restores the original handlers when the context exits, then
     flushes and closes anything it added.

The implementation intentionally does NOT use ``logging.config.dictConfig`` —
that would replace config at module level and interfere with other code.
Instead it directly manipulates the root logger's handler list, the same
strategy used by ``interactive_logging`` in ``config.logger``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator, Optional

from config.logger import _build_app_file_handler

__all__ = ["headless_logging"]


@contextmanager
def headless_logging(*, slo_home: Path) -> Iterator[Optional[Path]]:
    """Redirect all root-logger output to ``app.log``, keeping stdout clean.

    Replaces stdout/stderr ``StreamHandler`` instances on the root logger with
    a rotating file sink under ``SLO_HOME/logs/app.log`` for the duration of
    the headless run.  The original handlers are restored on exit regardless of
    whether the body raises.

    File setup is best-effort — if the file handler cannot be created a
    ``NullHandler`` is installed so the root logger is still silenced from
    stdout, log records are simply dropped.

    Args:
        slo_home (Path): Resolved Slo home directory used to locate the logs
            sub-directory (``<slo_home>/logs/app.log``).

    Yields:
        Optional[Path]: Path to ``app.log`` when the file handler was created
            successfully, otherwise ``None``.
    """
    root_logger: logging.Logger = logging.getLogger()
    previous_handlers: list[logging.Handler] = list(root_logger.handlers)

    file_handler: Optional[RotatingFileHandler] = _build_app_file_handler(
        slo_home=slo_home,
    )
    added_handlers: list[logging.Handler] = _build_replacement_handlers(
        file_handler=file_handler,
    )
    root_logger.handlers = added_handlers
    log_path: Optional[Path] = Path(file_handler.baseFilename) if file_handler is not None else None
    try:
        yield log_path
    finally:
        root_logger.handlers = previous_handlers
        _flush_and_close(handlers=added_handlers)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_replacement_handlers(
    *,
    file_handler: Optional[RotatingFileHandler],
) -> list[logging.Handler]:
    """Return the handler list to install during the headless context.

    When the file handler is available it is the sole handler.  When it is
    not (e.g. permission error), a ``NullHandler`` is used so the root logger
    is configured but records are silently dropped rather than leaking to stdout.

    Args:
        file_handler (Optional[RotatingFileHandler]): The rotating file handler,
            or ``None`` if creation failed.

    Returns:
        list[logging.Handler]: Non-empty handler list for the root logger.
    """
    if file_handler is not None:
        return [file_handler]
    return [logging.NullHandler()]


def _flush_and_close(*, handlers: list[logging.Handler]) -> None:
    """Flush and close every handler in *handlers*, ignoring errors.

    Args:
        handlers (list[logging.Handler]): Handlers added during the context.
    """
    for handler in handlers:
        try:
            handler.flush()
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
