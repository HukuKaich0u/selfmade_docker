#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/publish_fastapi_bundle.sh \
    --image fastapi-demo:latest \
    --bucket selfmade-docker-bundles-245381852209-apne1 \
    --key bundles/fastapi-bundle.tar.gz

Optional:
  --work-dir /tmp/selfmade-docker-bundle
  --keep-work-dir
  --check-only
  --install-missing

What it does:
  1. docker save
  2. skopeo copy docker-archive -> oci layout
  3. umoci unpack -> OCI bundle
  4. remove network namespace from config.json
  5. tar.gz the bundle
  6. upload to S3

Where to run it:
  Run this on one build machine only.
  Do not run it on every app EC2 instance.
EOF
}

print_install_hints() {
  cat <<'EOF' >&2

Install hints:
  docker : install Docker Engine and confirm `docker images` works
  skopeo : Ubuntu example `sudo apt-get install -y skopeo`
  umoci  : Ubuntu example `sudo apt-get install -y umoci`
  jq     : Ubuntu example `sudo apt-get install -y jq`
  aws    : install AWS CLI v2 and confirm `aws sts get-caller-identity` works

Recommended place to run this script:
  one build machine only
  examples: dev EC2, CI runner, Linux workstation
EOF
}

IMAGE=""
BUCKET=""
KEY=""
WORK_DIR="/tmp/selfmade-docker-bundle"
KEEP_WORK_DIR=0
CHECK_ONLY=0
INSTALL_MISSING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --bucket)
      BUCKET="$2"
      shift 2
      ;;
    --key)
      KEY="$2"
      shift 2
      ;;
    --work-dir)
      WORK_DIR="$2"
      shift 2
      ;;
    --keep-work-dir)
      KEEP_WORK_DIR=1
      shift
      ;;
    --check-only)
      CHECK_ONLY=1
      shift
      ;;
    --install-missing)
      INSTALL_MISSING=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$IMAGE" || -z "$BUCKET" || -z "$KEY" ]]; then
  usage >&2
  exit 1
fi

MISSING_CMDS=()
for cmd in docker skopeo umoci jq aws tar; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    MISSING_CMDS+=("$cmd")
  fi
done

if [[ "${#MISSING_CMDS[@]}" -gt 0 ]]; then
  if [[ "$INSTALL_MISSING" -eq 1 ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    "$SCRIPT_DIR/install_bundle_publish_deps.sh"

    MISSING_CMDS=()
    for cmd in docker skopeo umoci jq aws tar; do
      if ! command -v "$cmd" >/dev/null 2>&1; then
        MISSING_CMDS+=("$cmd")
      fi
    done
  fi

  if [[ "${#MISSING_CMDS[@]}" -gt 0 ]]; then
    echo "missing required commands: ${MISSING_CMDS[*]}" >&2
    print_install_hints
    exit 1
  fi
fi

echo "prerequisite check passed"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  exit 0
fi

TAR_PATH="$WORK_DIR/fastapi-bundle.tar.gz"
OCI_LAYOUT="$WORK_DIR/oci-layout"
BUNDLE_DIR="$WORK_DIR/fastapi-bundle"

if [[ "$KEEP_WORK_DIR" -eq 0 ]]; then
  rm -rf "$WORK_DIR"
fi
mkdir -p "$WORK_DIR"

echo "==> docker save: $IMAGE"
docker save "$IMAGE" -o "$WORK_DIR/image.tar"

echo "==> convert docker archive to oci layout"
rm -rf "$OCI_LAYOUT"
mkdir -p "$OCI_LAYOUT"
skopeo copy "docker-archive:$WORK_DIR/image.tar" "oci:$OCI_LAYOUT:latest"

echo "==> unpack oci bundle"
rm -rf "$BUNDLE_DIR"
umoci unpack --image "$OCI_LAYOUT:latest" "$BUNDLE_DIR"

echo "==> remove network namespace"
TMP_CONFIG="$WORK_DIR/config.json.tmp"
jq '.linux.namespaces |= map(select(.type != "network"))' \
  "$BUNDLE_DIR/config.json" > "$TMP_CONFIG"
mv "$TMP_CONFIG" "$BUNDLE_DIR/config.json"

echo "==> create tar.gz bundle"
rm -f "$TAR_PATH"
tar czf "$TAR_PATH" -C "$WORK_DIR" fastapi-bundle

echo "==> upload to s3://$BUCKET/$KEY"
aws s3 cp "$TAR_PATH" "s3://$BUCKET/$KEY"

echo "==> done"
echo "uploaded: s3://$BUCKET/$KEY"
echo "bundle archive: $TAR_PATH"
