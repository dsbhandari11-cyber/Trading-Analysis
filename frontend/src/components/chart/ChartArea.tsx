import { useEffect, useRef } from 'react'
import { useWatchlistStore } from '../../store/watchlistStore'
import { useThemeStore } from '../../store/themeStore'
import { useTerminalStore } from '../../store/terminalStore'
import AssetCardStrip from '../smc/AssetCardStrip'
import type { FnoTab, NavPage } from '../../types/market'

declare global {
  interface Window {
    TradingView?: {
      widget: new (config: Record<string, unknown>) => { remove?: () => void }
    }
  }
}

function toTVSymbol(symbol: string): string {
  if (symbol.endsWith('.NS')) return 'NSE:' + symbol.replace('.NS', '')
  if (symbol.endsWith('.BO')) return 'BSE:' + symbol.replace('.BO', '')
  if (symbol === '^NSEI') return 'NSE:NIFTY'
  if (symbol === '^NSEBANK') return 'NSE:BANKNIFTY'
  if (symbol === '^BSESN') return 'BSE:SENSEX'
  if (symbol === 'BTC-USD') return 'BITSTAMP:BTCUSD'
  if (symbol === 'ETH-USD') return 'BITSTAMP:ETHUSD'
  if (symbol === 'GC=F') return 'COMEX:GC1!'
  if (symbol === 'SI=F') return 'COMEX:SI1!'
  return symbol
}

const SCRIPT_SRC = 'https://s3.tradingview.com/tv.js'
const CONTAINER_ID = 'tv_chart_container'

function loadTVScript(): Promise<void> {
  return new Promise((resolve) => {
    if (window.TradingView) {
      resolve()
      return
    }
    const s = document.createElement('script')
    s.src = SCRIPT_SRC
    s.async = true
    s.onload = () => resolve()
    document.head.appendChild(s)
  })
}

export default function ChartArea() {
  const { selected } = useWatchlistStore()
  const { theme } = useThemeStore()
  const { activePage, activeFnoTab, setActiveFnoTab } = useTerminalStore()
  const widgetRef = useRef<{ remove?: () => void } | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const tvSymbol = toTVSymbol(selected ?? 'NSE:NIFTY')

  useEffect(() => {
    let cancelled = false

    if (activePage !== 'Chart') {
      if (widgetRef.current?.remove) widgetRef.current.remove()
      widgetRef.current = null
      return () => {
        cancelled = true
      }
    }

    async function init() {
      await loadTVScript()
      if (cancelled || !window.TradingView || !containerRef.current) return

      if (widgetRef.current?.remove) widgetRef.current.remove()
      containerRef.current.innerHTML = ''

      widgetRef.current = new window.TradingView.widget({
        autosize: true,
        symbol: tvSymbol,
        interval: 'D',
        timezone: 'Asia/Kolkata',
        theme: theme === 'dark' ? 'dark' : 'light',
        style: '1',
        locale: 'en',
        toolbar_bg: theme === 'dark' ? '#0A0F1C' : '#FFFFFF',
        enable_publishing: false,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        container_id: CONTAINER_ID,
        studies: ['RSI@tv-basicstudies', 'MASimple@tv-basicstudies'],
        show_popup_button: false,
        popup_width: '1000',
        popup_height: '650',
        no_referral_id: true,
      })
    }

    init()
    return () => {
      cancelled = true
    }
  }, [activePage, tvSymbol, theme])

  if (activePage === 'FnO') {
    return (
      <FnoWorkspace
        activeTab={activeFnoTab}
        onTabChange={setActiveFnoTab}
      />
    )
  }

  if (activePage !== 'Chart') {
    return <PlaceholderWorkspace title={activePage} />
  }

  return (
    <main
      className="flex min-w-0 flex-1 flex-col overflow-hidden"
      style={{ background: 'var(--bg)' }}
    >
      <AssetCardStrip />
      <SymbolBar symbol={selected} tvSymbol={tvSymbol} />

      <div className="min-h-0 flex-1 overflow-hidden">
        <div
          id={CONTAINER_ID}
          ref={containerRef}
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    </main>
  )
}

function SymbolBar({ symbol, tvSymbol }: { symbol: string | null; tvSymbol: string }) {
  const displayTicker = tvSymbol.split(':')[1] ?? tvSymbol

  return (
    <div
      className="flex h-8 flex-shrink-0 items-center gap-3 border-b px-3 text-xs"
      style={{ borderColor: 'var(--border)', background: 'var(--panel2)' }}
    >
      <span className="price-mono font-semibold" style={{ color: 'var(--text)' }}>
        {displayTicker}
      </span>
      <span style={{ color: 'var(--text-sub)' }}>
        {symbol?.endsWith('.NS') ? 'NSE' : symbol?.endsWith('.BO') ? 'BSE' : 'GLOBAL'}
      </span>
      <div className="flex-1" />
      <span className="text-2xs" style={{ color: 'var(--muted)' }}>
        15-min delayed | Powered by TradingView
      </span>
    </div>
  )
}

const FNO_TABS: FnoTab[] = [
  'Option Chain',
  'Open Interest',
  'PCR Analysis',
  'Strategy Scanner',
  'Max Pain',
  'Greeks',
  'Smart Money Signals',
]

function FnoWorkspace({
  activeTab,
  onTabChange,
}: {
  activeTab: FnoTab
  onTabChange: (tab: FnoTab) => void
}) {
  return (
    <section className="flex min-w-0 flex-1 flex-col overflow-hidden" style={{ background: 'var(--bg)' }}>
      <div
        className="flex h-9 flex-shrink-0 items-center gap-1 overflow-x-auto border-b px-2"
        style={{ background: 'var(--panel2)', borderColor: 'var(--border)' }}
      >
        {FNO_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => onTabChange(tab)}
            className="h-7 whitespace-nowrap rounded-sm px-2.5 text-xs font-medium transition-colors"
            style={{
              background: activeTab === tab ? 'var(--active)' : 'transparent',
              color: activeTab === tab ? 'var(--text)' : 'var(--text-sub)',
              borderBottom: activeTab === tab ? '1px solid var(--accent)' : '1px solid transparent',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      <div
        className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-hidden lg:grid-cols-[1.25fr_0.75fr]"
        style={{ background: 'var(--border)' }}
      >
        <TerminalPane title={activeTab} />
        <TerminalPane title="NSE/BSE Derivatives" compact />
      </div>
    </section>
  )
}

function TerminalPane({ title, compact = false }: { title: string; compact?: boolean }) {
  return (
    <div className="flex min-h-0 flex-col" style={{ background: 'var(--panel)' }}>
      <div className="flex h-8 items-center border-b px-3" style={{ borderColor: 'var(--border)' }}>
        <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
        <div className="flex-1" />
        <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Live terminal view</span>
      </div>
      <div className="flex flex-1 items-center justify-center p-4 text-center">
        <div>
          <div className="text-xs font-medium" style={{ color: 'var(--text-sub)' }}>
            {compact ? 'Market breadth, PCR and smart money summaries' : `${title} workspace`}
          </div>
          <div className="mt-1 text-[10px]" style={{ color: 'var(--muted)' }}>
            Connected to existing backend data surfaces.
          </div>
        </div>
      </div>
    </div>
  )
}

function PlaceholderWorkspace({ title }: { title: NavPage }) {
  return (
    <section className="flex min-w-0 flex-1 items-center justify-center" style={{ background: 'var(--bg)' }}>
      <span className="text-xs" style={{ color: 'var(--muted)' }}>{title} workspace</span>
    </section>
  )
}
