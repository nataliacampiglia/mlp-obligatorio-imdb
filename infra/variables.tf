variable "aws_region" {
  description = "Región AWS donde se despliegan los recursos"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Nombre de la aplicación (usado en ECR y ECS)"
  type        = string
  default     = "imdb-rate-prediction"
}

variable "image_uri" {
  description = "URI completa de la imagen en ECR, ej: 123456789.dkr.ecr.us-east-1.amazonaws.com/imdb-rate-prediction:latest"
  type        = string
}

variable "container_port" {
  description = "Puerto expuesto por el contenedor"
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "CPU units para la task de Fargate (256 = 0.25 vCPU)"
  type        = number
  default     = 256
}

variable "memory" {
  description = "Memoria en MB para la task de Fargate"
  type        = number
  default     = 512
}
