# syntax=docker/dockerfile:1.4

ARG ORG=ngwpc
ARG NGEN_IMAGE_TAG=latest
ARG NGEN_IMAGE=ghcr.io/${ORG}/ngen:${NGEN_IMAGE_TAG}
FROM ${NGEN_IMAGE}

# Uncomment when building ngen locally or if ngen-int image is available locally
# modify to use image tag for local ngen image if needed
#FROM ngen

# OCI Metadata Arguments
ARG NGEN_IMAGE
ARG BASE_IMAGE_DIGEST="unknown"
ARG BASE_IMAGE_REVISION="unknown"
ARG IMAGE_SOURCE="unknown"
ARG IMAGE_VENDOR="unknown"
ARG IMAGE_VERSION="unknown"
ARG IMAGE_REVISION="unknown"

# OCI Standard Labels
LABEL org.opencontainers.image.base.name="${NGEN_IMAGE}" \
    org.opencontainers.image.base.digest="${BASE_IMAGE_DIGEST}" \
    io.ngwpc.image.base.revision="${BASE_IMAGE_REVISION}" \
    org.opencontainers.image.source="${IMAGE_SOURCE}" \
    org.opencontainers.image.vendor="${IMAGE_VENDOR}" \
    org.opencontainers.image.version="${IMAGE_VERSION}" \
    org.opencontainers.image.revision="${IMAGE_REVISION}" \
    org.opencontainers.image.title="NGEN Forecast/Hindcast" \
    org.opencontainers.image.description="Docker image for the NGEN Forecast/Hindcast application"

# Activate the existing virtual environment
ENV PATH="/ngen-app/ngen-python/bin:${PATH}"

RUN set -eux; \
    dnf install -y jq; \
    dnf clean all

COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/

RUN set -eux; \
    chmod +x /ngen-app/bin/run-ngen-fcst.sh

WORKDIR /ngen-app/ngen-fcst

# Install missing dependencies that aren't in base image
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache \
    set -eux; \
    pip3 install \
        "matplotlib~=3.10.6"; \
        #"geopandas~=1.1.1"; \
    pip3 cache purge

# ── EWTS (Error, Warning and Trapping System)
#
# Build args – override at build time to pin a branch, tag, or full commit SHA:
#   docker build --build-arg EWTS_REF=v1.2.3 ...
#   docker build --build-arg EWTS_REF=abc123def456 ...
ARG EWTS_ORG=NGWPC
ARG EWTS_REF=development
ARG EWTS_CACHE_BUST=1

# Clone nwm-ewts, install the Python package, capture git metadata for
# provenance, then remove the source tree.
# Try shallow clone by branch/tag name first; fall back to full clone + checkout
# for bare commit SHAs (which git clone -b doesn't support).
#
# NOTE: Unlike the ngen Dockerfile, clone + pip install + cleanup are kept in a
# single RUN so the source tree never persists in a layer.  In ngen the split is
# safe because cmake installs the wheel to /opt/ewts before the source is removed;
# here there is no cmake step, so the source must remain until pip finishes.
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache \
    echo "EWTS cache bust: ${EWTS_CACHE_BUST}" && \
    set -eux && \
    ewts_dir="$(mktemp -d)" && \
    git clone "https://github.com/${EWTS_ORG}/nwm-ewts.git" "${ewts_dir}" && \
    cd "${ewts_dir}" && \
    git checkout "${EWTS_REF}" && \
    pip install "${ewts_dir}/runtime/python/ewts" && \
    rm -rf "${ewts_dir}"

# Install MSWM package
ARG MSW_MGR_VERSION=development
ARG MSWM_CACHE_BUST=1
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache \
    set -eux; \
    echo "MSWM cache bust: ${MSWM_CACHE_BUST}" && \
    pip3 install mswm@git+https://github.com/NGWPC/nwm-msw-mgr.git@${MSW_MGR_VERSION} ; \
    pip3 cache purge

# Install into the existing virtual environment without upgrading base packages
ARG FCST_CACHE_BUST=1
RUN set -eux; \
    echo "FCST cache bust: ${FCST_CACHE_BUST}" && \
    pip3 install --no-deps . || pip3 install .; \
    pip3 cache purge;

ARG CI_COMMIT_REF_NAME

RUN set -eux; \
    # Get the remote URL from Git configuration
    repo_url=$(git config --get remote.origin.url); \
    # Extract the repo name (everything after the last slash) and remove any trailing .git
    key=${repo_url##*/}; \
    key=${key%.git}; \
    # Construct the file path using the derived key
    GIT_INFO_PATH="/ngen-app/${key}_git_info.json"; \
    # Determine branch name: use CI_COMMIT_REF_NAME if set; otherwise, use git's current branch
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
      > $GIT_INFO_PATH

WORKDIR /

ENTRYPOINT [ "/ngen-app/bin/run-ngen-fcst.sh" ]
