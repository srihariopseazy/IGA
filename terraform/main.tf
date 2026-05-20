# ============================================================
# IGA Platform — Terraform Infrastructure (AWS)
# ============================================================
# Resources:
#   - VPC with public/private/database subnets across 3 AZs
#   - EKS cluster with managed node groups
#   - RDS PostgreSQL (Multi-AZ)
#   - ElastiCache Redis (cluster mode disabled, single shard)
#   - S3 bucket for Terraform state (bootstrap separately)
#   - ECR repositories for Docker images
#   - Route53 DNS + ACM certificate
#   - IAM roles (IRSA for EKS workloads)
# ============================================================

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.33"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.16"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket         = "iga-terraform-state"
    key            = "iga/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "iga-terraform-locks"
  }
}

# ── Provider configuration ────────────────────────────────────────────────────
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "IGA Platform"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = var.team_email
    }
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

# ── Data sources ─────────────────────────────────────────────────────────────
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

# ── Random suffix for globally unique names ───────────────────────────────────
resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  cluster_name = "${var.project_name}-${var.environment}-${random_id.suffix.hex}"
  azs          = slice(data.aws_availability_zones.available.names, 0, 3)

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ============================================================
# VPC
# ============================================================
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.project_name}-${var.environment}-vpc"
  cidr = var.vpc_cidr

  azs              = local.azs
  public_subnets   = var.public_subnet_cidrs
  private_subnets  = var.private_subnet_cidrs
  database_subnets = var.database_subnet_cidrs

  # Internet Gateway for public subnets
  create_igw = true

  # NAT Gateway — one per AZ for HA, or single for cost savings
  enable_nat_gateway     = true
  single_nat_gateway     = var.single_nat_gateway
  one_nat_gateway_per_az = !var.single_nat_gateway

  # DNS
  enable_dns_hostnames = true
  enable_dns_support   = true

  # VPC Flow Logs
  enable_flow_log                      = var.enable_vpc_flow_logs
  create_flow_log_cloudwatch_log_group = var.enable_vpc_flow_logs
  create_flow_log_cloudwatch_iam_role  = var.enable_vpc_flow_logs
  flow_log_max_aggregation_interval    = 60

  # Database subnet group (for RDS)
  create_database_subnet_group       = true
  create_database_subnet_route_table = true

  # Tags required by EKS for subnet auto-discovery
  public_subnet_tags = {
    "kubernetes.io/role/elb"                          = "1"
    "kubernetes.io/cluster/${local.cluster_name}"     = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"                 = "1"
    "kubernetes.io/cluster/${local.cluster_name}"     = "shared"
  }

  tags = local.common_tags
}

# ============================================================
# Security Groups
# ============================================================

# ── EKS cluster SG ───────────────────────────────────────────────────────────
resource "aws_security_group" "eks_cluster" {
  name        = "${local.cluster_name}-eks-cluster"
  description = "EKS cluster security group"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-eks-cluster" })
}

# ── RDS SG ────────────────────────────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${local.cluster_name}-rds"
  description = "RDS PostgreSQL security group"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
    description     = "PostgreSQL from EKS nodes"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-rds" })
}

# ── ElastiCache SG ────────────────────────────────────────────────────────────
resource "aws_security_group" "elasticache" {
  name        = "${local.cluster_name}-elasticache"
  description = "ElastiCache Redis security group"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
    description     = "Redis from EKS nodes"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-elasticache" })
}

# ============================================================
# EKS Cluster
# ============================================================
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.28"

  cluster_name    = local.cluster_name
  cluster_version = var.eks_cluster_version

  # Enable private AND public endpoint (restrict public via allowed CIDRs in prod)
  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.eks_public_access_cidrs
  cluster_endpoint_private_access      = true

  # VPC
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Enable IRSA (IAM Roles for Service Accounts)
  enable_irsa = true

  # EKS add-ons
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent    = true
      before_compute = true
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = aws_iam_role.ebs_csi.arn
    }
  }

  # Cluster access entry — grant admin to the deploying IAM entity
  enable_cluster_creator_admin_permissions = true

  # Managed node groups
  eks_managed_node_groups = {
    # General-purpose nodes (backend, frontend, monitoring)
    general = {
      name            = "${local.cluster_name}-general"
      instance_types  = var.eks_node_instance_types
      min_size        = var.eks_min_nodes
      max_size        = var.eks_max_nodes
      desired_size    = var.eks_desired_nodes
      capacity_type   = "ON_DEMAND"
      disk_size       = 50

      subnet_ids = module.vpc.private_subnets

      labels = {
        role = "general"
      }

      update_config = {
        max_unavailable_percentage = 33
      }

      tags = merge(local.common_tags, {
        "k8s.io/cluster-autoscaler/enabled"            = "true"
        "k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
      })
    }

    # Spot nodes for Celery workers (fault-tolerant workloads)
    spot = {
      name            = "${local.cluster_name}-spot"
      instance_types  = ["t3.xlarge", "t3a.xlarge", "m5.xlarge", "m5a.xlarge"]
      min_size        = 0
      max_size        = var.eks_max_spot_nodes
      desired_size    = 0
      capacity_type   = "SPOT"
      disk_size       = 50

      subnet_ids = module.vpc.private_subnets

      labels = {
        role             = "spot"
        "workload-type"  = "batch"
      }

      taints = [
        {
          key    = "spot"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]

      tags = merge(local.common_tags, {
        "k8s.io/cluster-autoscaler/enabled"            = "true"
        "k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
      })
    }
  }

  # Node security group — allow all traffic within the cluster VPC
  node_security_group_additional_rules = {
    ingress_self_all = {
      description = "Node to node all ports/protocols"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "ingress"
      self        = true
    }
  }

  tags = local.common_tags
}

# ── IAM Role for EBS CSI Driver (IRSA) ───────────────────────────────────────
resource "aws_iam_role" "ebs_csi" {
  name = "${local.cluster_name}-ebs-csi-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:kube-system:ebs-csi-controller-sa"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

# ── IAM Role for IGA Backend (IRSA) ──────────────────────────────────────────
resource "aws_iam_role" "iga_backend" {
  name = "${local.cluster_name}-iga-backend"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:iga:iga-backend"
        }
      }
    }]
  })
}

resource "aws_iam_policy" "iga_backend" {
  name        = "${local.cluster_name}-iga-backend"
  description = "IGA backend permissions: S3, Secrets Manager, SES"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.iga_artifacts.arn,
          "${aws_s3_bucket.iga_artifacts.arn}/*"
        ]
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:iga/*"
      },
      {
        Sid    = "SES"
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "iga_backend" {
  role       = aws_iam_role.iga_backend.name
  policy_arn = aws_iam_policy.iga_backend.arn
}

# ============================================================
# RDS PostgreSQL (Multi-AZ)
# ============================================================
resource "aws_db_subnet_group" "this" {
  name        = "${local.cluster_name}-db-subnet-group"
  description = "IGA RDS subnet group"
  subnet_ids  = module.vpc.database_subnets

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-db-subnet-group" })
}

resource "aws_db_parameter_group" "postgres" {
  name        = "${local.cluster_name}-pg16"
  family      = "postgres16"
  description = "IGA PostgreSQL 16 parameter group"

  parameter {
    name  = "max_connections"
    value = "200"
  }
  parameter {
    name  = "shared_buffers"
    value = "{DBInstanceClassMemory/16384}"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
  parameter {
    name  = "log_checkpoints"
    value = "1"
  }
  parameter {
    name  = "log_lock_waits"
    value = "1"
  }
  parameter {
    name  = "track_activity_query_size"
    value = "2048"
  }
  parameter {
    name  = "pg_stat_statements.track"
    value = "ALL"
  }

  tags = local.common_tags
}

# Random password for RDS
resource "random_password" "rds" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "rds_password" {
  name                    = "iga/${var.environment}/rds/password"
  description             = "IGA RDS master password"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "rds_password" {
  secret_id     = aws_secretsmanager_secret.rds_password.id
  secret_string = random_password.rds.result
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.cluster_name}-postgres"

  # Engine
  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  # Storage
  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  # Database
  db_name  = "iga_db"
  username = "iga_user"
  password = random_password.rds.result

  # Network
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  port                   = 5432

  # High availability
  multi_az = var.rds_multi_az

  # Parameter group
  parameter_group_name = aws_db_parameter_group.postgres.name

  # Backups
  backup_retention_period   = var.rds_backup_retention_days
  backup_window             = "03:00-04:00"
  maintenance_window        = "Mon:04:00-Mon:05:00"
  delete_automated_backups  = false
  copy_tags_to_snapshot     = true
  final_snapshot_identifier = "${local.cluster_name}-postgres-final-snapshot"
  skip_final_snapshot       = var.environment != "production"

  # Performance Insights
  performance_insights_enabled          = var.rds_enable_performance_insights
  performance_insights_retention_period = 7
  monitoring_interval                   = 60
  monitoring_role_arn                   = aws_iam_role.rds_enhanced_monitoring.arn

  # Deletion protection
  deletion_protection = var.environment == "production"

  # Auto minor version upgrade
  auto_minor_version_upgrade = true

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-postgres" })
}

# ── RDS Enhanced Monitoring role ─────────────────────────────────────────────
resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "${local.cluster_name}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ── KMS key for RDS encryption ────────────────────────────────────────────────
resource "aws_kms_key" "rds" {
  description             = "IGA RDS encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(local.common_tags, { Name = "${local.cluster_name}-rds-kms" })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${local.cluster_name}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# ============================================================
# ElastiCache Redis
# ============================================================
resource "aws_elasticache_subnet_group" "this" {
  name        = "${local.cluster_name}-redis-subnet-group"
  description = "IGA ElastiCache subnet group"
  subnet_ids  = module.vpc.private_subnets

  tags = local.common_tags
}

resource "aws_elasticache_parameter_group" "redis" {
  name        = "${local.cluster_name}-redis7"
  family      = "redis7"
  description = "IGA Redis 7 parameter group"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
  parameter {
    name  = "activerehashing"
    value = "yes"
  }
  parameter {
    name  = "lazyfree-lazy-eviction"
    value = "yes"
  }
  parameter {
    name  = "notify-keyspace-events"
    value = "Ex"
  }

  tags = local.common_tags
}

resource "random_password" "redis" {
  length           = 32
  special          = false
}

resource "aws_secretsmanager_secret" "redis_password" {
  name                    = "iga/${var.environment}/redis/password"
  description             = "IGA ElastiCache Redis auth token"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "redis_password" {
  secret_id     = aws_secretsmanager_secret.redis_password.id
  secret_string = random_password.redis.result
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${local.cluster_name}-redis"
  description          = "IGA Redis replication group"

  # Engine
  engine               = "redis"
  engine_version       = var.redis_engine_version
  node_type            = var.redis_node_type
  parameter_group_name = aws_elasticache_parameter_group.redis.name
  port                 = 6379

  # Auth
  auth_token                 = random_password.redis.result
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.elasticache.arn

  # Replication
  num_cache_clusters = var.redis_num_replicas + 1
  automatic_failover_enabled = var.redis_num_replicas > 0
  multi_az_enabled           = var.redis_num_replicas > 0

  # Network
  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.elasticache.id]

  # Maintenance & backup
  maintenance_window         = "tue:05:00-tue:06:00"
  snapshot_window            = "04:00-05:00"
  snapshot_retention_limit   = var.redis_snapshot_retention_days

  # Auto minor version upgrade
  auto_minor_version_upgrade = true

  # Apply changes immediately in non-prod
  apply_immediately = var.environment != "production"

  tags = merge(local.common_tags, { Name = "${local.cluster_name}-redis" })
}

# ── KMS key for ElastiCache encryption ───────────────────────────────────────
resource "aws_kms_key" "elasticache" {
  description             = "IGA ElastiCache encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(local.common_tags, { Name = "${local.cluster_name}-elasticache-kms" })
}

resource "aws_kms_alias" "elasticache" {
  name          = "alias/${local.cluster_name}-elasticache"
  target_key_id = aws_kms_key.elasticache.key_id
}

# ============================================================
# S3 — Artifact / Report Storage
# ============================================================
resource "aws_s3_bucket" "iga_artifacts" {
  bucket        = "${var.project_name}-${var.environment}-artifacts-${random_id.suffix.hex}"
  force_destroy = var.environment != "production"
  tags          = merge(local.common_tags, { Name = "iga-artifacts" })
}

resource "aws_s3_bucket_versioning" "iga_artifacts" {
  bucket = aws_s3_bucket.iga_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "iga_artifacts" {
  bucket = aws_s3_bucket.iga_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "iga_artifacts" {
  bucket                  = aws_s3_bucket.iga_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "iga_artifacts" {
  bucket = aws_s3_bucket.iga_artifacts.id

  rule {
    id     = "expire-old-reports"
    status = "Enabled"
    filter { prefix = "reports/" }
    expiration { days = 2555 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }

  rule {
    id     = "transition-exports-to-ia"
    status = "Enabled"
    filter { prefix = "exports/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    expiration { days = 365 }
  }
}

resource "aws_kms_key" "s3" {
  description             = "IGA S3 encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(local.common_tags, { Name = "${local.cluster_name}-s3-kms" })
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${local.cluster_name}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

# ============================================================
# ECR — Container Registries
# ============================================================
resource "aws_ecr_repository" "backend" {
  name                 = "${var.project_name}-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.ecr.arn
  }

  tags = merge(local.common_tags, { Name = "${var.project_name}-backend" })
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${var.project_name}-frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.ecr.arn
  }

  tags = merge(local.common_tags, { Name = "${var.project_name}-frontend" })
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 production images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = aws_ecr_lifecycle_policy.backend.policy
}

resource "aws_kms_key" "ecr" {
  description             = "IGA ECR encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(local.common_tags, { Name = "${local.cluster_name}-ecr-kms" })
}

# ============================================================
# Route53 + ACM Certificate
# ============================================================
data "aws_route53_zone" "this" {
  count = var.create_dns_records ? 1 : 0
  name  = var.hosted_zone_name
}

resource "aws_acm_certificate" "this" {
  count             = var.create_dns_records ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${var.domain_name}",
    "api.${var.domain_name}"
  ]

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(local.common_tags, { Name = var.domain_name })
}

resource "aws_route53_record" "cert_validation" {
  for_each = var.create_dns_records ? {
    for dvo in aws_acm_certificate.this[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.this[0].zone_id
}

resource "aws_acm_certificate_validation" "this" {
  count                   = var.create_dns_records ? 1 : 0
  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# ============================================================
# Cluster Autoscaler IAM
# ============================================================
resource "aws_iam_policy" "cluster_autoscaler" {
  name        = "${local.cluster_name}-cluster-autoscaler"
  description = "EKS Cluster Autoscaler policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ClusterAutoscalerDescribe"
        Effect = "Allow"
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup"
        ]
        Resource = ["*"]
      },
      {
        Sid    = "ClusterAutoscalerModify"
        Effect = "Allow"
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup"
        ]
        Resource = ["*"]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/enabled" = "true"
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role" "cluster_autoscaler" {
  name = "${local.cluster_name}-cluster-autoscaler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:kube-system:cluster-autoscaler"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_autoscaler" {
  role       = aws_iam_role.cluster_autoscaler.name
  policy_arn = aws_iam_policy.cluster_autoscaler.arn
}

# ============================================================
# WAF (Web Application Firewall) for ALB
# ============================================================
resource "aws_wafv2_web_acl" "this" {
  count = var.enable_waf ? 1 : 0
  name  = "${local.cluster_name}-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # AWS Managed Rules
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesCommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesKnownBadInputsRuleSet"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimitRule"
    priority = 3
    action { block {} }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRule"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.cluster_name}-waf"
    sampled_requests_enabled   = true
  }

  tags = local.common_tags
}
