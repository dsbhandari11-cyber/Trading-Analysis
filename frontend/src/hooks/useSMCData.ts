import { useEffect, useRef, useState } from 'react'
import type { SMCData } from '../types/market'

const BASE = (import.meta.env.VITE_API_BASE ?? '') as string
const POLL_MS = 30_000

export function useSMCData(symbol: string | null) {
  const [data, setData] = useState<SMCData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const symbolRef = useRef<string | null>(null)

  const fetchData = async (sym: string) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ symbol: sym, period: '3mo', interval: '1d' })
      const res = await fetch(`${BASE}/api/smc?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: SMCData = await res.json()
      if (json.error) throw new Error(json.error)
      setData(json)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'fetch failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (!symbol) {
      setData(null)
      setLoading(false)
      return
    }
    if (symbolRef.current !== symbol) {
      symbolRef.current = symbol
      setData(null)
    }
    fetchData(symbol)
    timerRef.current = setInterval(() => fetchData(symbol), POLL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [symbol])

  return { data, loading, error }
}
