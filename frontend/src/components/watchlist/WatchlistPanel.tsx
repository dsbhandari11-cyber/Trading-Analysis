import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Check, Plus, Search, X } from 'lucide-react'
import { useWatchlistStore } from '../../store/watchlistStore'
import { useWatchlistPrices } from '../../hooks/useWatchlistPrices'
import WatchlistRow from './WatchlistRow'
import type { WatchlistSymbol } from '../../types/market'

const PANEL_WIDTH = 'clamp(320px, 25vw, 380px)'

function AddForm({ onAdd, onClose }: { onAdd: (sym: WatchlistSymbol) => void; onClose: () => void }) {
  const [val, setVal] = useState('')

  const submit = () => {
    const raw = val.trim().toUpperCase()
    if (!raw) return
    const symbol =
      raw.endsWith('.NS') || raw.endsWith('.BO') || raw.startsWith('^') || raw.includes('-')
        ? raw
        : `${raw}.NS`

    onAdd({ symbol, displayName: raw.replace(/\.(NS|BO)$/, ''), exchange: symbol.endsWith('.BO') ? 'BSE' : 'NSE' })
    onClose()
  }

  return (
    <div
      className="flex h-8 items-center gap-1.5 border-b px-2"
      style={{ borderColor: 'var(--border)', background: 'var(--panel2)' }}
    >
      <input
        autoFocus
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
          if (e.key === 'Escape') onClose()
        }}
        placeholder="RELIANCE or AAPL"
        className="min-w-0 flex-1 bg-transparent text-xs outline-none"
        style={{ color: 'var(--text)', caretColor: 'var(--accent)' }}
      />
      <button
        onClick={submit}
        className="h-5 rounded-sm px-1.5 text-2xs font-semibold"
        style={{ background: 'var(--accent)', color: '#fff' }}
      >
        Add
      </button>
      <button
        onClick={onClose}
        className="flex h-5 w-5 items-center justify-center rounded-sm"
        style={{ color: 'var(--muted)' }}
        title="Close"
      >
        <X size={12} />
      </button>
    </div>
  )
}

export default function WatchlistPanel() {
  const {
    symbols,
    selected,
    editMode,
    searchQuery,
    addSymbol,
    removeSymbol,
    selectSymbol,
    toggleEditMode,
    setSearchQuery,
  } = useWatchlistStore()

  const [showAdd, setShowAdd] = useState(false)

  const symbolKeys = useMemo(() => symbols.map((s) => s.symbol), [symbols])
  const { prices, loading } = useWatchlistPrices(symbolKeys)

  const filtered = useMemo(() => {
    if (!searchQuery) return symbols
    const q = searchQuery.toLowerCase()
    return symbols.filter(
      (s) =>
        s.symbol.toLowerCase().includes(q) ||
        s.displayName.toLowerCase().includes(q)
    )
  }, [symbols, searchQuery])

  const columns = editMode
    ? 'minmax(92px,1fr) 78px 58px 58px 28px'
    : 'minmax(92px,1fr) 78px 58px 58px'

  return (
    <aside
      className="flex flex-shrink-0 flex-col overflow-hidden border-l"
      style={{
        width: PANEL_WIDTH,
        background: 'var(--panel)',
        borderColor: 'var(--border)',
      }}
    >
      <div
        className="flex h-9 flex-shrink-0 items-center gap-1.5 border-b px-2"
        style={{ borderColor: 'var(--border)' }}
      >
        <span className="flex-1 text-xs font-semibold" style={{ color: 'var(--text)' }}>
          Watchlist
        </span>
        <button
          onClick={() => setShowAdd((v) => !v)}
          className="flex h-6 w-6 items-center justify-center rounded-sm transition-colors"
          style={{ color: 'var(--text-sub)' }}
          title="Add symbol"
        >
          <Plus size={14} />
        </button>
        <button
          onClick={toggleEditMode}
          className="flex h-6 min-w-8 items-center justify-center rounded-sm px-2 text-2xs font-semibold transition-colors"
          style={{
            background: editMode ? 'var(--accent)' : 'var(--active)',
            color: editMode ? '#fff' : 'var(--text-sub)',
          }}
          title={editMode ? 'Done editing' : 'Edit watchlist'}
        >
          {editMode ? <Check size={12} /> : 'Edit'}
        </button>
      </div>

      {showAdd && (
        <AddForm
          onAdd={(sym) => {
            addSymbol(sym)
            setShowAdd(false)
          }}
          onClose={() => setShowAdd(false)}
        />
      )}

      <div
        className="mx-2 my-1.5 flex h-7 flex-shrink-0 items-center gap-2 rounded-sm px-2"
        style={{
          background: 'var(--panel2)',
          border: '1px solid var(--border)',
        }}
      >
        <Search size={11} style={{ color: 'var(--muted)', flexShrink: 0 }} />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search..."
          className="min-w-0 flex-1 bg-transparent text-xs outline-none"
          style={{ color: 'var(--text)', caretColor: 'var(--accent)' }}
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="flex h-5 w-5 items-center justify-center rounded-sm"
            style={{ color: 'var(--muted)' }}
            title="Clear search"
          >
            <X size={11} />
          </button>
        )}
      </div>

      <div
        className="watchlist-grid h-6 flex-shrink-0 items-center border-y px-2 text-[10px] uppercase"
        style={{
          borderColor: 'var(--border)',
          background: 'var(--panel2)',
          color: 'var(--muted)',
          gridTemplateColumns: columns,
        }}
      >
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="text-right">Change</span>
        <span className="text-right">Chg %</span>
        {editMode && <span />}
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {loading && !Object.keys(prices).length ? (
          <SkeletonRows count={filtered.length || 10} columns={columns} />
        ) : (
          filtered.map((entry) => (
            <WatchlistRow
              key={entry.symbol}
              entry={entry}
              priceData={prices[entry.symbol]}
              isSelected={entry.symbol === selected}
              isEditMode={editMode}
              onSelect={() => selectSymbol(entry.symbol)}
              onDelete={() => removeSymbol(entry.symbol)}
            />
          ))
        )}
        {filtered.length === 0 && !loading && (
          <div className="flex h-16 items-center justify-center">
            <span className="text-2xs" style={{ color: 'var(--muted)' }}>No results</span>
          </div>
        )}
      </div>

      <div
        className="flex h-6 flex-shrink-0 items-center border-t px-2"
        style={{ borderColor: 'var(--border)', background: 'var(--panel2)' }}
      >
        <span className="text-2xs" style={{ color: 'var(--muted)' }}>
          {symbols.length} symbols
        </span>
      </div>
    </aside>
  )
}

function SkeletonRows({ count, columns }: { count: number; columns: string }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <motion.div
          key={i}
          className="watchlist-grid items-center px-2"
          style={{ height: 34, borderBottom: '1px solid var(--border)', gridTemplateColumns: columns }}
          animate={{ opacity: [0.4, 0.72, 0.4] }}
          transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.05 }}
        >
          <div className="h-2.5 w-20 rounded-sm" style={{ background: 'var(--active)' }} />
          <div className="h-2.5 w-16 justify-self-end rounded-sm" style={{ background: 'var(--active)' }} />
          <div className="h-2.5 w-10 justify-self-end rounded-sm" style={{ background: 'var(--hover)' }} />
          <div className="h-2.5 w-10 justify-self-end rounded-sm" style={{ background: 'var(--hover)' }} />
        </motion.div>
      ))}
    </>
  )
}
