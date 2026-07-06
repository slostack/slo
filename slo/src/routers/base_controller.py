"""Shared response envelope helpers for every API route.

Every router lands its success payload through
``SuccessResponseDAO.build`` and every failure flows through the central
exception handlers in ``src.web_app._initialize_exception_handlers``
(which call ``FailureResponseDAO.build`` internally). Routers MUST NOT
inline ``JSONResponse(FailureResponseDAO.build(...))`` — that duplicates
envelope construction and drifts away from the standard shape over time.

Mirrors lattice's ``src/routers/base_controller.py`` 1:1.
"""
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict


__all__ = ["FailureResponseDAO", "ResponseErrorsDAO", "SuccessResponseDAO"]


T = TypeVar("T")

API_VERSION: str = "1.0"


class ResponseErrorsDAO(BaseModel):
    """Standard error payload included in every API response."""

    msg: List[str] = []
    code: Optional[str] = None

    model_config = ConfigDict(
        title="errors",
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )


class SuccessResponseDAO(BaseModel, Generic[T]):
    """Standard wrapper for successful API responses."""

    data: Optional[Any] = {}
    api_version: str = API_VERSION
    errors: ResponseErrorsDAO = ResponseErrorsDAO()

    model_config = ConfigDict(
        title="success_response",
        arbitrary_types_allowed=True,
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )

    @classmethod
    def build(
        cls,
        *,
        payload: Any,
        api_version: str = API_VERSION,
        errors: Optional[ResponseErrorsDAO] = None,
    ) -> Dict[str, Any]:
        """Build a JSON-serializable success response dict.

        Args:
            payload (Any): The primary data to include in the response.
            api_version (str, optional): API version string. Defaults to ``"1.0"``.
            errors (Optional[ResponseErrorsDAO], optional): Error payload.
                Defaults to an empty ``ResponseErrorsDAO``.

        Returns:
            Dict[str, Any]: JSON-encodable response dict.
        """
        resolved_errors: ResponseErrorsDAO = errors if errors else ResponseErrorsDAO()
        success_response_dao: "SuccessResponseDAO" = cls(
            api_version=api_version,
            data=payload,
            errors=resolved_errors,
        )
        return jsonable_encoder(success_response_dao)


class FailureResponseDAO(BaseModel, Generic[T]):
    """Standard wrapper for failed API responses."""

    data: Optional[Any] = {}
    api_version: str = API_VERSION
    errors: ResponseErrorsDAO

    model_config = ConfigDict(
        title="failure_response",
        arbitrary_types_allowed=True,
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )

    @classmethod
    def build(
        cls,
        *,
        error_code: str,
        errors: Optional[List[str]] = None,
        payload: Optional[Any] = None,
        api_version: str = API_VERSION,
    ) -> Dict[str, Any]:
        """Build a JSON-serializable failure response dict.

        Args:
            error_code (str): Machine-readable error code.
            errors (Optional[List[str]], optional): Human-readable error
                messages. Defaults to an empty list.
            payload (Optional[Any], optional): Additional data. Defaults to
                an empty dict.
            api_version (str, optional): API version string. Defaults to ``"1.0"``.

        Returns:
            Dict[str, Any]: JSON-encodable response dict.
        """
        failure_response_dao: "FailureResponseDAO" = cls(
            api_version=api_version,
            data=payload if payload is not None else {},
            errors=ResponseErrorsDAO(
                msg=errors if errors is not None else [],
                code=error_code,
            ),
        )
        return jsonable_encoder(failure_response_dao)
