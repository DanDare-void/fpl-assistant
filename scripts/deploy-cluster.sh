#!/usr/bin/env bash
# Build the fpl-assistant image natively on keel-w5 and roll it out on the
# cluster. Run from anywhere on the management box (Beelink/WSL).
#
#   scripts/deploy-cluster.sh
#
# Steps: rsync source -> keel-w5, podman build (arm64, native), import the
# image into k3s containerd, apply manifests, restart the deployment.
set -euo pipefail

NODE="${NODE:-192.168.50.45}"                # keel-w5
KEY="$HOME/.ssh/void_runner"
SSH=(ssh -i "$KEY" "andrew@$NODE")
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="localhost/fpl-assistant:dev"

echo "==> Syncing source to keel-w5"
"${SSH[@]}" "mkdir -p build/fpl-assistant"
rsync -az --delete \
  --exclude .git --exclude venv --exclude data --exclude logs --exclude .env \
  --exclude frontend/node_modules --exclude frontend/dist \
  --exclude __pycache__ \
  -e "ssh -i $KEY" "$REPO_DIR"/ "andrew@$NODE:build/fpl-assistant/"

echo "==> Building image (podman, native arm64)"
"${SSH[@]}" "cd build/fpl-assistant && podman build -t $IMAGE ."

echo "==> Importing image into k3s containerd"
"${SSH[@]}" "podman save $IMAGE | sudo k3s ctr -n k8s.io images import -"

echo "==> Applying manifests + restarting"
kubectl apply -f "$REPO_DIR/k8s/fpl-assistant.yaml"
kubectl -n football rollout restart deployment/fpl-assistant
kubectl -n football rollout status deployment/fpl-assistant --timeout=300s

echo "==> Done. App at http://$NODE:30080 (any node IP works)"
