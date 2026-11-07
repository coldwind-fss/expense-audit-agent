FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" FILE_ROOT=/data/files
CMD ["uvicorn", "reimbursement.main:app", "--host", "0.0.0.0", "--port", "8000"]
