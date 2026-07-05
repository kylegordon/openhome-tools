#!/usr/bin/env python3
"""
Tests for songcast_group.py

Run with:
    .venv/bin/python -m pytest tests/test_songcast_group.py -v
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import songcast_group  # noqa: E402  (import-succeeds is itself a regression test)


def _make_prod(sources, source_count=None):
    """Build a mock Product service whose Source(Index=i) returns sources[i]."""
    prod = MagicMock()

    async def source_count_call():
        return {"Value": source_count if source_count is not None else len(sources)}

    async def source_call(Index):
        entry = sources[Index]
        if isinstance(entry, Exception):
            raise entry
        return entry

    prod.action.side_effect = lambda name: {
        "SourceCount": MagicMock(async_call=source_count_call),
        "Source": MagicMock(async_call=source_call),
    }[name]
    return prod


def _make_dev(prod):
    dev = MagicMock()
    dev.device.service_id.return_value = prod
    return dev


def _grouper(debug=False):
    return songcast_group.LinnSongcastGrouper(
        sender_ip="10.0.0.1", sender_udn="4c494e4e-fake", receivers=[], debug=debug
    )


class TestFindSongcastIndex:
    def test_returns_visible_match_immediately(self):
        sources = [
            {"Name": "Radio", "Type": "radio", "Visible": "true"},
            {"Name": "Songcast", "Type": "receiver", "Visible": "true"},
        ]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper()._find_songcast_index(dev))
        assert result == 1

    def test_falls_back_to_invisible_match_when_no_visible_match(self):
        sources = [
            {"Name": "Radio", "Type": "radio", "Visible": "true"},
            {"Name": "Songcast", "Type": "receiver", "Visible": "false"},
        ]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper()._find_songcast_index(dev))
        assert result == 1

    def test_prefers_later_visible_match_over_earlier_invisible_one(self):
        sources = [
            {"Name": "Songcast", "Type": "receiver", "Visible": "false"},
            {"Name": "Songcast", "Type": "receiver", "Visible": "true"},
        ]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper()._find_songcast_index(dev))
        assert result == 1

    def test_missing_visible_field_defaults_to_visible(self):
        sources = [{"Name": "Songcast", "Type": "receiver"}]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper()._find_songcast_index(dev))
        assert result == 0

    def test_no_match_returns_none(self):
        sources = [
            {"Name": "Radio", "Type": "radio", "Visible": "true"},
            {"Name": "Playlist", "Type": "playlist", "Visible": "true"},
        ]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper()._find_songcast_index(dev))
        assert result is None

    def test_per_source_exception_is_skipped_not_fatal(self):
        # Regression test: a failure reading one source must not abort the scan
        # (and must not raise NameError from the debug-print referencing `e`).
        sources = [
            RuntimeError("simulated SOAP failure"),
            {"Name": "Songcast", "Type": "receiver", "Visible": "true"},
        ]
        dev = _make_dev(_make_prod(sources))
        result = asyncio.run(_grouper(debug=True)._find_songcast_index(dev))
        assert result == 1
