# Podman Support (Additive Path)

This repository maintains Docker as its primary documented and production CI path. Podman is supported as an **additional** option for local development, rootless execution, and container build/smoke verification.

Existing Docker workflows (`.github/workflows/ci-cd.yml`) and production release tags remain untouched and active.

---

## Prerequisites

Verify that Podman is installed on your workstation:

```bash
podman version
podman info
```

For Ubuntu 24.04+ (Noble) or RHEL 8/9, Podman 4.9+ is recommended.

---

## Registry Authentication

The Dockerfile builds from `ghcr.io/ngwpc/ngen:latest`. Before building, ensure you are logged in to GHCR:

```bash
echo "<GITHUB_PAT_OR_TOKEN>" | podman login ghcr.io -u "<GITHUB_USERNAME>" --password-stdin
```

---

## Building with Podman

Build the image directly using the existing `Dockerfile`. Following NOAA-OWP/WRES conventions, use `--format docker` to ensure standard OCI/Docker compatibility:

```bash
podman build --ulimit nofile=65535:65535 --format docker -t local/nwm-fcst-mgr:podman-test .
```

*Note: The Dockerfile uses BuildKit syntax (`# syntax=docker/dockerfile:1.4`) and `--mount=type=cache` for pip cache. Modern Podman (via Buildah $\ge$ 1.24) natively resolves cache mounts locally without requiring a Docker daemon.*

---

## Smoke Verification

### 1. Test Entrypoint Script & Usage
```bash
podman run --rm local/nwm-fcst-mgr:podman-test --help
# Note: run-ngen-fcst.sh displays usage options and intentionally exits 1 on bare --help.
```

### 2. Verify Python Environment & Dependencies
Test that Python 3.12, `nwm_fcst_mgr`, and `mswm` are operational:
```bash
podman run --rm --entrypoint python local/nwm-fcst-mgr:podman-test --version
podman run --rm --entrypoint python local/nwm-fcst-mgr:podman-test -c "import nwm_fcst_mgr, mswm; print('Environment healthy')"
```

### 3. Verify Provenance Metadata
```bash
podman run --rm --entrypoint test local/nwm-fcst-mgr:podman-test -s /ngen-app/nwm-fcst-mgr_git_info.json
```

---

## CI / Automation

* **Workflow:** `.github/workflows/podman-smoke.yml`
* **Triggers:** Manual (`workflow_dispatch`) and automated checks on pull requests modifying container/source files (`Dockerfile`, `docker/**`, `pyproject.toml`, `requirements.txt`, `python/**`).
* **Runner Environment:** Pinned to `ubuntu-24.04`.
* **Registry Policy:** By default, builds remain local to the runner. When `push_images=true` is dispatched, only `:podman-test` and `:<sha>-podman-test` tags are published to GHCR. Production aliases (`:latest`, release tags) are never touched.
