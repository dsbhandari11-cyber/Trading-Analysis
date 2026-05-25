import { useRef } from 'react'
import { motion } from 'framer-motion'
import { useCFDPrices } from '../../hooks/useCFDPrices'
import { useWatchlistStore } from '../../store/watchlistStore'
import type { CfdAsset } from '../../types/market'

// Map CFD symbol to TV-compatible symbol for the watchlist store
const CFD_TO_INTERNAL: Record<string, string> = {
  'GC=F':     'GC=F',
  'SI=F':     'SI=F',
  'BTC-USD':  'BTC-USD',
  'ETH-USD':  'ETH-USD',
  '^NSEI':    '^NSEI',
  '^NSEBANK': '^NSEBANK',
  'NQ=F':     'NQ=F',
  'CL=F':     'CL=F',
  'EURUSD=X': 'EURUSD=X',
  'GBPUSD=X': 'GBPUSD=X',
}

const CATEGORY_COLORS: Record<string, string> = {
  COMMODITY: '#F59E0B',
  CRYPTO:    '#8B5CF6',
  INDEX:     '#3B82F6',
  FOREX:     '#00D4AA',
}

function formatPrice(price: number | null, symbol: string): string {
  if (price == null) return '—'
  const isForex = symbol.includes('=X')
  if (isForex) return price.toFixed(4)
  if (price > 10000) return price.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (price > 100)   return price.toLocaleString('en-US', { maximumFractionDigits: 2 })
  return price.toFixed(4)
}

function AssetCard({ asset }: { asset: CfdAsset }) {
  const { selectSymbol } = useWatchlistStore()
  const bull   = asset.change_pct != null ? asset.change_pct >= 0 : null
  const clr    = bull === true ? 'var(--bull)' : bull === false ? 'var(--bear)' : 'var(--muted)'
  const catClr = CATEGORY_COLORS[asset.category] ?? '#94A3B8'
  const arrow  = bull === true ? '▲' : bull === false ? '▼' : '●'

  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={() => {
        const sym = CFD_TO_INTERNAL[asset.symbol]
        if (sym) selectSymbol(sym)
      }}
      className="flex-shrink-0 flex flex-col gap-0.5 rounded-sm px-2.5 py-1.5 text-left transition-colors"
      style={{
        minWidth: 98,
        maxWidth: 120,
        background: 'var(--panel2)',
        border: '1px solid var(--border)',
        borderTop: `2px solid ${catClr}44`,
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = `${catClr}66`
        e.currentTarget.style.boxShadow = `0 0 10px ${catClr}18`
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--border)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      {/* Header row: icon + category */}
      <div className="flex items-center justify-between gap-1">
        <span
          className="price-mono flex items-center justify-center rounded-sm text-[9px] font-black"
          style={{
            minWidth: 24, height: 16, padding: '0 3px',
            background: `${catClr}22`,
            color: catClr,
            border: `1px solid ${catClr}44`,
          }}
        >
          {asset.icon}
        </span>
        <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: catClr }}>
          {asset.category}
        </span>
      </div>

      {/* Name */}
      <span className="text-[10px] font-semibold leading-none truncate" style={{ color: 'var(--text)' }}>
        {asset.name}
      </span>

      {/* Price */}
      <span className="price-mono text-[11px] font-bold leading-none" style={{ color: 'var(--text)' }}>
        {formatPrice(asset.price, asset.symbol)}
      </span>

      {/* Change */}
      <span
        className="price-mono text-[10px] font-semibold leading-none"
        style={{ color: clr }}
      >
        {arrow}&nbsp;
        {asset.change_pct != null
          ? `${asset.change_pct >= 0 ? '+' : ''}${asset.change_pct.toFixed(2)}%`
          : '—'}
      </span>

      {/* Live pulse dot */}
      {asset.price != null && (
        <motion.div
          animate={{ opacity: [1, 0.3, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
          style={{
            position: 'absolute', bottom: 4, right: 5,
            width: 5, height: 5, borderRadius: '50%',
            background: clr,
            boxShadow: `0 0 5px ${clr}`,
          }}
        />
      )}
    </motion.button>
  )
}

export default function AssetCardStrip() {
  const { assets, loading } = useCFDPrices()
  const scrollRef = useRef<HTMLDivElement>(null)

  if (loading && !assets.length) {
    return (
      <div
        className="flex h-14 flex-shrink-0 items-center gap-2 overflow-x-auto px-3 border-b"
        style={{ background: 'var(--panel2)', borderColor: 'var(--border)' }}
      >
        {Array.from({ length: 10 }).map((_, i) => (
          <motion.div
            key={i}
            animate={{ opacity: [0.3, 0.6, 0.3] }}
            transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.08 }}
            className="h-10 w-24 flex-shrink-0 rounded-sm"
            style={{ background: 'var(--active)' }}
          />
        ))}
      </div>
    )
  }

  return (
    <div
      ref={scrollRef}
      className="flex flex-shrink-0 items-center gap-1.5 overflow-x-auto border-b px-2 py-1.5 scrollbar-thin"
      style={{
        background: 'var(--panel2)',
        borderColor: 'var(--border)',
        minHeight: 56,
      }}
    >
      {/* Label */}
      <span
        className="mr-1 flex-shrink-0 text-[9px] font-black uppercase tracking-widest"
        style={{ color: 'var(--muted)', writingMode: 'horizontal-tb' }}
      >
        CFD
      </span>

      {assets.map((asset) => (
        <AssetCard key={asset.symbol} asset={asset} />
      ))}

      {/* Trailing spacer so last card isn't flush */}
      <div className="flex-shrink-0 w-2" />
    </div>
  )
}
