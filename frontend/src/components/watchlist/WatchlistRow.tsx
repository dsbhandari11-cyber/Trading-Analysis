import { AnimatePresence, motion } from 'framer-motion'
import { Trash2 } from 'lucide-react'
import type { WatchlistSymbol, PriceData } from '../../types/market'

interface Props {
  entry: WatchlistSymbol
  priceData: PriceData | undefined
  isSelected: boolean
  isEditMode: boolean
  onSelect: () => void
  onDelete: () => void
}

function formatPrice(price: number | null, symbol: string): string {
  if (price == null) return '-'
  if (symbol.startsWith('^')) {
    return price.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  }

  const isINR = symbol.endsWith('.NS') || symbol.endsWith('.BO')
  const prefix = isINR ? '₹' : '$'
  return prefix + price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatChange(changePct: number | null): string {
  if (changePct == null) return '-'
  const sign = changePct >= 0 ? '+' : ''
  return `${sign}${changePct.toFixed(2)}%`
}

function formatChangeAbs(change: number | null, symbol: string): string {
  if (change == null) return '-'
  const isINR = symbol.endsWith('.NS') || symbol.endsWith('.BO')
  const sign = change >= 0 ? '+' : ''
  const prefix = isINR ? '' : '$'
  return `${sign}${prefix}${Math.abs(change).toFixed(2)}`
}

function getDisplayTicker(symbol: string): string {
  return symbol.replace(/\.(NS|BO)$/, '').replace(/^\^/, '')
}

export default function WatchlistRow({ entry, priceData, isSelected, isEditMode, onSelect, onDelete }: Props) {
  const { symbol, displayName } = entry
  const bull = priceData?.changePct != null ? priceData.changePct >= 0 : null
  const accentColor = bull === true ? 'var(--bull)' : bull === false ? 'var(--bear)' : 'var(--muted)'
  const ticker = getDisplayTicker(symbol)

  return (
    <motion.div
      layout
      className="watchlist-grid group relative w-full cursor-pointer select-none items-center px-2"
      style={{
        height: 34,
        background: isSelected ? 'var(--active)' : 'transparent',
        borderLeft: `2px solid ${isSelected ? accentColor : 'transparent'}`,
        borderBottom: '1px solid var(--border)',
        gridTemplateColumns: isEditMode
          ? 'minmax(92px,1fr) 78px 58px 58px 28px'
          : 'minmax(92px,1fr) 78px 58px 58px',
        transition: 'background 0.12s ease, border-color 0.12s ease',
      }}
      onClick={onSelect}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.background = 'var(--hover)'
      }}
      onMouseLeave={(e) => {
        if (!isSelected) e.currentTarget.style.background = 'transparent'
      }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1">
          <span
            className="price-mono block truncate text-[11px] font-semibold leading-none"
            style={{ color: isSelected ? accentColor : 'var(--text)', letterSpacing: 0 }}
          >
            {ticker}
          </span>
          {/* Micro sentiment dot */}
          {bull !== null && (
            <span
              style={{
                display: 'inline-block',
                width: 4,
                height: 4,
                borderRadius: '50%',
                background: accentColor,
                flexShrink: 0,
                boxShadow: isSelected ? `0 0 4px ${accentColor}` : 'none',
              }}
            />
          )}
        </div>
        <span
          className="mt-0.5 block truncate text-[10px] leading-none"
          style={{ color: 'var(--text-sub)' }}
        >
          {displayName}
        </span>
      </div>

      <span
        className="price-mono truncate text-right text-[11px] font-medium leading-none"
        style={{ color: 'var(--text)' }}
      >
        {formatPrice(priceData?.price ?? null, symbol)}
      </span>
      <span
        className="price-mono truncate text-right text-[11px] leading-none"
        style={{ color: accentColor }}
      >
        {formatChangeAbs(priceData?.change ?? null, symbol)}
      </span>
      <span
        className="price-mono truncate text-right text-[11px] font-medium leading-none"
        style={{ color: accentColor }}
      >
        {formatChange(priceData?.changePct ?? null)}
      </span>

      <AnimatePresence initial={false}>
        {isEditMode && (
          <motion.button
            key="delete"
            initial={{ opacity: 0, scale: 0.86, x: 6 }}
            animate={{ opacity: 1, scale: 1, x: 0 }}
            exit={{ opacity: 0, scale: 0.86, x: 6 }}
            transition={{ duration: 0.15, ease: 'easeInOut' }}
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            className="flex h-6 w-6 items-center justify-center justify-self-end rounded-sm transition-colors"
            style={{
              background: 'transparent',
              color: 'var(--bear)',
            }}
            title="Remove"
          >
            <Trash2 size={13} />
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
