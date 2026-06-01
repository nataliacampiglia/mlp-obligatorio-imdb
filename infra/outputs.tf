output "ecr_repository_url" {
  description = "URI del repositorio ECR (usar en scripts/push-to-ecr.sh y en terraform apply -var image_uri=...)"
  value       = data.aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Nombre del cluster ECS"
  value       = aws_ecs_cluster.app.name
}

output "ecs_service_name" {
  description = "Nombre del servicio ECS"
  value       = aws_ecs_service.app.name
}

output "app_url" {
  description = "URL pública de la aplicación"
  value       = "http://${aws_lb.app.dns_name}"
}
