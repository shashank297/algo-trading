"""Unit tests for SubscriptionRegistry and quota enforcement."""

from __future__ import annotations

import unittest

from data_platform.contracts import LiveTickerMode
from smartapi.subscription_registry import SubscriptionKey, SubscriptionRegistry


class TestSubscriptionRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SubscriptionRegistry()

    def test_single_subscription_and_duplicate_handling(self) -> None:
        key = SubscriptionKey(mode=LiveTickerMode.LTP, exchange_type=1, token="2885")
        added = self.registry.validate_and_add([key])
        self.assertEqual(len(added), 1)
        self.assertEqual(self.registry.total_count, 1)

        # Adding same key again is idempotent (returns empty list of newly added keys)
        added_again = self.registry.validate_and_add([key])
        self.assertEqual(len(added_again), 0)
        self.assertEqual(self.registry.total_count, 1)

    def test_multi_mode_subscription_counting(self) -> None:
        """Same token under multiple modes counts as distinct logical subscriptions."""
        key_ltp = SubscriptionKey(mode=LiveTickerMode.LTP, exchange_type=1, token="2885")
        key_quote = SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token="2885")
        key_snap = SubscriptionKey(mode=LiveTickerMode.SNAP_QUOTE, exchange_type=1, token="2885")

        added = self.registry.validate_and_add([key_ltp, key_quote, key_snap])
        self.assertEqual(len(added), 3)
        self.assertEqual(self.registry.total_count, 3)

    def test_batching_payload_boundaries_499_500_501(self) -> None:
        """Verify action payload batching splits tokens into 500-sized chunks."""
        # 499 tokens -> 1 payload batch
        keys_499 = [
            SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token=str(1000 + i))
            for i in range(499)
        ]
        payloads_499 = self.registry.build_action_payloads(keys_499, action=1)
        self.assertEqual(len(payloads_499), 1)
        self.assertEqual(len(payloads_499[0]["params"]["tokenList"][0]["tokens"]), 499)

        # 500 tokens -> 1 payload batch
        keys_500 = [
            SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token=str(1000 + i))
            for i in range(500)
        ]
        payloads_500 = self.registry.build_action_payloads(keys_500, action=1)
        self.assertEqual(len(payloads_500), 1)
        self.assertEqual(len(payloads_500[0]["params"]["tokenList"][0]["tokens"]), 500)

        # 501 tokens -> 2 payload batches (500 + 1)
        keys_501 = [
            SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token=str(1000 + i))
            for i in range(501)
        ]
        payloads_501 = self.registry.build_action_payloads(keys_501, action=1)
        self.assertEqual(len(payloads_501), 2)
        self.assertEqual(len(payloads_501[0]["params"]["tokenList"][0]["tokens"]), 500)
        self.assertEqual(len(payloads_501[1]["params"]["tokenList"][0]["tokens"]), 1)

    def test_session_quota_1000_limit(self) -> None:
        """Total subscriptions capped at 1000 per session."""
        keys_1000 = [
            SubscriptionKey(mode=LiveTickerMode.LTP, exchange_type=1, token=str(1000 + i))
            for i in range(1000)
        ]
        self.registry.validate_and_add(keys_1000)
        self.assertEqual(self.registry.total_count, 1000)

        # 1001th subscription must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            self.registry.validate_and_add([SubscriptionKey(mode=LiveTickerMode.LTP, exchange_type=1, token="99999")])
        self.assertIn("Subscription limit exceeded", str(ctx.exception))

    def test_depth_mode_50_limit_and_nse_cm_restriction(self) -> None:
        """DEPTH mode allows maximum 50 tokens and only NSE_CM (exchange_type 1)."""
        # Non-NSE_CM rejection (e.g. exchange_type=2 NSE_FO)
        with self.assertRaises(ValueError) as ctx:
            self.registry.validate_and_add([SubscriptionKey(mode=LiveTickerMode.DEPTH, exchange_type=2, token="FUT1")])
        self.assertIn("DEPTH mode (Mode 4) is only supported on NSE_CM", str(ctx.exception))

        # 50 DEPTH subscriptions allowed on NSE_CM
        depth_50 = [
            SubscriptionKey(mode=LiveTickerMode.DEPTH, exchange_type=1, token=str(2000 + i))
            for i in range(50)
        ]
        self.registry.validate_and_add(depth_50)
        self.assertEqual(self.registry.depth_count, 50)

        # 51st DEPTH subscription rejected
        with self.assertRaises(ValueError) as ctx:
            self.registry.validate_and_add([SubscriptionKey(mode=LiveTickerMode.DEPTH, exchange_type=1, token="2999")])
        self.assertIn("DEPTH subscription limit exceeded", str(ctx.exception))

    def test_unsubscribe_and_removal(self) -> None:
        keys = [
            SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token="2885"),
            SubscriptionKey(mode=LiveTickerMode.QUOTE, exchange_type=1, token="3045"),
        ]
        self.registry.validate_and_add(keys)
        self.assertEqual(self.registry.total_count, 2)

        removed = self.registry.remove([keys[0]])
        self.assertEqual(len(removed), 1)
        self.assertEqual(self.registry.total_count, 1)

        payloads = self.registry.build_action_payloads(removed, action=0)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["action"], 0)


if __name__ == "__main__":
    unittest.main()
