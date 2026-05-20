# IGA Platform — Enterprise Identity Governance & Administration

A production-ready, cloud-native IGA platform built with Python/FastAPI backend and React/TypeScript frontend.

## Features

- **Identity Lifecycle Management** — Joiner/Mover/Leaver/Rehire automation, HRMS sync
- **Role-Based Access Control** — Hierarchical RBAC with dynamic role rules and role mining
- **Access Request Workflow** — Multi-step approval workflows with SLA enforcement
- **Segregation of Duties** — Real-time SoD conflict detection, preventive controls, mitigation
- **Access Certifications** — Periodic review campaigns with automated reminders
- **Privileged Access Management** — Session recording, break-glass emergency access
- **Risk Scoring** — AI-powered composite risk scoring (SoD + anomaly + over-provisioning)
- **Compliance Reporting** — SOX, GDPR, HIPAA, ISO27001, PCI-DSS, NIST frameworks
- **Multi-Tenancy** — Row-level isolation, per-tenant branding, usage metering
- **Connectors** — LDAP/AD, SCIM 2.0, Microsoft 365, Google Workspace, Salesforce, ServiceNow, Slack
- **Security** — MFA (TOTP/Email/SMS), OAuth2/OIDC, JWT, AES-256-GCM, Argon2id, Zero Trust

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async |
| Database | PostgreSQL 16 (asyncpg), Redis 7 |
| Task Queue | Celery 5 + RabbitMQ |
| Frontend | React 18, TypeScript, Tailwind CSS, Redux Toolkit |
| Auth | JWT, OAuth2, SAML2, TOTP MFA |
| APIs | REST, GraphQL (Strawberry), WebSocket, SCIM 2.0 |
| Policy | Open Policy Agent (OPA) |
| Storage | MinIO (S3-compatible) |
| Observability | Prometheus, Grafana, ELK Stack, OpenTelemetry |
| Container | Docker Compose, Kubernetes, Helm |
| CI/CD | GitHub Actions |
| IaC | Terraform |

## Quick Start

### Prerequisites

- Docker 24+ and Docker Compose v2
- 8GB RAM minimum

### 1. Clone and configure

```bash
git clone <repo-url>
cd IGA
cp .env.example .env
# Edit .env with your settings
```

### 2. Start all services

```bash
docker compose -f docker/docker-compose.yml up -d
```

### 3. Run database migrations

```bash
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head
```

### 4. Seed demo data

```bash
docker compose -f docker/docker-compose.yml exec backend python -m seed.seed_data
```

### 5. Access the platform

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | admin@acme.com / Demo@123456 |
| API Docs | http://localhost:8000/docs | — |
| GraphQL | http://localhost:8000/graphql | — |
| Flower (Celery) | http://localhost:5555 | admin / admin |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| Grafana | http://localhost:3001 | admin / admin |
| Kibana | http://localhost:5601 | — |
| RabbitMQ | http://localhost:15672 | guest / guest |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     NGINX (TLS Termination)              │
└───────────────────┬─────────────────┬───────────────────┘
                    │                 │
        ┌───────────▼──────┐ ┌────────▼──────────┐
        │  React Frontend  │ │  FastAPI Backend  │
        │  (port 3000)     │ │  (port 8000)      │
        └──────────────────┘ └───────┬───────────┘
                                     │
              ┌──────────────────────┼─────────────────────┐
              │                      │                     │
    ┌─────────▼───────┐   ┌──────────▼──────┐   ┌─────────▼────────┐
    │  PostgreSQL 16  │   │    Redis 7       │   │  RabbitMQ        │
    │  (port 5432)    │   │  (port 6379)     │   │  (port 5672)     │
    └─────────────────┘   └─────────────────┘   └──────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  Celery Workers      │
                          │  (provisioning,      │
                          │   risk, sod, sync)   │
                          └─────────────────────┘
```

## Project Structure

```
IGA/
├── backend/
│   ├── ai/                  # ML risk scoring
│   ├── audit/               # Immutable audit logger
│   ├── connectors/          # 10+ identity connectors
│   ├── graphql/             # Strawberry GraphQL schema
│   ├── middleware/          # Auth, tenant, rate limit, security
│   ├── models/              # 50+ SQLAlchemy models
│   ├── policy_engine/       # OPA client
│   ├── routes/              # 20 API routers
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # Business logic services
│   ├── tasks/               # Celery async tasks
│   └── utils/               # JWT, email, Redis, MinIO, crypto
├── frontend/
│   └── src/
│       ├── components/      # Reusable UI components
│       ├── hooks/           # Custom React hooks
│       ├── pages/           # 20 full-featured pages
│       ├── store/           # Redux Toolkit slices
│       ├── types/           # TypeScript type definitions
│       └── utils/           # API client, helpers
├── docker/                  # Dockerfiles, docker-compose.yml
├── k8s/                     # Kubernetes manifests
├── migrations/              # Alembic database migrations
├── monitoring/              # Prometheus, Grafana, ELK configs
├── nginx/                   # NGINX configuration
├── seed/                    # Demo data seed scripts
├── terraform/               # Infrastructure as code
└── tests/                   # Unit, integration, security tests
```

## API Documentation

- **OpenAPI (Swagger)**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **GraphQL Playground**: http://localhost:8000/graphql

### Key API Endpoints

```
POST   /api/v1/auth/login              Login
POST   /api/v1/auth/refresh            Refresh tokens
POST   /api/v1/auth/mfa/verify         MFA verification

GET    /api/v1/users                   List users
POST   /api/v1/users                   Create user
GET    /api/v1/users/{id}              Get user

GET    /api/v1/access-requests         List requests
POST   /api/v1/access-requests         Submit request
POST   /api/v1/access-requests/{id}/approve  Approve/reject

GET    /api/v1/sod/violations          SoD violations
POST   /api/v1/sod/scan                Run SoD scan

GET    /api/v1/risk/scores             Risk scores
POST   /api/v1/risk/recalculate-all    Recalculate all scores

GET    /api/v1/certifications          Certification campaigns
POST   /api/v1/certifications          Create campaign

GET    /api/v1/audit/logs              Audit trail

# SCIM 2.0
GET    /scim/v2/Users                  SCIM users
POST   /scim/v2/Users                  Provision user
GET    /scim/v2/Groups                 SCIM groups
```

## Environment Variables

See [.env.example](.env.example) for the full list of configuration options.

Key variables:
- `DATABASE_URL` — PostgreSQL async connection string
- `REDIS_URL` — Redis connection string
- `RABBITMQ_URL` — RabbitMQ AMQP URL
- `JWT_SECRET_KEY` — 64-char random secret for JWT signing
- `ENCRYPTION_KEY` — 32-byte hex key for AES-256-GCM
- `MINIO_*` — Object storage configuration

## Development

```bash
# Backend development (with hot reload)
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000

# Frontend development
cd frontend
npm install
npm run dev

# Run tests
pytest tests/ -v

# Run specific test category
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/security/ -v
```

## Deployment

See [docs/deployment_guide.md](docs/deployment_guide.md) for:
- Docker Compose production deployment
- Kubernetes deployment with Helm
- Terraform infrastructure provisioning
- Monitoring setup

## Security

- All passwords hashed with Argon2id
- Sensitive config encrypted with AES-256-GCM at rest
- JWT tokens with Redis-based blacklisting
- TLS 1.3 enforced in production
- Rate limiting per endpoint category
- CSP, HSTS, X-Frame-Options security headers
- OPA for attribute-based access control
- Immutable audit log (append-only, partitioned by month)

## License

Proprietary — All rights reserved.
