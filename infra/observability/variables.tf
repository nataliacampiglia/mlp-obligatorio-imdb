variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "bucket_name" {
  description = "Nombre del bucket S3 publico para el log de predicciones (globalmente unico)."
  type        = string
  default     = "mlp-imdb-observability-2026"
}
