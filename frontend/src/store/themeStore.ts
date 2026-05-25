import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Theme } from '../types/market'

interface ThemeState {
  theme: Theme
  toggle: () => void
  set: (t: Theme) => void
}

function applyTheme(t: Theme) {
  if (t === 'dark') {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'dark',
      toggle: () =>
        set((s) => {
          const next: Theme = s.theme === 'dark' ? 'light' : 'dark'
          applyTheme(next)
          return { theme: next }
        }),
      set: (t) => {
        applyTheme(t)
        set({ theme: t })
      },
    }),
    {
      name: 'tt-theme',
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme)
      },
    }
  )
)
