export interface User {
  id: string
  email: string
  username: string
  firstName: string
  lastName: string
  displayName: string
  status: 'active' | 'inactive' | 'locked' | 'suspended' | 'pending'
  tenantId: string
  departmentId?: string
  managerId?: string
  isSuperadmin: boolean
  isTenantAdmin: boolean
  emailVerified: boolean
  mfaEnabled: boolean
  avatarUrl?: string
  phone?: string
  lastLoginAt?: string
  createdAt: string
  updatedAt: string
}

export interface Tenant {
  id: string
  name: string
  slug: string
  domain?: string
  status: 'active' | 'suspended' | 'trial'
  plan: string
  maxUsers: number
  userCount?: number
  createdAt: string
}

export interface Role {
  id: string
  tenantId: string
  name: string
  description?: string
  roleType: 'business' | 'technical' | 'dynamic'
  isPrivileged: boolean
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  createdAt: string
}

export interface Permission {
  id: string
  tenantId: string
  name: string
  resource: string
  action: string
  description?: string
}

export interface AccessRequest {
  id: string
  tenantId: string
  requesterId: string
  requesterName: string
  targetUserId: string
  targetUserName: string
  requestType: 'grant' | 'revoke' | 'modify'
  status: 'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired'
  priority: 'normal' | 'high' | 'emergency'
  justification: string
  riskScore?: number
  slaDeadline?: string
  items: AccessRequestItem[]
  createdAt: string
  updatedAt: string
}

export interface AccessRequestItem {
  id: string
  accessRequestId: string
  itemType: 'role' | 'entitlement' | 'application'
  itemId: string
  itemName: string
  action: 'grant' | 'revoke'
  validFrom?: string
  validUntil?: string
  status: string
}

export interface Approval {
  id: string
  accessRequestId: string
  approverId: string
  approverName: string
  status: 'pending' | 'approved' | 'rejected' | 'delegated' | 'expired'
  comments?: string
  approvedAt?: string
  createdAt: string
}

export interface Application {
  id: string
  tenantId: string
  name: string
  description?: string
  appType: string
  ownerId: string
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  isActive: boolean
  connectorId?: string
}

export interface Entitlement {
  id: string
  tenantId: string
  applicationId: string
  name: string
  description?: string
  entitlementType: string
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  requiresApproval: boolean
  isRequestable: boolean
}

export interface CertificationCampaign {
  id: string
  tenantId: string
  name: string
  description?: string
  campaignType: 'manager' | 'app_owner' | 'role_owner' | 'entitlement'
  status: 'draft' | 'active' | 'paused' | 'completed' | 'cancelled'
  startDate: string
  endDate: string
  deadline: string
  autoRevokeOnExpire: boolean
  totalItems?: number
  certifiedItems?: number
  revokedItems?: number
  pendingItems?: number
  createdAt: string
}

export interface CertificationItem {
  id: string
  campaignId: string
  userId: string
  userName: string
  itemType: string
  itemId: string
  itemName: string
  reviewerId: string
  status: 'pending' | 'certified' | 'revoked' | 'escalated'
  decisionReason?: string
  decidedAt?: string
  createdAt: string
}

export interface SODPolicy {
  id: string
  tenantId: string
  name: string
  description: string
  status: 'active' | 'inactive'
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  rules?: SODRule[]
}

export interface SODRule {
  id: string
  policyId: string
  name: string
  roleId1: string
  roleName1?: string
  roleId2: string
  roleName2?: string
  conflictType: string
  description: string
}

export interface SODViolation {
  id: string
  tenantId: string
  userId: string
  userName?: string
  ruleId: string
  ruleName?: string
  roleId1: string
  roleName1?: string
  roleId2: string
  roleName2?: string
  detectionDate: string
  status: 'open' | 'mitigated' | 'accepted' | 'resolved'
  riskScore: number
  mitigationNotes?: string
}

export interface RiskScore {
  userId: string
  tenantId: string
  overallScore: number
  sodScore: number
  anomalyScore: number
  overProvisioningScore: number
  certFailureScore: number
  peerDeviationScore: number
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  lastCalculatedAt: string
}

export interface Connector {
  id: string
  tenantId: string
  name: string
  connectorType: string
  status: 'active' | 'inactive' | 'error'
  healthStatus?: 'healthy' | 'unhealthy' | 'unknown'
  lastHealthCheck?: string
}

export interface AuditLog {
  id: string
  tenantId: string
  userId?: string
  userName?: string
  action: string
  resourceType: string
  resourceId?: string
  details?: Record<string, unknown>
  ipAddress?: string
  userAgent?: string
  result: 'success' | 'failure' | 'error'
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  createdAt: string
}

export interface Notification {
  id: string
  tenantId: string
  userId: string
  notificationType: string
  title: string
  message: string
  referenceType?: string
  referenceId?: string
  isRead: boolean
  readAt?: string
  createdAt: string
}

export interface PAMSession {
  id: string
  tenantId: string
  userId: string
  userName?: string
  privilegedAccountId: string
  accountName?: string
  justification: string
  status: 'active' | 'expired' | 'terminated'
  startedAt: string
  expiresAt: string
}

export interface DashboardStats {
  totalUsers: number
  activeUsers: number
  pendingApprovals: number
  openSODViolations: number
  activeCertifications: number
  highRiskUsers: number
  provisioningTasksPending: number
  connectorsHealthy: number
  connectorsTotal: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  perPage: number
}

export interface ApiResponse<T> {
  success: boolean
  data?: T
  message?: string
  error?: string
}

export interface LoginRequest {
  email: string
  password: string
  tenantSlug: string
  mfaCode?: string
}

export interface LoginResponse {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresIn: number
  user: User
}

export interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  tenantId: string | null
}

export interface WorkflowNode {
  id: string
  type: 'start' | 'approval' | 'condition' | 'parallel' | 'action' | 'end'
  label: string
  config?: Record<string, unknown>
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  label?: string
}

export interface Workflow {
  id: string
  tenantId: string
  name: string
  description?: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  isActive: boolean
  createdAt: string
  updatedAt: string
}

export interface Policy {
  id: string
  tenantId: string
  name: string
  description?: string
  effect: 'allow' | 'deny'
  subjectConditions: PolicyCondition[]
  resourceConditions: PolicyCondition[]
  actions: string[]
  isActive: boolean
  createdAt: string
}

export interface PolicyCondition {
  field: string
  operator: 'eq' | 'neq' | 'in' | 'nin' | 'gt' | 'lt' | 'contains'
  value: string | string[] | number
}

export interface HRMSSyncJob {
  id: string
  tenantId: string
  syncType: 'full' | 'incremental' | 'delta'
  status: 'pending' | 'running' | 'completed' | 'failed'
  recordsProcessed: number
  recordsFailed: number
  startedAt?: string
  completedAt?: string
  errorLog?: string
  createdAt: string
}

export interface ComplianceFramework {
  id: string
  name: string
  description: string
  controls: number
  passedControls: number
  failedControls: number
  compliancePercent: number
  lastAssessedAt?: string
  status: 'compliant' | 'non_compliant' | 'partial' | 'not_assessed'
}

export interface RoleMiningResult {
  id: string
  suggestedName: string
  userCount: number
  entitlements: string[]
  confidence: number
  businessUnit?: string
  status: 'suggested' | 'accepted' | 'rejected'
}
