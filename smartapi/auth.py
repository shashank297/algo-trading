"""Authentication client for Angel One SmartAPI."""

from __future__ import annotations

import base64
import json
import socket
import time
import uuid
import threading
from typing import Any

import pyotp
import requests
from loguru import logger


class SmartAPIAuth:
    """Manage SmartAPI login, token refresh, and request headers."""

    LOGIN_ENDPOINT = "/rest/auth/angelbroking/user/v1/loginByPassword"
    REFRESH_ENDPOINT = "/rest/auth/angelbroking/jwt/v1/generateTokens"
    PUBLIC_IP_URL = "https://api.ipify.org"
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the SmartAPI authentication client.

        Args:
            config: Full application configuration dictionary.
        """

        smartapi_config = config["smartapi"]
        self.api_key: str = smartapi_config["api_key"]
        self.client_code: str = smartapi_config["client_code"]
        self.pin: str = smartapi_config["pin"]
        self.totp_secret: str = smartapi_config["totp_secret"]
        self.base_url: str = smartapi_config["base_url"].rstrip("/")
        self.jwt_token: str | None = None
        self._refresh_token_value: str | None = None
        self.feed_token: str | None = None
        self.session = requests.Session()
        self._local_ip: str | None = None
        self._public_ip: str | None = None
        self._mac_address: str | None = None
        self._auth_lock = threading.Lock()

    def login(self) -> bool:
        """Authenticate with SmartAPI using client code, PIN, and TOTP.

        Returns:
            bool: True when login succeeds.

        Raises:
            RuntimeError: If authentication fails.
        """

        with self._auth_lock:
            payload = {
                "clientcode": self.client_code,
                "password": self.pin,
                "totp": pyotp.TOTP(self.totp_secret).now(),
            }
    
            response_payload = self._post(self.LOGIN_ENDPOINT, payload, self._build_base_headers())
            if not response_payload.get("status", False):
                error_code = response_payload.get("errorcode") or response_payload.get("errorCode")
                message = response_payload.get("message", "Unknown login error")
                logger.error("Login failed for client {}: {} - {}", self._masked_client_code(), error_code, message)
                raise RuntimeError(f"SmartAPI login failed: {error_code} - {message}")
    
            data = response_payload.get("data") or {}
            self.jwt_token = data.get("jwtToken")
            self._refresh_token_value = data.get("refreshToken")
            self.feed_token = data.get("feedToken")
            logger.info("✅ Login successful for client: {}", self._masked_client_code())
            return True

    def refresh_token(self) -> bool:
        """Refresh SmartAPI tokens using the cached refresh token.

        Returns:
            bool: True when the refresh succeeds.

        Raises:
            RuntimeError: If the refresh fails.
        """

        with self._auth_lock:
            if not self._refresh_token_value:
                logger.error("Refresh token unavailable. Please log in again.")
                raise RuntimeError("SmartAPI refresh token is not available.")
    
            payload = {"refreshToken": self._refresh_token_value}
            response_payload = self._post(self.REFRESH_ENDPOINT, payload, self._build_base_headers())
            if not response_payload.get("status", False):
                error_code = response_payload.get("errorcode") or response_payload.get("errorCode")
                message = response_payload.get("message", "Unknown token refresh error")
                logger.error("Token refresh failed: {} - {}", error_code, message)
                raise RuntimeError(f"SmartAPI token refresh failed: {error_code} - {message}")
    
            data = response_payload.get("data") or {}
            self.jwt_token = data.get("jwtToken", self.jwt_token)
            self.feed_token = data.get("feedToken", self.feed_token)
            self._refresh_token_value = data.get("refreshToken", self._refresh_token_value)
            logger.info("✅ Token refresh successful for client: {}", self._masked_client_code())
            return True

    def is_token_valid(self) -> bool:
        """Return whether the JWT token is valid for at least five more minutes."""

        if not self.jwt_token:
            return False

        try:
            payload_part = self.jwt_token.split(".")[1]
            payload_part += "=" * (-len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("utf-8")).decode("utf-8"))
            exp = int(payload["exp"])
            return exp > int(time.time()) + 300
        except Exception as exc:
            logger.warning("Unable to decode JWT token expiry: {}", exc)
            return False

    def get_headers(self) -> dict[str, str]:
        """Return authenticated request headers, refreshing the token when needed.

        Returns:
            dict[str, str]: Authenticated SmartAPI headers.
        """

        if not self.is_token_valid():
            self.refresh_token()

        headers = self._build_base_headers()
        if self.jwt_token:
            headers["Authorization"] = self.websocket_authorization
        return headers

    @property
    def websocket_authorization(self) -> str:
        """Return formatted WebSocket authorization header string ('Bearer <JWT>').

        Guarantees 'Bearer <JWT>' format exactly once without duplication.
        """
        if not self.jwt_token:
            return ""
        raw_jwt = self.jwt_token.strip()
        if raw_jwt.lower().startswith("bearer "):
            return f"Bearer {raw_jwt[7:].strip()}"
        return f"Bearer {raw_jwt}"


    def _build_base_headers(self) -> dict[str, str]:
        """Build SmartAPI base headers with cached network metadata.

        Returns:
            dict[str, str]: Base SmartAPI headers.
        """

        if self._local_ip is None:
            self._local_ip = self._get_local_ip()
        if self._public_ip is None:
            self._public_ip = self._get_public_ip()
        if self._mac_address is None:
            self._mac_address = self._get_mac_address()

        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-PrivateKey": self.api_key,
            "X-ClientLocalIP": self._local_ip,
            "X-ClientPublicIP": self._public_ip,
            "X-MACAddress": self._mac_address,
        }

    def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Send a JSON POST request to SmartAPI.

        Args:
            endpoint: Endpoint path relative to the base URL.
            payload: Request payload.
            headers: Request headers.

        Returns:
            dict[str, Any]: Parsed JSON response.

        Raises:
            RuntimeError: If the HTTP request or JSON parsing fails.
        """

        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.error("SmartAPI POST request failed for {}: {}", endpoint, type(exc).__name__)
            raise RuntimeError(f"SmartAPI request failed for {endpoint}") from exc

        status_code = getattr(response, "status_code", 200)
        if isinstance(status_code, int) and status_code >= 400:
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                logger.error("SmartAPI returned HTTP {} for {}", status_code, endpoint)
                raise RuntimeError(f"SmartAPI HTTP request failed for {endpoint}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("SmartAPI returned a non-JSON response for {}", endpoint)
            raise RuntimeError(f"SmartAPI returned invalid JSON for {endpoint}") from exc

        if not isinstance(payload, dict):
            logger.error("SmartAPI returned an unexpected JSON shape for {}", endpoint)
            raise RuntimeError(f"SmartAPI returned an invalid response for {endpoint}")
        return payload

    def _get_local_ip(self) -> str:
        """Return the local IP address for this machine."""

        return socket.gethostbyname(socket.gethostname())

    def _get_public_ip(self) -> str:
        """Return the public IP address or a safe fallback."""

        try:
            response = requests.get(self.PUBLIC_IP_URL, timeout=5)
            response.raise_for_status()
            return response.text.strip()
        except requests.RequestException as exc:
            logger.warning("Failed to resolve public IP address: {}", exc)
            return "0.0.0.0"

    def _get_mac_address(self) -> str:
        """Return the machine MAC address in colon-separated format."""

        mac_value = uuid.getnode()
        hex_value = f"{mac_value:012x}"
        return ":".join(hex_value[index : index + 2].upper() for index in range(0, 12, 2))

    def _masked_client_code(self) -> str:
        """Return a non-secret identifier suitable for operational logs."""

        if len(self.client_code) <= 4:
            return "****"
        return f"{self.client_code[:2]}***{self.client_code[-2:]}"
