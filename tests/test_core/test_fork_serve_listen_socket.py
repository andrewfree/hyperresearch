"""The viewer's listening socket: never share a port that another process answers on."""

from __future__ import annotations

import errno
import socket
from http.client import HTTPConnection
from threading import Thread

import pytest

from hyperresearch.serve.server import HyperresearchHandler, HyperresearchServer


def _ipv6_listener(v6only: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("no IPv6 on this host")
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, v6only)
        sock.bind(("::", 0))
    except OSError as e:
        sock.close()
        pytest.skip(f"cannot bind an IPv6 wildcard with IPV6_V6ONLY={v6only}: {e}")
    sock.listen(1)
    return sock


def _ipv4_wildcard_listener() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    return sock


def _answers_loopback(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.parametrize(
    "make_listener",
    [_ipv4_wildcard_listener, lambda: _ipv6_listener(0)],
    ids=["0.0.0.0", "dual-stack ::"],
)
def test_port_held_by_a_wildcard_listener_is_refused(make_listener):
    """BSD and macOS let a SO_REUSEADDR bind to 127.0.0.1 succeed beside another
    process's wildcard listener, and the more specific bind then receives all
    of that process's 127.0.0.1 connections. A plain bind would fail."""
    with make_listener() as other:
        port = other.getsockname()[1]
        assert _answers_loopback(port), "premise: the other listener answers 127.0.0.1"

        with pytest.raises(OSError) as exc:
            HyperresearchServer(("127.0.0.1", port), HyperresearchHandler)

        assert exc.value.errno == errno.EADDRINUSE


def test_ipv6_only_listener_does_not_block_the_port():
    """An IPv6-only wildcard listener never sees 127.0.0.1 traffic, so there is
    nothing to take from it and the port stays usable."""
    with _ipv6_listener(1) as other:
        port = other.getsockname()[1]
        assert not _answers_loopback(port), "premise: the other listener ignores 127.0.0.1"

        with HyperresearchServer(("127.0.0.1", port), HyperresearchHandler) as server:
            assert server.server_address == ("127.0.0.1", port)


def test_port_is_reclaimed_right_after_the_previous_server_closed(tmp_vault, monkeypatch):
    """SO_REUSEADDR exists so a restart can bind over the previous run's
    TIME_WAIT connections; the wildcard check must keep that working."""
    monkeypatch.setattr(HyperresearchHandler, "vault", tmp_vault)
    with HyperresearchServer(("127.0.0.1", 0), HyperresearchHandler) as first:
        port = first.server_address[1]
        worker = Thread(target=first.handle_request)
        worker.start()
        client = HTTPConnection("127.0.0.1", port, timeout=5)
        client.request("GET", "/")
        assert client.getresponse().status == 200
        client.close()
        worker.join(5)

    with HyperresearchServer(("127.0.0.1", port), HyperresearchHandler) as second:
        assert second.server_address == ("127.0.0.1", port)
