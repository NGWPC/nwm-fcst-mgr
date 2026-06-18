# syntax=docker/dockerfile:1.4

############################################################################
# Change/Verify these values when adopting this Dockerfile into another org:
#   GH_ORG, GHCR_ORG, IMAGE_NAMESPACE, APP_DIR,
#   MSW_MGR_ORG, MSW_MGR_REF, EWTS_ORG, EWTS_REF
############################################################################

# Ownership / branding overrides
ARG GH_ORG=NGWPC
ARG GHCR_ORG=ngwpc
ARG IMAGE_NAMESPACE=ngwpc

# Configurable application working directory. Defaults to /ngen-app, but
# can be overriden for environments where creating directories off root is restricted
ARG APP_DIR=/ngen-app

# External repository sources
ARG MSW_MGR_ORG=${GH_ORG}
ARG MSW_MGR_REF=development

ARG EWTS_ORG=${GH_ORG}
ARG EWTS_REF=development

ARG USE_EWTS=ON
ARG EWTS_CACHE_BUST=0

############################################################################
# Image selection
############################################################################

# Use the ngen image as the base.
#
# Default build:
#   docker build -t ngen-fcst .
#
# Build from a different published ngen image:
#   docker build \
#     --build-arg NGEN_IMAGE=ghcr.io/ngwpc/ngen:development \
#     -t ngen-fcst .
#
# Build from a locally built ngen image:
#   docker build \
#     --build-arg NGEN_IMAGE=ngen \
#     -t ngen-fcst .
ARG NGEN_IMAGE=ghcr.io/${GHCR_ORG}/ngen:latest

FROM ${NGEN_IMAGE}

# Re-expose args after FROM for the remaining build stage.
ARG GH_ORG
ARG GHCR_ORG
ARG IMAGE_NAMESPACE
ARG MSW_MGR_ORG
ARG MSW_MGR_REF
ARG EWTS_ORG
ARG EWTS_REF
ARG USE_EWTS
ARG EWTS_CACHE_BUST
ARG NGEN_IMAGE
ARG APP_DIR

# OCI Metadata Arguments
#
# BASE_IMAGE_* refers to the ngen image this image is built FROM.
ARG BASE_IMAGE_DIGEST="unknown"
ARG BASE_IMAGE_REVISION="unknown"
ARG IMAGE_SOURCE="unknown"
ARG IMAGE_VENDOR="unknown"
ARG IMAGE_VERSION="unknown"
ARG IMAGE_REVISION="unknown"
ARG MSW_MGR_REVISION="unknown"

# Image Labels: OCI-spec annotations followed by custom source-repo metadata.
LABEL org.opencontainers.image.base.name="${NGEN_IMAGE}" \
      org.opencontainers.image.base.digest="${BASE_IMAGE_DIGEST}" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.vendor="${IMAGE_VENDOR}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      org.opencontainers.image.title="NGEN Forecast/Hindcast Manager" \
      org.opencontainers.image.description="Docker image for the NGEN Forecast/Hindcast application" \
      io.${IMAGE_NAMESPACE}.image.base.revision="${BASE_IMAGE_REVISION}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.org="${MSW_MGR_ORG}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.ref="${MSW_MGR_REF}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.revision="${MSW_MGR_REVISION}"

# Reuse the Python virtual environment inherited from ngen. The dependency image
# creates the venv; forcing and ngen install their Python packages into that same
# environment. Do not recreate it here.
ENV VIRTUAL_ENV="/ngen-app/ngen-python" \
    PATH="${VIRTUAL_ENV}/bin:${PATH}"

SHELL ["/bin/bash", "-c"]

############################################################################
# Optional development-only EWTS Python override
############################################################################

# Production images should inherit EWTS from ngen. Set FCST_MGR_INSTALL_EWTS=ON
# only when testing a new EWTS Python package without rebuilding forcing/ngen.
#
# Example:
#   docker build \
#     --build-arg FCST_MGR_INSTALL_EWTS=ON \
#     --build-arg EWTS_REF=my-ewts-branch \
#     --build-arg EWTS_CACHE_BUST=$(date +%s) \
#     -t nwm-fcst-mgr .
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-bookworm \
    set -eux; \
    USE_EWTS="${USE_EWTS:-ON}"; \
    echo "USE_EWTS=${USE_EWTS}; EWTS ref: ${EWTS_REF}; cache bust: ${EWTS_CACHE_BUST}"; \
    USE_EWTS_NORMALIZED="$(echo "${USE_EWTS}" | tr '[:lower:]' '[:upper:]')"; \
    if [[ "${USE_EWTS_NORMALIZED}" =~ ^(ON|YES|TRUE|1)$ ]]; then \
        echo "Installing development EWTS Python override"; \
        rm -rf /tmp/nwm-ewts; \
        (git clone --depth 1 -b "${EWTS_REF}" \
            "https://github.com/${EWTS_ORG}/nwm-ewts.git" /tmp/nwm-ewts \
         || (git clone "https://github.com/${EWTS_ORG}/nwm-ewts.git" /tmp/nwm-ewts && \
             cd /tmp/nwm-ewts && git checkout "${EWTS_REF}")); \
        python -m pip install \
            --force-reinstall \
            --no-deps \
            /tmp/nwm-ewts/runtime/python/ewts; \
        rm -rf /tmp/nwm-ewts; \
    else \
        echo "Using EWTS inherited from ngen"; \
    fi

############################################################################
# Forecast manager source
############################################################################

COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/

RUN set -eux; \
    chmod +x ${APP_DIR}/bin/run-ngen-fcst.sh

WORKDIR ${APP_DIR}/ngen-fcst

############################################################################
# Forecast-specific Python dependencies
############################################################################

# Install forecast-specific Python dependencies not already provided by ngen.
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-bookworm \
    set -eux; \
    python -m pip install \
        "matplotlib~=3.10.6"

# Install MSWM package from the configured repository/ref.
# MSW_MGR_CACHE_BUST = nwm-msw-mgr commit SHA from CI; a new commit busts this layer so mswm is reinstalled from the requested ref, not a stale cache.
ARG MSW_MGR_CACHE_BUST=1
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    set -eux; \
    echo "MSW MGR cache bust: ${MSW_MGR_CACHE_BUST}" && \
    python -m pip install mswm@git+https://github.com/${MSW_MGR_ORG}/nwm-msw-mgr.git@${MSW_MGR_REF}; \
    python -m pip cache purge

# Install forecast manager into the inherited virtual environment.
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    set -eux; \
    python -m pip install .


# Verify that the inherited Python environment remains internally consistent.
RUN set -eux; \
    python -m pip check; \
    python -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version; print('Python version:', sys.version)"

############################################################################
# Git provenance
############################################################################

ARG CI_COMMIT_REF_NAME

RUN set -eux; \
    repo_url=$(git config --get remote.origin.url); \
    key=${repo_url##*/}; \
    key=${key%.git}; \
    GIT_INFO_PATH="/ngen-app/${key}_git_info.json"; \
    branch=$( [ -n "${CI_COMMIT_REF_NAME:-}" ] && echo "${CI_COMMIT_REF_NAME}" || git rev-parse --abbrev-ref HEAD ); \
    jq -n \
      --arg commit_hash "$(git rev-parse HEAD)" \
      --arg branch "$branch" \
      --arg tags "$(git tag --points-at HEAD | tr '\n' ' ')" \
      --arg author "$(git log -1 --pretty=format:'%an')" \
      --arg commit_date "$(date -u -d @$(git log -1 --pretty=format:'%ct') +'%Y-%m-%d %H:%M:%S UTC')" \
      --arg message "$(git log -1 --pretty=format:'%s' | tr '\n' ';')" \
      --arg build_date "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" \
      "{\"$key\": {commit_hash: \$commit_hash, branch: \$branch, tags: \$tags, author: \$author, commit_date: \$commit_date, message: \$message, build_date: \$build_date}}" \
      > "${GIT_INFO_PATH}"

WORKDIR /

ENTRYPOINT ["/ngen-app/bin/run-ngen-fcst.sh"]