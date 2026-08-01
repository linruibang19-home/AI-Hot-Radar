FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency layer is cached separately so source edits do not reinstall wheels.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY tests ./tests

# Run as a non-root user: this service fetches untrusted remote content.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "ahr.main:app", "--host", "0.0.0.0", "--port", "8000"]
