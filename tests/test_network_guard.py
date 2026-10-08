"""The socket guard in conftest.py: no test reaches the network (T-21, Q16)."""

import socket

import httpx
import pytest


def test_a_socket_connection_to_localhost_raises():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="T-21"):
            sock.connect(("127.0.0.1", 3300))


def test_connect_ex_raises_instead_of_returning_an_error_code():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="T-21"):
            sock.connect_ex(("127.0.0.1", 3300))


def test_create_connection_raises():
    with pytest.raises(RuntimeError, match="T-21"):
        socket.create_connection(("127.0.0.1", 3300), timeout=1)


def test_a_name_lookup_raises_so_no_dns_query_leaves_the_machine():
    with pytest.raises(RuntimeError, match="T-21"):
        socket.getaddrinfo("api.anthropic.com", 443)


def test_an_http_get_through_httpx_raises():
    """The guard holds under the HTTP library the client will use, not only raw sockets."""
    with pytest.raises(RuntimeError, match="T-21"):
        httpx.get("http://localhost:3300/corridor-scout/api/health", timeout=1)


def test_the_guard_error_is_not_a_connection_refused():
    """A refused connection means "tunnel down" (T-18); the guard must never pass for one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError) as caught:
            sock.connect(("127.0.0.1", 3300))
    assert not isinstance(caught.value, OSError)
