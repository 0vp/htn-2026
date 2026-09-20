#!/usr/bin/env bash
set -euo pipefail
# Installs the Codex CLI the voice agent runs on the server, and logs the service user in.
# Both binaries are required: without codex-code-mode-host every room/motion tool call fails
# ("Code Mode is unavailable"), and without codex on PATH voice sessions start with Codex off.
# Run as root. Uses OPENAI_API_KEY from /etc/htn/voice.env.
VERSION=${CODEX_VERSION:-0.154.0}
BASE=https://github.com/openai/codex/releases/download/rust-v$VERSION
cd "$(mktemp -d)"
for name in codex codex-code-mode-host; do
  curl -sfL -o "$name.tgz" "$BASE/$name-x86_64-unknown-linux-musl.tar.gz"
  tar -xzf "$name.tgz"
  install -m 755 "$name-x86_64-unknown-linux-musl" "/usr/local/bin/$name"
done
set -a; . /etc/htn/voice.env; set +a
sudo -u htn --preserve-env=OPENAI_API_KEY env HOME=/var/lib/htn \
  bash -c 'printenv OPENAI_API_KEY | codex login --with-api-key'
systemctl restart htn-backend
