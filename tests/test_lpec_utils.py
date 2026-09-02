#!/usr/bin/env python3
"""
Tests for lpec_utils.py shared LPEC utility functions.

Run with: python -m pytest tests/test_lpec_utils.py -v
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lpec_utils


# --- format_state_summary tests ---

class TestFormatStateSummary:
    def test_full_state(self):
        state = {
            "TransportState": "Playing",
            "Uri": "ohz://239.255.255.250:51972/4c494e4e-abc",
            "Status": "Yes",
        }
        result = lpec_utils.format_state_summary(state)
        assert "Transport=Playing" in result
        assert "Sender=ohz://..." in result
        assert "Status=Yes" in result

    def test_ohsongcast_sender(self):
        state = {"Uri": "ohSongcast://some-descriptor?room=Living"}
        result = lpec_utils.format_state_summary(state)
        assert "Sender=ohSongcast://..." in result

    def test_empty_sender(self):
        state = {"Uri": ""}
        result = lpec_utils.format_state_summary(state)
        assert "Sender=(empty)" in result

    def test_none_state(self):
        assert lpec_utils.format_state_summary(None) == "No state available"

    def test_empty_state(self):
        assert lpec_utils.format_state_summary({}) == "No state available"

    def test_transport_only(self):
        state = {"TransportState": "Stopped"}
        result = lpec_utils.format_state_summary(state)
        assert result == "Transport=Stopped"


# --- check_transport_playing tests ---

class TestCheckTransportPlaying:
    @patch("lpec_utils.query_receiver_state")
    def test_playing(self, mock_query):
        mock_query.return_value = {"TransportState": "Playing"}
        assert lpec_utils.check_transport_playing("1.2.3.4") is True

    @patch("lpec_utils.query_receiver_state")
    def test_buffering(self, mock_query):
        mock_query.return_value = {"TransportState": "Buffering"}
        assert lpec_utils.check_transport_playing("1.2.3.4") is True

    @patch("lpec_utils.query_receiver_state")
    def test_stopped(self, mock_query):
        mock_query.return_value = {"TransportState": "Stopped"}
        assert lpec_utils.check_transport_playing("1.2.3.4") is False

    @patch("lpec_utils.query_receiver_state")
    def test_none_state(self, mock_query):
        mock_query.return_value = None
        assert lpec_utils.check_transport_playing("1.2.3.4") is False


# --- check_sender_uri tests ---

class TestCheckSenderUri:
    @patch("lpec_utils.query_receiver_state")
    def test_ohz_match(self, mock_query):
        mock_query.return_value = {"Uri": "ohz://239.255.255.250:51972/some-udn"}
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is True
        assert uri.startswith("ohz://")

    @patch("lpec_utils.query_receiver_state")
    def test_ohz_no_match(self, mock_query):
        mock_query.return_value = {"Uri": "ohSongcast://descriptor"}
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is False

    @patch("lpec_utils.query_receiver_state")
    def test_empty_sender(self, mock_query):
        mock_query.return_value = {"Uri": ""}
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is False

    @patch("lpec_utils.query_receiver_state")
    def test_no_state(self, mock_query):
        mock_query.return_value = None
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is False
        assert uri is None


# --- wait_for_state tests ---

class TestWaitForState:
    @patch("lpec_utils.query_receiver_state")
    def test_immediate_match(self, mock_query):
        mock_query.return_value = {"TransportState": "Playing", "Status": "Yes"}
        success, state = lpec_utils.wait_for_state(
            "1.2.3.4",
            {"TransportState": "Playing"},
            timeout=1.0,
            poll_interval=0.1,
        )
        assert success is True
        assert state["TransportState"] == "Playing"

    @patch("lpec_utils.query_receiver_state")
    def test_timeout_no_match(self, mock_query):
        mock_query.return_value = {"TransportState": "Stopped"}
        success, state = lpec_utils.wait_for_state(
            "1.2.3.4",
            {"TransportState": "Playing"},
            timeout=0.3,
            poll_interval=0.1,
        )
        assert success is False
        assert state is not None
        assert state["TransportState"] == "Stopped"

    @patch("lpec_utils.query_receiver_state")
    def test_eventual_match(self, mock_query):
        """State transitions from Stopped to Playing on second poll"""
        mock_query.side_effect = [
            {"TransportState": "Stopped"},
            {"TransportState": "Buffering"},
            {"TransportState": "Playing"},
        ]
        success, state = lpec_utils.wait_for_state(
            "1.2.3.4",
            {"TransportState": "Playing"},
            timeout=5.0,
            poll_interval=0.05,
        )
        assert success is True
        assert state["TransportState"] == "Playing"

    @patch("lpec_utils.query_receiver_state")
    def test_connection_failure_returns_none(self, mock_query):
        mock_query.return_value = None
        success, state = lpec_utils.wait_for_state(
            "1.2.3.4",
            {"TransportState": "Playing"},
            timeout=0.3,
            poll_interval=0.1,
        )
        assert success is False
        assert state is None

    @patch("lpec_utils.query_receiver_state")
    def test_multi_key_match(self, mock_query):
        mock_query.return_value = {
            "TransportState": "Playing",
            "Status": "Yes",
            "Uri": "ohz://239.255.255.250:51972/abc",
        }
        success, state = lpec_utils.wait_for_state(
            "1.2.3.4",
            {"TransportState": "Playing", "Status": "Yes"},
            timeout=1.0,
            poll_interval=0.1,
        )
        assert success is True


# --- query_receiver_state tests (mocked socket) ---

class TestQueryReceiverState:
    @patch("lpec_utils.socket.socket")
    def test_parses_event_response(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        # Verbatim capture from a Linn DSM on port 23. Note the shape:
        # "EVENT <subscription-id> <seq> ...", the id is not 0, the service
        # name is absent, and the bound sender is published as Uri.
        alive_msg = (
            b"ALIVE Ds 4c494e4e-0026-0f22-5661-01531488013f\r\n"
            b"ALIVE MediaRenderer 4c494e4e-0026-0f22-5661-015314880171\r\n"
        )
        event_msg = (
            b'SUBSCRIBE 114\r\n'
            b'EVENT 114 0 Uri "ohz://239.255.255.250:51972/abc" Metadata "" '
            b'TransportState "Playing" '
            b'ProtocolInfo "ohz:*:*:*,ohm:*:*:*,ohu:*.*.*"\r\n'
        )

        # recv delivers ALIVE first, then the event after SUBSCRIBE.
        chunks = iter([alive_msg, event_msg])

        def recv_side_effect(size):
            return next(chunks, b"")

        mock_sock.recv.side_effect = recv_side_effect

        state = lpec_utils.query_receiver_state("172.24.32.210", timeout=2.0)

        mock_sock.connect.assert_called_once_with(("172.24.32.210", 23))
        calls = [c for c in mock_sock.sendall.call_args_list]
        assert any(b"SUBSCRIBE Ds/Receiver" in c[0][0] for c in calls)

        # Unconditional: the old `if state:` guard meant this never ran.
        assert state is not None, "real EVENT frame must parse"
        assert state["TransportState"] == "Playing"
        assert state["Uri"] == "ohz://239.255.255.250:51972/abc"
        assert state["ProtocolInfo"] == "ohz:*:*:*,ohm:*:*:*,ohu:*.*.*"
        assert "Sender" not in state, "Ds/Receiver publishes no Sender variable"
        assert "Status" not in state, "Ds/Receiver publishes no Status variable"

    @patch("lpec_utils.socket.socket")
    def test_connection_refused(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = ConnectionRefusedError()

        state = lpec_utils.query_receiver_state("1.2.3.4", timeout=1.0)
        assert state is None

    @patch("lpec_utils.socket.socket")
    def test_timeout(self, mock_socket_cls):
        import socket as real_socket
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = real_socket.timeout()

        state = lpec_utils.query_receiver_state("1.2.3.4", timeout=0.5)
        assert state is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestEventWireFormat:
    """The LPEC frame shape, pinned against a real capture.

    Frame: EVENT <subscription-id> <seq> <var> "<value>" ...
    The subscription id is a per-device counter, never 0, and Ds/Receiver
    publishes Uri/Metadata/TransportState/ProtocolInfo — no Sender, no Status.
    """

    REAL_FRAME = (
        'EVENT 114 0 Uri "ohz://239.255.255.250:51972/abc" Metadata "" '
        'TransportState "Stopped" ProtocolInfo "ohz:*:*:*,ohm:*:*:*,ohu:*.*.*"'
    )

    def test_sentinel_matches_a_real_frame(self):
        """The old r'^EVENT\\s+0\\s+' never matched, so every query blocked for
        its full timeout instead of returning as soon as the event arrived."""
        assert lpec_utils.EVENT_LINE_RE.search(self.REAL_FRAME) is not None

    def test_sentinel_rejects_a_non_event_line(self):
        assert lpec_utils.EVENT_LINE_RE.search("SUBSCRIBE 114") is None
        assert lpec_utils.EVENT_LINE_RE.search("ALIVE Ds 4c494e4e-x") is None

    def test_parses_all_four_receiver_variables(self):
        state = lpec_utils.parse_event_variables(self.REAL_FRAME)
        assert state["Uri"] == "ohz://239.255.255.250:51972/abc"
        assert state["TransportState"] == "Stopped"
        assert state["ProtocolInfo"] == "ohz:*:*:*,ohm:*:*:*,ohu:*.*.*"
        assert state["Metadata"] == ""

    def test_variable_names_are_matched_at_a_token_boundary(self):
        """An unanchored search lets a longer name satisfy a shorter one.

        'ReceiverUri "decoy"' must not be harvested as the Uri variable, and it
        appears first on the line, so a loose match would win.
        """
        line = 'EVENT 7 0 ReceiverUri "decoy" Uri "ohz://real" TransportState "Playing"'
        state = lpec_utils.parse_event_variables(line)
        assert state["Uri"] == "ohz://real"
        assert state["TransportState"] == "Playing"

    def test_a_name_inside_another_value_is_not_harvested(self):
        line = 'EVENT 7 0 Metadata "<DIDL>Uri \'x\' junk</DIDL>" TransportState "Playing"'
        state = lpec_utils.parse_event_variables(line)
        assert state.get("TransportState") == "Playing"
