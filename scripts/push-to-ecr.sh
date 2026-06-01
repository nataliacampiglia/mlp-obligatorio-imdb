#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-imdb-rate-prediction}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_NAME"

echo "==> Creando repositorio ECR (si no existe)..."
aws ecr describe-repositories --repository-names "$IMAGE_NAME" --region "$AWS_REGION" > /dev/null 2>&1 || \
  aws ecr create-repository \
    --repository-name "$IMAGE_NAME" \
    --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true \
    --image-tag-mutability MUTABLE

echo "==> Autenticando en ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

echo "==> Construyendo imagen..."
docker build -t "$IMAGE_NAME:latest" .

echo "==> Taggeando imagen..."
docker tag "$IMAGE_NAME:latest" "$ECR_URI:latest"

echo "==> Pusheando imagen a ECR..."
docker push "$ECR_URI:latest"

echo "==> Listo. Imagen disponible en:"
echo "    $ECR_URI:latest"
