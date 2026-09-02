"""Shared pytest configuration.

Two jobs:

1. Put the repo root on sys.path so tests can import the top-level modules
   (previously duplicated in every test file).
2. Fail any unit test that tries to open a network socket.

(2) matters because CI runs this suite on a runner with no Linn devices on the
network. Several helpers reach for `requests` directly rather than going through
a mockable seam, so a test whose fixture stops being rejected early can silently
start depending on hardware — it passes locally and hangs or fails in CI. This
turns that into an immediate, obvious failure instead.

Tests that genuinely need a socket can request the `allow_network` fixture.
"""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_real_socket_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class NetworkAccessAttempted(AssertionError):
    """Raised when a unit test tries to talk to the network."""


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if "allow_network" in request.fixturenames:
        return

    def _blocked(*args, **kwargs):
        target = args[1] if len(args) > 1 else kwargs.get("address", "?")
        raise NetworkAccessAttempted(
            f"Unit test attempted a network connection to {target!r}. "
            "Patch the transport (requests.post / socket.socket) instead, or "
            "request the 'allow_network' fixture if the test genuinely needs it."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture
def allow_network(monkeypatch):
    """Opt back in to real sockets for a test that genuinely needs one."""
    monkeypatch.setattr(socket.socket, "connect", _real_socket_connect)
    monkeypatch.setattr(socket, "create_connection", _real_create_connection)
