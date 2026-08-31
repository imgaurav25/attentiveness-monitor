#!/usr/bin/env bash
# init_data_dir.sh
# ------------------
# Run this ONCE before the very first `docker compose up`.
#
# Why this is needed: docker-compose bind-mounts individual files
# (labels.json, trained_model.yml, settings.json) into the backend
# container so they persist across restarts/rebuilds. If those files don't
# already exist on the HOST before the containers start, Docker creates a
# DIRECTORY at that path instead of a file (a well-known Docker gotcha) --
# and the app will then fail to read/write them. Pre-creating them here as
# empty files avoids that entirely.
set -e
cd "$(dirname "$0")/.."

mkdir -p data/logs/snapshots
mkdir -p data/dataset

[ -f data/labels.json ] || echo '{}' > data/labels.json
touch data/trained_model.yml
touch data/settings.json

echo "data/ is ready. You can now run: docker compose up -d --build"
