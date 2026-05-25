import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchWatchlistPrices } from '../lib/api'
import type { PriceData } from '../types/market'

const POLL_MS = 15_000

export function useWatchlistPrices(symbols: string[]) {
  const [prices, setPrices] = useState<Record<string, PriceData>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const keyRef = useRef(symbols.join(','))

  const refresh = useCallback(async () => {
    const key = keyRef.current
    if (!key) return
    const list = key.split(',').filter(Boolean)
    try {
      const data = await fetchWatchlistPrices(list)
      setPrices((prev) => {
        const next = { ...prev }
        for (const [sym, d] of Object.entries(data)) {
          next[sym] = {
            symbol: sym,
            price: d.price,
            change: d.change,
            changePct: d.change_pct,
            prevClose: d.prev_close,
          }
        }
        return next
      })
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    keyRef.current = symbols.join(',')
    setLoading(true)
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [symbols.join(','), refresh]) // eslint-disable-line

  return { prices, loading, error, refresh }
}
