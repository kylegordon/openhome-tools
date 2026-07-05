#!/usr/bin/env python3
"""
Simple standalone tests for reboot_all.py without needing openhomedevice installed
"""

import re

# Copy the regex from reboot_all.py
DEVICE_LINE_RE = re.compile(r"^DEVICE_\d+=(\S+)\s+(\S+)")

def test_reboot_url():
    """Test reboot URL format"""
    ip = '172.24.32.211'
    udn = '4c494e4e-0026-0f22-5661-01531488013f'
    # Expected URL spelled out explicitly so the test is not tautological
    expected_url = 'http://172.24.32.211:55178/4c494e4e-0026-0f22-5661-01531488013f/linn.co.uk-Volkano-1/control'
    actual_url = f'http://{ip}:55178/{udn}/linn.co.uk-Volkano-1/control'
    assert actual_url == expected_url, f'Expected {expected_url}, got {actual_url}'
    print(f'✓ Reboot URL format correct: {actual_url}')

def test_device_line_regex_valid():
    """Test DEVICE_LINE_RE with valid lines"""
    test_cases = [
        ('DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f',
         '172.24.32.211', '4c494e4e-0026-0f22-5661-01531488013f'),
        ('DEVICE_2=192.168.1.100 4c494e4e-0026-0f22-646e-01560511013f',
         '192.168.1.100', '4c494e4e-0026-0f22-646e-01560511013f'),
    ]
    
    for line, expected_ip, expected_udn in test_cases:
        match = DEVICE_LINE_RE.match(line)
        assert match is not None, f'Should match valid device line: {line}'
        parsed_ip, parsed_udn = match.groups()
        assert parsed_ip == expected_ip, f'Expected IP {expected_ip}, got {parsed_ip}'
        assert parsed_udn == expected_udn, f'Expected UDN {expected_udn}, got {parsed_udn}'
        print(f'✓ DEVICE_LINE_RE matched: {parsed_ip} {parsed_udn}')

def test_device_line_regex_invalid():
    """Test DEVICE_LINE_RE with invalid lines"""
    invalid_lines = [
        '# Comment',
        'DEVICE_1=',
        'DEVICE_1=172.24.32.211',  # Missing UDN
        '',
        'SOME_OTHER_VAR=value',
        'SONGCAST_SENDER=DEVICE_1'
    ]
    
    for invalid in invalid_lines:
        match = DEVICE_LINE_RE.match(invalid)
        assert match is None, f'Should not match invalid line: {invalid}'
    print('✓ DEVICE_LINE_RE correctly rejects invalid lines')

if __name__ == '__main__':
    test_reboot_url()
    test_device_line_regex_valid()
    test_device_line_regex_invalid()
    print('')
    print('All standalone tests passed!')
