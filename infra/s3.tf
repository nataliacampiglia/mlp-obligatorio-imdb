data "aws_s3_bucket" "app_data" {
  bucket = "imdb-test-bucket-2026"
}

resource "aws_s3_bucket_policy" "app_read" {
  bucket = data.aws_s3_bucket.app_data.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowECSTaskRead"
        Effect = "Allow"
        Principal = {
          AWS = data.aws_iam_role.lab_role.arn
        }
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          data.aws_s3_bucket.app_data.arn,
          "${data.aws_s3_bucket.app_data.arn}/*"
        ]
      }
    ]
  })
}
