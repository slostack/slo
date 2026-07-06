import logging
import logging.config
import os
from contextlib import contextmanager
from logging import Logger, getLogger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator, Optional

from pythonjsonlogger import jsonlogger
from textual.logging import TextualHandler

from config.cfg import cfg, is_dev, is_test

_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_TEXT_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(funcName)s:%(lineno)d | %(message)s"
_JSON_FMT = "%(asctime)s %(levelname)s %(name)s %(filename)s %(funcName)s %(lineno)d %(message)s"
_TUI_LOG_MAX_BYTES: int = 5 * 1024 * 1024
_TUI_LOG_BACKUP_COUNT: int = 3
_APP_LOG_MAX_BYTES: int = 5 * 1024 * 1024
_APP_LOG_BACKUP_COUNT: int = 3


def _formatter_config() -> dict:
    if cfg("LOG_FORMAT") == "text":
        return {
            "format": _TEXT_FMT,
            "datefmt": _LOG_DATEFMT,
        }
    return {
        "()": "pythonjsonlogger.json.JsonFormatter",
        "fmt": _JSON_FMT,
        "datefmt": _LOG_DATEFMT,
        "json_default": str,
    }


def _build_runtime_formatter() -> logging.Formatter:
    """Return the text or JSON formatter matching the active config.

    Returns:
        logging.Formatter: Formatter aligned with ``SLO_LOG_FORMAT``.
    """
    if cfg("LOG_FORMAT") == "text":
        return logging.Formatter(fmt=_TEXT_FMT, datefmt=_LOG_DATEFMT)
    return jsonlogger.JsonFormatter(
        fmt=_JSON_FMT,
        datefmt=_LOG_DATEFMT,
        json_default=str,
    )


def _ensure_private_log_file(*, slo_home: Path) -> Path:
    """Create ``SLO_HOME/logs/tui.log`` with user-only permissions.

    Args:
        slo_home (Path): The resolved Slo home directory.

    Returns:
        Path: The interactive log file path.
    """
    logs_dir: Path = slo_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(logs_dir, 0o700)

    log_path: Path = logs_dir / "tui.log"
    if not log_path.exists():
        log_path.touch(mode=0o600)
    else:
        os.chmod(log_path, 0o600)
    return log_path


def _build_interactive_file_handler(
    *,
    slo_home: Path,
    formatter: logging.Formatter,
) -> Optional[RotatingFileHandler]:
    """Build the private rotating file sink for TUI sessions.

    File logging is best-effort: if the directory or handler cannot be
    created, the TUI still runs with terminal-stream isolation via the
    Textual handler alone.

    Args:
        slo_home (Path): The resolved Slo home directory.
        formatter (logging.Formatter): Formatter to attach to the handler.

    Returns:
        Optional[RotatingFileHandler]: The configured file handler when
            setup succeeds, otherwise ``None``.
    """
    try:
        log_path: Path = _ensure_private_log_file(slo_home=slo_home)
        file_handler: RotatingFileHandler = RotatingFileHandler(
            filename=log_path,
            maxBytes=_TUI_LOG_MAX_BYTES,
            backupCount=_TUI_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None

    file_handler.setFormatter(formatter)
    return file_handler


def _build_app_log_formatter() -> logging.Formatter:
    """Return the text or JSON formatter for the persistent app log.

    Development and test environments use a human-readable text format so
    local tails are easy to read. All other environments (staging, production)
    use the same JSON format as the existing console and TUI sinks.

    Returns:
        logging.Formatter: Text formatter for dev/test; JSON formatter otherwise.
    """
    if is_dev() or is_test():
        return logging.Formatter(fmt=_TEXT_FMT, datefmt=_LOG_DATEFMT)
    return jsonlogger.JsonFormatter(
        fmt=_JSON_FMT,
        datefmt=_LOG_DATEFMT,
        json_default=str,
    )


def _ensure_app_log_file(*, slo_home: Path) -> Path:
    """Create ``SLO_HOME/logs/app.log`` with user-only permissions.

    Args:
        slo_home (Path): The resolved Slo home directory.

    Returns:
        Path: The app log file path.
    """
    logs_dir: Path = slo_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(logs_dir, 0o700)

    log_path: Path = logs_dir / "app.log"
    if not log_path.exists():
        log_path.touch(mode=0o600)
    else:
        os.chmod(log_path, 0o600)
    return log_path


def _build_app_file_handler(*, slo_home: Path) -> Optional[RotatingFileHandler]:
    """Build the rotating file handler for the persistent app log.

    Best-effort: returns ``None`` if the directory or handler cannot be
    created so callers degrade gracefully.

    Args:
        slo_home (Path): The resolved Slo home directory.

    Returns:
        Optional[RotatingFileHandler]: Configured handler on success, ``None``
            otherwise.
    """
    try:
        log_path: Path = _ensure_app_log_file(slo_home=slo_home)
        handler: RotatingFileHandler = RotatingFileHandler(
            filename=log_path,
            maxBytes=_APP_LOG_MAX_BYTES,
            backupCount=_APP_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None

    handler.setFormatter(_build_app_log_formatter())
    return handler


def _remove_console_handlers(*, root_logger: logging.Logger) -> None:
    """Remove stdout/stderr ``StreamHandler`` instances from the root logger.

    File-based handlers (``FileHandler`` and its subclasses) are left intact.
    Used by ``configure_app_file_logging`` to redirect console output to the
    persistent app log file.

    Args:
        root_logger (logging.Logger): The root logger to modify in place.
    """
    console_handlers: list[logging.Handler] = [
        handler
        for handler in root_logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
    ]
    for handler in console_handlers:
        root_logger.removeHandler(handler)


def configure_app_file_logging(*, slo_home: Path) -> Optional[Path]:
    """Redirect application logs from the console to a persistent ``app.log`` file.

    Removes any stdout/stderr ``StreamHandler`` instances from the root logger
    and replaces them with a rotating file sink at ``SLO_HOME/logs/app.log``.
    This keeps application-level log records out of the terminal while ensuring
    they are captured in a queryable file.

    Unlike ``interactive_logging`` (which is a temporary context manager for TUI
    isolation), this change is permanent for the lifetime of the process.

    Text format is used in development and test environments; JSON for all
    others. The format decision is environment-based so local tails are readable
    without setting ``SLO_LOG_FORMAT=text`` manually.

    File setup is best-effort: if the directory or handler cannot be created the
    function returns ``None`` and the existing handlers are left untouched.

    Args:
        slo_home (Path): The resolved Slo home directory.

    Returns:
        Optional[Path]: The app log file path when setup succeeds, otherwise
            ``None``.
    """
    file_handler: Optional[RotatingFileHandler] = _build_app_file_handler(slo_home=slo_home)
    if file_handler is None:
        return None

    root_logger: logging.Logger = logging.getLogger()
    _remove_console_handlers(root_logger=root_logger)
    root_logger.addHandler(file_handler)
    return Path(file_handler.baseFilename)


@contextmanager
def interactive_logging(*, slo_home: Path) -> Iterator[Optional[Path]]:
    """Temporarily isolate TUI logging from terminal stdout/stderr.

    Installs a Textual-aware handler with no stdout/stderr fallback and,
    when possible, a private rotating file sink under ``SLO_HOME/logs``.
    Also installs the persistent ``app.log`` file handler so application
    log records remain captured during the TUI session. Restores the
    original root handlers when the context exits.

    Args:
        slo_home (Path): The resolved Slo home directory.

    Yields:
        Optional[Path]: The interactive log file path when file logging is
            available, otherwise ``None``.
    """
    root_logger: logging.Logger = logging.getLogger()
    previous_handlers: list[logging.Handler] = list(root_logger.handlers)
    formatter: logging.Formatter = _build_runtime_formatter()

    textual_handler: TextualHandler = TextualHandler(stderr=False, stdout=False)
    textual_handler.setFormatter(formatter)

    file_handler: Optional[RotatingFileHandler] = _build_interactive_file_handler(
        slo_home=slo_home,
        formatter=formatter,
    )
    app_file_handler: Optional[RotatingFileHandler] = _build_app_file_handler(
        slo_home=slo_home,
    )
    new_handlers: list[logging.Handler] = [textual_handler]
    if file_handler is not None:
        new_handlers.append(file_handler)
    if app_file_handler is not None:
        new_handlers.append(app_file_handler)

    root_logger.handlers = new_handlers
    log_path: Optional[Path] = Path(file_handler.baseFilename) if file_handler is not None else None
    try:
        yield log_path
    finally:
        root_logger.handlers = previous_handlers
        for handler in new_handlers:
            try:
                handler.flush()
            finally:
                handler.close()


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": _formatter_config(),
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "standard",
        },
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["console"],
    },
    "loggers": {
        "slo": {"level": "DEBUG", "propagate": True},
        "uvicorn": {"level": "DEBUG", "propagate": True},
        "uvicorn.error": {"level": "INFO", "propagate": True},
        "uvicorn.access": {"level": "INFO", "propagate": True},
        "httpx": {"level": "INFO", "propagate": True},
        "a2a": {"level": "WARNING", "propagate": True},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

log: Logger = getLogger("slo")


def capture_exc(error: Exception) -> None:
    """Hook for sending exceptions to an external sink (Sentry / OTel).

    No-op in v1; placeholder so call sites already include the contract.
    """
    if is_dev() or is_test():
        return None
    return None


def log_debug(msg: str, **kwargs) -> None:
    if cfg("ENV") != "prod":
        log.debug(msg, stacklevel=2, extra=kwargs)


def log_info(msg: str, **kwargs) -> None:
    log.info(msg, stacklevel=2, extra=kwargs)


def log_warning(msg: str, **kwargs) -> None:
    log.warning(msg, stacklevel=2, extra=kwargs)


def log_error(
    msg: str,
    e: Exception | None = None,
    stack_trace: bool = True,
    **kwargs,
) -> None:
    if not stack_trace:
        log.error(msg, stacklevel=2, extra=kwargs)
    else:
        log.error(msg, exc_info=True, stack_info=True, stacklevel=2, extra=kwargs)

    if e and (not is_test() and not is_dev()):
        capture_exc(error=e)
