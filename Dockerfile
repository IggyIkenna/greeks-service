# Dockerfile for greeks-service
#
# Build:
#   docker build --build-arg PROJECT_ID=central-element-323112 -t greeks-service .
#
# Base image — Cloud Build passes PROJECT_ID via --build-arg; local builds must pass it too.
# Pulls unified-trading-library:latest from Artifact Registry (canonical workspace base image).
ARG PROJECT_ID
# Digest-pinned UTL base image (QG STEP 5.79 -- reproducible builds + UTL/UAC provenance).
# Refreshed by the dependency-update fan-out (update-dependency-version.yml) on base-image
# republish; cloudbuild may override at build time: --build-arg BASE_IMAGE_DIGEST=sha256:...
ARG BASE_IMAGE_DIGEST=sha256:75926d35b5960cfc88eb3dd95e9498461857a5d6b0e8070880a35c951bafd4a8
FROM --platform=linux/amd64 asia-northeast1-docker.pkg.dev/${PROJECT_ID}/unified-trading-library/unified-trading-library@${BASE_IMAGE_DIGEST} AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

RUN useradd --create-home --shell /bin/bash appuser

# Install dependencies BEFORE copying source (canonical dep-layer-first pattern).
WORKDIR /app/greeks-service
COPY pyproject.toml uv.lock README.md ./
COPY unified-api-contracts/ /app/unified-api-contracts/
COPY unified-trading-library/ /app/unified-trading-library/
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code (after deps so source edits don't bust the dep layer)
COPY . .

RUN chmod +x scripts/quality-gates.sh
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/greeks-service

ENV ENVIRONMENT=production \
    UCS_SKIP_GCSFUSE_CHECK=1 \
    GCS_REGION=asia-northeast1-c \
    GCS_LOCATION=asia-northeast1 \
    PATH="/app/greeks-service/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import greeks_service; print('healthy')" || exit 1

EXPOSE 8080
ENTRYPOINT []
CMD ["uvicorn", "greeks_service.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
