import React, { useState, useRef, useEffect } from 'react'
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  LayoutDashboard, BarChart2, Inbox, CheckSquare, Award,
  Users, Shield, Grid, AlertTriangle, Network, FileText,
  FileCheck, GitBranch, Plug, RefreshCw, Key, Search,
  Building, Settings, ChevronLeft, ChevronRight, Bell,
  Sun, Moon, LogOut, User, Menu, X, ChevronDown
} from 'lucide-react'
import { RootState, AppDispatch } from '@/store'
import { toggleTheme } from '@/store/slices/uiSlice'
import { toggleSidebar } from '@/store/slices/uiSlice'
import { logoutThunk } from '@/store/slices/authSlice'
import { markAllAsRead } from '@/store/slices/notificationSlice'
import { generateInitials, getAvatarColor, formatRelativeTime } from '@/utils/helpers'
import { useWebSocket } from '@/hooks/useWebSocket'

interface NavItem {
  label: string
  path: string
  icon: React.ComponentType<{ size?: number; className?: string }>
}

interface NavGroup {
  group: string
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    group: 'Overview',
    items: [
      { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
      { label: 'Analytics', path: '/analytics', icon: BarChart2 },
    ],
  },
  {
    group: 'Access',
    items: [
      { label: 'Requests', path: '/requests', icon: Inbox },
      { label: 'Approvals', path: '/approvals', icon: CheckSquare },
      { label: 'Certifications', path: '/certifications', icon: Award },
    ],
  },
  {
    group: 'Identity',
    items: [
      { label: 'Users', path: '/users', icon: Users },
      { label: 'Roles', path: '/roles', icon: Shield },
      { label: 'Applications', path: '/applications', icon: Grid },
    ],
  },
  {
    group: 'Governance',
    items: [
      { label: 'SoD', path: '/sod', icon: AlertTriangle },
      { label: 'Role Mining', path: '/role-mining', icon: Network },
      { label: 'Policy', path: '/policy', icon: FileText },
      { label: 'Compliance', path: '/compliance', icon: FileCheck },
    ],
  },
  {
    group: 'Operations',
    items: [
      { label: 'Workflows', path: '/workflows', icon: GitBranch },
      { label: 'Connectors', path: '/connectors', icon: Plug },
      { label: 'HRMS Sync', path: '/hrms', icon: RefreshCw },
    ],
  },
  {
    group: 'Security',
    items: [
      { label: 'PAM', path: '/pam', icon: Key },
      { label: 'Audit Logs', path: '/audit', icon: Search },
    ],
  },
  {
    group: 'Admin',
    items: [
      { label: 'Tenants', path: '/tenants', icon: Building },
      { label: 'Settings', path: '/settings', icon: Settings },
    ],
  },
]

function getBreadcrumbs(pathname: string): string[] {
  const parts = pathname.split('/').filter(Boolean)
  if (parts.length === 0) return ['Dashboard']
  return parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1).replace(/-/g, ' '))
}

export default function AppLayout() {
  const dispatch = useDispatch<AppDispatch>()
  const navigate = useNavigate()
  const location = useLocation()
  useWebSocket()

  const theme = useSelector((state: RootState) => state.ui.theme)
  const sidebarCollapsed = useSelector((state: RootState) => state.ui.sidebarCollapsed)
  const user = useSelector((state: RootState) => state.auth.user)
  const notifications = useSelector((state: RootState) => state.notifications.notifications)
  const unreadCount = useSelector((state: RootState) => state.notifications.unreadCount)

  const [mobileOpen, setMobileOpen] = useState(false)
  const [userDropdownOpen, setUserDropdownOpen] = useState(false)
  const [notifDropdownOpen, setNotifDropdownOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')

  const userDropdownRef = useRef<HTMLDivElement>(null)
  const notifDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (userDropdownRef.current && !userDropdownRef.current.contains(e.target as Node)) {
        setUserDropdownOpen(false)
      }
      if (notifDropdownRef.current && !notifDropdownRef.current.contains(e.target as Node)) {
        setNotifDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleLogout = async () => {
    await dispatch(logoutThunk())
    navigate('/login')
  }

  const breadcrumbs = getBreadcrumbs(location.pathname)

  const userName = user ? `${user.firstName} ${user.lastName}` : 'User'
  const initials = generateInitials(userName)
  const avatarColor = getAvatarColor(userName)

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-900 overflow-hidden">
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed top-0 left-0 h-full z-50 flex flex-col bg-slate-900 dark:bg-slate-950
          transition-all duration-300 ease-in-out
          ${sidebarCollapsed ? 'w-16' : 'w-64'}
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center h-16 px-4 border-b border-slate-700 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Shield size={18} className="text-white" />
            </div>
            {!sidebarCollapsed && (
              <span className="font-bold text-white text-base truncate">IGA Platform</span>
            )}
          </div>
          <button
            onClick={() => setMobileOpen(false)}
            className="ml-auto lg:hidden text-slate-400 hover:text-white"
          >
            <X size={20} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-4 scrollbar-thin">
          {navGroups.map((group) => (
            <div key={group.group} className="mb-2">
              {!sidebarCollapsed && (
                <p className="px-4 mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {group.group}
                </p>
              )}
              {group.items.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setMobileOpen(false)}
                    title={sidebarCollapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      `flex items-center gap-3 mx-2 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
                        isActive
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-400 hover:text-white hover:bg-slate-700'
                      } ${sidebarCollapsed ? 'justify-center' : ''}`
                    }
                  >
                    <Icon size={18} className="flex-shrink-0" />
                    {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>

        {/* Collapse button */}
        <div className="p-3 border-t border-slate-700 flex-shrink-0">
          <button
            onClick={() => dispatch(toggleSidebar())}
            className="hidden lg:flex w-full items-center justify-center gap-2 px-3 py-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors text-sm"
          >
            {sidebarCollapsed ? <ChevronRight size={16} /> : <><ChevronLeft size={16} /><span>Collapse</span></>}
          </button>
        </div>
      </aside>

      {/* Main area */}
      <div
        className={`flex flex-col flex-1 min-w-0 transition-all duration-300 ${
          sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
        }`}
      >
        {/* Navbar */}
        <header className="flex-shrink-0 h-16 flex items-center gap-4 px-4 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 z-30">
          {/* Mobile menu button */}
          <button
            onClick={() => setMobileOpen(true)}
            className="lg:hidden text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white"
          >
            <Menu size={22} />
          </button>

          {/* Search */}
          <div className="flex-1 max-w-md">
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search users, roles, requests..."
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm bg-slate-100 dark:bg-slate-700 border border-transparent focus:border-blue-500 focus:bg-white dark:focus:bg-slate-800 rounded-lg text-slate-700 dark:text-slate-200 placeholder-slate-400 focus:outline-none transition-colors"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 ml-auto">
            {/* Theme toggle */}
            <button
              onClick={() => dispatch(toggleTheme())}
              className="p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
            </button>

            {/* Notifications */}
            <div className="relative" ref={notifDropdownRef}>
              <button
                onClick={() => setNotifDropdownOpen(!notifDropdownOpen)}
                className="relative p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Bell size={20} />
                {unreadCount > 0 && (
                  <span className="absolute top-1 right-1 min-w-[16px] h-4 flex items-center justify-center bg-red-500 text-white text-xs font-bold rounded-full px-0.5">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </button>

              {notifDropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-80 bg-white dark:bg-slate-800 rounded-xl shadow-xl border border-slate-200 dark:border-slate-700 z-50 animate-fade-in">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                    <h3 className="font-semibold text-slate-900 dark:text-white text-sm">Notifications</h3>
                    {unreadCount > 0 && (
                      <button
                        onClick={() => dispatch(markAllAsRead())}
                        className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
                      >
                        Mark all read
                      </button>
                    )}
                  </div>
                  <div className="max-h-80 overflow-y-auto scrollbar-thin">
                    {notifications.length === 0 ? (
                      <div className="py-8 text-center text-slate-500 dark:text-slate-400 text-sm">
                        No notifications
                      </div>
                    ) : (
                      notifications.slice(0, 10).map((n) => (
                        <div
                          key={n.id}
                          className={`px-4 py-3 border-b border-slate-100 dark:border-slate-700 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer ${
                            !n.isRead ? 'bg-blue-50/50 dark:bg-blue-900/10' : ''
                          }`}
                        >
                          <div className="flex items-start gap-2">
                            {!n.isRead && (
                              <div className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0 mt-1.5" />
                            )}
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">{n.title}</p>
                              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">{n.message}</p>
                              <p className="text-xs text-slate-400 mt-1">{formatRelativeTime(n.createdAt)}</p>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* User dropdown */}
            <div className="relative" ref={userDropdownRef}>
              <button
                onClick={() => setUserDropdownOpen(!userDropdownOpen)}
                className="flex items-center gap-2 pl-1 pr-2 py-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <div className={`w-8 h-8 rounded-full ${avatarColor} flex items-center justify-center text-white text-xs font-semibold flex-shrink-0`}>
                  {initials}
                </div>
                <div className="hidden sm:block text-left">
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-200 leading-tight">{userName}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 leading-tight truncate max-w-[120px]">{user?.email}</p>
                </div>
                <ChevronDown size={14} className="text-slate-400 hidden sm:block" />
              </button>

              {userDropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-56 bg-white dark:bg-slate-800 rounded-xl shadow-xl border border-slate-200 dark:border-slate-700 z-50 animate-fade-in">
                  <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                    <p className="font-semibold text-slate-900 dark:text-white text-sm">{userName}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{user?.email}</p>
                  </div>
                  <div className="py-1">
                    <button
                      onClick={() => { navigate('/settings'); setUserDropdownOpen(false) }}
                      className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                    >
                      <User size={16} /> Profile
                    </button>
                    <button
                      onClick={() => { navigate('/settings'); setUserDropdownOpen(false) }}
                      className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                    >
                      <Settings size={16} /> Settings
                    </button>
                  </div>
                  <div className="border-t border-slate-200 dark:border-slate-700 py-1">
                    <button
                      onClick={handleLogout}
                      className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      <LogOut size={16} /> Sign out
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          {/* Breadcrumb */}
          <div className="px-6 py-3 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
            <nav className="flex items-center gap-2 text-sm">
              {breadcrumbs.map((crumb, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <span className="text-slate-400">/</span>}
                  <span
                    className={
                      idx === breadcrumbs.length - 1
                        ? 'text-slate-700 dark:text-slate-300 font-medium'
                        : 'text-slate-400 dark:text-slate-500'
                    }
                  >
                    {crumb}
                  </span>
                </React.Fragment>
              ))}
            </nav>
          </div>

          <div className="p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
