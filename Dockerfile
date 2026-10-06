FROM python:3.13-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-trixie AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /app/.venv /app/.venv
COPY configs/logging.json /app/configs/logging.json
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "infergate.runtime:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-config", "/app/configs/logging.json"]
