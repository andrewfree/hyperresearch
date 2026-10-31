"""The viewer answers only requests addressed to a loopback name (DNS rebinding).

A page on an attacker's domain can re-point that domain at 127.0.0.1 and then
read the viewer same-origin. The browser still sends the attacker's hostname in
Host, so that header is what tells the two apart.
"""

from __future__ import annotations

import socket
from threading import Thread

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.server import HyperresearchHandler, HyperresearchServer


@pytest.fixture
def address(tmp_vault, monkeypatch):
    write_note(tmp_vault.notes_dir, "Secret", body="top secret body")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    monkeypatch.setattr(HyperresearchHandler, "vault", tmp_vault)
    with HyperresearchServer(("127.0.0.1", 0), HyperresearchHandler) as server:
        serving = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        serving.start()
        try:
            yield server.server_address
        finally:
            server.shutdown()
            serving.join(5)


def _raw_get(address, target: str, host: str | None) -> tuple[int, bytes]:
    request = f"GET {target} HTTP/1.1\r\n"
    if host is not None:
        request += f"Host: {host}\r\n"
    request += "Connection: close\r\n\r\n"
    with socket.create_connection(address, timeout=5) as client:
        client.sendall(request.encode("latin-1"))
        chunks = []
        while chunk := client.recv(65536):
            chunks.append(chunk)
    response = b"".join(chunks)
    return int(response.split(b" ", 2)[1]), response


@pytest.mark.parametrize("path", ["/note/secret", "/", "/api/graph", "/search?q=secret"])
def test_foreign_host_is_refused_without_vault_content(address, path):
    status, response = _raw_get(address, path, f"evil.example:{address[1]}")

    assert status == 403
    assert b"top secret body" not in response
    # The nav lists recent note titles on every HTML page.
    assert b"Secret" not in response


def test_absolute_form_target_with_foreign_host_is_refused(address):
    status, response = _raw_get(address, "http://evil.example/note/secret", "evil.example")

    assert status == 403
    assert b"top secret body" not in response


def test_absolute_form_target_is_checked_even_with_a_loopback_host_header(address):
    """RFC 9112 makes an absolute-form target's authority the request's host,
    so a loopback Host header alone does not let it through."""
    status, _ = _raw_get(address, "http://evil.example/note/secret", f"127.0.0.1:{address[1]}")

    assert status == 403


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:{port}", "localhost:{port}", "LOCALHOST:{port}", "[::1]:{port}", "localhost", "localhost:9000"],
)
def test_loopback_hosts_are_served(address, host):
    """Any port is accepted: an SSH tunnel such as `ssh -L 9000:127.0.0.1:8080`
    makes the browser send its own local port, and an attacker cannot make a
    browser send a loopback name for a page it serves."""
    status, response = _raw_get(address, "/note/secret", host.format(port=address[1]))

    assert status == 200
    assert b"top secret body" in response


def test_request_without_host_is_served(address):
    """Browsers always send Host, so a request without one is not a rebinding
    attempt; HTTP/1.0 tools that omit it keep working."""
    with socket.create_connection(address, timeout=5) as client:
        client.sendall(b"GET /note/secret HTTP/1.0\r\n\r\n")
        response = b"".join(iter(lambda: client.recv(65536), b""))

    assert response.startswith(b"HTTP/1.0 200")
    assert b"top secret body" in response
