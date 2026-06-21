#!/usr/bin/env bash
# Build and push the monitoring image to ECR.
# Run from the repo root with valid AWS creds in env.
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
REPO_NAME="${REPO_NAME:-mlp-imdb-monitoring}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}"

echo "==> Login to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Build image (linux/amd64)"
docker buildx build --platform linux/amd64 \
  -f monitoring/Dockerfile \
  -t "$REPO_NAME:$IMAGE_TAG" \
  --load \
  .

echo "==> Tag and push to ECR"
docker tag "$REPO_NAME:$IMAGE_TAG" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

echo "==> Pushed: ${ECR_URI}:${IMAGE_TAG}"
echo "==> Forcing ECS service to redeploy"
aws ecs update-service \
  --cluster mlp-imdb-monitoring \
  --service mlp-imdb-monitoring \
  --force-new-deployment \
  --region "$AWS_REGION" \
  >/dev/null
echo "==> Done"
