# Publicar imagen Docker en AWS ECR

## Pre-requisitos

- AWS CLI instalado (`aws --version`)
- Credenciales configuradas (`aws configure`)
- Docker corriendo localmente

## Variables de entorno recomendadas

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export IMAGE_NAME=imdb-rate-prediction
```

---

## Paso 1 — Crear el repositorio ECR (solo la primera vez)

```bash
aws ecr create-repository \
  --repository-name $IMAGE_NAME \
  --region $AWS_REGION
```

> Este paso también puede realizarse con Terraform (ver `infra/ecr.tf`).

---

## Paso 2 — Autenticarse en ECR

El token de autenticación expira cada 12 horas.

```bash
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

---

## Paso 3 — Construir la imagen local

```bash
docker build -t $IMAGE_NAME:latest .
```

---

## Paso 4 — Taggear la imagen con la URI del repositorio ECR

```bash
docker tag $IMAGE_NAME:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_NAME:latest
```

---

## Paso 5 — Hacer push al repositorio ECR

```bash
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_NAME:latest
```

---

## Paso 6 — Verificar que la imagen subió correctamente

```bash
aws ecr describe-images \
  --repository-name $IMAGE_NAME \
  --region $AWS_REGION
```

---

## Script automatizado

Todos los pasos anteriores están encadenados en `scripts/push-to-ecr.sh`.

```bash
chmod +x scripts/push-to-ecr.sh
./scripts/push-to-ecr.sh
```

---

## Siguiente paso: desplegar en ECS

Una vez que la imagen está en ECR, se puede levantar en AWS ECS con Terraform:

```bash
cd infra/
terraform init
terraform apply -var="image_uri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_NAME:latest"
```

Ver `infra/` para más detalles.
