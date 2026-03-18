#!/bin/bash
# Диагностика Docker на сервере. Запуск: ./diagnose_docker.sh /opt/deploy/eee555

set -e
BUILD_PATH="${1:-/opt/deploy/eee555}"

echo "=== Docker diagnostic ==="
echo "PATH=$PATH"
echo "Build path: $BUILD_PATH"
echo "Path exists: $([ -d "$BUILD_PATH" ] && echo yes || echo no)"
echo "Dockerfile exists: $([ -f "$BUILD_PATH/Dockerfile" ] && echo yes || echo no)"
echo ""
echo "Docker version:"
docker version 2>&1 || true
echo ""
echo "Docker info (builder):"
docker buildx ls 2>&1 || true
echo ""
echo "Base images (локальные теги — Docker не ходит в registry за metadata):"
for img in deploy-node:22-alpine deploy-nginx:alpine; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "  $img — в кэше"
  else
    echo "  $img — НЕТ, запустить: /opt/deploy_api/scripts/docker_pull_images.sh"
  fi
done
echo ""
echo "Test 1: docker build . (from dir)"
(cd "$BUILD_PATH" && docker build -t test-diagnose . 2>&1) || true
echo ""
echo "Test 2: docker build PATH (absolute)"
docker build -t test-diagnose2 "$BUILD_PATH" 2>&1 || true
echo ""
echo "Test 3: bash -c with path"
bash -c "docker build -t test-diagnose3 $BUILD_PATH" 2>&1 || true
echo ""
echo "Test 4: deploy_single.sh style (cd + DOCKER_BUILDKIT=1 + .)"
(cd "$BUILD_PATH" && DOCKER_BUILDKIT=1 docker build -t test-deploy-style --pull never . 2>&1) || true
echo ""
echo "Test 5: как воркер (минимальный PATH)"
(PATH=/usr/bin:/bin cd "$BUILD_PATH" && DOCKER_BUILDKIT=1 docker build -t test-worker-style --pull never . 2>&1) || true
