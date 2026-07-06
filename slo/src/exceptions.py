"""Typed API exceptions raised from services and routers.

Routers and services raise these instead of returning a
``JSONResponse(FailureResponseDAO.build(...))`` inline. The handlers registered
in :func:`src.web_app._initialize_exception_handlers` translate every
:class:`ApiException` subclass to the standard envelope automatically.

Convention reference:
``awesome-agi/claude-md/code-prompts/build-routers.md`` § "router writes
the success path and **only** the success path".
"""


class ApiException(Exception):
    """Base class for all typed exceptions surfaced as HTTP responses.

    Carries the three attributes the central handler needs to build the
    failure envelope: a human-readable message, a machine-readable error
    code, and the HTTP status code.
    """

    def __init__(
        self,
        msg: str,
        code: str,
        http_error_code: int = 500,
    ) -> None:
        """Construct the exception.

        Args:
            msg (str): Human-readable error message — surfaces in
                ``errors.msg[0]``.
            code (str): Machine-readable error code — surfaces in
                ``errors.code``. Snake_case.
            http_error_code (int): HTTP status code. Defaults to 500.
        """
        super().__init__(msg)
        self.msg: str = msg
        self.code: str = code
        self.http_error_code: int = http_error_code


class NotFoundException(ApiException):
    """Resource not found (HTTP 404)."""

    def __init__(
        self,
        msg: str,
        code: str = "not_found",
        http_error_code: int = 404,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class BadRequestException(ApiException):
    """Bad request (HTTP 400)."""

    def __init__(
        self,
        msg: str,
        code: str = "bad_request",
        http_error_code: int = 400,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class UnauthorizedException(ApiException):
    """Authentication failure (HTTP 401)."""

    def __init__(
        self,
        msg: str,
        code: str = "error_unauthorized",
        http_error_code: int = 401,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class UnsupportedMediaTypeException(ApiException):
    """Unsupported media type (HTTP 415)."""

    def __init__(
        self,
        msg: str,
        code: str = "unsupported_media_type",
        http_error_code: int = 415,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class PayloadTooLargeException(ApiException):
    """Payload exceeds the configured upload cap (HTTP 413)."""

    def __init__(
        self,
        msg: str,
        code: str = "payload_too_large",
        http_error_code: int = 413,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class ValueErrorException(ApiException):
    """Validation / value error (HTTP 422)."""

    def __init__(
        self,
        msg: str,
        code: str = "unprocessable_entity",
        http_error_code: int = 422,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)


class InternalServerErrorException(ApiException):
    """Generic server error (HTTP 500)."""

    def __init__(
        self,
        msg: str,
        code: str = "internal_server_error",
        http_error_code: int = 500,
    ) -> None:
        super().__init__(msg=msg, code=code, http_error_code=http_error_code)
