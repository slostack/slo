"""Parse a priority-ordered model list into a ``ModelPoolDAO`` (37.a.4).

The operator-facing surface for opting a session into multi-model fallback is a
comma-separated **or JSON-array** priority-ordered list of model names, supplied
either via the ``SLO_MODEL_POOL`` environment variable or the persisted
``UserPreferencesDAO.default_model_pool`` preference.  This module is the single
place that list becomes a validated ``ModelPoolDAO``.

Accepted formats for ``SLO_MODEL_POOL``:

  Comma-list form  →  ``gpt-5.4,claude-opus-4-8,claude-sonnet-4-6``
  JSON-array form  →  ``["gpt-5.4","claude-opus-4-8","claude-sonnet-4-6"]``
  JSON-object form →  ``[{"model_name":"gpt-5.4"},{"model_name":"claude-opus-4-8"}]``

The JSON-object form passes raw dicts to ``ModelPoolEntryDAO`` so callers can
supply ``priority``, ``cooldown_seconds``, and ``rate_limit_cooldown_seconds``
explicitly.  When a JSON-object entry omits ``provider``, it is inferred via
``provider_for_model``, matching the existing comma-list behaviour.

Detection: if the stripped source starts with ``[`` the JSON path is used; any
parse error falls through to an ``ValueError`` with the original source quoted.

Imports of ``ModelPoolDAO`` / ``ModelPoolEntryDAO`` and ``provider_for_model``
are deferred into the function body to avoid an import cycle: ``provider_for_model``
imports ``src.agents.base``, which imports ``config.ai_model_config`` — pulling
those names in at module load would close that loop through the config layer.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Optional

from config.cfg import cfg
from config.logger import log_info

if TYPE_CHECKING:
    from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO

__all__ = ["parse_model_pool_config"]


def parse_model_pool_config(
    *,
    raw_value: Optional[str] = None,
    preference_value: Optional[str] = None,
) -> Optional["ModelPoolDAO"]:
    """Parse a priority-ordered model list into a ModelPoolDAO.

    Reads ``SLO_MODEL_POOL`` (or the explicit ``raw_value``) first, then the
    saved preference.  Accepts either a comma-separated list of model names or a
    JSON array of name strings / ``ModelPoolEntryDAO``-shaped objects.

    Returns ``None`` when no value is set or fewer than two members resolve (a
    pool needs >= 2).  In the single-member case it logs and returns ``None`` so
    the caller falls back to the single-model path.

    Args:
        raw_value (Optional[str]): Explicit override (tests). ``None`` reads
            ``cfg(key="SLO_MODEL_POOL")``.
        preference_value (Optional[str]): Saved preference fallback.

    Returns:
        Optional[ModelPoolDAO]: A validated pool, or ``None`` for the
            single-model path.

    Raises:
        ValueError: If a listed model name matches no known provider prefix, or
            if the source starts with ``[`` but is not valid JSON.
    """
    from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.provider_for_model import provider_for_model

    source: str = (
        (raw_value if raw_value is not None else cfg(key="SLO_MODEL_POOL"))
        or preference_value
        or ""
    ).strip()

    if not source:
        return None

    entries: list["ModelPoolEntryDAO"] = _parse_source(
        source=source,
        ModelPoolEntryDAO=ModelPoolEntryDAO,
        provider_for_model=provider_for_model,
    )
    if len(entries) < 2:
        if len(entries) == 1:
            log_info(
                msg="model_pool_config_single_member_ignored",
                model_name=entries[0].model_name,
            )
        return None
    return ModelPoolDAO(entries=entries)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_source(
    *,
    source: str,
    ModelPoolEntryDAO: type["ModelPoolEntryDAO"],
    provider_for_model: Callable[..., str],
) -> list["ModelPoolEntryDAO"]:
    """Dispatch to JSON or comma-list parser based on the leading character.

    Args:
        source (str): Stripped, non-empty pool source string.
        ModelPoolEntryDAO (type[ModelPoolEntryDAO]): Class used to build entry objects.
            Passed as a parameter to avoid a circular import at module load time.
        provider_for_model (Callable[..., str]): Callable to infer provider from
            a model name.  Passed as a parameter for the same reason.

    Returns:
        list[ModelPoolEntryDAO]: Parsed pool entries (may be empty or length 1).

    Raises:
        ValueError: If the source starts with ``[`` but is not valid JSON.
    """
    if source.startswith("["):
        return _parse_json_array(
            source=source,
            ModelPoolEntryDAO=ModelPoolEntryDAO,
            provider_for_model=provider_for_model,
        )
    return _parse_comma_list(
        source=source,
        ModelPoolEntryDAO=ModelPoolEntryDAO,
        provider_for_model=provider_for_model,
    )


def _parse_json_array(
    *,
    source: str,
    ModelPoolEntryDAO: type["ModelPoolEntryDAO"],
    provider_for_model: Callable[..., str],
) -> list["ModelPoolEntryDAO"]:
    """Parse a JSON-array model pool source.

    Supports two element shapes:
    - Plain string  →  treated as the model name.
    - Object dict   →  passed to ``ModelPoolEntryDAO`` with ``provider``
      inferred when absent and ``priority`` set to index when absent.

    Args:
        source (str): JSON array string starting with ``[``.
        ModelPoolEntryDAO (type[ModelPoolEntryDAO]): DAO class to construct entries.
        provider_for_model (Callable[..., str]): Callable to infer provider from
            a model name.

    Returns:
        list[ModelPoolEntryDAO]: Parsed entries.

    Raises:
        ValueError: If *source* is not valid JSON.
    """
    try:
        raw: list = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"SLO_MODEL_POOL looks like JSON but could not be parsed: {source!r}"
        ) from exc

    if not isinstance(raw, list):
        raise ValueError(
            f"SLO_MODEL_POOL JSON must be an array, got {type(raw).__name__}: {source!r}"
        )

    return [
        _entry_from_json_element(
            element=element,
            index=index,
            ModelPoolEntryDAO=ModelPoolEntryDAO,
            provider_for_model=provider_for_model,
        )
        for index, element in enumerate(raw)
    ]


def _entry_from_json_element(
    *,
    element: Any,
    index: int,
    ModelPoolEntryDAO: type["ModelPoolEntryDAO"],
    provider_for_model: Callable[..., str],
) -> "ModelPoolEntryDAO":
    """Coerce one JSON array element into a ``ModelPoolEntryDAO``.

    Args:
        element (Any): A parsed JSON value — either a string or a dict.
        index (int): Zero-based position used as the default priority.
        ModelPoolEntryDAO (type[ModelPoolEntryDAO]): DAO class to construct the entry.
        provider_for_model (Callable[..., str]): Callable to infer provider from
            a model name.

    Returns:
        ModelPoolEntryDAO: The constructed entry.

    Raises:
        ValueError: If *element* is neither a string nor a dict.
    """
    if isinstance(element, str):
        return ModelPoolEntryDAO(
            model_name=element,
            provider=provider_for_model(model_name=element),
            priority=index,
        )
    if isinstance(element, dict):
        return _entry_from_dict(
            data=element,
            index=index,
            ModelPoolEntryDAO=ModelPoolEntryDAO,
            provider_for_model=provider_for_model,
        )
    raise ValueError(
        f"SLO_MODEL_POOL JSON array element at index {index} must be a string or "
        f"object, got {type(element).__name__!r}"
    )


def _entry_from_dict(
    *,
    data: dict,
    index: int,
    ModelPoolEntryDAO: type["ModelPoolEntryDAO"],
    provider_for_model: Callable[..., str],
) -> "ModelPoolEntryDAO":
    """Build a ``ModelPoolEntryDAO`` from a dict, inferring missing fields.

    Args:
        data (dict): Parsed object from the JSON array.
        index (int): Zero-based position used as the default priority.
        ModelPoolEntryDAO (type[ModelPoolEntryDAO]): DAO class to construct the entry.
        provider_for_model (Callable[..., str]): Callable to infer provider from
            a model name.

    Returns:
        ModelPoolEntryDAO: The constructed entry.

    Raises:
        ValueError: If ``model_name`` is absent from *data*.
    """
    model_name: Optional[str] = data.get("model_name")
    if not model_name:
        raise ValueError(
            f"SLO_MODEL_POOL JSON object at index {index} is missing 'model_name': {data!r}"
        )
    kwargs: dict = dict(data)
    if "provider" not in kwargs:
        kwargs["provider"] = provider_for_model(model_name=model_name)
    if "priority" not in kwargs:
        kwargs["priority"] = index
    return ModelPoolEntryDAO(**kwargs)


def _parse_comma_list(
    *,
    source: str,
    ModelPoolEntryDAO: type["ModelPoolEntryDAO"],
    provider_for_model: Callable[..., str],
) -> list["ModelPoolEntryDAO"]:
    """Parse a comma-separated model name list into pool entries.

    Args:
        source (str): Comma-delimited model name string.
        ModelPoolEntryDAO (type[ModelPoolEntryDAO]): DAO class to construct entries.
        provider_for_model (Callable[..., str]): Callable to infer provider from
            a model name.

    Returns:
        list[ModelPoolEntryDAO]: Parsed entries (may be empty or length 1).
    """
    names: list[str] = [name.strip() for name in source.split(",") if name.strip()]
    return [
        ModelPoolEntryDAO(
            model_name=name,
            provider=provider_for_model(model_name=name),
            priority=index,
        )
        for index, name in enumerate(names)
    ]
