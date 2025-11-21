from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Union

TimeoutArg = Union[float, tuple[float, float]]

class RequestException(Exception): ...

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
