"""Exercise Winsock's wildcard guard without Windows or real socket binds."""

import errno
import socket
from http.server import ThreadingHTTPServer

import pytest

from hyperresearch.serve import server as viewer


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setattr(viewer, "_WINDOWS_WILDCARD_PROBES", True)
    events = []
    failures = {}

    class Probe:
        def __init__(self, family, kind):
            self.family = family
            events.append(("socket", family, kind))
            if (family, "socket") in failures:
                raise failures[family, "socket"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append(("close", self.family))

        def setsockopt(self, level, option, value):
            events.append(("option", self.family, level, option, value))
            if (self.family, "option") in failures:
                raise failures[self.family, "option"]

        def bind(self, address):
            events.append(("bind", self.family, address))
            if (self.family, "bind") in failures:
                raise failures[self.family, "bind"]

    monkeypatch.setattr(viewer.socket, "socket", Probe)

    def connect(address, timeout):
        events.append(("connect", address, timeout))
        if "connect" in failures:
            raise failures["connect"]
        return Probe(socket.AF_INET, socket.SOCK_STREAM)

    monkeypatch.setattr(viewer.socket, "create_connection", connect)
    monkeypatch.setattr(ThreadingHTTPServer, "server_bind", lambda self: events.append(("server_bind",)))
    return events, failures


def _bind(port=8123):
    server = viewer.HyperresearchServer.__new__(viewer.HyperresearchServer)
    server.server_address = ("127.0.0.1", port)
    server.server_bind()


def test_windows_probes_both_wildcards_without_reuseaddr(probes):
    events, _ = probes
    _bind()
    assert events == [
        ("socket", socket.AF_INET, socket.SOCK_STREAM),
        ("bind", socket.AF_INET, ("0.0.0.0", 8123)),
        ("close", socket.AF_INET),
        ("socket", socket.AF_INET6, socket.SOCK_STREAM),
        ("option", socket.AF_INET6, socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0),
        ("bind", socket.AF_INET6, ("::", 8123)),
        ("close", socket.AF_INET6),
        ("server_bind",),
    ]


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_windows_occupied_wildcard_refuses_loopback_bind(probes, family):
    events, failures = probes
    failures[family, "bind"] = OSError(10048, "Address already in use")
    with pytest.raises(OSError) as exc:
        _bind()
    assert exc.value.errno == errno.EADDRINUSE
    assert ("server_bind",) not in events
    assert ("close", family) in events


@pytest.mark.parametrize("stage", ["socket", "option", "bind"])
@pytest.mark.parametrize("code", [errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL, errno.EACCES])
def test_windows_without_ipv6_can_still_serve(probes, stage, code):
    events, failures = probes
    failures[socket.AF_INET6, stage] = OSError(code, "IPv6 unavailable")
    _bind()
    assert events[-1] == ("server_bind",)
    if stage != "socket":
        assert ("close", socket.AF_INET6) in events


def test_windows_ephemeral_port_needs_no_probe(probes):
    events, _ = probes
    _bind(port=0)
    assert events == [("server_bind",)]


def test_windows_occupied_probe_is_refused_even_if_connections_are_refused(probes):
    events, failures = probes
    failures[socket.AF_INET6, "bind"] = OSError(10048, "Address already in use")
    failures["connect"] = ConnectionRefusedError(10061, "Connection refused")
    with pytest.raises(OSError) as exc:
        _bind()
    assert exc.value.errno == errno.EADDRINUSE
    assert ("server_bind",) not in events
    assert not any(event[0] == "connect" for event in events)


@pytest.mark.parametrize("error", [TimeoutError("full backlog"), OSError(errno.EACCES, "denied")])
def test_windows_unreachable_ipv4_holder_is_not_hijacked(probes, error):
    events, failures = probes
    failures[socket.AF_INET6, "bind"] = OSError(10048, "Address already in use")
    failures["connect"] = error
    with pytest.raises(OSError, match="Address already in use"):
        _bind()
    assert ("server_bind",) not in events
