# IMDB Rate Prediction

Servicio web para predicción de sentimiento en reseñas de películas IMDB. Backend construido con FastAPI, empaquetado en Docker y desplegado en AWS ECS con Fargate.

---

## Estructura del proyecto

```
.
├── deployment/          # Aplicación FastAPI
│   ├── main.py
│   ├── requirements.txt
│   └── static/
│       └── index.html
├── docs/
│   └── ecr-publish.md   # Guía detallada de publicación en ECR
├── infra/               # Infraestructura como código (Terraform)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── ecr.tf
│   └── ecs.tf
├── scripts/
│   └── push-to-ecr.sh   # Script para publicar imagen en ECR
├── Dockerfile
└── docker-compose.yml
```

---

## Levantar la app localmente

### Pre-requisitos

- Docker y Docker Compose instalados

### Pasos

```bash
docker compose up --build
```

La app queda disponible en [http://localhost:8000](http://localhost:8000).

### Endpoints disponibles

| Método | Ruta      | Descripción                  |
|--------|-----------|------------------------------|
| GET    | `/`       | Página web principal         |
| GET    | `/status` | Health check del servicio    |

---

## Desplegar en AWS ECS

### Pre-requisitos

- AWS CLI instalado y configurado (`aws configure`)
- Docker corriendo localmente
- Terraform >= 1.0 instalado

### Paso 1 — Publicar la imagen en ECR

El script crea el repositorio ECR si no existe, construye la imagen y la publica:

```bash
chmod +x scripts/push-to-ecr.sh
./scripts/push-to-ecr.sh
```

Variables configurables (opcionales, tienen defaults):

```bash
export IMAGE_NAME=imdb-rate-prediction
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<tu-account-id>
```

### Paso 2 — Provisionar infraestructura con Terraform

```bash
cd infra/
terraform init
terraform apply -var="image_uri=<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/imdb-rate-prediction:latest"
```

Al finalizar, Terraform imprime la URL pública de la aplicación:

```
app_url = "http://imdb-rate-prediction-xxxx.us-east-1.elb.amazonaws.com"
```

### Paso 3 — Verificar el despliegue

```bash
curl http://<app_url>/status
# {"status": "ok", "model": "not loaded"}
```

### Destruir la infraestructura

```bash
cd infra/
terraform destroy -var="image_uri=<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/imdb-rate-prediction:latest"
```

> El repositorio ECR no es gestionado por Terraform (fue creado por el script). Para eliminarlo manualmente:
> ```bash
> aws ecr delete-repository --repository-name imdb-rate-prediction --force --region us-east-1
> ```
