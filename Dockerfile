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
ARG BASE_IMAGE_DIGEST=sha256:ec21883c130cb53d06fbb0a69acd881650b5f575206c673b50ce74633bb618d1
FROM --platform=linux/amd64 asia-northeast1-docker.pkg.dev/${PROJECT_ID}/unified-trading-library/unified-trading-library@${BASE_IMAGE_DIGEST}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app/greeks-service

# Copy the whole single-repo build context (tests/scripts/cloudbuild needed by the in-image QG
# step). Normalized off the prior Pattern-B vendored-sibling form (COPY unified-api-contracts/
# unified-trading-library/ into the context + `uv sync --frozen` against local path sources) —
# see plans/active/issues/service_dockerfile_pattern_normalization_2026_06_17.md. Sibling source
# repos are NOT needed in the build context: UTL+UAC are PRE-INSTALLED in the base image, and
# --no-sources below ignores [tool.uv.sources] local path deps + resolves fastapi/uvicorn/pydantic
# straight from PyPI instead of COPYing ../unified-* (which fails a single-repo build context).
COPY . .

# hatch-vcs (source = "vcs"): .git is .dockerignore'd + COPY . . excludes it, so `uv pip install -e .`
# cannot run `git describe`. Cloud Build resolves the real tag in extract-version and passes it via
# --build-arg SETUPTOOLS_SCM_PRETEND_VERSION; export it BEFORE the install else setuptools-scm fails
# with "unable to detect version for /workspace". Default keeps a local `docker build` working.
ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

# Install this service (UTL + UAC pre-installed in the base image; --no-sources skips local path
# deps and resolves fastapi/uvicorn/pydantic from PyPI instead).
RUN uv pip install --system --no-sources -e .

RUN chmod +x scripts/quality-gates.sh
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/greeks-service

ENV ENVIRONMENT=production \
    UCS_SKIP_GCSFUSE_CHECK=1 \
    GCS_REGION=asia-northeast1-c \
    GCS_LOCATION=asia-northeast1

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import greeks_service; print('healthy')" || exit 1

EXPOSE 8080
ENTRYPOINT []
CMD ["uvicorn", "greeks_service.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
