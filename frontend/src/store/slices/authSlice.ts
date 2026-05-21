import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit'
import { AuthState, User, LoginRequest, LoginResponse } from '@/types'
import api from '@/utils/api'

const initialState: AuthState = {
  user: null,
  accessToken: localStorage.getItem('accessToken'),
  refreshToken: localStorage.getItem('refreshToken'),
  isAuthenticated: !!localStorage.getItem('accessToken'),
  isLoading: false,
  error: null,
  tenantId: localStorage.getItem('tenantId'),
}

export const loginThunk = createAsyncThunk<LoginResponse, LoginRequest>(
  'auth/login',
  async (credentials, { rejectWithValue }) => {
    try {
      const response = await api.post<LoginResponse>('/api/v1/auth/login', credentials)
      return response.data
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      return rejectWithValue(error.response?.data?.detail || 'Login failed')
    }
  }
)

export const logoutThunk = createAsyncThunk('auth/logout', async (_, { getState }) => {
  try {
    const state = getState() as { auth: AuthState }
    if (state.auth.refreshToken) {
      await api.post('/api/v1/auth/logout', { refreshToken: state.auth.refreshToken })
    }
  } catch {
    // ignore errors on logout
  }
})

export const refreshTokenThunk = createAsyncThunk('auth/refreshToken', async (_, { getState, rejectWithValue }) => {
  try {
    const state = getState() as { auth: AuthState }
    const response = await api.post<{ access_token: string; expiresIn: number }>('/api/v1/auth/refresh', {
      refresh_token: state.auth.refreshToken,
    })
    return response.data
  } catch (err: unknown) {
    const error = err as { response?: { data?: { detail?: string } } }
    return rejectWithValue(error.response?.data?.detail || 'Token refresh failed')
  }
})

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials: (state, action: PayloadAction<LoginResponse>) => {
      state.user = action.payload.user
      state.accessToken = action.payload.accessToken
      state.refreshToken = action.payload.refreshToken
      state.isAuthenticated = true
      state.tenantId = action.payload.user.tenantId
      state.error = null
      localStorage.setItem('accessToken', action.payload.accessToken)
      localStorage.setItem('refreshToken', action.payload.refreshToken)
      localStorage.setItem('tenantId', action.payload.user.tenantId)
    },
    logout: (state) => {
      state.user = null
      state.accessToken = null
      state.refreshToken = null
      state.isAuthenticated = false
      state.tenantId = null
      state.error = null
      localStorage.removeItem('accessToken')
      localStorage.removeItem('refreshToken')
      localStorage.removeItem('tenantId')
    },
    updateUser: (state, action: PayloadAction<Partial<User>>) => {
      if (state.user) {
        state.user = { ...state.user, ...action.payload }
      }
    },
    setLoading: (state, action: PayloadAction<boolean>) => {
      state.isLoading = action.payload
    },
    setError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload
    },
    clearError: (state) => {
      state.error = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loginThunk.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(loginThunk.fulfilled, (state, action) => {
        const p = action.payload as any
        const accessToken = p.access_token || p.accessToken
        const refreshToken = p.refresh_token || p.refreshToken
        const tenantId = p.user?.tenant_id || p.user?.tenantId
        state.isLoading = false
        state.user = p.user
        state.accessToken = accessToken
        state.refreshToken = refreshToken
        state.isAuthenticated = true
        state.tenantId = tenantId
        state.error = null
        localStorage.setItem('accessToken', accessToken)
        localStorage.setItem('refreshToken', refreshToken)
        localStorage.setItem('tenantId', tenantId)
      })
      .addCase(loginThunk.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.payload as string
      })
      .addCase(logoutThunk.fulfilled, (state) => {
        state.user = null
        state.accessToken = null
        state.refreshToken = null
        state.isAuthenticated = false
        state.tenantId = null
        localStorage.removeItem('accessToken')
        localStorage.removeItem('refreshToken')
        localStorage.removeItem('tenantId')
      })
      .addCase(refreshTokenThunk.fulfilled, (state, action) => {
        state.accessToken = action.payload.accessToken
        localStorage.setItem('accessToken', action.payload.accessToken)
      })
      .addCase(refreshTokenThunk.rejected, (state) => {
        state.user = null
        state.accessToken = null
        state.refreshToken = null
        state.isAuthenticated = false
        state.tenantId = null
        localStorage.removeItem('accessToken')
        localStorage.removeItem('refreshToken')
        localStorage.removeItem('tenantId')
      })
  },
})

export const { setCredentials, logout, updateUser, setLoading, setError, clearError } = authSlice.actions
export default authSlice.reducer
