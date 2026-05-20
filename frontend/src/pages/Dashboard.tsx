import React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'
import {
  Users, AlertTriangle, CheckSquare, Shield, Activity, Plug,
  TrendingUp, Clock, Check, X
} from 'lucide-react'
import { format, subDays } from 'date-fns'
import api from '@/utils/api'
import { StatsCard } from '@/components/ui/StatsCard'
import { Badge } from '@/components/ui/Badge'
import { PageHeader } from '@/components/ui/PageHeader'
import { formatRelativeTime, formatDate, getRiskBgColor } from '@/utils/helpers'
import { DashboardStats, AccessRequest, Connector, AuditLog, CertificationCampaign } from '@/types'
import toast from 'react-hot-toast'

// Generate 30-day mock trend data
const generateTrendData = () => {
  return Array.from({ length: 30 }, (_, i) => ({
    date: format(subDays(new Date(), 29 - i), 'MMM d'),
    requests: Math.floor(Math.random() * 40) + 10,
    approved: Math.floor(Math.random() * 30) + 5,
    rejected: Math.floor(Math.random() * 8) + 1,
  }))
}
const trendData = generateTrendData()

const mockStats: DashboardStats = {
  totalUsers: 2847,
  activeUsers: 2612,
  pendingApprovals: 23,
  openSODViolations: 7,
  activeCertifications: 3,
  highRiskUsers: 12,
  provisioningTasksPending: 5,
  connectorsHealthy: 8,
  connectorsTotal: 10,
}

const mockApprovals: AccessRequest[] = [
  { id: '1', tenantId: 't1', requesterId: 'u1', requesterName: 'Alice Johnson', targetUserId: 'u2', targetUserName: 'Bob Smith', requestType: 'grant', status: 'pending', priority: 'high', justification: 'Project escalation requires admin access', riskScore: 72, slaDeadline: subDays(new Date(), -1).toISOString(), items: [], createdAt: subDays(new Date(), 2).toISOString(), updatedAt: subDays(new Date(), 2).toISOString() },
  { id: '2', tenantId: 't1', requesterId: 'u3', requesterName: 'Carol White', targetUserId: 'u4', targetUserName: 'David Lee', requestType: 'grant', status: 'pending', priority: 'normal', justification: 'Read access to finance reports', riskScore: 25, slaDeadline: subDays(new Date(), -2).toISOString(), items: [], createdAt: subDays(new Date(), 1).toISOString(), updatedAt: subDays(new Date(), 1).toISOString() },
  { id: '3', tenantId: 't1', requesterId: 'u5', requesterName: 'Emma Davis', targetUserId: 'u6', targetUserName: 'Frank Miller', requestType: 'revoke', status: 'pending', priority: 'normal', justification: 'Employee offboarding', riskScore: 15, items: [], createdAt: subDays(new Date(), 0).toISOString(), updatedAt: subDays(new Date(), 0).toISOString() },
  { id: '4', tenantId: 't1', requesterId: 'u7', requesterName: 'Grace Wilson', targetUserId: 'u8', targetUserName: 'Henry Brown', requestType: 'grant', status: 'pending', priority: 'emergency', justification: 'Emergency database access for incident response', riskScore: 88, slaDeadline: subDays(new Date(), -0.1).toISOString(), items: [], createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() },
  { id: '5', tenantId: 't1', requesterId: 'u9', requesterName: 'Ivy Taylor', targetUserId: 'u10', targetUserName: 'Jack Martinez', requestType: 'grant', status: 'pending', priority: 'normal', justification: 'New role assignment for promotion', riskScore: 38, items: [], createdAt: subDays(new Date(), 3).toISOString(), updatedAt: subDays(new Date(), 3).toISOString() },
]

const mockConnectors: Connector[] = [
  { id: '1', tenantId: 't1', name: 'Active Directory', connectorType: 'LDAP', status: 'active', healthStatus: 'healthy', lastHealthCheck: new Date().toISOString() },
  { id: '2', tenantId: 't1', name: 'Salesforce', connectorType: 'SAML', status: 'active', healthStatus: 'healthy', lastHealthCheck: new Date().toISOString() },
  { id: '3', tenantId: 't1', name: 'AWS IAM', connectorType: 'SCIM', status: 'active', healthStatus: 'unhealthy', lastHealthCheck: subDays(new Date(), 0.1).toISOString() },
  { id: '4', tenantId: 't1', name: 'Okta', connectorType: 'OIDC', status: 'active', healthStatus: 'healthy', lastHealthCheck: new Date().toISOString() },
  { id: '5', tenantId: 't1', name: 'GitHub', connectorType: 'OAuth', status: 'inactive', healthStatus: 'unknown', lastHealthCheck: subDays(new Date(), 1).toISOString() },
]

const mockAuditLogs: AuditLog[] = [
  { id: '1', tenantId: 't1', userName: 'admin@company.com', action: 'user.login', resourceType: 'auth', result: 'success', riskLevel: 'low', createdAt: subDays(new Date(), 0.01).toISOString() },
  { id: '2', tenantId: 't1', userName: 'alice@company.com', action: 'access.request.created', resourceType: 'access_request', result: 'success', riskLevel: 'medium', createdAt: subDays(new Date(), 0.05).toISOString() },
  { id: '3', tenantId: 't1', userName: 'unknown', action: 'user.login.failed', resourceType: 'auth', ipAddress: '192.168.1.55', result: 'failure', riskLevel: 'high', createdAt: subDays(new Date(), 0.1).toISOString() },
  { id: '4', tenantId: 't1', userName: 'bob@company.com', action: 'role.assigned', resourceType: 'role', result: 'success', riskLevel: 'medium', createdAt: subDays(new Date(), 0.2).toISOString() },
  { id: '5', tenantId: 't1', userName: 'carol@company.com', action: 'sod.violation.detected', resourceType: 'sod_policy', result: 'error', riskLevel: 'critical', createdAt: subDays(new Date(), 0.3).toISOString() },
]

const mockCertifications: CertificationCampaign[] = [
  { id: '1', tenantId: 't1', name: 'Q4 2025 Manager Review', campaignType: 'manager', status: 'active', startDate: subDays(new Date(), 10).toISOString(), endDate: subDays(new Date(), -20).toISOString(), deadline: subDays(new Date(), -5).toISOString(), autoRevokeOnExpire: true, totalItems: 240, certifiedItems: 168, revokedItems: 12, pendingItems: 60, createdAt: subDays(new Date(), 10).toISOString() },
  { id: '2', tenantId: 't1', name: 'Privileged Access Review', campaignType: 'app_owner', status: 'active', startDate: subDays(new Date(), 5).toISOString(), endDate: subDays(new Date(), -25).toISOString(), deadline: subDays(new Date(), -10).toISOString(), autoRevokeOnExpire: false, totalItems: 84, certifiedItems: 30, revokedItems: 5, pendingItems: 49, createdAt: subDays(new Date(), 5).toISOString() },
  { id: '3', tenantId: 't1', name: 'SOX Compliance Review', campaignType: 'entitlement', status: 'active', startDate: subDays(new Date(), 2).toISOString(), endDate: subDays(new Date(), -28).toISOString(), deadline: subDays(new Date(), -14).toISOString(), autoRevokeOnExpire: true, totalItems: 156, certifiedItems: 20, revokedItems: 2, pendingItems: 134, createdAt: subDays(new Date(), 2).toISOString() },
]

const riskAlerts = [
  { id: '1', severity: 'critical', message: 'SoD violation: John Doe has both AP Clerk and AP Manager roles', time: '10 min ago' },
  { id: '2', severity: 'high', message: '5 consecutive failed logins for user external@vendor.com', time: '35 min ago' },
  { id: '3', severity: 'high', message: '3 orphaned accounts detected in Active Directory', time: '2 hours ago' },
  { id: '4', severity: 'medium', message: 'Over-provisioning detected: 12 users have unused privileged roles', time: '4 hours ago' },
]

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      try {
        const res = await api.get<DashboardStats>('/api/v1/dashboard/stats')
        return res.data
      } catch {
        return mockStats
      }
    },
  })

  const displayStats = stats || mockStats

  const handleApprove = (id: string) => toast.success(`Request ${id} approved`)
  const handleReject = (id: string) => toast.error(`Request ${id} rejected`)

  const isOverdue = (deadline?: string) => {
    if (!deadline) return false
    return new Date(deadline) < new Date()
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description={`${format(new Date(), 'EEEE, MMMM d, yyyy')} — Enterprise Identity Governance`}
      />

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatsCard
          label="Total Users"
          value={displayStats.totalUsers}
          icon={Users}
          iconColor="text-blue-600"
          iconBg="bg-blue-100 dark:bg-blue-900/30"
          trend={3.2}
          trendLabel="this month"
          loading={statsLoading}
        />
        <StatsCard
          label="Pending Approvals"
          value={displayStats.pendingApprovals}
          icon={CheckSquare}
          iconColor="text-yellow-600"
          iconBg="bg-yellow-100 dark:bg-yellow-900/30"
          trend={-8.5}
          trendLabel="vs last week"
          loading={statsLoading}
        />
        <StatsCard
          label="Open SoD Violations"
          value={displayStats.openSODViolations}
          icon={AlertTriangle}
          iconColor="text-red-600"
          iconBg="bg-red-100 dark:bg-red-900/30"
          trend={14.3}
          trendLabel="this week"
          loading={statsLoading}
        />
        <StatsCard
          label="High Risk Users"
          value={displayStats.highRiskUsers}
          icon={Shield}
          iconColor="text-orange-600"
          iconBg="bg-orange-100 dark:bg-orange-900/30"
          trend={-5.1}
          trendLabel="vs last month"
          loading={statsLoading}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Access Request Trend */}
        <div className="xl:col-span-2 card p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-white">Access Request Trend</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Last 30 days</p>
            </div>
            <div className="flex items-center gap-4 text-xs text-slate-500">
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-500 inline-block" />Requests</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" />Approved</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-400 inline-block" />Rejected</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="reqGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="appGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={4} />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: '#1e293b', border: 'none', borderRadius: '8px', color: '#f1f5f9', fontSize: '12px' }} />
              <Area type="monotone" dataKey="requests" stroke="#3b82f6" strokeWidth={2} fill="url(#reqGradient)" name="Requests" />
              <Area type="monotone" dataKey="approved" stroke="#22c55e" strokeWidth={2} fill="url(#appGradient)" name="Approved" />
              <Area type="monotone" dataKey="rejected" stroke="#ef4444" strokeWidth={2} fill="none" name="Rejected" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Risk Alerts */}
        <div className="card p-6">
          <h3 className="font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
            <Activity size={16} className="text-red-500" />
            Risk Alerts
          </h3>
          <div className="space-y-3">
            {riskAlerts.map((alert) => (
              <div key={alert.id} className="flex gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
                <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                  alert.severity === 'critical' ? 'bg-red-500' : alert.severity === 'high' ? 'bg-orange-500' : 'bg-yellow-500'
                }`} />
                <div className="min-w-0">
                  <p className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">{alert.message}</p>
                  <p className="text-xs text-slate-400 mt-1">{alert.time}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Middle Row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Pending Approvals */}
        <div className="xl:col-span-2 card overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
            <h3 className="font-semibold text-slate-900 dark:text-white">Pending Approvals</h3>
            <a href="/approvals" className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400">View all →</a>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-header">Requester</th>
                  <th className="table-header">Target</th>
                  <th className="table-header">Priority</th>
                  <th className="table-header">SLA</th>
                  <th className="table-header">Risk</th>
                  <th className="table-header">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                {mockApprovals.map((req) => (
                  <tr key={req.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/30">
                    <td className="table-cell font-medium text-slate-800 dark:text-slate-200">{req.requesterName}</td>
                    <td className="table-cell text-slate-600 dark:text-slate-400">{req.targetUserName}</td>
                    <td className="table-cell">
                      <Badge variant={req.priority === 'emergency' ? 'critical' : req.priority === 'high' ? 'high' : 'low'}>
                        {req.priority}
                      </Badge>
                    </td>
                    <td className="table-cell">
                      {req.slaDeadline ? (
                        <span className={`text-xs font-medium ${isOverdue(req.slaDeadline) ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                          {isOverdue(req.slaDeadline) ? '⚠ Overdue' : formatDate(req.slaDeadline, 'MMM d')}
                        </span>
                      ) : '-'}
                    </td>
                    <td className="table-cell">
                      {req.riskScore !== undefined && (
                        <span className={`text-xs font-semibold ${req.riskScore >= 70 ? 'text-red-600' : req.riskScore >= 40 ? 'text-yellow-600' : 'text-green-600'}`}>
                          {req.riskScore}
                        </span>
                      )}
                    </td>
                    <td className="table-cell">
                      <div className="flex items-center gap-1">
                        <button onClick={() => handleApprove(req.id)} className="p-1.5 rounded text-green-600 hover:bg-green-100 dark:hover:bg-green-900/20" title="Approve">
                          <Check size={14} />
                        </button>
                        <button onClick={() => handleReject(req.id)} className="p-1.5 rounded text-red-600 hover:bg-red-100 dark:hover:bg-red-900/20" title="Reject">
                          <X size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Connector Health */}
        <div className="card p-6">
          <h3 className="font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
            <Plug size={16} className="text-blue-500" />
            Connector Health
            <span className="ml-auto text-xs text-slate-500">{displayStats.connectorsHealthy}/{displayStats.connectorsTotal} healthy</span>
          </h3>
          <div className="space-y-2">
            {mockConnectors.map((connector) => (
              <div key={connector.id} className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-700/50">
                <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  connector.healthStatus === 'healthy' ? 'bg-green-500' :
                  connector.healthStatus === 'unhealthy' ? 'bg-red-500' : 'bg-slate-400'
                }`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">{connector.name}</p>
                  <p className="text-xs text-slate-500">{connector.connectorType}</p>
                </div>
                <Badge variant={(connector.healthStatus || 'unknown') as 'healthy' | 'unhealthy' | 'unknown'}>
                  {connector.healthStatus || 'unknown'}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Active Certifications */}
        <div className="card p-6">
          <h3 className="font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
            <TrendingUp size={16} className="text-blue-500" />
            Active Certifications
          </h3>
          <div className="space-y-4">
            {mockCertifications.map((cert) => {
              const pct = cert.totalItems ? Math.round(((cert.certifiedItems || 0) + (cert.revokedItems || 0)) / cert.totalItems * 100) : 0
              return (
                <div key={cert.id}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{cert.name}</span>
                    <span className="text-xs text-slate-500">{pct}%</span>
                  </div>
                  <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5">
                    <div
                      className="bg-blue-600 h-1.5 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-xs text-slate-500">{cert.pendingItems} pending</span>
                    <span className="text-xs text-slate-500 flex items-center gap-1">
                      <Clock size={10} />
                      Due {formatDate(cert.deadline, 'MMM d')}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Recent Audit Events */}
        <div className="card p-6">
          <h3 className="font-semibold text-slate-900 dark:text-white mb-4">Recent Audit Events</h3>
          <div className="space-y-3">
            {mockAuditLogs.map((log) => (
              <div key={log.id} className="flex items-start gap-3">
                <span className={`inline-flex mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${getRiskBgColor(log.riskLevel)}`}>
                  {log.riskLevel}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-slate-800 dark:text-slate-200">
                    <span className="font-medium">{log.userName}</span>{' '}
                    <span className="text-slate-500 dark:text-slate-400">{log.action.replace(/\./g, ' ')}</span>
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {formatRelativeTime(log.createdAt)}
                    {log.ipAddress && <span> · {log.ipAddress}</span>}
                  </p>
                </div>
                <span className={`text-xs font-medium flex-shrink-0 ${log.result === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                  {log.result}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
