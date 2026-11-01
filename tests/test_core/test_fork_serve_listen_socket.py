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
    for _ in range(10):
        with _ipv6_listener(1) as other:
            port = other.getsockname()[1]
            # IPv6's ephemeral port may already be occupied in IPv4.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as e:
                    if e.errno != errno.EADDRINUSE:
                        raise
                    continue
            assert not _answers_loopback(port), "premise: the other listener ignores 127.0.0.1"

            with HyperresearchServer(("127.0.0.1", port), HyperresearchHandler) as server:
                assert server.server_address == ("127.0.0.1", port)
            return
    pytest.fail("could not find a port free in both IPv4 and IPv6")


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


def _status_line(client: socket.socket) -> str:
    try:
        client.sendall(b"GET /api/graph HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        with client.makefile("rb") as reader:
            return reader.readline().decode("latin-1").strip()
    except OSError as e:
        return type(e).__name__


def test_burst_of_clients_waits_in_the_queue_instead_of_being_reset(tmp_vault, monkeypatch):
    """Connections that arrive before the server accepts them wait in the
    listen queue. socketserver's default queue of 5 made macOS reset every
    connection past the first handful, so a burst of 32 clients mostly
    failed with ECONNRESET."""
    monkeypatch.setattr(HyperresearchHandler, "vault", tmp_vault)
    with HyperresearchServer(("127.0.0.1", 0), HyperresearchHandler) as server:
        clients, refused = [], []
        for _ in range(64):
            try:
                clients.append(socket.create_connection(server.server_address, timeout=2))
            except OSError as e:
                refused.append(type(e).__name__)
        serving = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        serving.start()
        try:
            statuses = [_status_line(client) for client in clients]
        finally:
            server.shutdown()
            serving.join(5)
            for client in clients:
                client.close()

    assert refused == []
    assert statuses == ["HTTP/1.0 200 OK"] * 64
