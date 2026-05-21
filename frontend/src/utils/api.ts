import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { LoginResponse } from '@/types'

// Read auth state directly from localStorage to avoid circular dependency
const getStore = () => ({
  getState: () => ({
    auth: {
      accessToken: localStorage.getItem('accessToken'),
      refreshToken: localStorage.getItem('refreshToken'),
      tenantId: localStorage.getItem('tenantId'),
    }
  }),
  dispatch: (action: any) => {
    if (action?.type === 'auth/logout' || action?.payload?.type === 'auth/logout') {
      localStorage.removeItem('accessToken')
      localStorage.removeItem('refreshToken')
      localStorage.removeItem('tenantId')
      window.location.href = '/login'
    }
  }
})
const getAuthActions = () => ({
  logout: () => ({ type: 'auth/logout' }),
  setCredentials: (data: any) => ({ type: 'auth/setCredentials', payload: data })
})

let isRefreshing = false
let failedQueue: Array<{
  resolve: (value: string) => void
  reject: (reason: unknown) => void
}> = []

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error)
    } else {
      resolve(token!)
    }
  })
  failedQueue = []
}

const api: AxiosInstance = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
})

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const state = getStore().getState()
    const token = state.auth.accessToken
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    const tenantId = state.auth.tenantId
    if (tenantId && config.headers) {
      config.headers['X-Tenant-ID'] = tenantId
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            return api(originalRequest)
          })
          .catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      const state = getStore().getState()
      const refreshToken = state.auth.refreshToken

      if (!refreshToken) {
        getStore().dispatch(getAuthActions().logout())
        window.location.href = '/login'
        return Promise.reject(error)
      }

      try {
        const response = await axios.post<LoginResponse>('/api/v1/auth/refresh', {
          refreshToken,
        })
        const { accessToken } = response.data
        getStore().dispatch(getAuthActions().setCredentials(response.data))
        processQueue(null, accessToken)
        originalRequest.headers.Authorization = `Bearer ${accessToken}`
        return api(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        getStore().dispatch(getAuthActions().logout())
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export default api
