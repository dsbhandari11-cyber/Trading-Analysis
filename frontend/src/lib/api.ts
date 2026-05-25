const BASE = (import.meta.env.VITE_API_BASE ?? '') as string

export interface RawPriceData {
  symbol: string
  price: number | null
  change: number | null
  change_pct: number | null
  prev_close: number | null
}

export async function fetchWatchlistPrices(
  symbols: string[]
): Promise<Record<string, RawPriceData>> {
  if (!symbols.length) return {}
  const q = encodeURIComponent(symbols.join(','))
  const res = await fetch(`${BASE}/api/watchlist/prices?symbols=${q}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
