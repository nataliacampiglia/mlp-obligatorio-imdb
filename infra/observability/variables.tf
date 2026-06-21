variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "bucket_name" {
  description = "Nombre del bucket S3 publico para el log de predicciones (globalmente unico)."
  type        = string
  default     = "mlp-imdb-observability-2026"
}

variable "image_tag" {
  description = "Tag de la imagen en ECR a desplegar."
  type        = string
  default     = "latest"
}

variable "cpu" {
  description = "Fargate CPU units (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate memory en MB."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Cantidad de tasks corriendo. Poner 0 para apagar y dejar de pagar."
  type        = number
  default     = 1
}
