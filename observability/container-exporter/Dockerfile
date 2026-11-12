FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --only-group exporter
COPY observability/container-exporter/exporter.py .
EXPOSE 9101
CMD ["/app/.venv/bin/python", "exporter.py"]