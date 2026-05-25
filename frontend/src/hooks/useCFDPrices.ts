import { useEffect, useRef, useState } from 'react'
import type { CfdAsset } from '../types/market'

const BASE = (import.meta.env.VITE_API_BASE ?? '') as string
const POLL_MS = 20_000

export function useCFDPrices() {
  const [assets, setAssets] = useState<CfdAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchPrices = async () => {
    try {
      const res = await fetch(`${BASE}/api/cfd/prices`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: CfdAsset[] = await res.json()
      setAssets(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'fetch failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPrices()
    timerRef.current = setInterval(fetchPrices, POLL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  return { assets, loading, error }
}
