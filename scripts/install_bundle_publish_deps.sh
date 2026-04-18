#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/install_bundle_publish_deps.sh

What it installs on Ubuntu:
  - docker.io
  - skopeo
  - umoci
  - jq
  - unzip
  - AWS CLI v2

Notes:
  - requires sudo
  - expects Ubuntu with apt-get
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f /etc/os-release ]]; then
  echo "unsupported environment: missing /etc/os-release" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "unsupported distribution: expected Ubuntu, got ${ID:-unknown}" >&2
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "missing required command: sudo" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y docker.io skopeo umoci jq unzip curl

sudo systemctl enable --now docker

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$TMP_DIR/awscliv2.zip"
unzip -q "$TMP_DIR/awscliv2.zip" -d "$TMP_DIR"
sudo "$TMP_DIR/aws/install" --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update

echo "==> installed bundle publish dependencies"
echo "docker: $(command -v docker || true)"
echo "skopeo: $(command -v skopeo || true)"
echo "umoci: $(command -v umoci || true)"
echo "jq: $(command -v jq || true)"
echo "aws: $(command -v aws || true)"
