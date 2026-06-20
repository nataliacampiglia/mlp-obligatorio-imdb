resource "aws_ecr_repository" "monitoring" {
  name                 = "mlp-imdb-monitoring"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
