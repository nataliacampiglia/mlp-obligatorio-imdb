output "bucket_name" {
  value = aws_s3_bucket.observability.bucket
}

output "bucket_url" {
  description = "URL HTTPS base. Los objetos quedan accesibles como <bucket_url>/<key>."
  value       = "https://${aws_s3_bucket.observability.bucket}.s3.${var.aws_region}.amazonaws.com"
}
