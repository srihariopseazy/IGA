import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ColumnDef } from '@tanstack/react-table'
import { Plus, Upload, Lock, RefreshCw, Eye, X, Shield, Activity, Star } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { subDays } from 'date-fns'
import { PageHeader } from '@/components/ui/PageHeader'
import { DataTable } from '@/components/ui/DataTable'
import { Badge, BadgeVariant } from '@/components/ui/Badge'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { generateInitials, getAvatarColor, formatRelativeTime, formatDate, getRiskBgColor } from '@/utils/helpers'
import { User } from '@/types'
import api from '@/utils/api'

const createUserSchema = z.object({
  firstName: z.string().min(1, 'Required'),
  lastName: z.string().min(1, 'Required'),
  email: z.string().email('Valid email required'),
  username: z.string().min(3, 'Min 3 characters'),
  departmentId: z.string().optional(),
  role: z.string().optional(),
})
type CreateUserForm = z.infer<typeof createUserSchema>

const mockUsers: User[] = [
  { id: '1', email: 'alice.johnson@company.com', username: 'alice.j', firstName: 'Alice', lastName: 'Johnson', displayName: 'Alice Johnson', status: 'active', tenantId: 't1', departmentId: 'finance', isSuperadmin: false, isTenantAdmin: true, emailVerified: true, mfaEnabled: true, lastLoginAt: subDays(new Date(), 0.5).toISOString(), createdAt: subDays(new Date(), 180).toISOString(), updatedAt: subDays(new Date(), 1).toISOString() },
  { id: '2', email: 'bob.smith@company.com', username: 'bob.s', firstName: 'Bob', lastName: 'Smith', displayName: 'Bob Smith', status: 'active', tenantId: 't1', departmentId: 'engineering', isSuperadmin: false, isTenantAdmin: false, emailVerified: true, mfaEnabled: false, lastLoginAt: subDays(new Date(), 1).toISOString(), createdAt: subDays(new Date(), 365).toISOString(), updatedAt: subDays(new Date(), 2).toISOString() },
  { id: '3', email: 'carol.white@company.com', username: 'carol.w', firstName: 'Carol', lastName: 'White', displayName: 'Carol White', status: 'locked', tenantId: 't1', departmentId: 'hr', isSuperadmin: false, isTenantAdmin: false, emailVerified: true, mfaEnabled: true, lastLoginAt: subDays(new Date(), 7).toISOString(), createdAt: subDays(new Date(), 200).toISOString(), updatedAt: subDays(new Date(), 0.1).toISOString() },
  { id: '4', email: 'david.lee@company.com', username: 'david.l', firstName: 'David', lastName: 'Lee', displayName: 'David Lee', status: 'inactive', tenantId: 't1', isSuperadmin: false, isTenantAdmin: false, emailVerified: false, mfaEnabled: false, createdAt: subDays(new Date(), 90).toISOString(), updatedAt: subDays(new Date(), 30).toISOString() },
  { id: '5', email: 'emma.davis@company.com', username: 'emma.d', firstName: 'Emma', lastName: 'Davis', displayName: 'Emma Davis', status: 'active', tenantId: 't1', departmentId: 'finance', isSuperadmin: false, isTenantAdmin: false, emailVerified: true, mfaEnabled: true, lastLoginAt: subDays(new Date(), 0.1).toISOString(), createdAt: subDays(new Date(), 120).toISOString(), updatedAt: subDays(new Date(), 0.5).toISOString() },
  { id: '6', email: 'frank.miller@company.com', username: 'frank.m', firstName: 'Frank', lastName: 'Miller', displayName: 'Frank Miller', status: 'suspended', tenantId: 't1', isSuperadmin: false, isTenantAdmin: false, emailVerified: true, mfaEnabled: false, lastLoginAt: subDays(new Date(), 14).toISOString(), createdAt: subDays(new Date(), 300).toISOString(), updatedAt: subDays(new Date(), 5).toISOString() },
  { id: '7', email: 'grace.wilson@company.com', username: 'grace.w', firstName: 'Grace', lastName: 'Wilson', displayName: 'Grace Wilson', status: 'pending', tenantId: 't1', isSuperadmin: false, isTenantAdmin: false, emailVerified: false, mfaEnabled: false, createdAt: subDays(new Date(), 1).toISOString(), updatedAt: subDays(new Date(), 1).toISOString() },
]

const riskLevels = ['low', 'medium', 'high', 'critical'] as const
const getUserRisk = (userId: string): typeof riskLevels[number] => {
  const idx = parseInt(userId) % 4
  return riskLevels[idx]
}

export default function UserManagement() {
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showImportModal, setShowImportModal] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [confirmLock, setConfirmLock] = useState<User | null>(null)
  const [selectedRows, setSelectedRows] = useState<User[]>([])

  const { data: users = mockUsers, isLoading } = useQuery({
    queryKey: ['users', searchQuery, statusFilter],
    queryFn: async () => {
      try {
        const res = await api.get<{ items: User[] }>('/api/v1/users', {
          params: { search: searchQuery, status: statusFilter || undefined, page: 1, per_page: 100 }
        })
        return res.data.items
      } catch { return mockUsers }
    },
  })

  const lockMutation = useMutation({
    mutationFn: (userId: string) => api.post(`/api/v1/users/${userId}/lock`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success('User locked successfully')
      setConfirmLock(null)
    },
    onError: () => toast.error('Failed to lock user'),
  })

  const createMutation = useMutation({
    mutationFn: (data: CreateUserForm) => api.post('/api/v1/users', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success('User created successfully')
      setShowCreateModal(false)
      createForm.reset()
    },
    onError: () => toast.error('Failed to create user'),
  })

  const createForm = useForm<CreateUserForm>({ resolver: zodResolver(createUserSchema) })

  const onCreateSubmit = (data: CreateUserForm) => createMutation.mutate(data)

  const columns: ColumnDef<User, unknown>[] = [
    {
      id: 'user',
      header: 'User',
      accessorFn: (row) => row.displayName,
      cell: ({ row }) => {
        const u = row.original
        const initials = generateInitials(u.displayName)
        const color = getAvatarColor(u.displayName)
        return (
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-full ${color} flex items-center justify-center text-white text-xs font-semibold flex-shrink-0`}>
              {initials}
            </div>
            <div>
              <p className="font-medium text-slate-800 dark:text-slate-200">{u.displayName}</p>
              <p className="text-xs text-slate-500">{u.email}</p>
            </div>
          </div>
        )
      },
    },
    {
      accessorKey: 'username',
      header: 'Username',
      cell: ({ getValue }) => <code className="text-xs bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 rounded">{getValue() as string}</code>,
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => <Badge variant={getValue() as BadgeVariant}>{getValue() as string}</Badge>,
    },
    {
      id: 'riskLevel',
      header: 'Risk',
      cell: ({ row }) => {
        const risk = getUserRisk(row.original.id)
        return <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${getRiskBgColor(risk)}`}>{risk}</span>
      },
    },
    {
      accessorKey: 'mfaEnabled',
      header: 'MFA',
      cell: ({ getValue }) => (
        <span className={`text-xs font-medium ${getValue() ? 'text-green-600' : 'text-red-600'}`}>
          {getValue() ? 'Enabled' : 'Disabled'}
        </span>
      ),
    },
    {
      accessorKey: 'lastLoginAt',
      header: 'Last Login',
      cell: ({ getValue }) => <span className="text-slate-500 dark:text-slate-400">{formatRelativeTime(getValue() as string)}</span>,
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <button
            onClick={() => setSelectedUser(row.original)}
            className="p-1.5 rounded text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/20"
            title="View"
          >
            <Eye size={14} />
          </button>
          <button
            onClick={() => setConfirmLock(row.original)}
            className="p-1.5 rounded text-orange-600 hover:bg-orange-100 dark:hover:bg-orange-900/20"
            title="Lock"
          >
            <Lock size={14} />
          </button>
          <button
            onClick={() => toast.success('Password reset email sent')}
            className="p-1.5 rounded text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700"
            title="Reset Password"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      ),
      enableSorting: false,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="User Management"
        description="Manage identities, roles, and access across your organization"
        actions={
          <>
            <button
              onClick={() => setShowImportModal(true)}
              className="btn-secondary flex items-center gap-2 text-sm"
            >
              <Upload size={15} /> Import CSV
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="btn-primary flex items-center gap-2 text-sm"
            >
              <Plus size={15} /> Create User
            </button>
          </>
        }
      />

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input w-auto text-sm py-1.5"
        >
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="locked">Locked</option>
          <option value="suspended">Suspended</option>
          <option value="pending">Pending</option>
        </select>
        {selectedRows.length > 0 && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm text-slate-500">{selectedRows.length} selected</span>
            <button className="btn-secondary text-sm py-1.5" onClick={() => toast.success('Bulk lock initiated')}>
              <Lock size={13} className="inline mr-1" /> Lock Selected
            </button>
          </div>
        )}
      </div>

      <DataTable
        data={users}
        columns={columns}
        loading={isLoading}
        onSearch={setSearchQuery}
        searchPlaceholder="Search users..."
        onRowSelectionChange={setSelectedRows}
        exportFilename="users"
        totalRows={users.length}
      />

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Create New User</h2>
              <button onClick={() => setShowCreateModal(false)} className="text-slate-400 hover:text-slate-600"><X size={20} /></button>
            </div>
            <form onSubmit={createForm.handleSubmit(onCreateSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">First Name</label>
                  <input {...createForm.register('firstName')} className="input" placeholder="John" />
                  {createForm.formState.errors.firstName && <p className="text-red-500 text-xs mt-1">{createForm.formState.errors.firstName.message}</p>}
                </div>
                <div>
                  <label className="label">Last Name</label>
                  <input {...createForm.register('lastName')} className="input" placeholder="Doe" />
                  {createForm.formState.errors.lastName && <p className="text-red-500 text-xs mt-1">{createForm.formState.errors.lastName.message}</p>}
                </div>
              </div>
              <div>
                <label className="label">Email Address</label>
                <input {...createForm.register('email')} type="email" className="input" placeholder="john.doe@company.com" />
                {createForm.formState.errors.email && <p className="text-red-500 text-xs mt-1">{createForm.formState.errors.email.message}</p>}
              </div>
              <div>
                <label className="label">Username</label>
                <input {...createForm.register('username')} className="input" placeholder="john.doe" />
                {createForm.formState.errors.username && <p className="text-red-500 text-xs mt-1">{createForm.formState.errors.username.message}</p>}
              </div>
              <div>
                <label className="label">Department</label>
                <select {...createForm.register('departmentId')} className="input">
                  <option value="">Select department...</option>
                  <option value="engineering">Engineering</option>
                  <option value="finance">Finance</option>
                  <option value="hr">Human Resources</option>
                  <option value="sales">Sales</option>
                  <option value="operations">Operations</option>
                </select>
              </div>
              <div>
                <label className="label">Initial Role</label>
                <select {...createForm.register('role')} className="input">
                  <option value="">None</option>
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="manager">Manager</option>
                </select>
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setShowCreateModal(false)} className="btn-secondary text-sm">Cancel</button>
                <button type="submit" disabled={createMutation.isPending} className="btn-primary text-sm flex items-center gap-2">
                  {createMutation.isPending && <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
                  Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Import CSV Modal */}
      {showImportModal && (
        <div className="modal-overlay" onClick={() => setShowImportModal(false)}>
          <div className="modal-content max-w-md p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Import Users via CSV</h2>
              <button onClick={() => setShowImportModal(false)} className="text-slate-400 hover:text-slate-600"><X size={20} /></button>
            </div>
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-xl p-8 text-center mb-4">
              <Upload size={32} className="mx-auto text-slate-400 mb-3" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Drop your CSV file here</p>
              <p className="text-xs text-slate-500 mb-3">or click to browse</p>
              <input type="file" accept=".csv" className="hidden" id="csv-upload" onChange={() => toast.success('File selected')} />
              <label htmlFor="csv-upload" className="btn-secondary text-sm cursor-pointer">Browse Files</label>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              Required columns: email, firstName, lastName, username. Optional: departmentId, phone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setShowImportModal(false)} className="btn-secondary text-sm">Cancel</button>
              <button onClick={() => { toast.success('Import started'); setShowImportModal(false) }} className="btn-primary text-sm">Start Import</button>
            </div>
          </div>
        </div>
      )}

      {/* User Detail Drawer */}
      {selectedUser && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-black/40" onClick={() => setSelectedUser(null)} />
          <div className="w-full max-w-md bg-white dark:bg-slate-800 h-full overflow-y-auto shadow-2xl animate-slide-in">
            <div className="flex items-center justify-between p-6 border-b border-slate-200 dark:border-slate-700">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">User Details</h2>
              <button onClick={() => setSelectedUser(null)} className="text-slate-400 hover:text-slate-600"><X size={20} /></button>
            </div>
            <div className="p-6 space-y-6">
              {/* Profile */}
              <div className="flex items-center gap-4">
                <div className={`w-14 h-14 rounded-full ${getAvatarColor(selectedUser.displayName)} flex items-center justify-center text-white text-xl font-bold`}>
                  {generateInitials(selectedUser.displayName)}
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{selectedUser.displayName}</h3>
                  <p className="text-sm text-slate-500">{selectedUser.email}</p>
                  <Badge variant={selectedUser.status as BadgeVariant} className="mt-1">{selectedUser.status}</Badge>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-slate-500 text-xs mb-1">Username</p>
                  <p className="font-medium text-slate-800 dark:text-slate-200">{selectedUser.username}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs mb-1">Department</p>
                  <p className="font-medium text-slate-800 dark:text-slate-200">{selectedUser.departmentId || 'N/A'}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs mb-1">MFA</p>
                  <p className={`font-medium ${selectedUser.mfaEnabled ? 'text-green-600' : 'text-red-600'}`}>
                    {selectedUser.mfaEnabled ? 'Enabled' : 'Disabled'}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs mb-1">Last Login</p>
                  <p className="font-medium text-slate-800 dark:text-slate-200">{formatRelativeTime(selectedUser.lastLoginAt)}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs mb-1">Created</p>
                  <p className="font-medium text-slate-800 dark:text-slate-200">{formatDate(selectedUser.createdAt)}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs mb-1">Email Verified</p>
                  <p className={`font-medium ${selectedUser.emailVerified ? 'text-green-600' : 'text-yellow-600'}`}>
                    {selectedUser.emailVerified ? 'Verified' : 'Pending'}
                  </p>
                </div>
              </div>

              {/* Roles */}
              <div>
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white mb-2 flex items-center gap-2">
                  <Shield size={14} /> Assigned Roles
                </h4>
                <div className="flex flex-wrap gap-2">
                  {['Finance Viewer', 'Report Generator', 'Dashboard User'].map((role) => (
                    <span key={role} className="px-2 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 rounded text-xs font-medium">{role}</span>
                  ))}
                </div>
              </div>

              {/* Risk Score */}
              <div>
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white mb-2 flex items-center gap-2">
                  <Star size={14} /> Risk Profile
                </h4>
                <div className="space-y-2">
                  {[
                    { label: 'Overall Risk', value: 42, max: 100 },
                    { label: 'SoD Score', value: 10, max: 100 },
                    { label: 'Anomaly Score', value: 25, max: 100 },
                  ].map(({ label, value, max }) => (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-600 dark:text-slate-400">{label}</span>
                        <span className="font-medium text-slate-800 dark:text-slate-200">{value}/{max}</span>
                      </div>
                      <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${value >= 70 ? 'bg-red-500' : value >= 40 ? 'bg-yellow-500' : 'bg-green-500'}`}
                          style={{ width: `${(value / max) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Recent Activity */}
              <div>
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white mb-2 flex items-center gap-2">
                  <Activity size={14} /> Recent Activity
                </h4>
                <div className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
                  <div className="flex justify-between"><span>Login from 192.168.1.1</span><span>{formatRelativeTime(subDays(new Date(), 0.5).toISOString())}</span></div>
                  <div className="flex justify-between"><span>Role assigned: Finance Viewer</span><span>{formatRelativeTime(subDays(new Date(), 3).toISOString())}</span></div>
                  <div className="flex justify-between"><span>Password changed</span><span>{formatRelativeTime(subDays(new Date(), 14).toISOString())}</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Lock Confirm */}
      <ConfirmDialog
        open={!!confirmLock}
        title="Lock User Account"
        message={`Are you sure you want to lock ${confirmLock?.displayName}'s account? They will not be able to log in until unlocked.`}
        confirmLabel="Lock Account"
        variant="danger"
        loading={lockMutation.isPending}
        onConfirm={() => confirmLock && lockMutation.mutate(confirmLock.id)}
        onCancel={() => setConfirmLock(null)}
      />
    </div>
  )
}
