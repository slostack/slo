"""Adapter registry — built-in adapters and ``module:Class`` loading (108.5 §3).

``slo channel run telegram`` builds a built-in adapter from its config file;
``slo channel run --adapter pkg.mod:Class`` imports a custom adapter class and
builds it with no arguments (a custom adapter reads its own configuration).

A custom reference runs arbitrary local code, exactly like ``--plugin``: it is
an explicit, trusted choice of the same user who runs the command. The current
directory is appended to ``sys.path`` (never prepended, so it cannot shadow
installed packages) so references such as ``tests.fixtures:EchoAdapter`` work
from a checkout.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Optional

from src.channels.errors import AdapterConfigError
from src.channels.protocol import ChannelAdapter

__all__ = ["AdapterRegistry"]

_ADAPTER_METHODS: tuple[str, ...] = ("start", "deliver", "stop")


def _build_telegram(*, config_path: Optional[Path]) -> ChannelAdapter:
    """Build the built-in Telegram adapter from its config file.

    Imported lazily so ``slo channel`` commands that never run Telegram do not
    import its HTTP client.

    Args:
        config_path (Optional[Path]): Config file; defaults to
            ``$SLO_HOME/channels/telegram.json``.

    Returns:
        ChannelAdapter: The configured adapter.

    Raises:
        AdapterConfigError: The config file or bot token is missing or invalid.
    """
    from src.channels.adapters.telegram.adapter import TelegramAdapter

    return TelegramAdapter.from_config_file(config_path=config_path)


class AdapterRegistry:
    """Resolves which adapter ``slo channel run`` should host."""

    _BUILTINS: dict[str, Callable[..., ChannelAdapter]] = {"telegram": _build_telegram}

    @classmethod
    def builtin_names(cls) -> tuple[str, ...]:
        """Return the names of the built-in adapters.

        Returns:
            tuple[str, ...]: e.g. ``("telegram",)``.
        """
        return tuple(cls._BUILTINS)

    @classmethod
    def load(
        cls,
        *,
        builtin: Optional[str] = None,
        reference: Optional[str] = None,
        config_path: Optional[Path] = None,
    ) -> ChannelAdapter:
        """Build exactly one adapter: a built-in by name, or a ``module:Class`` reference.

        Args:
            builtin (Optional[str]): Built-in adapter name, e.g. ``telegram``.
            reference (Optional[str]): Custom adapter, ``pkg.module:ClassName``.
            config_path (Optional[Path]): Config file for a built-in adapter.

        Returns:
            ChannelAdapter: The built adapter.

        Raises:
            AdapterConfigError: Neither or both choices were given, the name is
                unknown, the reference cannot be loaded or built, or the built
                object does not implement ``ChannelAdapter``.
        """
        if (builtin is None) == (reference is None):
            raise AdapterConfigError("choose exactly one adapter: a built-in name or --adapter module:Class")
        if builtin is not None:
            return cls._load_builtin(name=builtin, config_path=config_path)
        if config_path is not None:
            raise AdapterConfigError("--config applies to built-in adapters only")
        assert reference is not None
        return cls._load_reference(reference=reference)

    @classmethod
    def _load_builtin(cls, *, name: str, config_path: Optional[Path]) -> ChannelAdapter:
        """Build one built-in adapter.

        Args:
            name (str): Built-in name.
            config_path (Optional[Path]): Its config file, or ``None`` for the default.

        Returns:
            ChannelAdapter: The built adapter.

        Raises:
            AdapterConfigError: Unknown name or invalid configuration.
        """
        factory: Optional[Callable[..., ChannelAdapter]] = cls._BUILTINS.get(name)
        if factory is None:
            raise AdapterConfigError(
                f"unknown adapter {name!r}; built-in adapters: {', '.join(cls.builtin_names())} "
                "(or use --adapter module:Class)"
            )
        return factory(config_path=config_path)

    @classmethod
    def _load_reference(cls, *, reference: str) -> ChannelAdapter:
        """Import ``module:Class``, build it with no arguments and check the protocol.

        Args:
            reference (str): ``pkg.module:ClassName``.

        Returns:
            ChannelAdapter: The built adapter.

        Raises:
            AdapterConfigError: Any import, lookup, build or protocol failure.
        """
        module_name, separator, class_name = reference.partition(":")
        if not separator or not module_name or not class_name:
            raise AdapterConfigError(f"adapter reference {reference!r} must look like module:Class")
        adapter_class: type = cls._import_class(module_name=module_name, class_name=class_name)
        try:
            adapter: object = adapter_class()
        except Exception as exc:  # noqa: BLE001 — any constructor failure is a config error
            raise AdapterConfigError(f"adapter {reference} could not be built: {type(exc).__name__}: {exc}")
        cls._ensure_adapter(reference=reference, adapter=adapter)
        return adapter  # type: ignore[return-value]  # checked by _ensure_adapter

    @classmethod
    def _import_class(cls, *, module_name: str, class_name: str) -> type:
        """Import one module (current directory appended to ``sys.path``) and fetch a class.

        Args:
            module_name (str): Dotted module path.
            class_name (str): Attribute naming the adapter class.

        Returns:
            type: The adapter class.

        Raises:
            AdapterConfigError: The module cannot be imported, or the attribute
                is missing or not a class.
        """
        working_directory: str = os.getcwd()
        if working_directory not in sys.path:
            sys.path.append(working_directory)
        try:
            module: ModuleType = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — any import failure is a config error
            raise AdapterConfigError(f"cannot import {module_name}: {type(exc).__name__}: {exc}")
        if not hasattr(module, class_name):
            raise AdapterConfigError(f"{module_name} has no attribute {class_name}")
        candidate: object = getattr(module, class_name)
        if not inspect.isclass(candidate):
            raise AdapterConfigError(f"{module_name}:{class_name} is not a class")
        return candidate

    @classmethod
    def _ensure_adapter(cls, *, reference: str, adapter: object) -> None:
        """Reject an object that does not implement the async adapter protocol.

        Args:
            reference (str): The reference, for the error message.
            adapter (object): The built object.

        Raises:
            AdapterConfigError: A protocol member is missing, or ``start``,
                ``deliver`` or ``stop`` is not ``async``.
        """
        if not isinstance(adapter, ChannelAdapter):
            raise AdapterConfigError(
                f"{reference} does not implement the ChannelAdapter protocol "
                "(kind, name, async start/deliver/stop)"
            )
        synchronous: list[str] = [
            method for method in _ADAPTER_METHODS if not inspect.iscoroutinefunction(getattr(adapter, method))
        ]
        if synchronous:
            raise AdapterConfigError(f"{reference}: {', '.join(synchronous)} must be async methods")
