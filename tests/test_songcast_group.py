#!/usr/bin/env python3
"""
Tests for songcast_group.py

Run with:
    .venv/bin/python -m pytest tests/test_songcast_group.py -v
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

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


class TestUriFromDidl:
    """Sender.Metadata is the authoritative source for a sender's ohz:// URI.

    The sender identifier in that URI is not always the bare device UDN, so it
    cannot be reconstructed from the UDN alone — it has to be read from the
    <res> element of the descriptor the sender advertises.
    """

    # Verbatim response from Sender.Metadata on a real Linn DSM.
    REAL = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"'
        ' xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="0" restricted="True">'
        "<dc:title>Linn Study</dc:title>"
        '<res protocolInfo="ohz:*:*:u">'
        "ohz://239.255.255.250:51972/4c494e4e-0026-0f22-5661-01531488013f</res>"
        "<upnp:albumArtURI>http://172.24.32.211:55178/x/icons/1022.png</upnp:albumArtURI>"
        "<upnp:class>object.item.audioItem</upnp:class>"
        "</item></DIDL-Lite>"
    )

    def test_extracts_ohz_uri_from_real_sender_metadata(self):
        assert songcast_group._uri_from_didl(self.REAL) == (
            "ohz://239.255.255.250:51972/4c494e4e-0026-0f22-5661-01531488013f"
        )

    def test_extracts_non_udn_sender_identifier(self):
        # The identifier in the URI is not always the bare device UDN, so
        # constructing the URI from the UDN can produce the wrong address.
        didl = self.REAL.replace("51972/4c494e4e", "51972/softsender-4c494e4e")
        assert songcast_group._uri_from_didl(didl) == (
            "ohz://239.255.255.250:51972/softsender-4c494e4e-0026-0f22-5661-01531488013f"
        )

    def test_undeclared_namespace_still_parses(self):
        didl = (
            '<DIDL-Lite><item><res protocolInfo="ohz:*:*:u">'
            "ohz://239.255.255.250:51972/abc</res></item></DIDL-Lite>"
        )
        assert songcast_group._uri_from_didl(didl) == "ohz://239.255.255.250:51972/abc"

    def test_missing_res_returns_none(self):
        didl = "<DIDL-Lite><item><dc:title xmlns:dc='http://purl.org/dc/elements/1.1/'>x</dc:title></item></DIDL-Lite>"
        assert songcast_group._uri_from_didl(didl) is None

    def test_empty_res_is_ignored(self):
        didl = (
            '<DIDL-Lite><item><res protocolInfo="ohz:*:*:u"></res></item></DIDL-Lite>'
        )
        assert songcast_group._uri_from_didl(didl) is None

    def test_malformed_xml_returns_none_not_raises(self):
        assert songcast_group._uri_from_didl("<DIDL-Lite><item>") is None

    def test_empty_and_none_return_none(self):
        assert songcast_group._uri_from_didl("") is None
        assert songcast_group._uri_from_didl(None) is None


class TestUriFromDidlRejectsUntrustedInput:
    """Sender.Metadata is remote input, and whatever it yields is handed to
    Receiver.SetSender on a *different* device. It is validated, not trusted:
    rejection makes the caller fall back to the URI built from the UDN in .env.
    """

    @staticmethod
    def _didl(uri):
        return f'<DIDL-Lite><item><res protocolInfo="ohz:*:*:u">{uri}</res></item></DIDL-Lite>'

    def test_accepts_all_three_songcast_schemes(self):
        for uri in (
            "ohz://239.255.255.250:51972/abc",
            "ohm://239.255.255.250:51972/abc",
            "ohu://192.168.1.10:51972/abc",
        ):
            assert songcast_group._uri_from_didl(self._didl(uri)) == uri

    def test_rejects_non_songcast_schemes(self):
        for uri in (
            "http://evil.example/pwn",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "ohz",
            "/no/scheme/at/all",
        ):
            assert songcast_group._uri_from_didl(self._didl(uri)) is None

    def test_skips_bad_res_and_takes_a_valid_later_one(self):
        didl = (
            "<DIDL-Lite><item>"
            '<res protocolInfo="http-get:*:*:*">http://evil.example/pwn</res>'
            '<res protocolInfo="ohz:*:*:u">ohz://239.255.255.250:51972/good</res>'
            "</item></DIDL-Lite>"
        )
        assert songcast_group._uri_from_didl(didl) == "ohz://239.255.255.250:51972/good"

    def test_rejects_overlong_uri(self):
        long_uri = "ohz://239.255.255.250:51972/" + (
            "a" * songcast_group._MAX_URI_BYTES
        )
        assert songcast_group._uri_from_didl(self._didl(long_uri)) is None

    def test_rejects_oversized_descriptor_without_parsing(self):
        padding = "<!--" + ("x" * songcast_group._MAX_DIDL_BYTES) + "-->"
        didl = padding + self._didl("ohz://239.255.255.250:51972/abc")
        assert songcast_group._uri_from_didl(didl) is None


class TestUriFromDidlTagMatching:
    """<res> must be matched by exact local name.

    A suffix test also matches <xres> or <oh:sourceres>, so a sender could put a
    decoy earlier in the document and have it win over its real <res> — and the
    winner is fed straight to Receiver.SetSender on another device.
    """

    def test_decoy_xres_does_not_shadow_the_real_res(self):
        didl = (
            "<DIDL-Lite><item>"
            "<xres>ohz://239.255.255.250:51972/DECOY</xres>"
            '<res protocolInfo="ohz:*:*:u">ohz://239.255.255.250:51972/REAL</res>'
            "</item></DIDL-Lite>"
        )
        assert songcast_group._uri_from_didl(didl) == "ohz://239.255.255.250:51972/REAL"

    def test_namespaced_decoy_is_ignored(self):
        didl = (
            '<DIDL-Lite xmlns:oh="urn:example:oh"><item>'
            "<oh:sourceres>ohm://239.0.0.1:51972/DECOY</oh:sourceres>"
            "<res>ohz://239.255.255.250:51972/REAL</res>"
            "</item></DIDL-Lite>"
        )
        assert songcast_group._uri_from_didl(didl) == "ohz://239.255.255.250:51972/REAL"

    def test_namespaced_res_is_still_accepted(self):
        didl = (
            '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"><item>'
            "<res>ohz://239.255.255.250:51972/abc</res>"
            "</item></DIDL-Lite>"
        )
        assert songcast_group._uri_from_didl(didl) == "ohz://239.255.255.250:51972/abc"


class TestSenderDescriptorIsReadViaMetadata:
    """The sender's own descriptor comes from Sender.Metadata.

    The Sender service has no "Sender" action — that lives on Receiver. Calling
    a non-existent action raises KeyError inside async_upnp_client before any
    request is sent, and the surrounding except swallowed it for months.
    """

    @staticmethod
    def _no_sleep():
        """The join poll sleeps between attempts; unit tests must not wall-clock."""

        async def _instant(_seconds):
            return None

        return patch("songcast_group.asyncio.sleep", _instant)

    @staticmethod
    def _make_devices(metadata_value):
        real_didl = (
            '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
            '<item id="0" restricted="True">'
            '<res protocolInfo="ohz:*:*:u">'
            "ohz://239.255.255.250:51972/4c494e4e-sender</res>"
            "</item></DIDL-Lite>"
        )

        async def metadata_call():
            return {"Value": metadata_value or real_didl}

        sender_service = MagicMock()
        sender_service.action.return_value = MagicMock(async_call=metadata_call)

        sender_dev = MagicMock()
        sender_dev.device.service_id.return_value = sender_service

        async def room():
            return "Study"

        async def name():
            return "Majik DSM"

        sender_dev.room = room
        sender_dev.name = name

        async def recv_call(**kwargs):
            return {}

        recv_service = MagicMock()
        recv_service.action.return_value = MagicMock(async_call=recv_call)
        receiver_dev = MagicMock()
        receiver_dev.device.service_id.return_value = recv_service

        return receiver_dev, sender_dev, sender_service

    def test_sender_service_is_queried_with_the_Metadata_action(self):
        receiver_dev, sender_dev, sender_service = self._make_devices(None)
        with self._no_sleep(), patch("songcast_group.requests.post") as post:
            post.return_value = MagicMock(
                status_code=200, raise_for_status=lambda: None
            )
            asyncio.run(
                _grouper()._receiver_join(
                    receiver_dev,
                    sender_dev,
                    "1.2.3.4",
                    "recv-udn",
                    "4c494e4e-sender",
                    "Study",
                )
            )
        actions = [c.args[0] for c in sender_service.action.call_args_list]
        assert "Metadata" in actions, f"expected Sender.Metadata, got {actions}"
        assert "Sender" not in actions, "Sender service has no 'Sender' action"

    def test_advertised_uri_outranks_the_constructed_one(self):
        """The device's own answer must be tried first, not the UDN guess."""
        didl = (
            '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"><item>'
            "<res>ohz://239.255.255.250:51972/advertised-id</res>"
            "</item></DIDL-Lite>"
        )
        receiver_dev, sender_dev, _ = self._make_devices(didl)
        with self._no_sleep(), patch("songcast_group.requests.post") as post:
            post.return_value = MagicMock(
                status_code=200, raise_for_status=lambda: None
            )
            asyncio.run(
                _grouper()._receiver_join(
                    receiver_dev,
                    sender_dev,
                    "1.2.3.4",
                    "recv-udn",
                    "4c494e4e-sender",
                    "Study",
                )
            )
        first_body = post.call_args_list[0][1]["data"]
        assert "advertised-id" in first_body


class TestTransportStateOutputArgument:
    """Receiver.TransportState declares a single out-arg named "Value".

    The code used to read .get("TransportState") / .get("state"), neither of
    which the library ever returns, so every transport-state check silently
    evaluated as "not playing".
    """

    @staticmethod
    def _receiver_returning(state_dict):
        async def ts_call():
            return state_dict

        async def sender_call():
            return {"Uri": "", "Metadata": ""}

        svc = MagicMock()
        svc.action.side_effect = lambda n: {
            "TransportState": MagicMock(async_call=ts_call),
            "Sender": MagicMock(async_call=sender_call),
        }[n]
        dev = MagicMock()
        dev.device.service_id.return_value = svc
        return dev

    def test_playing_is_detected_from_the_Value_key(self):
        dev = self._receiver_returning({"Value": "Playing"})
        assert asyncio.run(_grouper()._is_grouped(dev)) is True

    def test_waiting_counts_as_grouped(self):
        """Waiting = bound to a sender that is not currently streaming."""
        dev = self._receiver_returning({"Value": "Waiting"})
        assert asyncio.run(_grouper()._is_grouped(dev)) is True

    def test_stopped_is_not_grouped(self):
        dev = self._receiver_returning({"Value": "Stopped"})
        assert asyncio.run(_grouper()._is_grouped(dev)) is False

    def test_legacy_key_is_not_consulted(self):
        """If the code still read "TransportState", this would wrongly pass."""
        dev = self._receiver_returning({"TransportState": "Playing"})
        assert asyncio.run(_grouper()._is_grouped(dev)) is False
