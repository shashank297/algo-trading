"""Unit tests for timezone and chunking helpers."""

from __future__ import annotations

import unittest
from datetime import date

from utils.timezone import get_date_chunks


class TimezoneHelperTests(unittest.TestCase):
    """Test inclusive chunk sizing for date ranges."""

    def test_get_date_chunks_uses_inclusive_chunk_sizes(self) -> None:
        """Chunk boundaries should not exceed the configured number of days."""

        chunks = get_date_chunks(date(2026, 6, 1), date(2026, 6, 5), 2)

        self.assertEqual(
            chunks,
            [
                (date(2026, 6, 1), date(2026, 6, 2)),
                (date(2026, 6, 3), date(2026, 6, 4)),
                (date(2026, 6, 5), date(2026, 6, 5)),
            ],
        )

    def test_get_date_chunks_handles_single_day_ranges(self) -> None:
        """A one-day chunk should return the original date unchanged."""

        chunks = get_date_chunks(date(2026, 6, 17), date(2026, 6, 17), 1)

        self.assertEqual(chunks, [(date(2026, 6, 17), date(2026, 6, 17))])


if __name__ == "__main__":
    unittest.main()
