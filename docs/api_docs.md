# API Documentation

Base URL: `https://api.yourcompany.com`  
API Version: `v1`  
Authentication: Bearer JWT

## Authentication

### Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass@123",
  "device_fingerprint": "optional-device-id"
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGci...",
    "refresh_token": "eyJhbGci...",
    "token_type": "bearer",
    "expires_in": 900,
    "mfa_required": false,
    "user": { "id": "uuid", "email": "user@example.com", "full_name": "..." }
  }
}
```

### Refresh Token

```http
POST /api/v1/auth/refresh
Content-Type: application/json

{ "refresh_token": "eyJhbGci..." }
```

### MFA Verify

```http
POST /api/v1/auth/mfa/verify
Content-Type: application/json

{ "mfa_token": "tmp-token", "code": "123456", "method": "totp" }
```

### Logout

```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
```

---

## Users

### List Users

```http
GET /api/v1/users?page=1&limit=20&search=alice&is_active=true
Authorization: Bearer <token>
```

**Response:**
```json
{
  "success": true,
  "data": [...],
  "total": 100,
  "page": 1,
  "limit": 20
}
```

### Create User

```http
POST /api/v1/users
Authorization: Bearer <token>
Content-Type: application/json

{
  "email": "newuser@company.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "username": "jane.doe",
  "password": "SecurePass@123",
  "department_id": "uuid",
  "employee_id": "EMP001"
}
```

### Update User

```http
PATCH /api/v1/users/{user_id}
Authorization: Bearer <token>
Content-Type: application/json

{ "first_name": "Janet", "department_id": "new-uuid" }
```

### Deactivate/Activate User

```http
POST /api/v1/users/{user_id}/deactivate
POST /api/v1/users/{user_id}/activate
Authorization: Bearer <token>
```

---

## Access Requests

### Submit Request

```http
POST /api/v1/access-requests
Authorization: Bearer <token>
Content-Type: application/json

{
  "entitlement_ids": ["uuid1", "uuid2"],
  "business_justification": "Need for project XYZ",
  "request_for_user_id": "optional-uuid"
}
```

### List My Requests

```http
GET /api/v1/access-requests?status=pending&page=1&limit=20
Authorization: Bearer <token>
```

### Approve / Reject

```http
POST /api/v1/access-requests/{request_id}/approve
Authorization: Bearer <token>
Content-Type: application/json

{
  "action": "approve",
  "comment": "Approved for Q3 project"
}
```

### Bulk Approve

```http
POST /api/v1/access-requests/bulk-approve
Authorization: Bearer <token>
Content-Type: application/json

{
  "request_ids": ["uuid1", "uuid2"],
  "action": "approve"
}
```

---

## SoD (Segregation of Duties)

### List Violations

```http
GET /api/v1/sod/violations?status=open&severity=high
Authorization: Bearer <token>
```

### Run SoD Scan

```http
POST /api/v1/sod/scan
Authorization: Bearer <token>
```

### Simulate Conflict

```http
POST /api/v1/sod/simulate
Authorization: Bearer <token>
Content-Type: application/json

{
  "user_id": "uuid",
  "entitlement_id": "uuid"
}
```

### Mitigate Violation

```http
POST /api/v1/sod/violations/{violation_id}/mitigate
Authorization: Bearer <token>
Content-Type: application/json

{ "note": "Mitigation control in place: dual approval required" }
```

---

## Risk

### Get Risk Scores

```http
GET /api/v1/risk/scores?risk_level=high&page=1&limit=50
Authorization: Bearer <token>
```

### Get User Risk Details

```http
GET /api/v1/risk/users/{user_id}
Authorization: Bearer <token>
```

### Recalculate All Scores

```http
POST /api/v1/risk/recalculate-all
Authorization: Bearer <token>
```

---

## Certifications

### List Campaigns

```http
GET /api/v1/certifications?status=active
Authorization: Bearer <token>
```

### Create Campaign

```http
POST /api/v1/certifications
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Q2 2026 User Access Review",
  "campaign_type": "user_access",
  "start_date": "2026-06-01",
  "end_date": "2026-06-30"
}
```

### Submit Decision

```http
POST /api/v1/certifications/{campaign_id}/items/{item_id}/decision
Authorization: Bearer <token>
Content-Type: application/json

{ "decision": "certify", "comment": "Access verified and appropriate" }
```

---

## Audit Logs

### Search Audit Logs

```http
GET /api/v1/audit/logs?action=login&actor_id=uuid&date_from=2026-01-01&date_to=2026-12-31&status=success&page=1&limit=50
Authorization: Bearer <token>
```

### Export Logs (CSV)

```http
GET /api/v1/audit/export?date_from=2026-01-01&date_to=2026-03-31
Authorization: Bearer <token>
```

---

## SCIM 2.0

SCIM endpoint: `/scim/v2/`  
Authentication: Bearer token

### List Users

```http
GET /scim/v2/Users?startIndex=1&count=100&filter=userName eq "alice"
Authorization: Bearer <scim-token>
```

### Provision User

```http
POST /scim/v2/Users
Authorization: Bearer <scim-token>
Content-Type: application/scim+json

{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
  "userName": "alice@company.com",
  "name": { "givenName": "Alice", "familyName": "Smith" },
  "emails": [{ "value": "alice@company.com", "primary": true }],
  "active": true
}
```

### Deprovision User

```http
PATCH /scim/v2/Users/{id}
Authorization: Bearer <scim-token>
Content-Type: application/scim+json

{
  "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
  "Operations": [{ "op": "replace", "path": "active", "value": false }]
}
```

---

## GraphQL

Endpoint: `/graphql`

```graphql
query ListUsers {
  users(limit: 20, offset: 0) {
    id
    email
    fullName
    isActive
    createdAt
  }
}

query GetRiskScores {
  riskScores(limit: 50) {
    id
    userId
    overallScore
    riskLevel
    calculatedAt
  }
}

query ListApplications {
  applications(limit: 50) {
    id
    name
    description
    isActive
  }
}
```

---

## WebSocket

Connect: `wss://api.yourcompany.com/ws/{tenant_id}/{user_id}?token={access_token}`

### Message Types

```json
{ "type": "notification", "data": { "title": "...", "message": "...", "level": "info" } }
{ "type": "risk_alert", "data": { "user_id": "...", "new_risk_level": "high" } }
{ "type": "approval_required", "data": { "request_id": "...", "requester_name": "..." } }
{ "type": "sod_violation", "data": { "violation_id": "...", "severity": "critical" } }
{ "type": "provisioning_complete", "data": { "request_id": "...", "status": "success" } }
```

---

## Error Responses

All errors follow the format:

```json
{
  "success": false,
  "message": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE",
  "details": {}
}
```

| Status | Error Code | Meaning |
|--------|-----------|---------|
| 400 | VALIDATION_ERROR | Invalid request data |
| 401 | UNAUTHORIZED | Missing or invalid token |
| 403 | FORBIDDEN | Insufficient permissions |
| 404 | NOT_FOUND | Resource not found |
| 409 | CONFLICT | Duplicate resource |
| 422 | UNPROCESSABLE | Business rule violation |
| 429 | RATE_LIMITED | Too many requests |
| 500 | INTERNAL_ERROR | Server error |
