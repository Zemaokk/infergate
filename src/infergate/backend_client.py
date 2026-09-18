from dataclasses import dataclass

import httpx

from infergate.router import Backend


@dataclass(frozen=True)
class BackendResponse:
    status_code: int
    body: bytes
    content_type: str | None


class BackendTransportError(Exception):
    pass


class BackendClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def forward(
        self, backend: Backend, path: str, payload: dict[str, object]
    ) -> BackendResponse:
        url = f"{backend.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            r = await self._client.post(url=url, json=payload)
            backend_response = BackendResponse(
                r.status_code, r.content, r.headers.get("content-type")
            )
        except httpx.TransportError as e:
            raise BackendTransportError(
                f"Transport failure for backend {backend.id}"
            ) from e
        return backend_response
