# HEPHAESTUS — single-image build: compile the Vue SPA, then serve it + the API from FastAPI.
#
# NOTE: this image runs the **dashboard, API, and review/merge UI**. The autonomous
# loop additionally needs the agent CLIs (claude / opencode / codex) and their auth,
# which are NOT bundled here — install them in a derived image or run the loop on the
# host. See SECURITY.md for the trust model before pointing HEPHAESTUS at a repo.

# ---- Stage 1: build the frontend SPA ----
FROM node:22-slim AS frontend
WORKDIR /build
# Pin pnpm to match the lockfile format + CI (v10). corepack's default pulls pnpm 11,
# which handles the build-script allowlist differently and aborts the install.
RUN corepack enable && corepack prepare pnpm@10.30.3 --activate
# Install deps first (cached layer). pnpm-workspace.yaml carries the build-script
# allowlist (esbuild, vue-demi) so pnpm 10 doesn't abort with ERR_PNPM_IGNORED_BUILDS.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build   # -> /build/dist

# ---- Stage 2: Python runtime serving API + the built SPA ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HEPHAESTUS_LOOP_HOME=/app \
    HEPHAESTUS_DASHBOARD_HOST=0.0.0.0 \
    HEPHAESTUS_DASHBOARD_PORT=8765
WORKDIR /app

# Install the backend. setuptools auto-discovery packages the `app` module and
# excludes `tests/` by default, so this is a clean runtime install.
COPY backend/ /app/backend/
RUN pip install /app/backend

# The API serves the SPA from <HEPHAESTUS_LOOP_HOME>/frontend/dist, and reads prompts
# from <HEPHAESTUS_LOOP_HOME>/prompts when the loop runs.
COPY --from=frontend /build/dist /app/frontend/dist
COPY prompts/ /app/prompts/

# Run as an unprivileged user; /app/state holds workspaces/connections/run history.
RUN useradd --create-home --uid 10001 hephaestus \
    && mkdir -p /app/state \
    && chown -R hephaestus:hephaestus /app
USER hephaestus

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
