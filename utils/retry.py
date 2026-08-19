"""Retry helpers for transient SmartAPI and authentication failures."""

from __future__ import annotations

from typing import Any, Callable, TypeVar, cast

import requests
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

TRANSIENT_HTTP_CODES = [403, 429, 500, 502, 503, 504]
PERMANENT_API_ERRORS = [
    "AB1009",
    "AB1008",
    "AB1012",
]
TOKEN_EXPIRY_ERRORS = [
    "AG8001",
    "AG8002",
]

F = TypeVar("F", bound=Callable[..., Any])


class SmartAPIRequestError(Exception):
    """Base exception for SmartAPI request failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        """Initialize the SmartAPI request error.

        Args:
            message: Human-readable exception message.
            status_code: Optional HTTP status code.
            error_code: Optional SmartAPI error code.
        """

        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class TransientAPIError(SmartAPIRequestError):
    """Exception raised for retryable SmartAPI failures."""


class PermanentAPIError(SmartAPIRequestError):
    """Exception raised for permanent SmartAPI failures."""


class AuthTokenError(SmartAPIRequestError):
    """Exception raised when the access token is invalid or expired."""


def _log_transient_retry(retry_state: Any) -> None:
    """Log a transient retry attempt."""

    logger.warning(
        "Retry attempt {} for {}",
        retry_state.attempt_number,
        retry_state.fn.__name__,
    )


def _resolve_auth_client(instance: Any) -> Any | None:
    """Resolve an auth client from a decorated bound method instance."""

    if instance is None:
        return None
    if hasattr(instance, "refresh_token") and callable(instance.refresh_token):
        return instance
    return getattr(instance, "auth", None)


def _refresh_auth_before_retry(retry_state: Any) -> None:
    """Refresh the SmartAPI token before an auth retry."""

    instance = retry_state.args[0] if retry_state.args else None
    auth_client = _resolve_auth_client(instance)

    logger.warning(
        "Auth retry attempt {} for {}",
        retry_state.attempt_number,
        retry_state.fn.__name__,
    )

    if auth_client is None or not callable(getattr(auth_client, "refresh_token", None)):
        logger.error("Unable to resolve auth client for token refresh retry.")
        return

    try:
        auth_client.refresh_token()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.exception("Token refresh failed before retry: {}", exc)
        raise


def _configured_retry_attempts(retry_state: Any) -> int:
    """Read retry attempts from the bound client, with a safe default."""

    instance = retry_state.args[0] if retry_state.args else None
    value = getattr(instance, "retry_max_attempts", 5)
    return retry_state.attempt_number >= max(int(value), 1)


def _configured_retry_wait(retry_state: Any) -> float:
    """Calculate exponential backoff from the bound client's configuration."""

    instance = retry_state.args[0] if retry_state.args else None
    multiplier = max(float(getattr(instance, "retry_wait_seconds", 2)), 0.0)
    maximum = max(float(getattr(instance, "retry_max_wait_seconds", 30)), 0.0)
    return min(multiplier * (2 ** max(retry_state.attempt_number - 1, 0)), maximum)


def retry_transient(func: F) -> F:
    """Retry transient network and SmartAPI failures with exponential backoff."""

    decorated = retry(
        retry=retry_if_exception_type(
            (requests.Timeout, requests.ConnectionError, TransientAPIError),
        ),
        wait=_configured_retry_wait,
        stop=_configured_retry_attempts,
        before_sleep=_log_transient_retry,
        reraise=True,
    )(func)
    return cast(F, decorated)


def retry_auth(func: F) -> F:
    """Retry token-expiry failures after refreshing the access token."""

    decorated = retry(
        retry=retry_if_exception_type(AuthTokenError),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=0, max=1),
        before_sleep=_refresh_auth_before_retry,
        reraise=True,
    )(func)
    return cast(F, decorated)
