#!/usr/bin/env python3
"""
Tests for songcast_disband.py

Run with:
    .venv/bin/python -m pytest tests/test_songcast_disband.py -v

Or standalone:
    .venv/bin/python tests/test_songcast_disband.py
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

import requests

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lpec_utils
import songcast_disband


# --- .env loading tests ---

class TestLoadDevices:
    def test_load_valid_env_with_udns(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f # Study\n"
            "DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f\n"
        )
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 2
        assert devices[0] == {"ip": "172.24.32.211", "udn": "4c494e4e-0026-0f22-5661-01531488013f"}
        assert devices[1] == {"ip": "172.24.32.210", "udn": "4c494e4e-0026-0f22-646e-01560511013f"}

    @patch("songcast_disband.discover_udn")
    def test_load_ip_only_discovers_udn(self, mock_discover, tmp_path):
        mock_discover.return_value = "4c494e4e-0026-0f22-5661-01531488013f"
        env = tmp_path / ".env"
        env.write_text("DEVICE_1=172.24.32.211\n")
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 1
        assert devices[0] == {"ip": "172.24.32.211", "udn": "4c494e4e-0026-0f22-5661-01531488013f"}
        mock_discover.assert_called_once_with("172.24.32.211")

    @patch("songcast_disband.discover_udn")
    def test_load_ip_only_skips_on_discovery_failure(self, mock_discover, tmp_path):
        mock_discover.return_value = None
        env = tmp_path / ".env"
        env.write_text(
            "DEVICE_1=172.24.32.211\n"
            "DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f\n"
        )
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 1
        assert devices[0]["ip"] == "172.24.32.210"

    @patch("songcast_disband.discover_udn")
    def test_load_mixed_ip_and_udn(self, mock_discover, tmp_path):
        mock_discover.return_value = "4c494e4e-discovered"
        env = tmp_path / ".env"
        env.write_text(
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
            "DEVICE_2=172.24.32.210\n"
        )
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 2
        assert devices[0]["udn"] == "4c494e4e-0026-0f22-5661-01531488013f"
        assert devices[1]["udn"] == "4c494e4e-discovered"
        mock_discover.assert_called_once_with("172.24.32.210")

    def test_load_env_skips_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# This is a comment\n"
            "\n"
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
            "SONGCAST_SENDER=DEVICE_1\n"
        )
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 1

    def test_load_empty_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# only comments\n")
        devices = songcast_disband.load_devices(str(env))
        assert len(devices) == 0

    def test_device_line_regex_ip_only(self):
        line = "DEVICE_1=172.24.32.211"
        m = songcast_disband.DEVICE_LINE_RE.match(line)
        assert m is not None
        assert m.group(1) == "172.24.32.211"
        assert m.group(2) is None

    def test_device_line_regex(self):
        valid = "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f"
        m = songcast_disband.DEVICE_LINE_RE.match(valid)
        assert m is not None
        assert m.group(1) == "172.24.32.211"
        assert m.group(2) == "4c494e4e-0026-0f22-5661-01531488013f"

    def test_device_line_regex_rejects_invalid(self):
        for line in ["# comment", "", "SONGCAST_SENDER=DEVICE_1", "DEVICE_1="]:
            assert songcast_disband.DEVICE_LINE_RE.match(line) is None


# --- UDN discovery tests ---

class TestDiscoverUdn:
    @patch("songcast_disband.socket.socket")
    def test_discover_udn_success(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"ALIVE Ds 4c494e4e-0026-0f22-5661-01531488013f\r\n"
        udn = songcast_disband.discover_udn("172.24.32.211")
        assert udn == "4c494e4e-0026-0f22-5661-01531488013f"
        mock_sock.connect.assert_called_once_with(("172.24.32.211", 23))

    @patch("songcast_disband.socket.socket")
    def test_discover_udn_connection_refused(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = ConnectionRefusedError()
        udn = songcast_disband.discover_udn("172.24.32.211")
        assert udn is None

    @patch("songcast_disband.socket.socket")
    def test_discover_udn_timeout(self, mock_socket_cls):
        import socket as real_socket
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.side_effect = real_socket.timeout()
        udn = songcast_disband.discover_udn("172.24.32.211", timeout=0.1)
        assert udn is None

    @patch("songcast_disband.socket.socket")
    def test_discover_udn_no_alive_message(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"SOME OTHER DATA\r\n"
        # After first recv, timeout to stop loop
        mock_sock.recv.side_effect = [b"SOME OTHER DATA\r\n", b""]
        udn = songcast_disband.discover_udn("172.24.32.211", timeout=0.1)
        assert udn is None


# --- SOAP URL construction tests ---

# --- Device classification tests ---

class TestClassifyDevices:
    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.is_receiver_active")
    @patch("songcast_disband._soap_request")
    def test_classify_active_receiver(self, mock_soap, mock_active, mock_source, mock_name):
        mock_name.return_value = "Tin Hut"
        mock_source.return_value = {"index": 3, "type": "Receiver", "name": "Songcast"}
        mock_active.return_value = True

        devices = [{"ip": "172.24.32.210", "udn": "udn-receiver"}]
        result = songcast_disband.classify_devices(devices)
        assert len(result) == 1
        assert result[0]["role"] == "receiver"
        assert result[0]["name"] == "Tin Hut"

    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.is_receiver_active")
    @patch("songcast_disband._soap_request")
    def test_classify_idle_receiver(self, mock_soap, mock_active, mock_source, mock_name):
        mock_name.return_value = "Tin Hut"
        mock_source.return_value = {"index": 3, "type": "Receiver", "name": "Songcast"}
        mock_active.return_value = False

        devices = [{"ip": "172.24.32.210", "udn": "udn-receiver"}]
        result = songcast_disband.classify_devices(devices)
        assert result[0]["role"] == "receiver-idle"

    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband._soap_request")
    def test_classify_sender_via_sender_status(self, mock_soap, mock_source, mock_name):
        mock_name.return_value = "Study"
        # Source is Playlist, not Receiver/Songcast
        mock_source.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        # Sender.Status2 reports it is actively streaming
        mock_soap.return_value = '<Value>Sending</Value>'

        devices = [{"ip": "172.24.32.211", "udn": "udn-sender"}]
        result = songcast_disband.classify_devices(devices)
        assert result[0]["role"] == "sender"

    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband._soap_request")
    def test_idle_sender_service_is_not_a_sender(self, mock_soap, mock_source, mock_name):
        """An enabled-but-idle Sender service must not classify as sender.

        Every device reports Sender.Status == "Enabled" whenever the service is
        switched on. Status2 "Ready" is the idle state; only "Sending" means
        this device is actually the group leader.
        """
        mock_name.return_value = "Living Room"
        mock_source.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        mock_soap.return_value = '<Value>Ready</Value>'

        devices = [{"ip": "172.24.32.212", "udn": "udn-idle"}]
        result = songcast_disband.classify_devices(devices)
        assert result[0]["role"] == "standalone"

    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband._soap_request")
    def test_classify_standalone(self, mock_soap, mock_source, mock_name):
        mock_name.return_value = "Living Room"
        mock_source.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        # Sender.Status query fails (not sending)
        mock_soap.side_effect = Exception("No sender")

        devices = [{"ip": "172.24.32.212", "udn": "udn-standalone"}]
        result = songcast_disband.classify_devices(devices)
        assert result[0]["role"] == "standalone"

    @patch("songcast_disband.get_device_name")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.is_receiver_active")
    @patch("songcast_disband._soap_request")
    def test_classify_full_group(self, mock_soap, mock_active, mock_source, mock_name):
        """Classify a 3-device group: 1 sender + 2 receivers."""
        devices = [
            {"ip": "172.24.32.211", "udn": "udn-sender"},
            {"ip": "172.24.32.210", "udn": "udn-recv1"},
            {"ip": "172.24.32.212", "udn": "udn-recv2"},
        ]

        def name_side_effect(ip, udn, **kw):
            return {"172.24.32.211": "Study", "172.24.32.210": "Tin Hut", "172.24.32.212": "Living Room"}[ip]

        def source_side_effect(ip, udn, debug=False):
            if ip == "172.24.32.211":
                return {"index": 0, "type": "Playlist", "name": "Playlist"}
            return {"index": 3, "type": "Receiver", "name": "Songcast"}

        def active_side_effect(ip, udn, debug=False):
            return ip != "172.24.32.211"

        def soap_side_effect(ip, udn, service_path, service_urn, action, timeout=5):
            if ip == "172.24.32.211" and "Sender" in service_path:
                return "<Value>Sending</Value>"
            raise Exception("Not available")

        mock_name.side_effect = name_side_effect
        mock_source.side_effect = source_side_effect
        mock_active.side_effect = active_side_effect
        mock_soap.side_effect = soap_side_effect

        result = songcast_disband.classify_devices(devices)
        roles = {r["ip"]: r["role"] for r in result}
        assert roles["172.24.32.211"] == "sender"
        assert roles["172.24.32.210"] == "receiver"
        assert roles["172.24.32.212"] == "receiver"


# --- Receiver state detection tests ---

class TestReceiverDetection:
    @patch("songcast_disband._soap_request")
    def test_transport_state_playing(self, mock_soap):
        mock_soap.return_value = "<Value>Playing</Value>"
        state = songcast_disband.get_receiver_transport_state("1.2.3.4", "udn")
        assert state == "Playing"

    @patch("songcast_disband._soap_request")
    def test_transport_state_stopped(self, mock_soap):
        mock_soap.return_value = "<Value>Stopped</Value>"
        state = songcast_disband.get_receiver_transport_state("1.2.3.4", "udn")
        assert state == "Stopped"

    @patch("songcast_disband._soap_request")
    def test_transport_state_failure(self, mock_soap):
        mock_soap.side_effect = Exception("timeout")
        state = songcast_disband.get_receiver_transport_state("1.2.3.4", "udn")
        assert state is None

    @patch("songcast_disband._soap_request")
    def test_sender_uri_ohz(self, mock_soap):
        mock_soap.return_value = "<Uri>ohz://239.255.255.250:51972/4c494e4e-abc</Uri>"
        uri = songcast_disband.get_receiver_sender_uri("1.2.3.4", "udn")
        assert uri.startswith("ohz://")

    @patch("songcast_disband.get_receiver_transport_state")
    @patch("songcast_disband.get_receiver_sender_uri")
    def test_is_receiver_active_playing(self, mock_uri, mock_state):
        mock_state.return_value = "Playing"
        mock_uri.return_value = ""
        assert songcast_disband.is_receiver_active("1.2.3.4", "udn") is True

    @patch("songcast_disband.get_receiver_transport_state")
    @patch("songcast_disband.get_receiver_sender_uri")
    def test_is_receiver_active_ohz_uri(self, mock_uri, mock_state):
        mock_state.return_value = "Stopped"
        mock_uri.return_value = "ohz://239.255.255.250:51972/some-udn"
        assert songcast_disband.is_receiver_active("1.2.3.4", "udn") is True

    @patch("songcast_disband.get_receiver_transport_state")
    @patch("songcast_disband.get_receiver_sender_uri")
    def test_is_receiver_not_active(self, mock_uri, mock_state):
        mock_state.return_value = "Stopped"
        mock_uri.return_value = ""
        assert songcast_disband.is_receiver_active("1.2.3.4", "udn") is False


# --- Stop operations tests ---

class TestStopOperations:
    @patch("songcast_disband._soap_request")
    def test_stop_receiver_success(self, mock_soap):
        mock_soap.return_value = "<ok/>"
        assert songcast_disband.stop_receiver("1.2.3.4", "udn") is True
        mock_soap.assert_called_once_with(
            "1.2.3.4", "udn",
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "Stop",
        )

    @patch("songcast_disband._soap_request")
    def test_stop_receiver_failure(self, mock_soap):
        mock_soap.side_effect = Exception("connection refused")
        assert songcast_disband.stop_receiver("1.2.3.4", "udn") is False

    @patch("songcast_disband._soap_request_with_params")
    def test_clear_receiver_sender_success(self, mock_soap):
        mock_soap.return_value = "<ok/>"
        assert songcast_disband.clear_receiver_sender("1.2.3.4", "udn") is True
        mock_soap.assert_called_once_with(
            "1.2.3.4", "udn",
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "SetSender",
            {"Uri": "", "Metadata": ""},
        )

    @patch("songcast_disband._soap_request_with_params")
    def test_clear_receiver_sender_failure(self, mock_soap):
        mock_soap.side_effect = Exception("connection refused")
        assert songcast_disband.clear_receiver_sender("1.2.3.4", "udn") is False

    @patch("songcast_disband._soap_request_with_params")
    def test_set_source_index_success(self, mock_soap):
        mock_soap.return_value = "<ok/>"
        assert songcast_disband.set_source_index("1.2.3.4", "udn", 0) is True
        mock_soap.assert_called_once_with(
            "1.2.3.4", "udn",
            "av.openhome.org-Product-4",
            "urn:av-openhome-org:service:Product:4",
            "SetSourceIndex",
            {"Value": "0"},
        )

    @patch("songcast_disband._soap_request_with_params")
    def test_set_source_index_failure(self, mock_soap):
        mock_soap.side_effect = Exception("connection refused")
        assert songcast_disband.set_source_index("1.2.3.4", "udn", 0) is False

    @patch("songcast_disband._soap_request")
    def test_stop_playlist_success(self, mock_soap):
        mock_soap.return_value = "<ok/>"
        assert songcast_disband.stop_playlist("1.2.3.4", "udn") is True
        mock_soap.assert_called_once_with(
            "1.2.3.4", "udn",
            "av.openhome.org-Playlist-1",
            "urn:av-openhome-org:service:Playlist:1",
            "Stop",
        )

    @patch("songcast_disband._soap_request")
    def test_stop_playlist_failure(self, mock_soap):
        mock_soap.side_effect = Exception("connection refused")
        assert songcast_disband.stop_playlist("1.2.3.4", "udn") is False


# --- Full disband workflow tests ---

class TestDisbandGroup:
    @patch("songcast_disband.get_sender_status2", return_value="Ready")
    @patch("songcast_disband.get_receiver_sender_uri")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.stop_playlist")
    @patch("songcast_disband.set_source_index")
    @patch("songcast_disband.stop_receiver")
    @patch("songcast_disband.clear_receiver_sender")
    @patch("songcast_disband.classify_devices")
    def test_disband_full_group(self, mock_classify, mock_clear, mock_stop_recv,
                                mock_set_src, mock_stop_play, mock_get_src, mock_get_uri,
                                mock_status2):
        mock_classify.return_value = [
            {"ip": "172.24.32.211", "udn": "udn-s", "name": "Study", "role": "sender",
             "source": {"index": 1, "type": "Radio", "name": "Radio"}},
            {"ip": "172.24.32.210", "udn": "udn-r1", "name": "Tin Hut", "role": "receiver",
             "source": {"index": 3, "type": "Receiver", "name": "Songcast"}},
            {"ip": "172.24.32.212", "udn": "udn-r2", "name": "Living Room", "role": "receiver",
             "source": {"index": 3, "type": "Receiver", "name": "Songcast"}},
        ]
        mock_clear.return_value = True
        mock_stop_recv.return_value = True
        mock_set_src.return_value = True
        mock_stop_play.return_value = True
        # Verification: source is now Playlist, URI is empty
        mock_get_src.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        mock_get_uri.return_value = ""

        devices = [
            {"ip": "172.24.32.211", "udn": "udn-s"},
            {"ip": "172.24.32.210", "udn": "udn-r1"},
            {"ip": "172.24.32.212", "udn": "udn-r2"},
        ]
        result = songcast_disband.disband_group(devices)
        assert result is True
        assert mock_clear.call_count == 2
        assert mock_stop_recv.call_count == 2
        assert mock_set_src.call_count == 2
        # The sender must keep playing: ungrouping the receivers must not
        # interrupt whoever is listening on the sender.
        mock_stop_play.assert_not_called()

    @patch("songcast_disband.get_sender_status2")
    @patch("songcast_disband.get_receiver_sender_uri")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.stop_playlist")
    @patch("songcast_disband.set_source_index")
    @patch("songcast_disband.stop_receiver")
    @patch("songcast_disband.clear_receiver_sender")
    @patch("songcast_disband.classify_devices")
    def test_sender_playback_is_left_alone(self, mock_classify, mock_clear, mock_stop_recv,
                                           mock_set_src, mock_stop_play, mock_get_src,
                                           mock_get_uri, mock_status2):
        """Regression: disband must not stop playback on the sender.

        Disbanding ungroups the receivers. The person listening on the sender
        should keep listening; the Sender service drops back to "Ready" on its
        own once the last receiver detaches.
        """
        mock_classify.return_value = [
            {"ip": "172.24.32.211", "udn": "udn-s", "name": "Study", "role": "sender",
             "source": {"index": 0, "type": "Playlist", "name": "Playlist"}},
            {"ip": "172.24.32.210", "udn": "udn-r", "name": "Tin Hut", "role": "receiver",
             "source": {"index": 3, "type": "Receiver", "name": "Songcast"}},
        ]
        mock_clear.return_value = True
        mock_stop_recv.return_value = True
        mock_set_src.return_value = True
        mock_get_src.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        mock_get_uri.return_value = ""
        mock_status2.return_value = "Ready"

        devices = [{"ip": "172.24.32.211", "udn": "udn-s"},
                   {"ip": "172.24.32.210", "udn": "udn-r"}]

        assert songcast_disband.disband_group(devices) is True
        mock_stop_play.assert_not_called()

        # ...unless explicitly asked for.
        assert songcast_disband.disband_group(devices, stop_sender=True) is True
        assert mock_stop_play.call_count == 1

    @patch("songcast_disband.get_sender_status2")
    @patch("songcast_disband.get_receiver_sender_uri")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.stop_playlist")
    @patch("songcast_disband.set_source_index")
    @patch("songcast_disband.stop_receiver")
    @patch("songcast_disband.clear_receiver_sender")
    @patch("songcast_disband.classify_devices")
    def test_sender_still_streaming_after_disband_fails(self, mock_classify, mock_clear,
                                                        mock_stop_recv, mock_set_src,
                                                        mock_stop_play, mock_get_src,
                                                        mock_get_uri, mock_status2):
        """A sender still 'Sending' means a receiver never detached."""
        mock_classify.return_value = [
            {"ip": "172.24.32.211", "udn": "udn-s", "name": "Study", "role": "sender",
             "source": {"index": 0, "type": "Playlist", "name": "Playlist"}},
            {"ip": "172.24.32.210", "udn": "udn-r", "name": "Tin Hut", "role": "receiver",
             "source": {"index": 3, "type": "Receiver", "name": "Songcast"}},
        ]
        mock_clear.return_value = True
        mock_stop_recv.return_value = True
        mock_set_src.return_value = True
        mock_get_src.return_value = {"index": 0, "type": "Playlist", "name": "Playlist"}
        mock_get_uri.return_value = ""
        mock_status2.return_value = "Sending"

        devices = [{"ip": "172.24.32.211", "udn": "udn-s"},
                   {"ip": "172.24.32.210", "udn": "udn-r"}]
        assert songcast_disband.disband_group(devices) is False

    @patch("songcast_disband.stop_playlist")
    @patch("songcast_disband.set_source_index")
    @patch("songcast_disband.stop_receiver")
    @patch("songcast_disband.clear_receiver_sender")
    @patch("songcast_disband.classify_devices")
    def test_disband_no_group(self, mock_classify, mock_clear, mock_stop_recv,
                              mock_set_src, mock_stop_play):
        mock_classify.return_value = [
            {"ip": "172.24.32.211", "udn": "udn-1", "name": "Study", "role": "standalone",
             "source": {"index": 0, "type": "Playlist", "name": "Playlist"}},
            {"ip": "172.24.32.210", "udn": "udn-2", "name": "Tin Hut", "role": "standalone",
             "source": {"index": 0, "type": "Playlist", "name": "Playlist"}},
        ]

        devices = [
            {"ip": "172.24.32.211", "udn": "udn-1"},
            {"ip": "172.24.32.210", "udn": "udn-2"},
        ]
        result = songcast_disband.disband_group(devices)
        assert result is True
        mock_clear.assert_not_called()
        mock_stop_recv.assert_not_called()
        mock_set_src.assert_not_called()
        mock_stop_play.assert_not_called()

    @patch("songcast_disband.get_sender_status2", return_value="Ready")
    @patch("songcast_disband.get_receiver_sender_uri")
    @patch("songcast_disband.get_current_source")
    @patch("songcast_disband.stop_playlist")
    @patch("songcast_disband.set_source_index")
    @patch("songcast_disband.stop_receiver")
    @patch("songcast_disband.clear_receiver_sender")
    @patch("songcast_disband.classify_devices")
    def test_disband_source_switch_fails(self, mock_classify, mock_clear, mock_stop_recv,
                                         mock_set_src, mock_stop_play, mock_get_src, mock_get_uri,
                                         mock_status2):
        mock_classify.return_value = [
            {"ip": "172.24.32.211", "udn": "udn-s", "name": "Study", "role": "sender",
             "source": {"index": 1, "type": "Radio", "name": "Radio"}},
            {"ip": "172.24.32.210", "udn": "udn-r", "name": "Tin Hut", "role": "receiver",
             "source": {"index": 3, "type": "Receiver", "name": "Songcast"}},
        ]
        mock_clear.return_value = True
        mock_stop_recv.return_value = True
        mock_set_src.return_value = False  # Source switch fails
        mock_stop_play.return_value = True
        # Verification: still on Receiver source
        mock_get_src.return_value = {"index": 3, "type": "Receiver", "name": "Songcast"}
        mock_get_uri.return_value = "ohz://239.255.255.250:51972/some-udn"

        devices = [
            {"ip": "172.24.32.211", "udn": "udn-s"},
            {"ip": "172.24.32.210", "udn": "udn-r"},
        ]
        result = songcast_disband.disband_group(devices)
        assert result is False


# --- Standalone runner ---

if __name__ == "__main__":
    # Run basic non-mock tests directly
    print("=== Standalone tests for songcast_disband.py ===\n")

    # .env loading
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f # Study\n")
        f.write("DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f\n")
        f.write("# comment\n")
        f.write("SONGCAST_SENDER=DEVICE_1\n")
        f.write("DEVICE_3=172.24.32.212 4c494e4e-0026-0f22-3637-01475230013f\n")
        tmp_env = f.name

    try:
        devs = songcast_disband.load_devices(tmp_env)
        assert len(devs) == 3, f"Expected 3 devices, got {len(devs)}"
        assert devs[0]["ip"] == "172.24.32.211"
        assert devs[1]["ip"] == "172.24.32.210"
        assert devs[2]["ip"] == "172.24.32.212"
        print("✓ load_devices: correctly parsed 3 devices from .env")
    finally:
        os.unlink(tmp_env)

    # Regex tests
    valid = "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f"
    m = songcast_disband.DEVICE_LINE_RE.match(valid)
    assert m is not None
    assert m.group(1) == "172.24.32.211"
    assert m.group(2) == "4c494e4e-0026-0f22-5661-01531488013f"
    print("✓ DEVICE_LINE_RE: matches IP + UDN lines")

    ip_only = "DEVICE_1=172.24.32.211"
    m = songcast_disband.DEVICE_LINE_RE.match(ip_only)
    assert m is not None
    assert m.group(1) == "172.24.32.211"
    assert m.group(2) is None
    print("✓ DEVICE_LINE_RE: matches IP-only lines")

    for bad in ["# comment", "", "SONGCAST_SENDER=DEVICE_1", "DEVICE_1="]:
        assert songcast_disband.DEVICE_LINE_RE.match(bad) is None
    print("✓ DEVICE_LINE_RE: rejects invalid lines")

    # URL format verification
    ip = "172.24.32.210"
    udn = "4c494e4e-0026-0f22-646e-01560511013f"
    assert f"http://{ip}:55178/{udn}/av.openhome.org-Receiver-1/control" == \
        "http://172.24.32.210:55178/4c494e4e-0026-0f22-646e-01560511013f/av.openhome.org-Receiver-1/control"
    print("✓ SOAP URL format: Receiver control URL correct")

    assert f"http://{ip}:55178/{udn}/av.openhome.org-Playlist-1/control" == \
        "http://172.24.32.210:55178/4c494e4e-0026-0f22-646e-01560511013f/av.openhome.org-Playlist-1/control"
    print("✓ SOAP URL format: Playlist control URL correct")

    print("\n✓ All standalone tests passed!")


# --- Device responses are untrusted input ---

class TestSoapOut:
    """SOAP responses are parsed, not regex-scraped."""

    RESP = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        '<s:Body>'
        '<u:SourceResponse xmlns:u="urn:av-openhome-org:service:Product:4">'
        '<Type>Playlist</Type><Name>Kitchen &amp; Diner</Name>'
        '<Visible>true</Visible>'
        '</u:SourceResponse>'
        '</s:Body></s:Envelope>'
    )

    def test_reads_named_argument(self):
        assert songcast_disband._soap_out(self.RESP, "Type") == "Playlist"

    def test_unescapes_entities(self):
        # Regression: the previous regex returned "Kitchen &amp; Diner" raw.
        assert songcast_disband._soap_out(self.RESP, "Name") == "Kitchen & Diner"

    def test_namespaced_tags_match_on_local_name(self):
        resp = (
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><u:X xmlns:u="urn:x"><Value>Playing</Value></u:X>'
            '</s:Body></s:Envelope>'
        )
        assert songcast_disband._soap_out(resp, "Value") == "Playing"

    def test_missing_argument_returns_none(self):
        assert songcast_disband._soap_out(self.RESP, "Nope") is None

    def test_malformed_xml_returns_none_not_partial_match(self):
        # A regex would happily match inside a truncated body; the parser won't.
        assert songcast_disband._soap_out("<s:Body><Value>Playing", "Value") is None

    def test_empty_input_returns_none(self):
        assert songcast_disband._soap_out("", "Value") is None
        assert songcast_disband._soap_out(None, "Value") is None


class TestDisplaySanitising:
    """Device names reach the terminal and must not be able to forge it."""

    def test_strips_ansi_escapes(self):
        out = lpec_utils.safe_for_display("Study\x1b[2K\x1b[1A OK")
        assert "\x1b" not in out

    def test_strips_carriage_return_and_nulls(self):
        assert "\r" not in lpec_utils.safe_for_display("A\rB")
        assert "\x00" not in lpec_utils.safe_for_display("A\x00B")

    def test_collapses_whitespace_and_newlines(self):
        assert lpec_utils.safe_for_display("Tin\n\n  Hut") == "Tin Hut"

    def test_truncates_long_names(self):
        out = lpec_utils.safe_for_display("x" * 200)
        assert len(out) == lpec_utils.DISPLAY_CHARS
        assert out.endswith("…")

    def test_none_and_empty(self):
        assert lpec_utils.safe_for_display(None) == ""
        assert lpec_utils.safe_for_display("") == ""

    def test_ordinary_name_is_unchanged(self):
        assert lpec_utils.safe_for_display("Linn Tin Hut") == "Linn Tin Hut"


class TestBounding:
    def test_caps_length_for_matching(self):
        capped = lpec_utils.bounded("y" * 5000)
        assert len(capped) == lpec_utils.MAX_FIELD_CHARS

    def test_none_becomes_empty(self):
        assert lpec_utils.bounded(None) == ""

    def test_short_values_pass_through(self):
        assert lpec_utils.bounded("Songcast") == "Songcast"


class TestSourceIndexValidation:
    @patch("songcast_disband._soap_request")
    def test_non_numeric_index_returns_none(self, mock_soap):
        mock_soap.return_value = "<s:Body><Value>not-a-number</Value></s:Body>"
        assert songcast_disband.get_current_source("1.2.3.4", "udn") is None

    @patch("songcast_disband._soap_request")
    def test_implausible_index_is_rejected(self, mock_soap):
        mock_soap.return_value = "<s:Body><Value>999999</Value></s:Body>"
        assert songcast_disband.get_current_source("1.2.3.4", "udn") is None


# --- The SOAP layer itself ---
#
# These drive each helper all the way down to a patched requests.post and assert
# on the actual request. Without them the whole construction layer — port, path,
# SOAPACTION header, envelope, argument element names — is unverified, which is
# how three non-existent action names survived in this codebase for months.

class _FakeResponse:
    def __init__(self, body=b"<Body/>", status=200):
        self.content = body
        self.text = body.decode() if isinstance(body, bytes) else body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestSoapRequestConstruction:
    IP = "1.2.3.4"
    UDN = "udn-xyz"

    def test_builds_exact_url_headers_and_body(self):
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            songcast_disband._soap_request(
                self.IP, self.UDN,
                "av.openhome.org-Receiver-1",
                "urn:av-openhome-org:service:Receiver:1",
                "Stop",
            )
        url = post.call_args[0][0]
        headers = post.call_args[1]["headers"]
        body = post.call_args[1]["data"]

        assert url == "http://1.2.3.4:55178/udn-xyz/av.openhome.org-Receiver-1/control"
        assert headers["SOAPACTION"] == '"urn:av-openhome-org:service:Receiver:1#Stop"'
        assert headers["Content-Type"] == 'text/xml; charset="utf-8"'
        assert '<u:Stop xmlns:u="urn:av-openhome-org:service:Receiver:1"/>' in body
        # Envelope must be well-formed and carry the action inside s:Body.
        root = ET.fromstring(body)
        body_el = root.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")
        assert body_el is not None and len(body_el) == 1

    def test_serialises_named_arguments_as_elements(self):
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            songcast_disband._soap_request_with_params(
                self.IP, self.UDN,
                "av.openhome.org-Receiver-1",
                "urn:av-openhome-org:service:Receiver:1",
                "SetSender", {"Uri": "", "Metadata": ""},
            )
        body = post.call_args[1]["data"]
        assert "<Uri></Uri>" in body
        assert "<Metadata></Metadata>" in body

    def test_argument_values_are_xml_escaped(self):
        """A DIDL blob or a URI with & and < must not corrupt the envelope."""
        didl = '<DIDL-Lite><item id="0">A & B</item></DIDL-Lite>'
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            songcast_disband._soap_request_with_params(
                self.IP, self.UDN,
                "av.openhome.org-Receiver-1",
                "urn:av-openhome-org:service:Receiver:1",
                "SetSender", {"Uri": "ohz://x?a=1&b=2", "Metadata": didl},
            )
        body = post.call_args[1]["data"]
        root = ET.fromstring(body)  # must still be well-formed
        sent = {el.tag: el.text for el in root.iter() if el.tag in ("Uri", "Metadata")}
        assert sent["Uri"] == "ohz://x?a=1&b=2"
        assert sent["Metadata"] == didl

    def test_rejects_non_identifier_argument_names(self):
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()):
            with pytest.raises(ValueError):
                songcast_disband._soap_request_with_params(
                    self.IP, self.UDN, "svc", "urn:x", "Act", {"Uri><evil": "x"},
                )

    def test_http_500_soap_fault_raises(self):
        with patch("songcast_disband.requests.post", return_value=_FakeResponse(status=500)):
            with pytest.raises(requests.HTTPError):
                songcast_disband._soap_request(
                    self.IP, self.UDN, "svc", "urn:x", "Act")


class TestActionNamesMatchTheDevice:
    """Pin the exact service/action each helper invokes.

    Verified against the SCPDs of a live Linn DSM. If a name here stops matching
    the device, that is a real bug — which is precisely what went undetected
    before, because every failing call was swallowed by a bare except.
    """

    CASES = [
        ("get_receiver_transport_state",
         "av.openhome.org-Receiver-1", "urn:av-openhome-org:service:Receiver:1#TransportState"),
        ("get_receiver_sender_uri",
         "av.openhome.org-Receiver-1", "urn:av-openhome-org:service:Receiver:1#Sender"),
        ("stop_receiver",
         "av.openhome.org-Receiver-1", "urn:av-openhome-org:service:Receiver:1#Stop"),
        ("get_sender_status2",
         "av.openhome.org-Sender-2", "urn:av-openhome-org:service:Sender:2#Status2"),
        ("stop_playlist",
         "av.openhome.org-Playlist-1", "urn:av-openhome-org:service:Playlist:1#Stop"),
    ]

    @pytest.mark.parametrize("func_name,service_path,soapaction", CASES)
    def test_helper_uses_documented_service_and_action(self, func_name, service_path, soapaction):
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            getattr(songcast_disband, func_name)("1.2.3.4", "udn")
        assert service_path in post.call_args[0][0]
        assert post.call_args[1]["headers"]["SOAPACTION"] == f'"{soapaction}"'

    def test_sender_role_query_uses_status2_not_status(self):
        """Sender.Status reports "Enabled" on every idle device and cannot
        identify the leader; Status2 ("Ready"/"Sending") is the real signal."""
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            songcast_disband.get_sender_status2("1.2.3.4", "udn")
        action = post.call_args[1]["headers"]["SOAPACTION"]
        assert action.endswith('#Status2"')
        assert not action.endswith('#Status"')

    def test_set_source_index_sends_Value_argument(self):
        """Product:4 declares SetSourceIndex in=['Value'] — not aIndex."""
        with patch("songcast_disband.requests.post", return_value=_FakeResponse()) as post:
            songcast_disband.set_source_index("1.2.3.4", "udn", 0)
        body = post.call_args[1]["data"]
        assert "<Value>0</Value>" in body
        assert "aIndex" not in body
        assert "av.openhome.org-Product-4" in post.call_args[0][0]


class TestSoapOutTagMatching:
    """_soap_out must match the local tag name exactly.

    A suffix match would let <SystemName> satisfy a request for "Name" — the
    same defect that made query_sources.py's SystemName fallback unreachable.
    """

    RESP = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        '<u:SourceResponse xmlns:u="urn:av-openhome-org:service:Product:4">'
        "<SystemName>Songcast</SystemName><Name>Kitchen</Name>"
        "</u:SourceResponse></s:Body></s:Envelope>"
    )

    def test_exact_name_not_systemname(self):
        assert songcast_disband._soap_out(self.RESP, "Name") == "Kitchen"

    def test_systemname_read_separately(self):
        assert songcast_disband._soap_out(self.RESP, "SystemName") == "Songcast"

    def test_reads_a_genuinely_namespaced_output_argument(self):
        resp = (
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            '<u:TransportStateResponse xmlns:u="urn:av-openhome-org:service:Receiver:1">'
            "<u:Value>Playing</u:Value>"
            "</u:TransportStateResponse></s:Body></s:Envelope>"
        )
        assert songcast_disband._soap_out(resp, "Value") == "Playing"

    def test_does_not_double_unescape(self):
        """ElementTree already decodes entities; a second pass corrupts values.

        A source literally named 'AT&T' arrives on the wire as AT&amp;amp;T.
        """
        wire = "<Body><Name>AT&amp;amp;T</Name></Body>"
        assert songcast_disband._soap_out(wire, "Name") == "AT&amp;T"
        wire2 = "<Body><Name>Bar &amp;copy; Grill</Name></Body>"
        assert songcast_disband._soap_out(wire2, "Name") == "Bar &copy; Grill"


class TestPartialReceiverClearIsAFailure:
    """Clearing the sender URI and stopping the receiver must BOTH succeed.

    The clear is what releases a zombie receiver; the stop alone does not. If
    either fails the receiver may still be bound, so a partial result is a
    failure, not a success.
    """

    def _run(self, cleared, stopped):
        with patch("songcast_disband.classify_devices") as cls, \
             patch("songcast_disband.clear_receiver_sender", return_value=cleared), \
             patch("songcast_disband.stop_receiver", return_value=stopped), \
             patch("songcast_disband.set_source_index", return_value=True), \
             patch("songcast_disband.get_current_source",
                   return_value={"index": 0, "type": "Playlist", "name": "Playlist"}), \
             patch("songcast_disband.get_receiver_sender_uri", return_value=""), \
             patch("songcast_disband.get_sender_status2", return_value="Ready"):
            cls.return_value = [{
                "ip": "10.0.0.3", "udn": "u", "name": "Tin Hut", "role": "receiver",
                "source": {"index": 3, "type": "Receiver", "name": "Songcast"},
            }]
            return songcast_disband.disband_group([{"ip": "10.0.0.3", "udn": "u"}])

    def test_both_succeed_is_success(self):
        assert self._run(True, True) is True

    def test_clear_fails_is_failure(self):
        assert self._run(False, True) is False

    def test_stop_fails_is_failure(self):
        assert self._run(True, False) is False

    def test_both_fail_is_failure(self):
        assert self._run(False, False) is False


class TestUnreadableDevicesFailTheRun:
    """A device that cannot be read is not the same as a device that is idle.

    Every query helper returns None on failure, so an unreachable fleet used to
    classify as all-standalone and report "No active Songcast group found" with
    exit 0 — indistinguishable from a genuinely idle system, and the same shape
    the three invented action names took before they were found.
    """

    def test_unreadable_device_is_classified_as_unreadable(self):
        with patch("songcast_disband.get_device_name", return_value="Study"), \
             patch("songcast_disband.get_current_source", return_value=None), \
             patch("songcast_disband.get_sender_status2", return_value=None):
            result = songcast_disband.classify_devices([{"ip": "10.0.0.2", "udn": "u"}])
        assert result[0]["role"] == "unreadable"

    def test_answering_device_is_still_standalone(self):
        with patch("songcast_disband.get_device_name", return_value="Study"), \
             patch("songcast_disband.get_current_source",
                   return_value={"index": 0, "type": "Playlist", "name": "Playlist"}), \
             patch("songcast_disband.get_sender_status2", return_value="Ready"):
            result = songcast_disband.classify_devices([{"ip": "10.0.0.2", "udn": "u"}])
        assert result[0]["role"] == "standalone"

    def test_disband_fails_when_a_device_is_unreadable(self):
        with patch("songcast_disband.get_device_name", return_value="Study"), \
             patch("songcast_disband.get_current_source", return_value=None), \
             patch("songcast_disband.get_sender_status2", return_value=None):
            assert songcast_disband.disband_group([{"ip": "10.0.0.2", "udn": "u"}]) is False

    def test_total_query_failure_does_not_report_success(self):
        """End to end: every SOAP call raising must not yield exit 0."""
        with patch("songcast_disband.requests.post",
                   side_effect=requests.RequestException("unreachable")), \
             patch("songcast_disband.requests.get",
                   side_effect=requests.RequestException("unreachable")):
            assert songcast_disband.disband_group(
                [{"ip": "10.0.0.2", "udn": "a"}, {"ip": "10.0.0.3", "udn": "b"}]) is False
