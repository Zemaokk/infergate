from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from infergate.router import Backend


@dataclass(frozen=True)
class BackendResponse:
    status_code: int
    body: bytes
    content_type: str | None


# Wrapper
class BackendStreamResponse:
    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.content_type = response.headers.get("content-type")
        self._response = response

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        return self._response.aiter_bytes()

    async def aclose(self) -> None:
        await self._response.aclose()


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

    async def open_stream(
        self, backend: Backend, path: str, payload: dict[str, object]
    ) -> BackendStreamResponse:
        url = f"{backend.base_url.rstrip('/')}/{path.lstrip('/')}"
        request = self._client.build_request(method="POST", url=url, json=payload)
        try:
            response = await self._client.send(request, stream=True)
        except httpx.TransportError as e:
            raise BackendTransportError(
                f"Transport failure for backend {backend.id}"
            ) from e
        return BackendStreamResponse(response)
