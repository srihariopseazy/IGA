# Installation Guide

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Disk | 50 GB | 200 GB SSD |
| OS | Ubuntu 22.04 / RHEL 9 | Ubuntu 22.04 LTS |
| Docker | 24.0+ | Latest |
| Docker Compose | 2.20+ | Latest |
| Python | 3.12+ | 3.12 |
| Node.js | 20 LTS | 20 LTS |

## Option 1: Docker Compose (Recommended)

### Install Docker

```bash
# Ubuntu
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version        # Docker version 24+
docker compose version  # Docker Compose version v2.20+
```

### Clone and Configure

```bash
git clone <repository-url> iga
cd iga

# Create environment file
cp .env.example .env

# Generate required secrets
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"
echo "ENCRYPTION_KEY=$(openssl rand -hex 16)"
echo "DB_PASSWORD=$(openssl rand -base64 24)"
echo "REDIS_PASSWORD=$(openssl rand -base64 16)"
```

Edit `.env` and replace placeholder values with generated secrets above.

### Start Services

```bash
# Start all services in detached mode
docker compose -f docker/docker-compose.yml up -d

# Watch logs during startup
docker compose -f docker/docker-compose.yml logs -f backend

# Check all services are running
docker compose -f docker/docker-compose.yml ps
```

Expected output — all services should show `healthy`:
```
NAME              STATUS          PORTS
iga-postgres      healthy         5432/tcp
iga-redis         healthy         6379/tcp
iga-rabbitmq      healthy         5672/tcp, 15672/tcp
iga-backend       healthy         8000/tcp
iga-worker        running
iga-beat          running
iga-frontend      healthy         3000/tcp
iga-nginx         running         0.0.0.0:80->80/tcp
iga-minio         healthy         9000/tcp, 9001/tcp
```

### Initialize Database

```bash
# Run Alembic migrations
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head

# Verify tables created (should show 50+ tables)
docker compose -f docker/docker-compose.yml exec postgres \
  psql -U iga_user -d iga_db -c "\dt" | wc -l
```

### Seed Demo Data

```bash
docker compose -f docker/docker-compose.yml exec backend python -m seed.seed_data
```

This creates:
- Tenant: **Acme Corporation**
- 8 demo users (admin@acme.com password: `Demo@123456`)
- 6 applications with 17 entitlements
- Roles, permissions, SoD policies

### Access the Platform

| Service | URL |
|---------|-----|
| Frontend | http://localhost |
| API (Swagger) | http://localhost/docs |
| API (ReDoc) | http://localhost/redoc |
| GraphQL | http://localhost/graphql |
| Flower | http://localhost:5555 |
| MinIO Console | http://localhost:9001 |
| Grafana | http://localhost:3001 |
| Kibana | http://localhost:5601 |
| RabbitMQ | http://localhost:15672 |

---

## Option 2: Local Development Setup

### Python Backend

```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL=postgresql+asyncpg://iga_user:password@localhost:5432/iga_db
export REDIS_URL=redis://localhost:6379/0
export RABBITMQ_URL=amqp://guest:guest@localhost:5672/
export JWT_SECRET_KEY=$(openssl rand -hex 32)
export ENCRYPTION_KEY=$(openssl rand -hex 16)

# Run migrations
alembic upgrade head

# Start backend
uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0

# In separate terminals:
# Start Celery worker
celery -A backend.celery_app worker --loglevel=info -Q provisioning,risk,sod,notifications

# Start Celery beat
celery -A backend.celery_app beat --loglevel=info
```

### React Frontend

```bash
cd frontend

# Install dependencies
npm install

# Set API URL
echo "VITE_API_URL=http://localhost:8000" > .env.local

# Start development server
npm run dev
# Frontend available at http://localhost:5173

# Build for production
npm run build
```

### External Services (Docker only)

```bash
# Start just the supporting services
docker compose -f docker/docker-compose.yml up -d postgres redis rabbitmq minio
```

---

## Option 3: Kubernetes

See [deployment_guide.md](deployment_guide.md) for full Kubernetes instructions.

Quick start:

```bash
# Create namespace
kubectl create namespace iga

# Deploy
helm upgrade --install iga k8s/helm/ \
  --namespace iga \
  --set global.domain=iga.example.com

# Check pods
kubectl get pods -n iga
```

---

## Troubleshooting

### Backend won't start

```bash
# Check logs
docker compose -f docker/docker-compose.yml logs backend --tail=100

# Common issues:
# 1. Database not ready → wait 30s and retry
# 2. Missing env variable → check .env file
# 3. Port conflict → check if port 8000 is in use
```

### Database connection errors

```bash
# Test connection
docker compose -f docker/docker-compose.yml exec postgres \
  psql -U iga_user -d iga_db -c "SELECT 1"

# Reset database (DESTRUCTIVE)
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d postgres
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head
```

### Frontend not loading

```bash
# Check frontend logs
docker compose -f docker/docker-compose.yml logs frontend --tail=50

# Check NGINX
docker compose -f docker/docker-compose.yml logs nginx --tail=50

# Rebuild frontend
docker compose -f docker/docker-compose.yml build frontend
docker compose -f docker/docker-compose.yml up -d frontend
```

### Celery tasks not running

```bash
# Check worker status
docker compose -f docker/docker-compose.yml exec celery-worker \
  celery -A backend.celery_app inspect active

# Check RabbitMQ queues
# Open http://localhost:15672, login: guest/guest
# Check queue depth under Queues tab
```

### Reset Everything

```bash
# Stop all services and remove volumes (DESTRUCTIVE)
docker compose -f docker/docker-compose.yml down -v --remove-orphans

# Rebuild and restart
docker compose -f docker/docker-compose.yml up -d --build
```
