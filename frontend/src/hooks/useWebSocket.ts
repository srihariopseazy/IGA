import { useEffect, useRef, useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import toast from 'react-hot-toast'
import { RootState } from '@/store'
import { addNotification } from '@/store/slices/notificationSlice'
import { Notification } from '@/types'

interface WebSocketMessage {
  type: 'notification' | 'alert' | 'ping' | 'session_update'
  payload: unknown
}

const MAX_RECONNECT_ATTEMPTS = 8
const BASE_RECONNECT_DELAY = 1000

export function useWebSocket() {
  const dispatch = useDispatch()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempts = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const user = useSelector((state: RootState) => state.auth.user)
  const tenantId = useSelector((state: RootState) => state.auth.tenantId)
  const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated)

  const getReconnectDelay = useCallback(() => {
    return Math.min(BASE_RECONNECT_DELAY * 2 ** reconnectAttempts.current, 30000)
  }, [])

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data) as WebSocketMessage

        if (message.type === 'ping') return

        if (message.type === 'notification') {
          const notification = message.payload as Notification
          dispatch(addNotification(notification))

          if (notification.notificationType === 'approval_required') {
            toast('New approval request requires your attention', {
              icon: '🔔',
              duration: 5000,
            })
          } else if (notification.notificationType === 'sod_violation') {
            toast.error(`SoD Violation detected: ${notification.title}`, { duration: 6000 })
          } else if (notification.notificationType === 'access_granted') {
            toast.success(notification.title, { duration: 4000 })
          } else if (notification.notificationType === 'access_rejected') {
            toast.error(notification.title, { duration: 4000 })
          }
        }

        if (message.type === 'alert') {
          const alert = message.payload as { title: string; severity: string; message: string }
          if (alert.severity === 'critical') {
            toast.error(`CRITICAL: ${alert.title} - ${alert.message}`, { duration: 8000 })
          } else if (alert.severity === 'high') {
            toast(alert.message, { icon: '⚠️', duration: 6000 })
          }
        }
      } catch {
        // Ignore parse errors
      }
    },
    [dispatch]
  )

  const connect = useCallback(() => {
    if (!isAuthenticated || !user || !tenantId || !mountedRef.current) return

    const token = localStorage.getItem('accessToken')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/${tenantId}/${user.id}?token=${token}`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        reconnectAttempts.current = 0
      }

      ws.onmessage = handleMessage

      ws.onclose = (event) => {
        wsRef.current = null
        if (!mountedRef.current) return
        if (event.code !== 1000 && reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = getReconnectDelay()
          reconnectAttempts.current += 1
          reconnectTimerRef.current = setTimeout(() => {
            if (mountedRef.current) connect()
          }, delay)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      // WebSocket connection failed silently
    }
  }, [isAuthenticated, user, tenantId, handleMessage, getReconnectDelay])

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'Component unmounted')
      wsRef.current = null
    }
  }, [])

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    if (isAuthenticated) {
      connect()
    }
    return () => {
      mountedRef.current = false
      disconnect()
    }
  }, [isAuthenticated, connect, disconnect])

  return { sendMessage, disconnect, reconnect: connect }
}
