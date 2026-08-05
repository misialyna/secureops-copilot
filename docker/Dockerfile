# syntax=docker/dockerfile:1

# Stage 1: build the frontend (React + Vite) into static files.
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: the backend image — Python deps, the RAG index, and the built frontend.
FROM python:3.12-slim AS backend

# libgomp1: required at runtime by the CPU build of torch (sentence-transformers' dependency).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# WORKDIR is the repo root, not backend/ — Settings' relative paths (data/, knowledge/) and
# `python -m app.rag.ingest` both assume that, matching how the app is run outside Docker too
# (see README: `uv run uvicorn app.main:app --app-dir backend` is run from the repo root).
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN uv sync --frozen --no-dev --no-editable

COPY knowledge/.gitkeep knowledge/.gitkeep

# Baked in at build time, not on first request: downloads the NIST/CISA PDFs and the bge-m3
# embedding model (~2GB) and builds the local Qdrant index into the image. Railway/HF Spaces
# free-tier disks are ephemeral (same reason drafts/evidence are documented as ephemeral in
# README's Known limitations), so a volume-persisted index between deploys can't be relied on —
# baking it into the image trades build time/image size for a startup that needs no network call.
RUN uv run python -m app.rag.ingest

COPY --from=frontend-builder /frontend/dist frontend/dist

# The venv's own binaries directly, not `uv run` — `uv run` re-checks the environment against
# uv.lock on every invocation (a real, measured startup cost: rebuilds/reinstalls the local
# project package even right after `uv sync` already did it in the layer above) and would need
# network access to actually resolve anything if that check ever found a mismatch, which defeats
# the whole point of baking the RAG index in for a network-independent startup.
ENV PATH="/app/.venv/bin:$PATH"

# Railway (and most PaaS) inject PORT at runtime; default 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Shell form (not exec-form JSON array) because ${PORT} needs shell expansion — Railway (and
# most PaaS) inject it at runtime, so it can't be baked in as a literal. `exec` still replaces
# the shell process with uvicorn, so SIGTERM on container stop reaches uvicorn directly instead
# of being swallowed by an intermediate /bin/sh.
CMD exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}
