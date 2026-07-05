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
            "Sender": "ohz://239.255.255.250:51972/4c494e4e-abc",
            "Status": "Yes",
        }
        result = lpec_utils.format_state_summary(state)
        assert "Transport=Playing" in result
        assert "Sender=ohz://..." in result
        assert "Status=Yes" in result

    def test_ohsongcast_sender(self):
        state = {"Sender": "ohSongcast://some-descriptor?room=Living"}
        result = lpec_utils.format_state_summary(state)
        assert "Sender=ohSongcast://..." in result

    def test_empty_sender(self):
        state = {"Sender": ""}
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
        mock_query.return_value = {"Sender": "ohz://239.255.255.250:51972/some-udn"}
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is True
        assert uri.startswith("ohz://")

    @patch("lpec_utils.query_receiver_state")
    def test_ohz_no_match(self, mock_query):
        mock_query.return_value = {"Sender": "ohSongcast://descriptor"}
        matches, uri = lpec_utils.check_sender_uri("1.2.3.4", "ohz")
        assert matches is False

    @patch("lpec_utils.query_receiver_state")
    def test_empty_sender(self, mock_query):
        mock_query.return_value = {"Sender": ""}
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
            "Sender": "ohz://239.255.255.250:51972/abc",
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

        # Simulate LPEC conversation
        alive_msg = b"ALIVE Ds 4c494e4e-0026-0f22-5661-01531488013f\r\n"
        event_msg = (
            b'EVENT 0 Ds/Receiver TransportState "Playing" '
            b'Sender "ohz://239.255.255.250:51972/abc" '
            b'Status "Yes" '
            b'ProtocolInfo "ohz:*:*:*"\r\n'
        )

        # recv returns ALIVE first, then EVENT 0 after subscribe
        call_count = [0]
        def recv_side_effect(size):
            call_count[0] += 1
            if call_count[0] == 1:
                return alive_msg
            elif call_count[0] == 2:
                return b""  # empty after alive drain
            elif call_count[0] == 3:
                return event_msg
            return b""

        mock_sock.recv.side_effect = recv_side_effect

        state = lpec_utils.query_receiver_state("172.24.32.210", timeout=2.0)

        # Verify we connected to port 23
        mock_sock.connect.assert_called_once_with(("172.24.32.210", 23))
        # Verify we subscribed
        calls = [c for c in mock_sock.sendall.call_args_list]
        subscribe_sent = any(b"SUBSCRIBE Ds/Receiver" in c[0][0] for c in calls)
        assert subscribe_sent

        if state:
            assert state.get("TransportState") == "Playing"

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
