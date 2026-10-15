"""Fakes for the I/O modules (T-21, TESTING section 3). No fake reaches the network."""

from collections.abc import Iterable, Mapping

from daily_review.client import DEFAULT_TIMEOUT, Params, Result

Pairs = Iterable[tuple[tuple[str, Params | None], Result]]


def _key(path: str, params: Params | None) -> tuple:
    return (path, tuple(sorted((params or {}).items())))


class FakeClient:
    """Canned results by (path, params). Records every call. Like the real client, GET only."""

    def __init__(
        self,
        results: Mapping[tuple[str, None], Result] | Pairs,
        default: Result | None = None,
    ):
        """Results by (path, params): a mapping when params are None, else a list of pairs.

        `default` answers any call not in `results`; without one such a call is a KeyError.
        """
        pairs = results.items() if isinstance(results, Mapping) else results
        self._results = {_key(path, params): result for (path, params), result in pairs}
        self._default = default
        self.calls: list[tuple[str, Params | None, float]] = []

    def get(
        self, path: str, params: Params | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Result:
        self.calls.append((path, params, timeout))
        key = _key(path, params)
        if key not in self._results and self._default is not None:
            return self._default
        return self._results[key]
