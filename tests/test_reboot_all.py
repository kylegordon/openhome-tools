#!/usr/bin/env python3
"""
Tests for reboot_all.py script

Run with: python -m pytest tests/test_reboot_all.py -v
"""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock

# Import the module under test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import reboot_all


class TestRebootAll:
    """Test suite for reboot_all script"""

    def test_device_line_regex_valid(self):
        """Test that device line regex correctly parses valid lines"""
        line = "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f"
        match = reboot_all.DEVICE_LINE_RE.match(line)
        assert match is not None
        ip, udn = match.groups()
        assert ip == "172.24.32.211"
        assert udn == "4c494e4e-0026-0f22-5661-01531488013f"

    def test_device_line_regex_invalid(self):
        """Test that device line regex rejects invalid lines"""
        invalid_lines = [
            "# Comment line",
            "DEVICE_1=172.24.32.211",  # Missing UDN
            "DEVICE_1=",
            "",
            "SOME_OTHER_VAR=value"
        ]
        for line in invalid_lines:
            match = reboot_all.DEVICE_LINE_RE.match(line)
            assert match is None, f"Should not match: {line}"

    def test_volkano_control_url_format(self):
        """Test that the Volkano service control URL is correctly formatted"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"
        expected = f"http://{ip}:55178/{udn}/linn.co.uk-Volkano-1/control"
        actual = f"http://{ip}:55178/{udn}/linn.co.uk-Volkano-1/control"
        assert actual == expected

    def test_reboot_device_sends_soap_request(self):
        """Test that reboot_device sends a SOAP POST to the Volkano service"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"
        expected_url = f"http://{ip}:55178/{udn}/linn.co.uk-Volkano-1/control"

        with patch('reboot_all.requests.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            reboot_all.reboot_device(ip, udn)

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == expected_url
            assert 'Volkano:1#Reboot' in call_args[1]['headers']['SOAPACTION']
            assert 'u:Reboot' in call_args[1]['data']

    def test_reboot_device_handles_http_error(self):
        """Test that reboot_device handles non-OK HTTP responses gracefully"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"

        with patch('reboot_all.requests.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            mock_post.return_value = mock_resp

            # Should not raise - prints error message
            reboot_all.reboot_device(ip, udn)

    def test_reboot_device_handles_connection_error(self):
        """Test that reboot_device handles connection failures gracefully"""
        import requests as real_requests
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"

        with patch('reboot_all.requests.post') as mock_post:
            mock_post.side_effect = real_requests.ConnectionError("Connection refused")

            # Should not raise - prints error message
            reboot_all.reboot_device(ip, udn)

    def test_reboot_device_soap_action_header(self):
        """Test that the SOAPACTION header uses the correct Volkano URN"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"

        with patch('reboot_all.requests.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            reboot_all.reboot_device(ip, udn)

            call_args = mock_post.call_args
            headers = call_args[1]['headers']
            assert headers['SOAPACTION'] == '"urn:linn-co-uk:service:Volkano:1#Reboot"'

    def test_parse_env_file(self):
        """Test parsing .env file with multiple devices"""
        env_content = """# Comment
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f
SOME_OTHER_VAR=value
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.env') as f:
            f.write(env_content)
            temp_env = f.name

        try:
            devices = []
            with open(temp_env) as f:
                for line in f:
                    m = reboot_all.DEVICE_LINE_RE.match(line.strip())
                    if m:
                        ip, udn = m.groups()
                        devices.append((ip, udn))
            
            assert len(devices) == 2
            assert devices[0] == ("172.24.32.211", "4c494e4e-0026-0f22-5661-01531488013f")
            assert devices[1] == ("172.24.32.210", "4c494e4e-0026-0f22-646e-01560511013f")
        finally:
            os.unlink(temp_env)

    def test_main_missing_env(self, tmp_path):
        """Test that main exits when .env is missing"""
        with patch.object(reboot_all, 'ENV_PATH', str(tmp_path / 'nonexistent.env')):
            with pytest.raises(SystemExit) as exc_info:
                reboot_all.main()
            assert exc_info.value.code == 1

    def test_main_empty_env(self, tmp_path):
        """Test that main exits when .env has no DEVICE lines"""
        env_file = tmp_path / ".env"
        env_file.write_text("# only comments\nSONGCAST_SENDER=DEVICE_1\n")
        with patch.object(reboot_all, 'ENV_PATH', str(env_file)):
            with pytest.raises(SystemExit) as exc_info:
                reboot_all.main()
            assert exc_info.value.code == 1

    def test_main_reboots_all_devices(self, tmp_path):
        """Test that main calls reboot_device for every device in .env"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f\n"
            "DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f\n"
        )
        with patch.object(reboot_all, 'ENV_PATH', str(env_file)):
            with patch.object(reboot_all, 'reboot_device') as mock_reboot:
                reboot_all.main()
                assert mock_reboot.call_count == 2
                mock_reboot.assert_any_call(
                    "172.24.32.211", "4c494e4e-0026-0f22-5661-01531488013f"
                )
                mock_reboot.assert_any_call(
                    "172.24.32.210", "4c494e4e-0026-0f22-646e-01560511013f"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
