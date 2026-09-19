from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    message: str
    type: Literal["invalid_request_error", "gateway_error"]
    param: str | None = None
    code: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def create_error_response(
    *,
    status_code: int,
    message: str,
    error_type: Literal["invalid_request_error", "gateway_error"],
    param: str | None = None,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorDetail(message=message, type=error_type, param=param, code=code)
    )

    return JSONResponse(
        status_code=status_code, content=body.model_dump(), headers=headers
    )
