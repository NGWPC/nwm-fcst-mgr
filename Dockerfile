ARG  NGEN_VERSION=latest
FROM registry.sh.nextgenwaterprediction.com/ngwpc/nwm-ngen/ngen:${NGEN_VERSION}

RUN set -eux; \
    dnf install -y \
        jq; \
    dnf clean all

COPY requirements.txt .
RUN set -eux; \
	\
    pip3 install -r requirements.txt ; \
    pip3 cache purge ; \
    rm --force requirements.txt ;


COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/
RUN set -eux; \
	\
    chmod +x /ngen-app/bin/run-ngen-fcst.sh

WORKDIR /ngen-app/ngen-fcst

# Extract Git information and write it to the file specified by $GIT_INFO_PATH
ARG GIT_INFO_PATH=/ngen-app/ngen-fcst_git_info.json
ARG CI_COMMIT_REF_NAME

RUN set -eux; \
    # Determine branch name: if CI_COMMIT_REF_NAME is set (CI build), use it; otherwise, fall back to using the git command for manual builds.
    branch=$( [ -n "${CI_COMMIT_REF_NAME:-}" ] && echo "${CI_COMMIT_REF_NAME}" || git rev-parse --abbrev-ref HEAD ); \
    jq -n \
      --arg commit_hash "$(git rev-parse HEAD)" \
      --arg branch "$branch" \
      --arg tags "$(git tag --points-at HEAD | tr '\n' ' ')" \
      --arg author "$(git log -1 --pretty=format:'%an')" \
      --arg commit_date "$(date -u -d @$(git log -1 --pretty=format:'%ct') +'%Y-%m-%d %H:%M:%S UTC')" \
      --arg message "$(git log -1 --pretty=format:'%s' | tr '\n' ';')" \
      --arg build_date "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" \
      '{"ngen-fcst": {commit_hash: $commit_hash, branch: $branch, tags: $tags, author: $author, commit_date: $commit_date, message: $message, build_date: $build_date}}' \
      > $GIT_INFO_PATH

WORKDIR /

ENTRYPOINT [ "/ngen-app/bin/run-ngen-fcst.sh" ] 
