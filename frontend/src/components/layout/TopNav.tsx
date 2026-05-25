import { useState } from 'react'
import { Sun, Moon, Search, Settings, Bell, ChevronDown } from 'lucide-react'
import { useThemeStore } from '../../store/themeStore'
import { useWatchlistStore } from '../../store/watchlistStore'
import { useTerminalStore } from '../../store/terminalStore'
import type { NavPage } from '../../types/market'

const NAV_ITEMS: NavPage[] = ['Chart', 'FnO', 'Portfolio', 'News']

export default function TopNav() {
  const { theme, toggle } = useThemeStore()
  const { selected } = useWatchlistStore()
  const { activePage, setActivePage } = useTerminalStore()
  const [query, setQuery] = useState('')

  const selectedDisplay = selected
    ? selected.replace('.NS', '').replace('.BO', '').replace('^', '')
    : ''

  return (
    <header
      className="flex h-11 flex-shrink-0 items-center gap-2 border-b px-3"
      style={{
        background: 'var(--topbar)',
        borderColor: 'var(--border)',
      }}
    >
      <div className="mr-3 flex select-none items-center gap-1.5">
        <div
          className="flex h-6 w-6 items-center justify-center rounded-sm text-xs font-black"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          B
        </div>
        <span className="hidden text-sm font-semibold sm:block" style={{ color: 'var(--text)' }}>
          Terminal
        </span>
      </div>

      <nav className="flex items-center gap-0.5">
        {NAV_ITEMS.map((page) => (
          <button
            key={page}
            onClick={() => setActivePage(page)}
            className="h-7 rounded-sm px-3 text-xs font-medium transition-colors"
            style={{
              color: activePage === page ? 'var(--text)' : 'var(--text-sub)',
              background: activePage === page ? 'var(--active)' : 'transparent',
            }}
          >
            {page === 'FnO' ? 'F&O' : page}
          </button>
        ))}
      </nav>

      {selectedDisplay && (
        <div
          className="ml-2 flex h-6 cursor-pointer items-center gap-1 rounded-sm px-2 text-xs font-medium"
          style={{ background: 'var(--active)', color: 'var(--text)' }}
        >
          <span className="price-mono">{selectedDisplay}</span>
          <ChevronDown size={11} />
        </div>
      )}

      <div className="flex-1" />

      <div
        className="hidden h-7 w-44 items-center gap-2 rounded-sm px-2.5 text-xs md:flex"
        style={{
          background: 'var(--panel2)',
          border: '1px solid var(--border)',
          color: 'var(--text-sub)',
        }}
      >
        <Search size={12} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search symbol..."
          className="min-w-0 flex-1 bg-transparent outline-none"
          style={{ color: 'var(--text)', caretColor: 'var(--accent)' }}
        />
      </div>

      <div className="ml-1 flex items-center gap-0.5">
        <button
          className="flex h-7 w-7 items-center justify-center rounded-sm transition-colors"
          style={{ color: 'var(--text-sub)' }}
          title="Alerts"
        >
          <Bell size={15} />
        </button>
        <button
          className="flex h-7 w-7 items-center justify-center rounded-sm transition-colors"
          style={{ color: 'var(--text-sub)' }}
          title="Settings"
        >
          <Settings size={15} />
        </button>
        <button
          onClick={toggle}
          className="flex h-7 w-7 items-center justify-center rounded-sm transition-colors"
          style={{ color: 'var(--text-sub)' }}
          title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  )
}
