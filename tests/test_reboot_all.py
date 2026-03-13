#!/usr/bin/env python3
"""
Tests for reboot_all.py script

Run with: python -m pytest tests/test_reboot_all.py -v
"""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import Mock, patch, AsyncMock

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

    def test_location_url_format(self):
        """Test that location URL is correctly formatted"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"
        expected = f"http://{ip}:55178/{udn}/Upnp/device.xml"
        actual = reboot_all._location(ip, udn)
        assert actual == expected

    @pytest.mark.asyncio
    async def test_reboot_device_creates_correct_location(self):
        """Test that reboot_device creates Device with correct location URL"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"
        expected_location = f"http://{ip}:55178/{udn}/Upnp/device.xml"

        with patch('reboot_all.Device') as MockDevice:
            mock_dev = AsyncMock()
            mock_product = AsyncMock()
            mock_action = AsyncMock()
            
            MockDevice.return_value = mock_dev
            mock_dev.init = AsyncMock()
            mock_dev.device.service_id.return_value = mock_product
            mock_product.action.return_value = mock_action
            mock_action.async_call = AsyncMock()

            await reboot_all.reboot_device(ip, udn)
            
            # Verify Device was created with correct location
            MockDevice.assert_called_once_with(expected_location)
            # Verify init was called
            mock_dev.init.assert_called_once()

    @pytest.mark.asyncio
    async def test_reboot_device_calls_reboot_action(self):
        """Test that reboot_device calls the Reboot action"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"

        with patch('reboot_all.Device') as MockDevice:
            mock_dev = AsyncMock()
            mock_product = AsyncMock()
            mock_reboot_action = AsyncMock()
            mock_standby_action = AsyncMock()
            
            MockDevice.return_value = mock_dev
            mock_dev.init = AsyncMock()
            mock_dev.device.service_id.return_value = mock_product
            
            def mock_action(action_name):
                if action_name == "Reboot":
                    return mock_reboot_action
                elif action_name == "SetStandby":
                    return mock_standby_action
                return AsyncMock()
            
            mock_product.action = mock_action
            mock_reboot_action.async_call = AsyncMock()
            mock_standby_action.async_call = AsyncMock()

            await reboot_all.reboot_device(ip, udn)
            
            # Verify Reboot action was called
            mock_reboot_action.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_reboot_device_handles_exceptions(self):
        """Test that reboot_device handles exceptions gracefully"""
        ip = "172.24.32.211"
        udn = "4c494e4e-0026-0f22-5661-01531488013f"

        with patch('reboot_all.Device') as MockDevice:
            MockDevice.side_effect = Exception("Connection failed")
            
            # Should not raise exception, just print error
            await reboot_all.reboot_device(ip, udn)

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
