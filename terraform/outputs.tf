# ============================================================
# IGA Platform — Terraform Output Definitions
# ============================================================

# ── General ───────────────────────────────────────────────────────────────────
output "aws_region" {
  description = "AWS region where resources are deployed."
  value       = var.aws_region
}

output "aws_account_id" {
  description = "AWS account ID."
  value       = data.aws_caller_identity.current.account_id
}

output "environment" {
  description = "Deployment environment."
  value       = var.environment
}

# ── VPC ───────────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "ID of the VPC."
  value       = module.vpc.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC."
  value       = module.vpc.vpc_cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets."
  value       = module.vpc.public_subnets
}

output "private_subnet_ids" {
  description = "IDs of the private subnets (EKS nodes)."
  value       = module.vpc.private_subnets
}

output "database_subnet_ids" {
  description = "IDs of the database subnets."
  value       = module.vpc.database_subnets
}

output "database_subnet_group_name" {
  description = "Name of the RDS subnet group."
  value       = module.vpc.database_subnet_group_name
}

output "nat_gateway_public_ips" {
  description = "Public IP addresses of the NAT Gateways."
  value       = module.vpc.nat_public_ips
}

# ── EKS ───────────────────────────────────────────────────────────────────────
output "eks_cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "Endpoint of the EKS API server."
  value       = module.eks.cluster_endpoint
  sensitive   = true
}

output "eks_cluster_certificate_authority_data" {
  description = "Base64-encoded CA certificate data for the EKS cluster."
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "eks_cluster_version" {
  description = "Kubernetes version of the EKS cluster."
  value       = module.eks.cluster_version
}

output "eks_oidc_provider_arn" {
  description = "ARN of the OIDC provider associated with the EKS cluster (for IRSA)."
  value       = module.eks.oidc_provider_arn
}

output "eks_oidc_provider_url" {
  description = "URL of the OIDC provider (without https://)."
  value       = module.eks.oidc_provider
}

output "eks_node_groups" {
  description = "Map of EKS managed node group attributes."
  value       = module.eks.eks_managed_node_groups
}

output "kubeconfig_command" {
  description = "AWS CLI command to configure kubectl for this cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

# ── RDS ───────────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)."
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "rds_hostname" {
  description = "RDS PostgreSQL hostname."
  value       = aws_db_instance.postgres.address
  sensitive   = true
}

output "rds_port" {
  description = "RDS PostgreSQL port."
  value       = aws_db_instance.postgres.port
}

output "rds_database_name" {
  description = "Name of the primary database."
  value       = aws_db_instance.postgres.db_name
}

output "rds_username" {
  description = "RDS master username."
  value       = aws_db_instance.postgres.username
  sensitive   = true
}

output "rds_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS master password."
  value       = aws_secretsmanager_secret.rds_password.arn
}

output "rds_instance_id" {
  description = "RDS instance identifier."
  value       = aws_db_instance.postgres.identifier
}

output "rds_arn" {
  description = "ARN of the RDS instance."
  value       = aws_db_instance.postgres.arn
}

output "database_url" {
  description = "Full async database URL for the backend (with asyncpg driver)."
  value       = "postgresql+asyncpg://${aws_db_instance.postgres.username}:PASSWORD@${aws_db_instance.postgres.address}:${aws_db_instance.postgres.port}/${aws_db_instance.postgres.db_name}"
  sensitive   = true
}

# ── ElastiCache Redis ─────────────────────────────────────────────────────────
output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint address."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive   = true
}

output "redis_reader_endpoint" {
  description = "ElastiCache Redis reader endpoint address (for read replicas)."
  value       = aws_elasticache_replication_group.redis.reader_endpoint_address
  sensitive   = true
}

output "redis_port" {
  description = "ElastiCache Redis port."
  value       = aws_elasticache_replication_group.redis.port
}

output "redis_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Redis auth token."
  value       = aws_secretsmanager_secret.redis_password.arn
}

output "redis_url" {
  description = "Redis URL for the backend (rediss:// uses TLS)."
  value       = "rediss://:REDIS_PASSWORD@${aws_elasticache_replication_group.redis.primary_endpoint_address}:${aws_elasticache_replication_group.redis.port}/0"
  sensitive   = true
}

# ── S3 ────────────────────────────────────────────────────────────────────────
output "s3_artifacts_bucket_name" {
  description = "Name of the S3 bucket for IGA artifacts/reports."
  value       = aws_s3_bucket.iga_artifacts.id
}

output "s3_artifacts_bucket_arn" {
  description = "ARN of the S3 artifacts bucket."
  value       = aws_s3_bucket.iga_artifacts.arn
}

output "s3_artifacts_bucket_domain" {
  description = "Domain name of the S3 artifacts bucket."
  value       = aws_s3_bucket.iga_artifacts.bucket_domain_name
}

# ── ECR ───────────────────────────────────────────────────────────────────────
output "ecr_backend_repository_url" {
  description = "URL of the ECR repository for the backend image."
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository_url" {
  description = "URL of the ECR repository for the frontend image."
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecr_registry_id" {
  description = "ECR registry ID (AWS account ID)."
  value       = aws_ecr_repository.backend.registry_id
}

# ── IAM Roles ─────────────────────────────────────────────────────────────────
output "iga_backend_iam_role_arn" {
  description = "ARN of the IAM role for the IGA backend service account (IRSA)."
  value       = aws_iam_role.iga_backend.arn
}

output "cluster_autoscaler_iam_role_arn" {
  description = "ARN of the IAM role for the Kubernetes Cluster Autoscaler."
  value       = aws_iam_role.cluster_autoscaler.arn
}

output "ebs_csi_iam_role_arn" {
  description = "ARN of the IAM role for the EBS CSI driver."
  value       = aws_iam_role.ebs_csi.arn
}

# ── KMS Keys ──────────────────────────────────────────────────────────────────
output "kms_rds_key_arn" {
  description = "ARN of the KMS key used to encrypt RDS."
  value       = aws_kms_key.rds.arn
}

output "kms_elasticache_key_arn" {
  description = "ARN of the KMS key used to encrypt ElastiCache."
  value       = aws_kms_key.elasticache.arn
}

output "kms_s3_key_arn" {
  description = "ARN of the KMS key used to encrypt S3."
  value       = aws_kms_key.s3.arn
}

# ── Security Groups ───────────────────────────────────────────────────────────
output "eks_cluster_security_group_id" {
  description = "ID of the EKS cluster security group."
  value       = aws_security_group.eks_cluster.id
}

output "rds_security_group_id" {
  description = "ID of the RDS security group."
  value       = aws_security_group.rds.id
}

output "elasticache_security_group_id" {
  description = "ID of the ElastiCache security group."
  value       = aws_security_group.elasticache.id
}

# ── DNS / ACM ─────────────────────────────────────────────────────────────────
output "acm_certificate_arn" {
  description = "ARN of the ACM certificate for the IGA domain."
  value       = var.create_dns_records ? aws_acm_certificate.this[0].arn : null
}

output "acm_certificate_status" {
  description = "Status of the ACM certificate."
  value       = var.create_dns_records ? aws_acm_certificate.this[0].status : null
}

# ── WAF ───────────────────────────────────────────────────────────────────────
output "waf_web_acl_arn" {
  description = "ARN of the WAFv2 WebACL (empty string if WAF is disabled)."
  value       = var.enable_waf ? aws_wafv2_web_acl.this[0].arn : ""
}

output "waf_web_acl_id" {
  description = "ID of the WAFv2 WebACL."
  value       = var.enable_waf ? aws_wafv2_web_acl.this[0].id : ""
}

# ── Summary ───────────────────────────────────────────────────────────────────
output "deployment_summary" {
  description = "Human-readable deployment summary."
  sensitive   = false
  value = <<-EOT
    ╔══════════════════════════════════════════════════════╗
    ║          IGA Platform Infrastructure Summary         ║
    ╠══════════════════════════════════════════════════════╣
    ║  Environment  : ${var.environment}
    ║  Region       : ${var.aws_region}
    ║  EKS Cluster  : ${module.eks.cluster_name}
    ║  RDS Endpoint : ${aws_db_instance.postgres.address}
    ║  Redis        : ${aws_elasticache_replication_group.redis.primary_endpoint_address}
    ║  ECR Backend  : ${aws_ecr_repository.backend.repository_url}
    ║  ECR Frontend : ${aws_ecr_repository.frontend.repository_url}
    ║  S3 Bucket    : ${aws_s3_bucket.iga_artifacts.id}
    ╠══════════════════════════════════════════════════════╣
    ║  Next steps:                                         ║
    ║  1. Run: ${join("\n    ", ["aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"])}
    ║  2. Apply Kubernetes manifests / Helm chart          ║
    ║  3. Run Alembic migrations: alembic upgrade head     ║
    ╚══════════════════════════════════════════════════════╝
  EOT
}
