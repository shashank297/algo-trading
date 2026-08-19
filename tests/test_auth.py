"""Unit tests for SmartAPI authentication."""

from __future__ import annotations

import base64
import json
import time
import unittest
from unittest.mock import Mock, patch

import requests

from smartapi.auth import SmartAPIAuth


def build_jwt(expiry_timestamp: int) -> str:
    """Build a lightweight unsigned JWT for expiry testing.

    Args:
        expiry_timestamp: Unix timestamp to place in the exp claim.

    Returns:
        str: JWT-like string suitable for local expiry parsing.
    """

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode("utf-8")).decode("utf-8").rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry_timestamp}).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{header}.{payload}.signature"


class SmartAPIAuthTests(unittest.TestCase):
    """Test SmartAPI authentication and token refresh behavior."""

    def setUp(self) -> None:
        """Create a reusable SmartAPI config for each test."""

        self.config = {
            "smartapi": {
                "api_key": "api-key",
                "client_code": "client-code",
                "pin": "1234",
                "totp_secret": "JBSWY3DPEHPK3PXP",
                "base_url": "https://apiconnect.angelone.in",
                "instrument_master_url": "https://example.com/master.json",
            },
        }

    @patch("smartapi.auth.pyotp.TOTP")
    @patch("smartapi.auth.requests.Session.post")
    def test_login_success_stores_tokens(self, post_mock: Mock, totp_mock: Mock) -> None:
        """Login should cache the returned JWT, refresh token, and feed token."""

        totp_mock.return_value.now.return_value = "123456"
        post_mock.return_value.json.return_value = {
            "status": True,
            "data": {
                "jwtToken": "jwt-token",
                "refreshToken": "refresh-token",
                "feedToken": "feed-token",
            },
        }

        auth = SmartAPIAuth(self.config)
        with patch.object(auth, "_get_local_ip", return_value="127.0.0.1"), patch.object(
            auth,
            "_get_public_ip",
            return_value="1.1.1.1",
        ), patch.object(auth, "_get_mac_address", return_value="AA:BB:CC:DD:EE:FF"):
            result = auth.login()

        self.assertTrue(result)
        self.assertEqual(auth.jwt_token, "jwt-token")
        self.assertEqual(auth._refresh_token_value, "refresh-token")
        self.assertEqual(auth.feed_token, "feed-token")

    @patch("smartapi.auth.pyotp.TOTP")
    @patch("smartapi.auth.requests.Session.post")
    def test_login_failure_raises_runtime_error(self, post_mock: Mock, totp_mock: Mock) -> None:
        """Login failure should raise a RuntimeError with the API error details."""

        totp_mock.return_value.now.return_value = "123456"
        post_mock.return_value.json.return_value = {
            "status": False,
            "errorcode": "AB9999",
            "message": "Invalid TOTP",
        }

        auth = SmartAPIAuth(self.config)
        with patch.object(auth, "_get_local_ip", return_value="127.0.0.1"), patch.object(
            auth,
            "_get_public_ip",
            return_value="1.1.1.1",
        ), patch.object(auth, "_get_mac_address", return_value="AA:BB:CC:DD:EE:FF"):
            with self.assertRaises(RuntimeError):
                auth.login()

    @patch("smartapi.auth.requests.get")
    def test_public_ip_failure_falls_back_to_zero_ip(self, get_mock: Mock) -> None:
        """Public IP lookup failure should fall back to 0.0.0.0."""

        get_mock.side_effect = requests.RequestException("network issue")
        auth = SmartAPIAuth(self.config)
        self.assertEqual(auth._get_public_ip(), "0.0.0.0")

    def test_is_token_valid_detects_expiry_window(self) -> None:
        """Tokens expiring within five minutes should be treated as invalid."""

        auth = SmartAPIAuth(self.config)
        auth.jwt_token = build_jwt(int(time.time()) + 600)
        self.assertTrue(auth.is_token_valid())

        auth.jwt_token = build_jwt(int(time.time()) + 120)
        self.assertFalse(auth.is_token_valid())

    @patch("smartapi.auth.requests.Session.post")
    def test_get_headers_refreshes_expired_token(self, post_mock: Mock) -> None:
        """Authenticated headers should trigger token refresh when the JWT is stale."""

        post_mock.return_value.json.return_value = {
            "status": True,
            "data": {
                "jwtToken": "new-jwt-token",
                "refreshToken": "new-refresh-token",
                "feedToken": "new-feed-token",
            },
        }

        auth = SmartAPIAuth(self.config)
        auth.jwt_token = build_jwt(int(time.time()) - 30)
        auth._refresh_token_value = "old-refresh-token"

        with patch.object(auth, "_get_local_ip", return_value="127.0.0.1"), patch.object(
            auth,
            "_get_public_ip",
            return_value="1.1.1.1",
        ), patch.object(auth, "_get_mac_address", return_value="AA:BB:CC:DD:EE:FF"):
            headers = auth.get_headers()

        self.assertEqual(headers["Authorization"], "Bearer new-jwt-token")
        self.assertEqual(auth._refresh_token_value, "new-refresh-token")

    def test_post_rejects_http_errors(self) -> None:
        """Authentication must not parse an HTTP error as a successful response."""

        auth = SmartAPIAuth(self.config)
        response = Mock(status_code=503)
        response.raise_for_status.side_effect = requests.HTTPError("service unavailable")
        auth.session.post = Mock(return_value=response)

        with self.assertRaises(RuntimeError):
            auth._post("/login", {}, {})


if __name__ == "__main__":
    unittest.main()
