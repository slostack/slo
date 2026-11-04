"""Validate and detach portable tool inventories before native admission."""

import json
from copy import deepcopy
from typing import ClassVar, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from .dao import ClaudeToolDefinitionDAO
from .exceptions import ClaudeBridgeError


class _InitializedMcpServerDAO(BaseModel):
    """Relevant pinned init server fields; source was absent on older CLIs."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    name: str
    status: Literal["connected"]
    source: Literal["sdk"] = "sdk"


class _InitializedInventoryDAO(BaseModel):
    """Validate relevant metadata only, not unrelated native capability fields."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    session_id: str = Field(min_length=1, max_length=256)
    tools: list[str]
    mcp_servers: list[_InitializedMcpServerDAO]
    skills: list[str]
    plugins: list[JsonValue]


class ClaudeToolInventory:
    """Own raw-schema admission without importing host tool implementations."""

    NAMES: ClassVar[frozenset[str]] = frozenset({"read", "grep", "find", "ls"})
    _SCHEMA_MAPS: ClassVar[frozenset[str]] = frozenset(
        {"$defs", "definitions", "properties", "patternProperties", "dependentSchemas"}
    )
    _SCHEMA_LISTS: ClassVar[frozenset[str]] = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
    _SCHEMAS: ClassVar[frozenset[str]] = frozenset(
        {
            "additionalProperties",
            "unevaluatedProperties",
            "propertyNames",
            "items",
            "contains",
            "unevaluatedItems",
            "not",
            "if",
            "then",
            "else",
            "additionalItems",
        }
    )

    @classmethod
    def freeze(cls, *, tools: tuple[ClaudeToolDefinitionDAO, ...]) -> tuple[ClaudeToolDefinitionDAO, ...]:
        """Return independently owned definitions or reject invalid names/schemas.

        Portable callers may offer a read-only subset; the host additionally
        requires its complete canonical bundle. No I/O or reference fetching occurs.
        """
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names) or not set(names).issubset(cls.NAMES):
            raise ValueError("Invalid Claude tool inventory.")
        return tuple(
            ClaudeToolDefinitionDAO(
                name=tool.name,
                description=tool.description,
                input_schema=cls._normalize_schema(schema=tool.input_schema),
            )
            for tool in tools
        )

    @classmethod
    def validate_initialization(
        cls,
        *,
        metadata: dict[str, object],
        tools: tuple[ClaudeToolDefinitionDAO, ...],
    ) -> str:
        """Require the exact advertised inventory before any response publication.

        The pinned SDK's system/init parser retains but does not validate these
        fields. Optional server source may be absent; capabilities are an open
        set and irrelevant here. A valid frame is not proof of source suppression.

        Returns:
            str: Native session association for the response scope validator.

        Raises:
            ClaudeBridgeError: Missing, malformed or unexpected initialized inventory.
        """
        try:
            initialized = _InitializedInventoryDAO.model_validate(metadata)
        except ValidationError:
            raise cls.initialization_error() from None
        expected_tools = {f"mcp__slo__{tool.name}" for tool in tools}
        expected_servers = ["slo"] if tools else []
        if (
            len(initialized.tools) != len(expected_tools)
            or set(initialized.tools) != expected_tools
            or [server.name for server in initialized.mcp_servers] != expected_servers
            or initialized.skills
            or initialized.plugins
        ):
            raise cls.initialization_error()
        return initialized.session_id

    @staticmethod
    def initialization_error() -> ClaudeBridgeError:
        """Build bounded diagnostics without raw native names or private paths."""
        return ClaudeBridgeError(
            code="stream_protocol_failed",
            safe_message="Claude initialized inventory is missing or unexpected.",
        )

    @classmethod
    def _normalize_schema(cls, *, schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Check object schemas and expand local references without dropping siblings."""
        try:
            json.dumps(obj=schema, allow_nan=False)
            Draft202012Validator.check_schema(schema)
            normalized = cls._expand_schema(schema=deepcopy(schema), root=schema, references=())
            if not isinstance(normalized, dict) or normalized.get("type") != "object":
                raise ValueError("Claude tool schema must have an object root.")
            Draft202012Validator.check_schema(normalized)
            return normalized
        except (SchemaError, RecursionError):
            raise ValueError("Invalid Claude tool schema.") from None

    @classmethod
    def _expand_schema(
        cls,
        *,
        schema: JsonValue,
        root: dict[str, JsonValue],
        references: tuple[str, ...],
    ) -> JsonValue:
        """Walk schema positions only; defaults/examples are uninterpreted JSON."""
        if isinstance(schema, bool):
            return schema
        if not isinstance(schema, dict):
            raise ValueError("Invalid Claude tool schema.")
        if "$schema" in schema and schema["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("Unsupported Claude schema dialect.")
        if any(
            key in schema
            for key in (
                "$id",
                "$anchor",
                "$dynamicRef",
                "$dynamicAnchor",
                "$recursiveRef",
                "$recursiveAnchor",
            )
        ):
            raise ValueError("Unsupported Claude schema reference scope.")
        if "$ref" in schema:
            return cls._expand_reference(schema=schema, root=root, references=references)
        expanded = deepcopy(schema)
        for key, value in schema.items():
            if key in cls._SCHEMA_MAPS and isinstance(value, dict):
                expanded[key] = {
                    name: cls._expand_schema(schema=child, root=root, references=references)
                    for name, child in value.items()
                }
            elif key in cls._SCHEMA_LISTS and isinstance(value, list):
                expanded[key] = [
                    cls._expand_schema(schema=child, root=root, references=references) for child in value
                ]
            elif key in cls._SCHEMAS:
                expanded[key] = cls._expand_schema(schema=value, root=root, references=references)
        return expanded

    @classmethod
    def _expand_reference(
        cls,
        *,
        schema: dict[str, JsonValue],
        root: dict[str, JsonValue],
        references: tuple[str, ...],
    ) -> JsonValue:
        """Intersect resolved references with siblings; never overwrite constraints."""
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/") or reference in references:
            raise ValueError("Unsupported Claude schema reference.")
        resolved: JsonValue = root
        for segment in reference[2:].split("/"):
            key = segment.replace("~1", "/").replace("~0", "~")
            if not isinstance(resolved, dict) or key not in resolved:
                raise ValueError("Unresolved Claude schema reference.")
            resolved = resolved[key]
        expanded = cls._expand_schema(schema=resolved, root=root, references=(*references, reference))
        siblings = cls._expand_schema(
            schema={key: value for key, value in schema.items() if key != "$ref"},
            root=root,
            references=references,
        )
        return {"allOf": [expanded, siblings]} if siblings else expanded
