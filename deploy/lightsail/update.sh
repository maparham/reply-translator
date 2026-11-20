#!/usr/bin/env bash
# Ship this checkout's source to the box and restart the translator. The data volume and translator.env
# on the box are left as they are.
# Usage (from any directory):  deploy/lightsail/update.sh ec2-user@<server-ip>
# If the new version doesn't answer /health within 30 s, the previous image is started again.
set -euo pipefail
HOST=${1:?usage: $0 user@host}
cd "$(dirname "$0")/../.."  # the repo root, wherever this is run from (rsync --delete mirrors the cwd)
REMOTE=translator/deploy/lightsail

rsync -az --delete --exclude .git --exclude .venv --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.db*' --exclude '*.env' \
  --exclude '*.key' --exclude '*.age' --exclude .deploy.lock --exclude docs --exclude tests --exclude .superpowers --exclude .playwright-mcp --exclude android ./ "$HOST:translator/"
ssh "$HOST" bash -s <<REMOTE_SCRIPT
set -euo pipefail
cd $REMOTE
exec 9>.deploy.lock; flock -n 9 || { echo "another deploy is running; try again shortly"; exit 1; }
TAG=manual-\$(date -u +%Y%m%dT%H%M%SZ)
PREV=\$(sed -n 's/^TRANSLATOR_TAG=//p' .env 2>/dev/null || true)
sudo docker build -q -t "translator:\$TAG" ../.. >/dev/null
printf 'TRANSLATOR_TAG=%s\n' "\$TAG" > .env
sudo docker compose up -d --no-build
healthy() {
  for i in \$(seq 30); do
    if curl -fsS --max-time 5 http://127.0.0.1:18490/health >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}
if ! healthy; then
  echo "translator:\$TAG did not answer on http://127.0.0.1:18490/health within 30 s" >&2
  if [ -n "\$PREV" ]; then
    echo "rolling back to translator:\$PREV" >&2
    printf 'TRANSLATOR_TAG=%s\n' "\$PREV" > .env
    sudo docker compose up -d --no-build
    healthy && echo "rolled back; translator:\$PREV is answering" >&2
  fi
  exit 1
fi
curl -fsS http://127.0.0.1:18490/health && echo
# Prune old translator images (newest 3 manual-* tags stay); claude-proxy images are never touched.
sudo docker images translator --format '{{.Tag}}' | { grep '^manual-' || true; } | sort -r | tail -n +4 \\
  | while read -r old; do sudo docker rmi "translator:\$old" >/dev/null 2>&1 || true; done
REMOTE_SCRIPT
