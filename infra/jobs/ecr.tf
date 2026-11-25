resource "aws_ecr_repository" "jobs" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Deployed images are tagged sha-<commit>. Keeping the newest var.ecr_retained_images of them
# protects the live version and every rollback target (CI rolls back within that window).
# Untagged layers left by interrupted pushes expire after a day.
resource "aws_ecr_lifecycle_policy" "jobs" {
  repository = aws_ecr_repository.jobs.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the newest deployed images for rollback"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_retained_images
        }
        action = { type = "expire" }
      },
    ]
  })
}
