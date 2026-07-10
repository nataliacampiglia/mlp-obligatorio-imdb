data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_iam_role" "lab_role" {
  name = "LabRole"
}

resource "aws_cloudwatch_log_group" "monitoring" {
  name              = "/ecs/mlp-imdb-monitoring"
  retention_in_days = 7
}

resource "aws_security_group" "monitoring" {
  name        = "mlp-imdb-monitoring-sg"
  description = "Allow Streamlit (8501) from internet"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_cluster" "monitoring" {
  name = "mlp-imdb-monitoring"
}

resource "aws_ecs_task_definition" "monitoring" {
  family                   = "mlp-imdb-monitoring"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = data.aws_iam_role.lab_role.arn

  container_definitions = jsonencode([
    {
      name      = "monitoring"
      image     = "${aws_ecr_repository.monitoring.repository_url}:${var.image_tag}"
      essential = true
      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "OBS_BUCKET_NAME", value = aws_s3_bucket.observability.bucket },
        { name = "OBS_BUCKET_REGION", value = var.aws_region },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.monitoring.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "monitoring" {
  name            = "mlp-imdb-monitoring"
  cluster         = aws_ecs_cluster.monitoring.id
  task_definition = aws_ecs_task_definition.monitoring.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.monitoring.id]
    assign_public_ip = true
  }
}
