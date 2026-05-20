import React, { Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { RootState } from './store'
import AppLayout from './components/layout/AppLayout'

// Lazy load pages
const Login = React.lazy(() => import('./pages/Login'))
const Dashboard = React.lazy(() => import('./pages/Dashboard'))
const UserManagement = React.lazy(() => import('./pages/UserManagement'))
const AccessRequestPortal = React.lazy(() => import('./pages/AccessRequestPortal'))
const ApprovalCenter = React.lazy(() => import('./pages/ApprovalCenter'))
const Certifications = React.lazy(() => import('./pages/Certifications'))
const SODConflicts = React.lazy(() => import('./pages/SODConflicts'))
const AuditInvestigation = React.lazy(() => import('./pages/AuditInvestigation'))
const ConnectorManagement = React.lazy(() => import('./pages/ConnectorManagement'))
const ComplianceCenter = React.lazy(() => import('./pages/ComplianceCenter'))
const Settings = React.lazy(() => import('./pages/Settings'))
const PrivilegedAccess = React.lazy(() => import('./pages/PrivilegedAccess'))
const Analytics = React.lazy(() => import('./pages/Analytics'))
const WorkflowBuilder = React.lazy(() => import('./pages/WorkflowBuilder'))
const TenantManagement = React.lazy(() => import('./pages/TenantManagement'))
const PolicyBuilder = React.lazy(() => import('./pages/PolicyBuilder'))
const RoleMining = React.lazy(() => import('./pages/RoleMining'))
const HRMSSync = React.lazy(() => import('./pages/HRMSSync'))
const NotFound = React.lazy(() => import('./pages/NotFound'))

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50 dark:bg-slate-900">
      <div className="flex flex-col items-center gap-4">
        <div className="w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-500 dark:text-slate-400 text-sm">Loading...</p>
      </div>
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated)
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function SuperAdminRoute({ children }: { children: React.ReactNode }) {
  const user = useSelector((state: RootState) => state.auth.user)
  if (!user?.isSuperadmin) {
    return <Navigate to="/dashboard" replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="requests" element={<AccessRequestPortal />} />
          <Route path="approvals" element={<ApprovalCenter />} />
          <Route path="certifications" element={<Certifications />} />
          <Route path="users" element={<UserManagement />} />
          <Route path="roles" element={<RoleMining />} />
          <Route path="applications" element={<ConnectorManagement />} />
          <Route path="sod" element={<SODConflicts />} />
          <Route path="role-mining" element={<RoleMining />} />
          <Route path="policy" element={<PolicyBuilder />} />
          <Route path="compliance" element={<ComplianceCenter />} />
          <Route path="workflows" element={<WorkflowBuilder />} />
          <Route path="connectors" element={<ConnectorManagement />} />
          <Route path="hrms" element={<HRMSSync />} />
          <Route path="pam" element={<PrivilegedAccess />} />
          <Route path="audit" element={<AuditInvestigation />} />
          <Route
            path="tenants"
            element={
              <SuperAdminRoute>
                <TenantManagement />
              </SuperAdminRoute>
            }
          />
          <Route path="settings" element={<Settings />} />
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
