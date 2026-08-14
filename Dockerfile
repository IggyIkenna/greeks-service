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
ARG BASE_IMAGE_DIGEST=sha256:e3b9da32f0bed45ddc7ee56470783604315c70fec4da5477250a5fcb614ba835
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
# uv does NOT read pip.conf's extra-index-url (pip-only convention) and its keyring-subprocess
# integration 401s against GAR in this container (unlike pip's in-process keyring import, which
# works) — see
# /plans/active/issues/cloud_build_unified_api_contracts_publish_ordering_race_2026_07_29.md. This
# surfaces only once a dependency floor-bump (e.g. unified-trading-library>=0.65.0) exceeds what
# the pinned base image already bundles, forcing uv to actually reach the private registry. Fix
# (mirrors instruments-service@4c05f2d3): mount a freshly-minted access token (same mechanism
# auth-precheck already proves works against this exact index) as a BuildKit secret, scoped to
# only this RUN layer — never baked into an image layer or history.
# Retry-with-backoff (3 attempts, ~45s total budget): hardens against the exact
# publish-ordering-race window this doc tracks recurring on the next cross-repo floor-bump.
RUN --mount=type=secret,id=gar_token \
    UV_EXTRA_INDEX_URL="https://oauth2accesstoken:$(cat /run/secrets/gar_token)@asia-northeast1-python.pkg.dev/central-element-323112/unified-libraries/simple/" \
    sh -c 'i=1; until uv pip install --system --no-sources -e .; do [ "$i" -ge 3 ] && { echo "uv pip install failed after 3 attempts" >&2; exit 1; }; w=$((15 * i)); echo "uv pip install failed (attempt $i/3) -- retrying in ${w}s"; sleep "$w"; i=$((i + 1)); done'

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
