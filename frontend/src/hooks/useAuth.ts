import { useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { RootState, AppDispatch } from '@/store'
import { loginThunk, logoutThunk } from '@/store/slices/authSlice'
import { LoginRequest } from '@/types'

export function useAuth() {
  const dispatch = useDispatch<AppDispatch>()
  const navigate = useNavigate()

  const user = useSelector((state: RootState) => state.auth.user)
  const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated)
  const isLoading = useSelector((state: RootState) => state.auth.isLoading)
  const error = useSelector((state: RootState) => state.auth.error)
  const tenantId = useSelector((state: RootState) => state.auth.tenantId)

  const login = useCallback(
    async (credentials: LoginRequest) => {
      const result = await dispatch(loginThunk(credentials))
      if (loginThunk.fulfilled.match(result)) {
        navigate('/dashboard')
        return { success: true }
      }
      return { success: false, error: result.payload as string }
    },
    [dispatch, navigate]
  )

  const logout = useCallback(async () => {
    await dispatch(logoutThunk())
    navigate('/login')
  }, [dispatch, navigate])

  const hasRole = useCallback(
    (roleName: string): boolean => {
      if (!user) return false
      if (user.isSuperadmin) return true
      // In a real app, you'd check user.roles array
      return false
    },
    [user]
  )

  const hasPermission = useCallback(
    (resource: string, action: string): boolean => {
      if (!user) return false
      if (user.isSuperadmin) return true
      if (user.isTenantAdmin) return true
      // In a real app, you'd check user.permissions array
      return false
    },
    [user]
  )

  const isSuperadmin = user?.isSuperadmin ?? false
  const isTenantAdmin = user?.isTenantAdmin ?? false

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
    tenantId,
    login,
    logout,
    hasRole,
    hasPermission,
    isSuperadmin,
    isTenantAdmin,
  }
}
