"""client.py: one GET with a timeout; refused is "tunnel down", never "no data" (T-18, T-26)."""

import socket

import httpcore
import httpx
import pytest

from daily_review.client import (
    DEFAULT_TIMEOUT,
    Client,
    HttpError,
    Response,
    Timeout,
    TunnelDown,
    Unreachable,
)

BASE = "http://localhost:3300/corridor-scout/api"


def client_answering(handler) -> Client:
    """A Client whose transport is httpx's MockTransport: no socket is ever opened."""
    return Client(BASE, transport_factory=lambda: httpx.MockTransport(handler))


def raising(error: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


def chained(error: httpx.TransportError, os_error: BaseException) -> httpx.TransportError:
    """The chain httpx 0.28 and httpcore 1.0 really build, seen on a refused localhost port.

    The httpx error is raised from an httpcore error. httpcore raises that one `from None`
    while handling the OS error, so the OS error sits only in `__context__`, suppressed.
    """
    middle = httpcore.ConnectError(str(os_error))
    middle.__context__ = os_error
    middle.__suppress_context__ = True
    error.__cause__ = middle
    return error


def test_a_2xx_answer_keeps_status_headers_and_body_bytes_exactly():
    """R-PULL-2: the body is the bytes received, whitespace and all."""
    body = b'{ "status" : "operational" }\n\n'
    client = client_answering(
        lambda request: httpx.Response(200, headers={"X-Thing": "1"}, content=body)
    )
    result = client.get("/health")
    assert isinstance(result, Response)
    assert result.status == 200
    assert result.headers["x-thing"] == "1"
    assert result.body == body


def test_the_request_is_a_get_to_base_url_plus_path_with_params():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"{}")

    client_answering(handler).get("/flow/history", {"hours": 168, "limit": 500})
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == f"{BASE}/flow/history?hours=168&limit=500"


def test_a_trailing_slash_on_the_base_url_is_not_doubled():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"{}")

    Client(BASE + "/", transport_factory=lambda: httpx.MockTransport(handler)).get("/health")
    assert seen == [f"{BASE}/health"]


def test_the_timeout_is_sent_and_defaults_to_thirty_seconds():
    """T-26: DEFAULT_TIMEOUT is 30 s, overridable per call."""
    timeouts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, content=b"{}")

    client = client_answering(handler)
    client.get("/health")
    client.get("/health", timeout=5)
    assert DEFAULT_TIMEOUT == 30
    assert timeouts[0]["read"] == 30
    assert timeouts[1]["read"] == 5


def test_an_http_500_is_an_http_error_with_status_and_body():
    body = b'{"error":{"code":"INTERNAL_ERROR","message":"boom"}}'
    result = client_answering(lambda request: httpx.Response(500, content=body)).get("/health")
    assert isinstance(result, HttpError)
    assert result.status == 500
    assert result.body == body
    assert "HTTP 500" in result.message
    assert "INTERNAL_ERROR" in result.message


def test_a_long_error_body_is_cut_to_three_hundred_characters():
    result = client_answering(lambda request: httpx.Response(502, content=b"x" * 5000)).get("/a")
    assert isinstance(result, HttpError)
    assert result.message == "HTTP 502: " + "x" * 300


def test_an_empty_error_body_gives_the_bare_status():
    result = client_answering(lambda request: httpx.Response(502)).get("/a")
    assert isinstance(result, HttpError)
    assert result.message == "HTTP 502"


def test_a_redirect_is_not_followed_and_is_an_http_error():
    """T-26: follow_redirects is off, so a 3xx can never lead the client somewhere else."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://elsewhere/"})

    result = client_answering(handler).get("/health")
    assert isinstance(result, HttpError)
    assert result.status == 302
    assert len(calls) == 1


def test_connection_refused_is_tunnel_down_naming_host_and_port():
    """T-18: the tunnel closes on inactivity and gives connection refused."""
    error = chained(httpx.ConnectError("Connection refused"), ConnectionRefusedError(111, "x"))
    result = client_answering(raising(error)).get("/health")
    assert isinstance(result, TunnelDown)
    assert result.message.startswith("tunnel down:")
    assert "connection refused" in result.message
    assert "localhost:3300" in result.message
    assert "no data" not in result.message


def test_connection_reset_is_tunnel_down():
    """T-18 and T-26: reset counts as the tunnel too."""
    error = chained(httpx.ReadError("reset"), ConnectionResetError(104, "x"))
    result = client_answering(raising(error)).get("/health")
    assert isinstance(result, TunnelDown)
    assert "connection reset" in result.message


def test_the_os_error_is_found_through_a_suppressed_context():
    """Guards the real chain: the OS error is reachable through `__context__` only."""
    error = chained(httpx.ConnectError("refused"), ConnectionRefusedError(111, "x"))
    assert error.__cause__.__cause__ is None
    assert error.__cause__.__suppress_context__
    assert isinstance(client_answering(raising(error)).get("/health"), TunnelDown)


def test_the_cause_is_found_deeper_in_the_chain():
    inner = chained(httpx.ConnectError("inner"), ConnectionRefusedError(111, "x"))
    outer = httpx.ConnectError("outer")
    outer.__cause__ = inner
    assert isinstance(client_answering(raising(outer)).get("/health"), TunnelDown)


def test_a_body_that_does_not_match_its_encoding_is_unreachable_not_a_crash():
    """T-26 as amended: a DecodingError is not a TransportError, but get must not raise."""
    client = client_answering(
        lambda request: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, content=b"not gzip"
        )
    )
    result = client.get("/health")
    assert isinstance(result, Unreachable)
    assert "could not be decoded" in result.message
    assert "tunnel down" not in result.message


@pytest.mark.parametrize(
    "error", [httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow"), httpx.PoolTimeout("slow")]
)
def test_a_timeout_is_a_timeout_not_tunnel_down(error):
    result = client_answering(raising(error)).get("/health", timeout=7)
    assert isinstance(result, Timeout)
    assert result.message.startswith("timeout:")
    assert "7 s" in result.message


def test_a_failed_name_lookup_is_unreachable_not_tunnel_down():
    """T-26: other transport errors are their own kind, never called "tunnel down"."""
    error = chained(httpx.ConnectError("Name or service not known"), socket.gaierror(-2, "x"))
    result = client_answering(raising(error)).get("/health")
    assert isinstance(result, Unreachable)
    assert result.message.startswith("unreachable:")
    assert "tunnel down" not in result.message


NON_GET = ["post", "put", "patch", "delete", "head", "options", "request", "send", "stream"]


@pytest.mark.parametrize("name", NON_GET)
def test_the_client_has_no_way_to_send_a_non_get_request(name):
    """R-PULL-5, D-03: GET only. The type and an instance have no other request method."""
    assert not hasattr(Client, name)
    assert not hasattr(Client(BASE), name)


def test_get_is_the_only_public_method():
    public = {name for name in dir(Client) if not name.startswith("_")}
    assert public == {"get"}
