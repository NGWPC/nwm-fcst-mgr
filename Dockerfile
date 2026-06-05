# syntax=docker/dockerfile:1.4

############################################################################
# Change/Verify these values when adopting this Dockerfile into another org:
#   GH_ORG, GHCR_ORG, IMAGE_NAMESPACE,
#   MSW_MGR_ORG, MSW_MGR_REF
############################################################################

# Ownership / branding overrides
ARG GH_ORG=NGWPC
ARG GHCR_ORG=ngwpc
ARG IMAGE_NAMESPACE=ngwpc

# External repository sources
ARG MSW_MGR_ORG=${GH_ORG}
ARG MSW_MGR_REF=development

############################################################################
# Image selection
############################################################################

ARG NGEN_IMAGE_TAG=latest
ARG NGEN_IMAGE=ghcr.io/${GHCR_ORG}/ngen:${NGEN_IMAGE_TAG}
FROM ${NGEN_IMAGE}

# Uncomment when building from a locally built ngen image
# FROM ngen

# Re-expose args after FROM for the remaining build stage
ARG GH_ORG
ARG GHCR_ORG
ARG IMAGE_NAMESPACE
ARG MSW_MGR_ORG
ARG MSW_MGR_REF

# OCI Metadata Arguments
ARG NGEN_IMAGE
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

# Re-expose the Python virtual environment inherited from ngen.
# The dependency image creates the venv and the unversioned `python` symlink.
# ngen-bmi-forcing and ngen install their Python packages into that venv.
# forecast should reuse it rather than recreating it.
ENV VIRTUAL_ENV="/ngen-app/ngen-python" \
    PATH="${VIRTUAL_ENV}/bin:${PATH}" \
    PYTHONPATH="${VIRTUAL_ENV}/lib/python3.11/site-packages:/usr/local/lib64/python3.11/site-packages:${PYTHONPATH}"

COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/

RUN set -eux; \
    chmod +x /ngen-app/bin/run-ngen-fcst.sh

WORKDIR /ngen-app/ngen-fcst

# Install forecast-specific Python dependencies not already provided by ngen.
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    set -eux; \
    python -m pip install "matplotlib~=3.10.6"; \
    python -m pip cache purge

# Install MSWM package from the configured repository/ref.
ARG MSWM_CACHE_BUST=1
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    set -eux; \
    echo "MSWM cache bust: ${MSWM_CACHE_BUST}" && \
    python -m pip install mswm@git+https://github.com/${MSW_MGR_ORG}/nwm-msw-mgr.git@${MSW_MGR_REF}; \
    python -m pip cache purge

# Install forecast manager into the inherited virtual environment.
ARG FCST_CACHE_BUST=1
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    set -eux; \
    echo "FCST cache bust: ${FCST_CACHE_BUST}" && \
    python -m pip install --no-deps . || python -m pip install .; \
    python -m pip cache purge

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
