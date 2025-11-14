from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple, Union

TimeoutArg = Union[float, Tuple[float, float]]


class RequestException(Exception):
    ...


class Response:
    status_code: int
    text: str
    reason: str

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


def get(
    url: str,
    *,
    params: Mapping[str, Any] | None = ...,
    timeout: TimeoutArg | None = ...,
) -> Response: ...


def post(
    url: str,
    *,
    json: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = ...,
    timeout: TimeoutArg | None = ...,
) -> Response: ...
