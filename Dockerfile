FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    AUTOBIM_DATA_DIR=/data/jobs

WORKDIR /app

# Locked runtime dependencies first, for layer caching.
COPY requirements.lock .
RUN pip install -r requirements.lock

# Optional extras from pyproject.toml (e.g. EXTRAS=seg), pinned against the lock where they overlap.
# Only their dependencies are installed; the app itself still runs from source.
ARG EXTRAS=""
COPY pyproject.toml /tmp/pyproject.toml
RUN if [ -n "$EXTRAS" ]; then \
      python -c "import sys, tomllib; extras = tomllib.load(open('/tmp/pyproject.toml', 'rb'))['project']['optional-dependencies']; print('\n'.join(d for e in sys.argv[1].split(',') for d in extras[e]))" "$EXTRAS" > /tmp/extras.txt \
      && pip install -c requirements.lock -r /tmp/extras.txt; \
    fi && rm -f /tmp/pyproject.toml /tmp/extras.txt

# Run from source (not pip-installed) so config/settings.yaml resolves next to app/.
COPY app ./app
COPY config ./config

RUN useradd --create-home --uid 1000 autobim && mkdir -p /data/jobs && chown -R autobim /data
USER autobim

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
