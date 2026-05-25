import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { WatchlistSymbol } from '../types/market'

const DEFAULT_WATCHLIST: WatchlistSymbol[] = [
  { symbol: '^NSEI',       displayName: 'Nifty 50',                 exchange: 'INDEX' },
  { symbol: '^NSEBANK',    displayName: 'Bank Nifty',               exchange: 'INDEX' },
  { symbol: 'RELIANCE.NS', displayName: 'Reliance Industries',      exchange: 'NSE'   },
  { symbol: 'TCS.NS',      displayName: 'Tata Consultancy Services', exchange: 'NSE'   },
  { symbol: 'HDFCBANK.NS', displayName: 'HDFC Bank',                exchange: 'NSE'   },
  { symbol: 'INFY.NS',     displayName: 'Infosys',                  exchange: 'NSE'   },
  { symbol: 'ADANIENT.NS', displayName: 'Adani Enterprises',        exchange: 'NSE'   },
  { symbol: 'ICICIBANK.NS',displayName: 'ICICI Bank',               exchange: 'NSE'   },
  { symbol: 'WIPRO.NS',    displayName: 'Wipro',                    exchange: 'NSE'   },
  { symbol: 'BTC-USD',     displayName: 'Bitcoin',                  exchange: 'CRYPTO'},
]

interface WatchlistState {
  symbols: WatchlistSymbol[]
  selected: string | null
  editMode: boolean
  searchQuery: string
  addSymbol: (sym: WatchlistSymbol) => void
  removeSymbol: (symbol: string) => void
  selectSymbol: (symbol: string | null) => void
  toggleEditMode: () => void
  setSearchQuery: (q: string) => void
}

export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set) => ({
      symbols: DEFAULT_WATCHLIST,
      selected: 'RELIANCE.NS',
      editMode: false,
      searchQuery: '',
      addSymbol: (sym) =>
        set((s) => ({
          symbols: s.symbols.some((x) => x.symbol === sym.symbol)
            ? s.symbols
            : [...s.symbols, sym],
        })),
      removeSymbol: (symbol) =>
        set((s) => ({
          symbols: s.symbols.filter((x) => x.symbol !== symbol),
          selected: s.selected === symbol ? null : s.selected,
        })),
      selectSymbol: (symbol) => set({ selected: symbol }),
      toggleEditMode: () => set((s) => ({ editMode: !s.editMode })),
      setSearchQuery: (q) => set({ searchQuery: q }),
    }),
    { name: 'tt-watchlist' }
  )
)
