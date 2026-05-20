import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Shield, Eye, EyeOff, Loader2, Mail, Lock, Building2, AlertCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import toast from 'react-hot-toast'
import { loginThunk } from '@/store/slices/authSlice'
import { AppDispatch } from '@/store'

const loginSchema = z.object({
  tenantSlug: z.string().min(1, 'Tenant slug is required'),
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

const mfaSchema = z.object({
  mfaCode: z.string().length(6, 'MFA code must be 6 digits').regex(/^\d+$/, 'Digits only'),
})

const forgotSchema = z.object({
  forgotEmail: z.string().email('Enter a valid email address'),
})

type LoginForm = z.infer<typeof loginSchema>
type MFAForm = z.infer<typeof mfaSchema>
type ForgotForm = z.infer<typeof forgotSchema>

export default function Login() {
  const dispatch = useDispatch<AppDispatch>()
  const navigate = useNavigate()

  const [showPassword, setShowPassword] = useState(false)
  const [step, setStep] = useState<'login' | 'mfa' | 'forgot' | 'magic'>('login')
  const [isLoading, setIsLoading] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [savedCredentials, setSavedCredentials] = useState<LoginForm | null>(null)
  const [forgotSent, setForgotSent] = useState(false)
  const [magicSent, setMagicSent] = useState(false)

  // Auto-detect tenant from subdomain
  const defaultTenantSlug = window.location.hostname.split('.')[0] !== 'localhost'
    ? window.location.hostname.split('.')[0]
    : 'demo'

  const loginForm = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { tenantSlug: defaultTenantSlug, email: '', password: '' },
  })

  const mfaForm = useForm<MFAForm>({
    resolver: zodResolver(mfaSchema),
    defaultValues: { mfaCode: '' },
  })

  const forgotForm = useForm<ForgotForm>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { forgotEmail: '' },
  })

  const onLoginSubmit = async (values: LoginForm) => {
    setIsLoading(true)
    setAuthError(null)
    try {
      const result = await dispatch(loginThunk(values))
      if (loginThunk.fulfilled.match(result)) {
        toast.success('Login successful!')
        navigate('/dashboard')
      } else if (loginThunk.rejected.match(result)) {
        const msg = result.payload as string
        if (msg?.includes('MFA') || msg?.includes('mfa')) {
          setSavedCredentials(values)
          setStep('mfa')
        } else {
          setAuthError(msg || 'Invalid credentials')
        }
      }
    } finally {
      setIsLoading(false)
    }
  }

  const onMFASubmit = async (values: MFAForm) => {
    if (!savedCredentials) return
    setIsLoading(true)
    setAuthError(null)
    try {
      const result = await dispatch(loginThunk({ ...savedCredentials, mfaCode: values.mfaCode }))
      if (loginThunk.fulfilled.match(result)) {
        toast.success('Login successful!')
        navigate('/dashboard')
      } else {
        setAuthError('Invalid MFA code')
      }
    } finally {
      setIsLoading(false)
    }
  }

  const onForgotSubmit = async (values: ForgotForm) => {
    setIsLoading(true)
    await new Promise((r) => setTimeout(r, 1000))
    setIsLoading(false)
    setForgotSent(true)
    toast.success('Password reset link sent!')
    console.log('Password reset for:', values.forgotEmail)
  }

  const handleMagicLink = async () => {
    const email = loginForm.getValues('email')
    if (!email) {
      loginForm.setError('email', { message: 'Enter email first' })
      return
    }
    setIsLoading(true)
    await new Promise((r) => setTimeout(r, 1000))
    setIsLoading(false)
    setMagicSent(true)
    toast.success('Magic link sent to your email!')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-600 shadow-xl mb-4">
            <Shield size={32} className="text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">IGA Platform</h1>
          <p className="text-slate-400 mt-1 text-sm">Enterprise Identity Governance & Administration</p>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl p-8">
          {/* Error Banner */}
          {authError && (
            <div className="flex items-center gap-2 p-3 mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
              <AlertCircle size={16} className="flex-shrink-0" />
              {authError}
            </div>
          )}

          {step === 'login' && (
            <>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-6">Sign in to your account</h2>
              <form onSubmit={loginForm.handleSubmit(onLoginSubmit)} className="space-y-4">
                <div>
                  <label className="label">Organization</label>
                  <div className="relative">
                    <Building2 size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      {...loginForm.register('tenantSlug')}
                      type="text"
                      placeholder="your-company"
                      className="input pl-9"
                    />
                  </div>
                  {loginForm.formState.errors.tenantSlug && (
                    <p className="text-red-500 text-xs mt-1">{loginForm.formState.errors.tenantSlug.message}</p>
                  )}
                </div>
                <div>
                  <label className="label">Email address</label>
                  <div className="relative">
                    <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      {...loginForm.register('email')}
                      type="email"
                      placeholder="you@company.com"
                      className="input pl-9"
                      autoComplete="email"
                    />
                  </div>
                  {loginForm.formState.errors.email && (
                    <p className="text-red-500 text-xs mt-1">{loginForm.formState.errors.email.message}</p>
                  )}
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="label mb-0">Password</label>
                    <button
                      type="button"
                      onClick={() => setStep('forgot')}
                      className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <div className="relative">
                    <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      {...loginForm.register('password')}
                      type={showPassword ? 'text' : 'password'}
                      placeholder="••••••••"
                      className="input pl-9 pr-10"
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  {loginForm.formState.errors.password && (
                    <p className="text-red-500 text-xs mt-1">{loginForm.formState.errors.password.message}</p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="btn-primary w-full flex items-center justify-center gap-2 py-2.5"
                >
                  {isLoading && <Loader2 size={16} className="animate-spin" />}
                  Sign in
                </button>
              </form>

              <div className="mt-4 relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-slate-200 dark:border-slate-600" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="px-2 bg-white dark:bg-slate-800 text-slate-500">or continue with</span>
                </div>
              </div>

              <div className="mt-4 space-y-2">
                <button
                  type="button"
                  onClick={handleMagicLink}
                  disabled={isLoading || magicSent}
                  className="btn-secondary w-full flex items-center justify-center gap-2 py-2.5 text-sm"
                >
                  <Mail size={16} />
                  {magicSent ? 'Magic link sent!' : 'Send Magic Link'}
                </button>
                <a
                  href="/api/v1/auth/oauth/google"
                  className="flex items-center justify-center gap-2 w-full py-2.5 px-4 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                  Continue with Google
                </a>
              </div>
            </>
          )}

          {step === 'mfa' && (
            <>
              <button
                onClick={() => setStep('login')}
                className="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 mb-4 flex items-center gap-1"
              >
                ← Back
              </button>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">Two-Factor Authentication</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
                Enter the 6-digit code from your authenticator app.
              </p>
              <form onSubmit={mfaForm.handleSubmit(onMFASubmit)} className="space-y-4">
                <div>
                  <label className="label">MFA Code</label>
                  <input
                    {...mfaForm.register('mfaCode')}
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    className="input text-center text-2xl tracking-widest font-mono"
                    autoFocus
                  />
                  {mfaForm.formState.errors.mfaCode && (
                    <p className="text-red-500 text-xs mt-1">{mfaForm.formState.errors.mfaCode.message}</p>
                  )}
                </div>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="btn-primary w-full flex items-center justify-center gap-2 py-2.5"
                >
                  {isLoading && <Loader2 size={16} className="animate-spin" />}
                  Verify
                </button>
              </form>
            </>
          )}

          {step === 'forgot' && (
            <>
              <button
                onClick={() => setStep('login')}
                className="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 mb-4 flex items-center gap-1"
              >
                ← Back to login
              </button>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">Reset your password</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
                Enter your email and we'll send a password reset link.
              </p>
              {forgotSent ? (
                <div className="text-center py-4">
                  <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-3">
                    <Mail size={24} className="text-green-600" />
                  </div>
                  <p className="font-medium text-slate-900 dark:text-white">Check your email</p>
                  <p className="text-sm text-slate-500 mt-1">Password reset link sent!</p>
                </div>
              ) : (
                <form onSubmit={forgotForm.handleSubmit(onForgotSubmit)} className="space-y-4">
                  <div>
                    <label className="label">Email address</label>
                    <div className="relative">
                      <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input
                        {...forgotForm.register('forgotEmail')}
                        type="email"
                        placeholder="you@company.com"
                        className="input pl-9"
                      />
                    </div>
                    {forgotForm.formState.errors.forgotEmail && (
                      <p className="text-red-500 text-xs mt-1">{forgotForm.formState.errors.forgotEmail.message}</p>
                    )}
                  </div>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="btn-primary w-full flex items-center justify-center gap-2 py-2.5"
                  >
                    {isLoading && <Loader2 size={16} className="animate-spin" />}
                    Send Reset Link
                  </button>
                </form>
              )}
            </>
          )}
        </div>

        <p className="text-center text-slate-500 text-xs mt-6">
          © {new Date().getFullYear()} IGA Platform. Enterprise Identity Governance.
        </p>
      </div>
    </div>
  )
}
