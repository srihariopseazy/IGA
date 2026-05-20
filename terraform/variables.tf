# ============================================================
# IGA Platform — Terraform Variable Definitions
# ============================================================

# ── General ───────────────────────────────────────────────────────────────────
variable "aws_region" {
  description = "AWS region to deploy resources into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short project identifier used as a prefix in all resource names."
  type        = string
  default     = "iga"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be 2-21 lowercase alphanumeric characters or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment: development | staging | production."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be one of: development, staging, production."
  }
}

variable "team_email" {
  description = "Email address of the team owning this infrastructure (used in default tags)."
  type        = string
  default     = "platform-team@example.com"
}

# ── Networking ────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid CIDR block."
  }
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ, up to 3)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private (EKS) subnets (one per AZ, up to 3)."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "database_subnet_cidrs" {
  description = "CIDR blocks for database subnets (one per AZ, up to 3)."
  type        = list(string)
  default     = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
}

variable "single_nat_gateway" {
  description = "Use a single shared NAT Gateway instead of one per AZ. Reduces cost but creates a single point of failure."
  type        = bool
  default     = false
}

variable "enable_vpc_flow_logs" {
  description = "Enable VPC Flow Logs to CloudWatch Logs."
  type        = bool
  default     = true
}

# ── EKS ───────────────────────────────────────────────────────────────────────
variable "eks_cluster_version" {
  description = "Kubernetes version for the EKS cluster."
  type        = string
  default     = "1.31"
}

variable "eks_node_instance_types" {
  description = "EC2 instance types for the general-purpose managed node group."
  type        = list(string)
  default     = ["t3.xlarge", "t3a.xlarge"]
}

variable "eks_min_nodes" {
  description = "Minimum number of nodes in the general node group."
  type        = number
  default     = 2

  validation {
    condition     = var.eks_min_nodes >= 1
    error_message = "eks_min_nodes must be at least 1."
  }
}

variable "eks_max_nodes" {
  description = "Maximum number of nodes in the general node group."
  type        = number
  default     = 10
}

variable "eks_desired_nodes" {
  description = "Desired number of nodes at launch in the general node group."
  type        = number
  default     = 3
}

variable "eks_max_spot_nodes" {
  description = "Maximum number of Spot nodes for batch/Celery workloads."
  type        = number
  default     = 5
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the EKS public API endpoint. Restrict in production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ── RDS ───────────────────────────────────────────────────────────────────────
variable "rds_engine_version" {
  description = "PostgreSQL engine version for RDS."
  type        = string
  default     = "16.4"
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.large"
}

variable "rds_allocated_storage" {
  description = "Initial storage in GiB allocated to RDS."
  type        = number
  default     = 50
}

variable "rds_max_allocated_storage" {
  description = "Maximum auto-scaled storage in GiB for RDS (Storage Autoscaling)."
  type        = number
  default     = 500
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ deployment for RDS."
  type        = bool
  default     = true
}

variable "rds_backup_retention_days" {
  description = "Number of days to retain automated RDS backups."
  type        = number
  default     = 14

  validation {
    condition     = var.rds_backup_retention_days >= 1 && var.rds_backup_retention_days <= 35
    error_message = "rds_backup_retention_days must be between 1 and 35."
  }
}

variable "rds_enable_performance_insights" {
  description = "Enable RDS Performance Insights."
  type        = bool
  default     = true
}

# ── ElastiCache Redis ─────────────────────────────────────────────────────────
variable "redis_engine_version" {
  description = "Redis engine version for ElastiCache."
  type        = string
  default     = "7.1"
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.medium"
}

variable "redis_num_replicas" {
  description = "Number of read replicas in the Redis replication group (0 = no replicas, just primary)."
  type        = number
  default     = 1

  validation {
    condition     = var.redis_num_replicas >= 0 && var.redis_num_replicas <= 5
    error_message = "redis_num_replicas must be between 0 and 5."
  }
}

variable "redis_snapshot_retention_days" {
  description = "Number of days to retain ElastiCache Redis snapshots."
  type        = number
  default     = 7
}

# ── DNS / ACM ─────────────────────────────────────────────────────────────────
variable "create_dns_records" {
  description = "Whether to create Route53 DNS records and ACM certificate."
  type        = bool
  default     = true
}

variable "hosted_zone_name" {
  description = "Route53 hosted zone name (e.g. example.com). Required when create_dns_records = true."
  type        = string
  default     = "example.com"
}

variable "domain_name" {
  description = "Primary domain name for the IGA platform (e.g. iga.example.com)."
  type        = string
  default     = "iga.example.com"
}

# ── Security / WAF ────────────────────────────────────────────────────────────
variable "enable_waf" {
  description = "Enable AWS WAFv2 WebACL for the Application Load Balancer."
  type        = bool
  default     = true
}

variable "allowed_admin_cidrs" {
  description = "CIDRs that are allowed direct admin access (bastion, VPN)."
  type        = list(string)
  default     = []
}

# ── Tagging ───────────────────────────────────────────────────────────────────
variable "additional_tags" {
  description = "Additional tags to apply to all resources."
  type        = map(string)
  default     = {}
}
