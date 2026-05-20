# Deployment Guide

## Docker Compose (Development / Staging)

### Prerequisites

- Docker 24+
- Docker Compose v2
- 8GB RAM, 4 CPU cores minimum

### Steps

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env: set JWT_SECRET_KEY, ENCRYPTION_KEY, DB passwords

# 2. Generate secrets
openssl rand -hex 32    # Use as JWT_SECRET_KEY
openssl rand -hex 16    # Use as ENCRYPTION_KEY (must be exactly 32 hex chars)

# 3. Start all services
docker compose -f docker/docker-compose.yml up -d

# 4. Wait for PostgreSQL to be ready (about 30 seconds)
docker compose -f docker/docker-compose.yml exec postgres pg_isready -U iga_user

# 5. Run migrations
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head

# 6. Seed demo data (optional)
docker compose -f docker/docker-compose.yml exec backend python -m seed.seed_data

# 7. Verify all services are healthy
docker compose -f docker/docker-compose.yml ps
```

### Service Health Checks

```bash
curl http://localhost:8000/api/v1/health
# Expected: {"success": true, "data": {"status": "healthy", ...}}
```

---

## Kubernetes (Production)

### Prerequisites

- Kubernetes 1.28+
- kubectl configured
- Helm 3.12+
- An ingress controller (nginx-ingress)
- cert-manager (for TLS)

### Deploy with Helm

```bash
# Add dependencies (if using external chart dependencies)
helm dependency update k8s/helm/iga/

# Create namespace
kubectl create namespace iga

# Create secrets
kubectl create secret generic iga-secrets \
  --namespace iga \
  --from-literal=JWT_SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 16) \
  --from-literal=DB_PASSWORD=<your-db-password> \
  --from-literal=REDIS_PASSWORD=<your-redis-password>

# Deploy
helm upgrade --install iga k8s/helm/ \
  --namespace iga \
  --values k8s/helm/values.yaml \
  --set global.domain=iga.yourcompany.com \
  --set backend.replicas=3 \
  --set worker.replicas=5

# Check rollout
kubectl rollout status deployment/iga-backend -n iga
kubectl rollout status deployment/iga-frontend -n iga
```

### Database Setup (Production)

Use a managed PostgreSQL service (RDS, Cloud SQL, Azure DB):

```bash
# Update DATABASE_URL in secrets
kubectl create secret generic iga-db-url \
  --namespace iga \
  --from-literal=DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/iga

# Run migrations as a Kubernetes Job
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: iga-migrate
  namespace: iga
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: <your-registry>/iga-backend:latest
        command: ["alembic", "upgrade", "head"]
        envFrom:
        - secretRef:
            name: iga-secrets
      restartPolicy: Never
EOF
```

### Scaling

```bash
# Scale backend
kubectl scale deployment iga-backend --replicas=5 -n iga

# Scale Celery workers
kubectl scale deployment iga-celery-worker --replicas=10 -n iga

# Enable HPA (Horizontal Pod Autoscaler)
kubectl apply -f k8s/hpa.yaml
```

---

## CI/CD (GitHub Actions)

The repository includes two workflows:

### `.github/workflows/ci.yml` — Continuous Integration

Triggers on: push to any branch, pull requests to `main`

Steps:
1. Python 3.12 setup, pip install
2. PostgreSQL + Redis service containers
3. Run database migrations
4. Run pytest (unit + integration + security)
5. Frontend: npm install, TypeScript check, build
6. Docker build validation

### `.github/workflows/deploy.yml` — Continuous Deployment

Triggers on: push to `main` or version tags

Steps:
1. Build and push Docker images to registry
2. Deploy to staging (Docker Compose over SSH)
3. Run smoke tests
4. On tag: promote to production (Kubernetes)

### Required GitHub Secrets

```
REGISTRY_URL          — Docker registry URL
REGISTRY_USERNAME     — Registry credentials
REGISTRY_PASSWORD     — Registry password
STAGING_HOST          — SSH host for staging
STAGING_SSH_KEY       — SSH private key
KUBE_CONFIG           — Kubeconfig for production cluster
JWT_SECRET_KEY        — Production JWT secret
ENCRYPTION_KEY        — Production encryption key
```

---

## Monitoring Setup

### Prometheus + Grafana

```bash
# Prometheus scrapes metrics from:
# - Backend: /metrics (FastAPI Instrumentator)
# - Redis: redis_exporter
# - PostgreSQL: postgres_exporter
# - RabbitMQ: rabbitmq built-in /api/metrics

# Access Grafana
open http://localhost:3001
# Login: admin / admin (change in production!)

# Import dashboard
# Dashboard JSON is at: monitoring/grafana/dashboards/iga-overview.json
```

### ELK Stack

```bash
# Logstash collects logs from Docker containers via TCP
# All backend logs are JSON-structured

# Access Kibana
open http://localhost:5601

# Create index pattern: logstash-*
# Key fields: tenant_id, user_id, action, resource_type, status
```

### Alerting

Alert rules are defined in `monitoring/alert_rules.yml`:

- `HighErrorRate` — >5% 5xx responses for 5 minutes
- `BackendDown` — Backend instance unreachable
- `HighRiskUsersSpike` — Critical risk users increase >20% in 1 hour
- `DatabaseConnectionPoolExhausted` — DB connections near limit
- `CeleryQueueBacklog` — Task queue depth >1000

---

## Terraform (Infrastructure)

```bash
cd terraform

# Initialize
terraform init

# Plan
terraform plan -var="region=us-east-1" -out=tfplan

# Apply
terraform apply tfplan
```

Provisions:
- VPC with public/private subnets
- EKS cluster (3 nodes)
- RDS PostgreSQL (Multi-AZ)
- ElastiCache Redis (cluster mode)
- Amazon MQ (RabbitMQ)
- S3 bucket for MinIO-equivalent storage
- ACM certificates
- Route53 DNS records

---

## Production Checklist

- [ ] Change all default passwords in `.env`
- [ ] Set `DEBUG=false`
- [ ] Configure `ALLOWED_HOSTS` / `CORS_ORIGINS` to your domain
- [ ] Enable TLS (configure certificates in nginx/nginx.conf)
- [ ] Set up external PostgreSQL (not containerized)
- [ ] Set up Redis with password and persistence
- [ ] Configure SMTP for email notifications
- [ ] Configure MinIO with proper credentials and bucket policies
- [ ] Set up Prometheus alerting with PagerDuty/Slack integration
- [ ] Enable automatic database backups
- [ ] Review and tune rate limits for your scale
- [ ] Enable OPA for policy-based access control
- [ ] Configure SAML/OIDC SSO for enterprise login
- [ ] Set up log retention policies in Elasticsearch
