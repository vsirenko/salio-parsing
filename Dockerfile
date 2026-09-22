FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code changes don't invalidate the pip layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Run as a non-root user. The snapshot directory is created here and handed over with it:
# Docker seeds a fresh named volume from the image's own directory, so a mount point that
# exists and is owned by appuser comes up writable. Left to the daemon it is created root
# owned, and the collector then fails on every product with a permission error while the
# run looks like a shop that served nothing.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /snapshots \
    && chown -R appuser:appuser /app /snapshots
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

# Add --workers N (or put this behind gunicorn) when you scale past one process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
