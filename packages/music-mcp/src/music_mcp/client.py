"""Typed HTTP client for the Workbench Domain API envelope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias, cast

import httpx

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
QueryValue: TypeAlias = str | int | float | bool


class DomainApiError(RuntimeError):
    """Raised when the Domain API is unavailable or returns a bad envelope."""


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        normalized: JsonObject = {}
        for key, item in cast(dict[object, object], value).items():
            if not isinstance(key, str):
                raise DomainApiError("Domain API returned a non-string JSON key")
            normalized[key] = _json_value(item)
        return normalized
    raise DomainApiError(f"Domain API returned unsupported JSON: {type(value).__name__}")


class DomainApiClient:
    """Small transport boundary shared by all MCP tool functions."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
        project_id: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout,
            headers={"X-Workbench-Project": project_id} if project_id else {},
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, JsonValue] | None = None,
        params: Mapping[str, QueryValue] | None = None,
    ) -> JsonObject:
        if self._project_id and body is not None and "project_id" in body:
            requested = body["project_id"]
            if requested is not None and requested != self._project_id:
                raise DomainApiError("Tool project_id differs from this task's project")
            body = {**body, "project_id": self._project_id}
        try:
            response = self._client.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            raise DomainApiError(f"Domain API request failed: {exc}") from exc
        try:
            decoded: object = response.json()
            value = _json_value(decoded)
        except (ValueError, DomainApiError) as exc:
            raise DomainApiError(
                f"Domain API returned invalid JSON ({response.status_code})"
            ) from exc
        if not isinstance(value, dict):
            raise DomainApiError("Domain API envelope must be a JSON object")
        if response.is_error:
            warning = value.get("warnings")
            raise DomainApiError(
                f"Domain API returned HTTP {response.status_code}: {warning!r}"
            )
        if value.get("ok") is not True:
            raise DomainApiError(f"Domain API returned a failed envelope: {value!r}")
        return value


__all__ = ["DomainApiClient", "DomainApiError", "JsonObject", "JsonValue"]
