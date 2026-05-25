import { create } from 'zustand'
import type { FnoTab, NavPage } from '../types/market'

interface TerminalState {
  activePage: NavPage
  activeFnoTab: FnoTab
  setActivePage: (page: NavPage) => void
  setActiveFnoTab: (tab: FnoTab) => void
}

export const useTerminalStore = create<TerminalState>((set) => ({
  activePage: 'Chart',
  activeFnoTab: 'Option Chain',
  setActivePage: (page) => set({ activePage: page }),
  setActiveFnoTab: (tab) => set({ activeFnoTab: tab }),
}))
