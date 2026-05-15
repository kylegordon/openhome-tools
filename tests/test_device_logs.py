#!/usr/bin/env python3
"""
Tests for device_logs.py log parsing, classification, and env loading.

Run with: python -m pytest tests/test_device_logs.py -v
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import device_logs


# --- Log line classification tests ---

class TestClassifyLine:
    def test_hls_lines(self):
        assert device_logs.classify_line("HlsPlaylistParser: segment 5 loaded") == "HLS"
        assert device_logs.classify_line("HlsM3uReader: parsing manifest") == "HLS"
        assert device_logs.classify_line("PlaylistProvider: next segment") == "HLS"
        assert device_logs.classify_line("HlsReloadTimer: scheduling reload") == "HLS"

    def test_http_lines(self):
        assert device_logs.classify_line("UriLoader:: status code: 200 aUri: http://example.com") == "HTTP"

    def test_pipeline_lines(self):
        assert device_logs.classify_line("Pipeline report property xyz") == "PIPELINE"

    def test_container_lines(self):
        assert device_logs.classify_line("Id3v2: reading tag") == "CONTAINER"
        assert device_logs.classify_line("Mpeg4Container: parsing moov") == "CONTAINER"
        assert device_logs.classify_line("MpegTs: syncing") == "CONTAINER"
        assert device_logs.classify_line("SegmentStreamer: buffering") == "CONTAINER"

    def test_songcast_lines(self):
        assert device_logs.classify_line("OhmReceiver: connected") == "SONGCAST"
        assert device_logs.classify_line("Sender: audio started") == "SONGCAST"

    def test_codec_lines(self):
        assert device_logs.classify_line("Codec: Flac detected") == "CODEC"
        assert device_logs.classify_line("Decoder: initializing Aac") == "CODEC"

    def test_volume_lines(self):
        assert device_logs.classify_line("Volume: set to 45") == "VOLUME"
        assert device_logs.classify_line("Mute: toggled") == "VOLUME"

    def test_transport_lines(self):
        assert device_logs.classify_line("Transport: Play command") == "TRANSPORT"

    def test_error_lines(self):
        assert device_logs.classify_line("Connection error: timeout") == "ERROR"
        assert device_logs.classify_line("Exception in handler") == "ERROR"
        assert device_logs.classify_line("Socket connection refused") == "ERROR"

    def test_hls_no_more_segments_classified_as_hls(self):
        """HlsNoMoreSegments should be HLS, not ERROR despite 'error'-like context"""
        assert device_logs.classify_line("HlsNoMoreSegments: end of stream") == "HLS"

    def test_other_lines(self):
        assert device_logs.classify_line("some random debug output") == "OTHER"
        assert device_logs.classify_line("") == "OTHER"


# --- HTTP status extraction tests ---

class TestExtractHttpStatus:
    def test_extract_status_code(self):
        assert device_logs.extract_http_status("code: 200 OK") == 200
        assert device_logs.extract_http_status("status: 404 Not Found") == 404

    def test_no_status_code(self):
        assert device_logs.extract_http_status("no status here") is None
        assert device_logs.extract_http_status("") is None


# --- URI extraction tests ---

class TestExtractUri:
    def test_extract_uri(self):
        line = "UriLoader:: aUri: http://stream.example.com/audio.flac"
        assert device_logs.extract_uri(line) == "http://stream.example.com/audio.flac"

    def test_no_uri(self):
        assert device_logs.extract_uri("no uri here") is None


# --- .env loading tests ---

class TestLoadDevicesFromEnv:
    def test_load_device_entries(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
            "DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f\n"
        )
        devices = device_logs.load_devices_from_env(str(env))
        assert len(devices) == 2
        assert devices[0]["ip"] == "172.24.32.211"
        assert devices[0]["udn"] == "4c494e4e-0026-0f22-5661-01531488013f"
        assert devices[0]["id"] == "DEVICE_1"
        assert devices[1]["ip"] == "172.24.32.210"

    def test_skips_non_device_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
            "SONGCAST_SENDER=DEVICE_1\n"
            "SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3\n"
        )
        devices = device_logs.load_devices_from_env(str(env))
        assert len(devices) == 1

    def test_skips_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# This is a comment\n"
            "\n"
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
        )
        devices = device_logs.load_devices_from_env(str(env))
        assert len(devices) == 1

    def test_empty_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# only comments\n")
        devices = device_logs.load_devices_from_env(str(env))
        assert len(devices) == 0

    def test_ip_only_line_skipped(self, tmp_path):
        """Lines with only IP (no UDN) should be skipped for device_logs"""
        env = tmp_path / ".env"
        env.write_text("DEVICE_1=172.24.32.211\n")
        devices = device_logs.load_devices_from_env(str(env))
        assert len(devices) == 0


# --- DeviceLogCapture unit tests (no network) ---

class TestDeviceLogCapture:
    def test_init_defaults(self):
        cap = device_logs.DeviceLogCapture("DEVICE_1", "172.24.32.211", "udn-1")
        assert cap.device_id == "DEVICE_1"
        assert cap.ip == "172.24.32.211"
        assert cap.port == 2323
        assert cap.max_lines == 5000
        assert cap.running is False
        assert cap.connected is False

    def test_init_custom_port(self):
        cap = device_logs.DeviceLogCapture("DEVICE_1", "172.24.32.211", "udn-1", port=9999)
        assert cap.port == 9999

    def test_filter_subsystems_uppercased(self):
        cap = device_logs.DeviceLogCapture(
            "DEVICE_1", "172.24.32.211", "udn-1",
            filter_subsystems=["hls", "error"]
        )
        assert cap.filter_subsystems == ["HLS", "ERROR"]

    def test_generate_analysis_empty(self):
        """Analysis report should work even with no captured data"""
        from datetime import datetime
        cap = device_logs.DeviceLogCapture("DEVICE_1", "172.24.32.211", "udn-1")
        cap.start_time = datetime(2026, 5, 15, 12, 0, 0)
        cap.end_time = datetime(2026, 5, 15, 12, 1, 0)
        report = cap.generate_analysis()
        assert "DEVICE_1" in report
        assert "172.24.32.211" in report
        assert "No data captured" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
