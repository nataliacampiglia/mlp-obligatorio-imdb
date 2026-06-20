output "bucket_name" {
  value = aws_s3_bucket.observability.bucket
}

output "bucket_url" {
  description = "URL HTTPS base. Los objetos quedan accesibles como <bucket_url>/<key>."
  value       = "https://${aws_s3_bucket.observability.bucket}.s3.${var.aws_region}.amazonaws.com"
}

output "ecr_repository_url" {
  description = "URI del repo ECR donde se publica la imagen del dashboard."
  value       = aws_ecr_repository.monitoring.repository_url
}

output "ecs_service_name" {
  description = "Nombre del service ECS. Util para 'aws ecs update-service ...'."
  value       = aws_ecs_service.monitoring.name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.monitoring.name
}

output "monitoring_public_ip_command" {
  description = "Comando para obtener la IP publica actual del task. La IP cambia cada vez que el task reinicia."
  value       = "aws ecs list-tasks --cluster ${aws_ecs_cluster.monitoring.name} --service-name ${aws_ecs_service.monitoring.name} --query 'taskArns[0]' --output text | xargs -I {} aws ecs describe-tasks --cluster ${aws_ecs_cluster.monitoring.name} --tasks {} --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text | xargs -I {} aws ec2 describe-network-interfaces --network-interface-ids {} --query 'NetworkInterfaces[0].Association.PublicIp' --output text"
}
