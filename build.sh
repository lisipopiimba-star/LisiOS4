#!/usr/bin/env bash
# Сборка ISO на Linux/macOS (нужен Docker или Podman):  ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
RT=docker; command -v docker >/dev/null || RT=podman
command -v "$RT" >/dev/null || { echo "Нужен docker или podman"; exit 1; }
mkdir -p out
"$RT" run --rm --privileged -v "$PWD":/src:ro -v "$PWD/out":/out \
  docker.io/library/archlinux:latest bash /src/scripts/build-in-container.sh
echo "ISO лежит в: $PWD/out"
