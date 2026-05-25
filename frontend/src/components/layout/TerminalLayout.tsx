import { useEffect } from 'react'
import TopNav from './TopNav'
import BottomPanel from './BottomPanel'
import WatchlistPanel from '../watchlist/WatchlistPanel'
import ChartArea from '../chart/ChartArea'
import { useThemeStore } from '../../store/themeStore'

export default function TerminalLayout() {
  const { theme } = useThemeStore()

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  return (
    <div
      className="h-screen flex flex-col overflow-hidden font-sans"
      style={{ background: 'var(--bg)' }}
    >
      <TopNav />

      {/* Main area: chart + watchlist */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        <ChartArea />
        <WatchlistPanel />
      </div>

      <BottomPanel />
    </div>
  )
}
