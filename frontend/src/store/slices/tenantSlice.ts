import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { Tenant } from '@/types'

interface TenantBranding {
  primaryColor: string
  logoUrl?: string
  faviconUrl?: string
  companyName: string
}

interface TenantState {
  currentTenant: Tenant | null
  branding: TenantBranding
  isLoading: boolean
  error: string | null
}

const defaultBranding: TenantBranding = {
  primaryColor: '#3b82f6',
  companyName: 'IGA Platform',
}

const initialState: TenantState = {
  currentTenant: null,
  branding: defaultBranding,
  isLoading: false,
  error: null,
}

const tenantSlice = createSlice({
  name: 'tenant',
  initialState,
  reducers: {
    setCurrentTenant: (state, action: PayloadAction<Tenant>) => {
      state.currentTenant = action.payload
      state.error = null
    },
    updateTenant: (state, action: PayloadAction<Partial<Tenant>>) => {
      if (state.currentTenant) {
        state.currentTenant = { ...state.currentTenant, ...action.payload }
      }
    },
    setBranding: (state, action: PayloadAction<Partial<TenantBranding>>) => {
      state.branding = { ...state.branding, ...action.payload }
    },
    clearTenant: (state) => {
      state.currentTenant = null
      state.branding = defaultBranding
    },
    setTenantLoading: (state, action: PayloadAction<boolean>) => {
      state.isLoading = action.payload
    },
    setTenantError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload
    },
  },
})

export const {
  setCurrentTenant,
  updateTenant,
  setBranding,
  clearTenant,
  setTenantLoading,
  setTenantError,
} = tenantSlice.actions

export default tenantSlice.reducer
