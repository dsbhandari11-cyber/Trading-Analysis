export type Exchange = 'NSE' | 'BSE' | 'US' | 'CRYPTO' | 'FX' | 'INDEX'

// ── CFD Asset Card ─────────────────────────────────────────────────────────
export interface CfdAsset {
  symbol: string
  name: string
  icon: string
  category: 'COMMODITY' | 'CRYPTO' | 'INDEX' | 'FOREX'
  unit: string
  price: number | null
  change: number | null
  change_pct: number | null
}

// ── SMC types ──────────────────────────────────────────────────────────────
export interface OrderBlock {
  time_start: number
  high: number
  low: number
  mitigated: boolean
  strength: number
  idx: number
}

export interface FVGEntry {
  time_start: number
  high: number
  low: number
  gap_pct: number
  filled: boolean
  active: boolean
}

export interface BosEvent {
  direction: 'bullish' | 'bearish'
  level: number
  time: number
}

export interface LiquidityLevel {
  type: 'EQH' | 'EQL'
  price: number
  time: number
}

export interface MarketStructure {
  trend: 'bullish' | 'bearish'
  bos: BosEvent[]
  choch: BosEvent[]
  zone: 'Premium' | 'Discount'
  eq_pct: number
  equilibrium: number
  recent_high: number
  recent_low: number
  liquidity: LiquidityLevel[]
}

export interface InstitutionalData {
  bias: string
  bull_prob: number
  bear_prob: number
  rsi: number
  momentum: number
  momentum_lbl: string
  volatility: number
  trend_str: number
  rvol: number
  session: string
  liq_dir: string
  position: 'Premium' | 'Discount'
  equilibrium: number
  range_high: number
  range_low: number
  entry_bull: number
  entry_bear: number
  sl_bull: number
  sl_bear: number
  tp1_bull: number
  tp2_bull: number
  tp1_bear: number
  tp2_bear: number
  rr_bull: number
  rr_bear: number
}

export interface SMCData {
  symbol: string
  current_price: number
  change_pct: number
  order_blocks: {
    bullish: OrderBlock[]
    bearish: OrderBlock[]
    active_bullish: OrderBlock[]
    active_bearish: OrderBlock[]
  }
  fvg: {
    bullish: FVGEntry[]
    bearish: FVGEntry[]
    bull_ifvg: FVGEntry[]
    bear_ifvg: FVGEntry[]
  }
  market_structure: MarketStructure
  institutional: InstitutionalData
  error?: string
}

export interface WatchlistSymbol {
  symbol: string
  displayName: string
  exchange: Exchange
}

export interface PriceData {
  symbol: string
  price: number | null
  change: number | null
  changePct: number | null
  prevClose: number | null
}

export type Theme = 'dark' | 'light'

export type BottomTab =
  | 'Orders'
  | 'Positions'
  | 'Holdings'
  | 'Trades'
  | 'Strategy Scanner'
  | 'Alerts'
  | 'Screener'
  | 'Institutional Analysis'

export type FnoTab =
  | 'Option Chain'
  | 'Open Interest'
  | 'PCR Analysis'
  | 'Strategy Scanner'
  | 'Max Pain'
  | 'Greeks'
  | 'Smart Money Signals'

export type NavPage = 'Chart' | 'FnO' | 'Portfolio' | 'News'
