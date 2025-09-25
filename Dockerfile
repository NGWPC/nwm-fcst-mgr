# syntax=docker/dockerfile:1.4
ARG  NGEN_IMAGE_TAG=latest
FROM ghcr.io/ngwpc/ngen:${NGEN_IMAGE_TAG}

# Uncomment when building ngen locally or if ngen-int image is available locally
# modify to use image tag for local ngen image if needed
#FROM ngen-int

RUN set -eux; \
    dnf install -y \
        jq; \
    dnf clean all

COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/
RUN set -eux; \
	\
    chmod +x /ngen-app/bin/run-ngen-fcst.sh

WORKDIR /ngen-app/ngen-fcst

RUN set -eux; \
    pip3 install . ; \
    pip3 cache purge ;

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
