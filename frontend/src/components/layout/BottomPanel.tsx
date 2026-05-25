import { useCallback, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronUp, GripHorizontal, X } from 'lucide-react'
import { useWatchlistStore } from '../../store/watchlistStore'
import InstitutionalPanel from '../smc/InstitutionalPanel'
import type { BottomTab } from '../../types/market'

const TABS: BottomTab[] = [
  'Orders',
  'Positions',
  'Holdings',
  'Trades',
  'Strategy Scanner',
  'Alerts',
  'Screener',
  'Institutional Analysis',
]

const DEFAULT_HEIGHT = 260
const MIN_HEIGHT = 140
const MAX_HEIGHT = 520

export default function BottomPanel() {
  const { selected } = useWatchlistStore()
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<BottomTab>('Positions')
  const [height, setHeight] = useState(DEFAULT_HEIGHT)

  const startResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = height

    const onMove = (moveEvent: PointerEvent) => {
      const delta = startY - moveEvent.clientY
      setHeight(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight + delta)))
    }

    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [height])

  return (
    <div className="flex-shrink-0">
      <div
        className="flex h-8 select-none items-center gap-0.5 border-t px-2"
        style={{
          background: 'var(--panel2)',
          borderColor: 'var(--border)',
        }}
      >
        <button
          onClick={() => setOpen((v) => !v)}
          className="mr-2 flex h-6 items-center gap-1 rounded-sm px-2 text-2xs font-medium transition-colors"
          style={{
            color: 'var(--text-sub)',
            background: 'var(--hover)',
          }}
        >
          {open ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
          <span>{open ? 'Collapse' : 'Terminal'}</span>
        </button>

        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => {
                setActiveTab(tab)
                if (tab === 'Institutional Analysis') setHeight(400)
                setOpen(true)
              }}
              className="h-6 whitespace-nowrap rounded-sm px-2.5 text-2xs font-medium transition-colors"
              style={{
                color: activeTab === tab && open ? 'var(--accent)' : 'var(--text-sub)',
                background: activeTab === tab && open ? 'var(--active)' : 'transparent',
                borderBottom: activeTab === tab && open ? '1px solid var(--accent)' : '1px solid transparent',
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {open && (
          <button
            onClick={() => setOpen(false)}
            className="flex h-6 w-6 items-center justify-center rounded-sm"
            style={{ color: 'var(--text-sub)' }}
            title="Close panel"
          >
            <X size={12} />
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="bottom-panel"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeInOut' }}
            style={{
              overflow: 'hidden',
              background: 'var(--panel)',
              borderTop: '1px solid var(--border)',
            }}
          >
            <div
              className="flex h-3 cursor-row-resize items-center justify-center border-b"
              style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}
              onPointerDown={startResize}
              title="Resize panel"
            >
              <GripHorizontal size={14} />
            </div>
            <div className="h-[calc(100%-12px)] overflow-auto">
              <PanelContent tab={activeTab} selected={selected} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function PanelContent({ tab, selected }: { tab: BottomTab; selected: string | null }) {
  if (tab === 'Institutional Analysis') {
    return <InstitutionalPanel symbol={selected} />
  }

  return (
    <div className="h-full">
      <div
        className="grid h-7 grid-cols-[1fr_120px_120px_120px] items-center border-b px-3 text-[10px] uppercase"
        style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}
      >
        <span>{tab}</span>
        <span className="text-right">Qty</span>
        <span className="text-right">Avg</span>
        <span className="text-right">P&L</span>
      </div>
      <div className="flex h-[calc(100%-28px)] flex-col items-center justify-center gap-1">
        <span className="text-xs font-medium" style={{ color: 'var(--text-sub)' }}>
          No {tab.toLowerCase()} to display
        </span>
        <span className="text-[10px]" style={{ color: 'var(--muted)' }}>
          Terminal dock ready for backend data.
        </span>
      </div>
    </div>
  )
}
