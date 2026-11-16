# syntax=docker/dockerfile:1
# SpaceSweepers production image: small, non-root, no build tools or test deps.

FROM python:3.14-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SS_CACHE_DIR=/tmp/spacesweepers
# Pick up Debian security fixes published after the base image was built. The image scan (Grype) blocks on fixable high findings;
# this cleared two in zlib1g (CVE-2026-76844, CVE-2026-85091). The apt lists are removed so the layer stays small.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin spacesweepers
WORKDIR /app
COPY --from=build /install /usr/local
COPY app/ app/
# Nimbus agent specs: the app loads its SI prompts and schemas from these files.
COPY Nimbus/ Nimbus/
# Everything the dashboard is built from, in one folder: the PSI snapshot (data/snapshot: records, test tables, document text,
# simulation list, manifest), the reviewed mappings and ledger, vocabulary, method flags and the pillar and outcome evidence.
COPY data/ data/
COPY static/ static/
# Licence documentation travels with the image: the code licence at the root, and license/ with the licence list and third-party notices.
COPY LICENSE.txt ./
COPY license/ license/
# Build-time check of the packaged data (the whole "cache": the catalog and search library are rebuilt in memory from data/).
# The build fails if the snapshot is incomplete or a mapped table changed after it was mapped.
RUN test -f data/snapshot/manifest.json && for d in records tables docs simulations analyzed; do test -d data/snapshot/$d || { echo "missing data/snapshot/$d"; exit 1; }; done \
 && python -m app.warm
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta', timeout=4)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
