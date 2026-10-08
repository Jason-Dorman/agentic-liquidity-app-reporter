"""Fakes for the I/O modules (T-21, TESTING section 3). No fake reaches the network."""

from collections.abc import Mapping

from daily_review.client import DEFAULT_TIMEOUT, Params, Result


def _key(path: str, params: Params | None) -> tuple:
    return (path, tuple(sorted((params or {}).items())))


class FakeClient:
    """Canned results by (path, params). Records every call. Like the real client, GET only."""

    def __init__(self, results: Mapping[tuple[str, Params | None], Result]):
        self._results = {_key(path, params): result for (path, params), result in results.items()}
        self.calls: list[tuple[str, Params | None, float]] = []

    def get(
        self, path: str, params: Params | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Result:
        self.calls.append((path, params, timeout))
        return self._results[_key(path, params)]
