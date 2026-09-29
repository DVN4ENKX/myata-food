import { useEffect, useRef, useState } from 'react'
import { getToken } from './api'

type Handler = (event: string, data: unknown) => void

/** Subscribes to a backend channel; reconnects with backoff while a token exists. */
export function useLiveChannel(channel: 'occupancy' | 'kitchen' | null, onMessage: Handler): boolean {
  const [online, setOnline] = useState(false)
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    if (!channel) return
    const token = getToken()
    if (!token) return

    let socket: WebSocket | null = null
    let closed = false
    let retry = 0
    let timer: number | undefined
    let heartbeat: number | undefined

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/api/ws/${channel}?token=${encodeURIComponent(token)}`
      socket = new WebSocket(url)

      socket.onopen = () => {
        retry = 0
        setOnline(true)
        // proxies drop idle sockets: the backend answers "ping" with "pong"
        heartbeat = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send('ping')
        }, 25000)
      }
      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as { event: string; data: unknown }
          handlerRef.current(parsed.event, parsed.data)
        } catch {
          /* ignore malformed frames */
        }
      }
      socket.onclose = () => {
        setOnline(false)
        if (heartbeat) window.clearInterval(heartbeat)
        if (closed) return
        retry += 1
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** (retry - 1), 15000))
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      closed = true
      if (timer) window.clearTimeout(timer)
      if (heartbeat) window.clearInterval(heartbeat)
      socket?.close()
    }
  }, [channel])

  return online
}
