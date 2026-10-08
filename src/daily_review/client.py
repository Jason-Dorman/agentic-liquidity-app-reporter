"""HTTP GET against the Blockford API base URL with a timeout. It has no POST method."""

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

DEFAULT_TIMEOUT = 30.0  # seconds per call, overridable per call (T-26)
_SNIPPET = 300  # characters of an error body kept in a message

# T-18 and T-26: the tunnel closes on inactivity and refuses or resets the connection.
_TUNNEL_CAUSES = {
    ConnectionRefusedError: "connection refused",
    ConnectionResetError: "connection reset",
}

Params = Mapping[str, str | int]


@dataclass(frozen=True)
class Response:
    """A 2xx answer. `body` is the bytes as received, never altered (R-PULL-2)."""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class HttpError:
    """A non-2xx answer, a 3xx included: redirects are never followed (T-26)."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def message(self) -> str:
        text = " ".join(self.body.decode("utf-8", "replace").split())[:_SNIPPET]
        return f"HTTP {self.status}: {text}" if text else f"HTTP {self.status}"


@dataclass(frozen=True)
class TunnelDown:
    """Connection refused or reset: the port-forward is closed (T-18). Never "no data"."""

    message: str


@dataclass(frozen=True)
class Timeout:
    """No answer within the timeout."""

    message: str


@dataclass(frozen=True)
class Unreachable:
    """Any other transport failure, such as a failed name lookup. Not called "tunnel down"."""

    message: str


Failure = HttpError | TunnelDown | Timeout | Unreachable
Result = Response | Failure


class Getter(Protocol):
    """What callers depend on: one GET. The real Client and the test FakeClient both fit."""

    def get(
        self, path: str, params: Params | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Result: ...


class Client:
    """GET only. Each call opens a fresh httpx client that is never kept, so nothing can POST."""

    def __init__(
        self,
        base_url: str,
        transport_factory: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport,
    ):
        self._base_url = base_url.rstrip("/")
        self._transport_factory = transport_factory

    def get(
        self, path: str, params: Params | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Result:
        """GET base URL + path. Returns a Response, or a Failure value; never raises for HTTP."""
        url = self._base_url + path
        try:
            with httpx.Client(transport=self._transport_factory(), follow_redirects=False) as http:
                return _answer(http.get(url, params=params, timeout=timeout))
        except httpx.TimeoutException:
            return Timeout(f"timeout: no answer from {path} within {timeout:g} s")
        except httpx.DecodingError as error:  # a body that does not match its Content-Encoding
            return Unreachable(f"unreachable: the body from {path} could not be decoded: {error}")
        except httpx.TransportError as error:
            return _transport_failure(error, httpx.URL(url))


def _answer(response: httpx.Response) -> Response | HttpError:
    kind = Response if response.is_success else HttpError
    return kind(status=response.status_code, headers=dict(response.headers), body=response.content)


def _causes(error: BaseException) -> Iterator[BaseException]:
    """The error and everything it was raised from, outermost first.

    Follows __context__ even when __suppress_context__ is set: httpcore raises its pooled
    connection errors `from None`, so the OS error is reachable only that way.
    """
    seen: BaseException | None = error
    while seen is not None:
        yield seen
        seen = seen.__cause__ or seen.__context__


def _transport_failure(error: httpx.TransportError, url: httpx.URL) -> TunnelDown | Unreachable:
    where = f"{url.host}:{url.port}" if url.port else url.host
    for cause in _causes(error):
        for kind, words in _TUNNEL_CAUSES.items():
            if isinstance(cause, kind):
                return TunnelDown(f"tunnel down: {words} at {where}")
    return Unreachable(f"unreachable: {where}: {error}")
