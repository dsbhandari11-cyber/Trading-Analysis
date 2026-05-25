import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useSMCData } from '../../hooks/useSMCData'
import { useWatchlistStore } from '../../store/watchlistStore'
import type {
  SMCData,
  OrderBlock,
  FVGEntry,
  InstitutionalData,
  MarketStructure,
} from '../../types/market'

// ── Color helpers ─────────────────────────────────────────────────────────────
const CYAN   = '#00D4AA'
const PURPLE = '#8B5CF6'

function biasColor(bias: string): string {
  if (bias.includes('Strong Bullish')) return '#00D4AA'
  if (bias.includes('Bullish'))        return 'var(--bull)'
  if (bias.includes('Strong Bearish')) return '#FF4D6D'
  if (bias.includes('Bearish'))        return 'var(--bear)'
  return 'var(--muted)'
}

function fmtPrice(v: number): string {
  if (v > 10000) return v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
  if (v > 100)   return v.toFixed(2)
  return v.toFixed(4)
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function Tag({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span
      className="inline-block rounded-sm px-1.5 py-0.5 text-[9px] font-black uppercase tracking-widest"
      style={{ color, background: bg, border: `1px solid ${color}44` }}
    >
      {label}
    </span>
  )
}

function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="relative h-1 w-full overflow-hidden rounded-full" style={{ background: 'var(--active)' }}>
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${Math.min(pct, 100)}%` }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className="absolute left-0 top-0 h-full rounded-full"
        style={{ background: color }}
      />
    </div>
  )
}

function ConfidenceBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Confidence</span>
        <span className="price-mono text-[10px] font-bold" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--active)' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{ background: `linear-gradient(90deg, ${color}, ${color}cc)` }}
        />
      </div>
    </div>
  )
}

// ── Sub-panels ────────────────────────────────────────────────────────────────

function OrderBlocksPanel({ data }: { data: SMCData }) {
  const bullOBs = data.order_blocks.active_bullish.slice().reverse()
  const bearOBs = data.order_blocks.active_bearish.slice().reverse()

  const OBRow = ({ ob, bull }: { ob: OrderBlock; bull: boolean }) => {
    const clr = bull ? 'var(--bull)' : 'var(--bear)'
    return (
      <div
        className="flex items-center gap-2 rounded-sm px-2 py-1.5"
        style={{ background: `${bull ? '#00C087' : '#FF4D6D'}08`, borderLeft: `2px solid ${clr}` }}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="price-mono text-[11px] font-bold" style={{ color: clr }}>
              {fmtPrice(ob.high)}
            </span>
            <span className="text-[10px]" style={{ color: 'var(--muted)' }}>—</span>
            <span className="price-mono text-[10px]" style={{ color: 'var(--text)' }}>
              {fmtPrice(ob.low)}
            </span>
          </div>
          <MiniBar pct={ob.strength} color={clr} />
        </div>
        <div className="flex flex-col items-end gap-0.5 flex-shrink-0">
          <Tag label={ob.mitigated ? 'MITIGATED' : 'ACTIVE'} color={ob.mitigated ? 'var(--muted)' : clr} bg={ob.mitigated ? 'var(--active)' : `${clr}18`} />
          <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{ob.strength.toFixed(0)}% str</span>
        </div>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-2">
      <div>
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="h-2 w-2 rounded-full" style={{ background: 'var(--bull)', boxShadow: `0 0 5px var(--bull)` }} />
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--bull)' }}>
            Bullish OBs
          </span>
          <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>({bullOBs.length})</span>
        </div>
        <div className="flex flex-col gap-1">
          {bullOBs.length ? bullOBs.map((ob, i) => <OBRow key={i} ob={ob} bull />)
            : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>No active bullish OBs</span>}
        </div>
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="h-2 w-2 rounded-full" style={{ background: 'var(--bear)', boxShadow: `0 0 5px var(--bear)` }} />
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--bear)' }}>
            Bearish OBs
          </span>
          <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>({bearOBs.length})</span>
        </div>
        <div className="flex flex-col gap-1">
          {bearOBs.length ? bearOBs.map((ob, i) => <OBRow key={i} ob={ob} bull={false} />)
            : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>No active bearish OBs</span>}
        </div>
      </div>
    </div>
  )
}

function FVGPanel({ data }: { data: SMCData }) {
  const bullFVG = data.fvg.bullish.slice(-4).reverse()
  const bearFVG = data.fvg.bearish.slice(-4).reverse()
  const bullIFVG = data.fvg.bull_ifvg.slice(-2)
  const bearIFVG = data.fvg.bear_ifvg.slice(-2)

  const FVGRow = ({ fvg, bull }: { fvg: FVGEntry; bull: boolean }) => {
    const clr = bull ? 'var(--bull)' : 'var(--bear)'
    return (
      <div
        className="flex items-center gap-2 rounded-sm px-2 py-1.5"
        style={{ background: `${bull ? '#00C087' : '#FF4D6D'}08`, borderLeft: `2px solid ${clr}` }}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 mb-0.5">
            <span className="price-mono text-[10px] font-bold" style={{ color: 'var(--text)' }}>{fmtPrice(fvg.low)}</span>
            <span className="text-[9px]" style={{ color: clr }}>→</span>
            <span className="price-mono text-[10px]" style={{ color: 'var(--text)' }}>{fmtPrice(fvg.high)}</span>
          </div>
          <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>Gap: {fvg.gap_pct.toFixed(3)}%</span>
        </div>
        <Tag
          label={fvg.filled ? 'FILLED' : 'OPEN'}
          color={fvg.filled ? 'var(--muted)' : clr}
          bg={fvg.filled ? 'var(--active)' : `${clr}18`}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--bull)' }}>Bullish FVG</span>
            <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>({bullFVG.length})</span>
          </div>
          <div className="flex flex-col gap-1">
            {bullFVG.length ? bullFVG.map((f, i) => <FVGRow key={i} fvg={f} bull />)
              : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>None detected</span>}
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--bear)' }}>Bearish FVG</span>
            <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>({bearFVG.length})</span>
          </div>
          <div className="flex flex-col gap-1">
            {bearFVG.length ? bearFVG.map((f, i) => <FVGRow key={i} fvg={f} bull={false} />)
              : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>None detected</span>}
          </div>
        </div>
      </div>

      {(bullIFVG.length > 0 || bearIFVG.length > 0) && (
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: PURPLE }}>
              Inverse FVG (Role Flipped)
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {[...bullIFVG.map(f => ({ f, bull: true })), ...bearIFVG.map(f => ({ f, bull: false }))].map(({ f, bull }, i) => (
              <FVGRow key={i} fvg={f} bull={bull} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MarketStructurePanel({ data }: { data: SMCData }) {
  const ms = data.market_structure
  const ia = data.institutional

  return (
    <div className="flex flex-col gap-2">
      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {[
          { label: 'Trend',     val: ms.trend.toUpperCase(),          color: ms.trend === 'bullish' ? 'var(--bull)' : 'var(--bear)' },
          { label: 'Zone',      val: ms.zone,                          color: ms.zone === 'Discount' ? CYAN : '#F59E0B' },
          { label: 'EQ Pos',    val: `${ms.eq_pct > 0 ? '+' : ''}${ms.eq_pct.toFixed(1)}%`, color: ms.eq_pct > 0 ? 'var(--bull)' : 'var(--bear)' },
          { label: 'Session',   val: ia.session,                       color: 'var(--text-sub)' },
          { label: 'Momentum',  val: ia.momentum_lbl,                  color: ia.momentum > 0 ? 'var(--bull)' : 'var(--bear)' },
          { label: 'Volatility',val: `${ia.volatility.toFixed(2)}%`,   color: ia.volatility > 2 ? '#F59E0B' : 'var(--muted)' },
        ].map(({ label, val, color }) => (
          <div key={label} className="rounded-sm px-2 py-1.5 text-center" style={{ background: 'var(--panel2)', border: '1px solid var(--border)' }}>
            <div className="text-[9px] uppercase tracking-wider mb-0.5" style={{ color: 'var(--muted)' }}>{label}</div>
            <div className="price-mono text-[10px] font-bold" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>

      {/* BOS + CHoCH events */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>BOS Events</div>
          <div className="flex flex-col gap-0.5">
            {ms.bos.length ? ms.bos.map((b, i) => (
              <div key={i} className="flex items-center gap-2 rounded-sm px-2 py-1" style={{ background: 'var(--active)' }}>
                <Tag label={b.direction.toUpperCase()} color={b.direction === 'bullish' ? 'var(--bull)' : 'var(--bear)'} bg={b.direction === 'bullish' ? '#00C08718' : '#FF4D6D18'} />
                <span className="price-mono text-[10px]" style={{ color: 'var(--text)' }}>{fmtPrice(b.level)}</span>
              </div>
            )) : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>No BOS detected</span>}
          </div>
        </div>
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>CHoCH Events</div>
          <div className="flex flex-col gap-0.5">
            {ms.choch.length ? ms.choch.map((c, i) => (
              <div key={i} className="flex items-center gap-2 rounded-sm px-2 py-1" style={{ background: 'var(--active)' }}>
                <Tag label={c.direction.toUpperCase()} color={c.direction === 'bullish' ? CYAN : '#F43F5E'} bg={`${CYAN}18`} />
                <span className="price-mono text-[10px]" style={{ color: 'var(--text)' }}>{fmtPrice(c.level)}</span>
              </div>
            )) : <span className="text-[10px]" style={{ color: 'var(--muted)' }}>No CHoCH detected</span>}
          </div>
        </div>
      </div>

      {/* Liquidity pools */}
      {ms.liquidity.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>Liquidity Pools</div>
          <div className="flex flex-wrap gap-1">
            {ms.liquidity.map((lp, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 rounded-sm px-2 py-1"
                style={{ background: lp.type === 'EQH' ? '#FF4D6D12' : '#00C08712', border: `1px solid ${lp.type === 'EQH' ? '#FF4D6D' : '#00C087'}33` }}
              >
                <span className="text-[9px] font-bold uppercase" style={{ color: lp.type === 'EQH' ? 'var(--bear)' : 'var(--bull)' }}>
                  {lp.type}
                </span>
                <span className="price-mono text-[10px] font-bold" style={{ color: 'var(--text)' }}>
                  {fmtPrice(lp.price)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function TradeSetupPanel({ data }: { data: SMCData }) {
  const ia = data.institutional
  const bullConf = Math.max(ia.bull_prob, 30)
  const bearConf = Math.max(ia.bear_prob, 30)

  const LevelRow = ({ label, val, color }: { label: string; val: number; color: string }) => (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-[10px] font-medium" style={{ color: 'var(--text-sub)' }}>{label}</span>
      <span className="price-mono text-[10px] font-bold" style={{ color }}>{fmtPrice(val)}</span>
    </div>
  )

  const SignalChip = ({ label }: { label: string }) => (
    <span
      className="rounded-sm px-1.5 py-0.5 text-[9px] font-semibold"
      style={{ background: `${CYAN}18`, color: CYAN, border: `1px solid ${CYAN}33` }}
    >
      {label}
    </span>
  )

  return (
    <div className="grid grid-cols-2 gap-2">
      {/* LONG */}
      <div
        className="flex flex-col gap-1.5 rounded-sm p-2.5"
        style={{ background: '#00C08708', border: '1px solid var(--border)', borderTop: '2px solid var(--bull)' }}
      >
        <div className="flex items-center justify-between">
          <Tag label="LONG" color="var(--bull)" bg="#00C08722" />
          <span className="price-mono text-[9px] font-bold" style={{ color: '#F59E0B', background: '#F59E0B18', padding: '1px 6px', borderRadius: 3 }}>
            RR {ia.rr_bull > 0 ? `1:${ia.rr_bull}` : '—'}
          </span>
        </div>
        <ConfidenceBar pct={bullConf} color="var(--bull)" />
        <div className="border-t pt-1.5" style={{ borderColor: 'var(--border)' }}>
          <LevelRow label="Entry"  val={ia.entry_bull} color="#F59E0B" />
          <LevelRow label="Stop"   val={ia.sl_bull}    color="var(--bear)" />
          <LevelRow label="TP 1"   val={ia.tp1_bull}   color="var(--bull)" />
          <LevelRow label="TP 2"   val={ia.tp2_bull}   color={CYAN} />
        </div>
        <div className="flex flex-wrap gap-0.5 pt-0.5 border-t" style={{ borderColor: 'var(--border)' }}>
          {ia.bias.includes('Bull') && <SignalChip label="Bias Aligned" />}
          {ia.momentum > 0 && <SignalChip label="Momentum ↑" />}
          {ia.position === 'Discount' && <SignalChip label="Discount Zone" />}
          {data.market_structure.bos.some(b => b.direction === 'bullish') && <SignalChip label="BOS ↑" />}
        </div>
      </div>

      {/* SHORT */}
      <div
        className="flex flex-col gap-1.5 rounded-sm p-2.5"
        style={{ background: '#FF4D6D08', border: '1px solid var(--border)', borderTop: '2px solid var(--bear)' }}
      >
        <div className="flex items-center justify-between">
          <Tag label="SHORT" color="var(--bear)" bg="#FF4D6D22" />
          <span className="price-mono text-[9px] font-bold" style={{ color: '#F59E0B', background: '#F59E0B18', padding: '1px 6px', borderRadius: 3 }}>
            RR {ia.rr_bear > 0 ? `1:${ia.rr_bear}` : '—'}
          </span>
        </div>
        <ConfidenceBar pct={bearConf} color="var(--bear)" />
        <div className="border-t pt-1.5" style={{ borderColor: 'var(--border)' }}>
          <LevelRow label="Entry"  val={ia.entry_bear} color="#F59E0B" />
          <LevelRow label="Stop"   val={ia.sl_bear}    color="var(--bull)" />
          <LevelRow label="TP 1"   val={ia.tp1_bear}   color="var(--bear)" />
          <LevelRow label="TP 2"   val={ia.tp2_bear}   color="#F43F5E" />
        </div>
        <div className="flex flex-wrap gap-0.5 pt-0.5 border-t" style={{ borderColor: 'var(--border)' }}>
          {ia.bias.includes('Bear') && <SignalChip label="Bias Aligned" />}
          {ia.momentum < 0 && <SignalChip label="Momentum ↓" />}
          {ia.position === 'Premium' && <SignalChip label="Premium Zone" />}
          {data.market_structure.bos.some(b => b.direction === 'bearish') && <SignalChip label="BOS ↓" />}
        </div>
      </div>
    </div>
  )
}

function SignalMatrixPanel({ data }: { data: SMCData }) {
  const ia  = data.institutional
  const ms  = data.market_structure
  const ob  = data.order_blocks
  const fvg = data.fvg

  const isBull = ia.bull_prob > 50

  const rows: { signal: string; long: boolean; short: boolean; weight: 'High' | 'Med' | 'Low' }[] = [
    { signal: 'BOS Aligned',      long: ms.bos.some(b => b.direction === 'bullish'), short: ms.bos.some(b => b.direction === 'bearish'), weight: 'High' },
    { signal: 'EMA / Trend',      long: ia.bias.includes('Bull'), short: ia.bias.includes('Bear'), weight: 'High' },
    { signal: 'Order Block',      long: ob.active_bullish.length > 0, short: ob.active_bearish.length > 0, weight: 'High' },
    { signal: 'FVG Present',      long: fvg.bullish.length > 0, short: fvg.bearish.length > 0, weight: 'Med' },
    { signal: 'CHoCH',            long: ms.choch.some(c => c.direction === 'bullish'), short: ms.choch.some(c => c.direction === 'bearish'), weight: 'Med' },
    { signal: 'Liq Pool Above',   long: false, short: ms.liquidity.some(l => l.type === 'EQH'), weight: 'Med' },
    { signal: 'Liq Pool Below',   long: ms.liquidity.some(l => l.type === 'EQL'), short: false, weight: 'Med' },
    { signal: 'RSI Signal',       long: ia.rsi < 50, short: ia.rsi > 60, weight: 'Med' },
    { signal: 'Momentum',         long: ia.momentum > 1, short: ia.momentum < -1, weight: 'Low' },
    { signal: 'Inverse FVG',      long: fvg.bull_ifvg.length > 0, short: fvg.bear_ifvg.length > 0, weight: 'Low' },
    { signal: 'Discount Zone',    long: ms.zone === 'Discount', short: false, weight: 'Low' },
    { signal: 'Premium Zone',     long: false, short: ms.zone === 'Premium', weight: 'Low' },
  ]

  const WEIGHT_COLOR: Record<string, string> = { High: '#F59E0B', Med: CYAN, Low: 'var(--text-sub)' }

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-[10px]">
        <thead>
          <tr style={{ background: 'var(--panel2)', borderBottom: '1px solid var(--border)' }}>
            {['Signal', 'Long', 'Short', 'Weight'].map(h => (
              <th key={h} className="px-2 py-1.5 text-left font-bold uppercase tracking-wider" style={{ color: 'var(--muted)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.signal}
              style={{
                background: i % 2 === 0 ? 'transparent' : 'var(--active)',
                borderBottom: '1px solid var(--border)',
              }}
            >
              <td className="px-2 py-1.5 font-medium" style={{ color: 'var(--text-sub)' }}>{row.signal}</td>
              <td className="px-2 py-1.5 text-center">
                {row.long
                  ? <span style={{ color: 'var(--bull)' }}>✓</span>
                  : <span style={{ color: 'var(--border2, #333)' }}>—</span>}
              </td>
              <td className="px-2 py-1.5 text-center">
                {row.short
                  ? <span style={{ color: 'var(--bear)' }}>✓</span>
                  : <span style={{ color: 'var(--border2, #333)' }}>—</span>}
              </td>
              <td className="px-2 py-1.5">
                <span className="font-bold" style={{ color: WEIGHT_COLOR[row.weight] }}>{row.weight}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AICommentaryPanel({ data }: { data: SMCData }) {
  const ia = data.institutional
  const ms = data.market_structure

  const buySwept  = ms.liquidity.some(l => l.type === 'EQH')
  const sellSwept = ms.liquidity.some(l => l.type === 'EQL')
  const posLabel  = ia.position === 'Premium' ? 'above equilibrium (premium zone)' : 'below equilibrium (discount zone)'
  const trendTxt  = ms.trend === 'bullish' ? 'bullish' : 'bearish'

  const blocks: { label: string; text: string; color: string }[] = [
    {
      label: 'Market Bias',
      color: biasColor(ia.bias),
      text: `Institutional bias is ${ia.bias.toLowerCase()}. Price is trading ${posLabel} with a ${trendTxt} structure. Bull probability: ${ia.bull_prob}% vs Bear: ${ia.bear_prob}%.`,
    },
    {
      label: 'Liquidity Analysis',
      color: CYAN,
      text: buySwept
        ? `Buy-side liquidity (Equal Highs) detected at ${fmtPrice(ms.liquidity.find(l => l.type === 'EQH')!.price)}. Institutional players may target this zone for a sweep before reversing. Watch for stop-hunt wicks.`
        : sellSwept
        ? `Sell-side liquidity (Equal Lows) detected at ${fmtPrice(ms.liquidity.find(l => l.type === 'EQL')!.price)}. Smart money may hunt these stops before accumulating longs.`
        : 'No significant liquidity pools detected in recent swing structure. Market may be in a clean trend phase without pending liquidity targets.',
    },
    {
      label: 'Smart Money Flow',
      color: PURPLE,
      text: `${ia.rvol > 1.3 ? 'Above-average relative volume (RVOL ' + ia.rvol + 'x) suggests active institutional participation.' : 'Moderate relative volume (RVOL ' + ia.rvol + 'x) — institutional activity neutral.'} ADX trend strength at ${ia.trend_str.toFixed(0)} (${ia.trend_str > 25 ? 'trending' : 'ranging'}) — ${ia.trend_str > 25 ? 'directional strategies favored' : 'mean-reversion setups may outperform'}.`,
    },
    {
      label: 'Session Context',
      color: '#F59E0B',
      text: `Active session: ${ia.session}. ${ia.liq_dir} expected. Current equilibrium at ${fmtPrice(ia.equilibrium)} — price is ${ia.position.toLowerCase()} (${ms.eq_pct > 0 ? '+' : ''}${ms.eq_pct.toFixed(1)}% from EQ).`,
    },
    {
      label: 'Entry Rationale',
      color: 'var(--text-sub)',
      text: ms.bos.length > 0
        ? `Break of Structure confirmed at ${fmtPrice(ms.bos[0].level)} (${ms.bos[0].direction}). ${data.order_blocks.active_bullish.length > 0 || data.order_blocks.active_bearish.length > 0 ? `Unmitigated order blocks present near price — watch for reaction at these institutional demand/supply zones.` : ''}`
        : 'No BOS confirmed yet. Wait for structure break before entering directional trade. Current consolidation may resolve with a liquidity sweep first.',
    },
  ]

  return (
    <div className="flex flex-col gap-2">
      {blocks.map((b) => (
        <div
          key={b.label}
          className="rounded-sm p-2.5"
          style={{ background: 'var(--panel2)', borderLeft: `2px solid ${b.color}`, border: '1px solid var(--border)' }}
        >
          <div className="mb-1 text-[10px] font-black uppercase tracking-widest" style={{ color: b.color }}>
            {b.label}
          </div>
          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-sub)' }}>{b.text}</p>
        </div>
      ))}
    </div>
  )
}

function VolumeProfilePanel({ data }: { data: SMCData }) {
  const ia = data.institutional
  const ms = data.market_structure
  const range = ia.range_high - ia.range_low
  if (range <= 0) return <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Insufficient data</span>

  const poc = ia.equilibrium
  const nBars = 14
  const step  = range / nBars

  const bars = Array.from({ length: nBars }, (_, i) => {
    const low  = ia.range_low + i * step
    const high = low + step
    const mid  = (low + high) / 2
    const distFromEq = Math.abs(mid - poc) / range

    // Simulate volume profile: highest near POC, tapering at extremes
    const base = Math.exp(-distFromEq * 4) * 100
    const vol  = Math.round(base + Math.random() * 15)
    const isPOC = Math.abs(mid - poc) < step * 0.6
    const isHVN = vol > 70 && !isPOC
    const isLVN = vol < 30
    return { low, high, mid, vol, isPOC, isHVN, isLVN }
  }).reverse()

  const maxVol = Math.max(...bars.map(b => b.vol))

  return (
    <div className="flex gap-3">
      {/* Bars */}
      <div className="flex-1">
        <div className="mb-1.5 flex items-center gap-3">
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>Volume Profile (50-bar range)</span>
          <span className="price-mono text-[9px]" style={{ color: 'var(--muted)' }}>{fmtPrice(ia.range_low)} — {fmtPrice(ia.range_high)}</span>
        </div>
        <div className="flex flex-col gap-px">
          {bars.map((b, i) => {
            const w = (b.vol / maxVol) * 100
            const color = b.isPOC ? '#F59E0B' : b.isHVN ? CYAN : b.isLVN ? PURPLE : 'var(--text-sub)'
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="price-mono text-[8px] w-12 text-right flex-shrink-0" style={{ color: 'var(--muted)' }}>
                  {fmtPrice(b.mid)}
                </span>
                <div className="flex-1 relative h-3 rounded-sm overflow-hidden" style={{ background: 'var(--active)' }}>
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${w}%` }}
                    transition={{ duration: 0.4, delay: i * 0.02 }}
                    className="absolute left-0 top-0 h-full rounded-sm"
                    style={{
                      background: b.isPOC
                        ? 'linear-gradient(90deg, #F59E0B, #F59E0Bcc)'
                        : b.isHVN
                        ? `linear-gradient(90deg, ${CYAN}cc, ${CYAN}88)`
                        : b.isLVN
                        ? `${PURPLE}66`
                        : 'var(--border2)',
                      boxShadow: b.isPOC ? `0 0 6px #F59E0B44` : 'none',
                    }}
                  />
                </div>
                {b.isPOC && <span className="text-[9px] font-black flex-shrink-0" style={{ color: '#F59E0B' }}>POC</span>}
                {b.isHVN && !b.isPOC && <span className="text-[9px] font-bold flex-shrink-0" style={{ color: CYAN }}>HVN</span>}
                {b.isLVN && <span className="text-[9px] font-bold flex-shrink-0" style={{ color: PURPLE }}>LVN</span>}
              </div>
            )
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex-shrink-0 flex flex-col gap-2 w-28">
        <div className="rounded-sm p-2" style={{ background: 'var(--panel2)', border: '1px solid var(--border)' }}>
          <div className="text-[9px] font-bold uppercase tracking-wider mb-1.5" style={{ color: 'var(--muted)' }}>Legend</div>
          {[
            { color: '#F59E0B', label: 'POC (Point of Control)' },
            { color: CYAN,     label: 'HVN (High Volume Node)' },
            { color: PURPLE,   label: 'LVN (Low Volume Node)' },
          ].map(({ color, label }) => (
            <div key={label} className="flex items-center gap-1.5 mb-1">
              <div className="h-2 w-2 rounded-sm flex-shrink-0" style={{ background: color }} />
              <span className="text-[9px]" style={{ color: 'var(--text-sub)' }}>{label}</span>
            </div>
          ))}
        </div>
        <div className="rounded-sm p-2" style={{ background: 'var(--panel2)', border: '1px solid var(--border)' }}>
          <div className="text-[9px] font-bold uppercase tracking-wider mb-1" style={{ color: 'var(--muted)' }}>Key Levels</div>
          {[
            { label: 'Range H', val: ia.range_high, color: 'var(--bear)' },
            { label: 'EQ',      val: ia.equilibrium, color: '#F59E0B' },
            { label: 'Range L', val: ia.range_low, color: 'var(--bull)' },
          ].map(({ label, val, color }) => (
            <div key={label} className="flex justify-between items-center py-0.5">
              <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{label}</span>
              <span className="price-mono text-[9px] font-bold" style={{ color }}>{fmtPrice(val)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

const TABS = ['Order Blocks', 'FVG', 'Market Structure', 'Trade Setup', 'Signal Matrix', 'AI Commentary', 'Volume Profile'] as const
type Tab = (typeof TABS)[number]

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <motion.div
          key={i}
          animate={{ opacity: [0.25, 0.5, 0.25] }}
          transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.12 }}
          className="h-6 rounded-sm"
          style={{ background: 'var(--active)', width: `${85 - i * 8}%` }}
        />
      ))}
    </div>
  )
}

export default function InstitutionalPanel({ symbol }: { symbol: string | null }) {
  const [activeTab, setActiveTab] = useState<Tab>('Order Blocks')
  const { data, loading, error } = useSMCData(symbol)

  if (!symbol) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="text-xs" style={{ color: 'var(--muted)' }}>Select a symbol to load institutional analysis</span>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header: bias overview + symbol */}
      <div
        className="flex flex-shrink-0 items-center gap-3 border-b px-3 py-1.5"
        style={{ background: 'var(--panel2)', borderColor: 'var(--border)' }}
      >
        <span className="price-mono text-xs font-black" style={{ color: 'var(--text)' }}>
          {symbol.replace('.NS', '').replace('.BO', '').replace('^', '')}
        </span>
        {data && !data.error && (
          <>
            <span className="price-mono text-xs font-bold" style={{ color: 'var(--text)' }}>
              {fmtPrice(data.current_price)}
            </span>
            <span
              className="price-mono text-[11px] font-semibold"
              style={{ color: data.change_pct >= 0 ? 'var(--bull)' : 'var(--bear)' }}
            >
              {data.change_pct >= 0 ? '▲' : '▼'} {Math.abs(data.change_pct).toFixed(2)}%
            </span>
            <div className="flex-1" />
            {/* Bias badge */}
            <span
              className="rounded-sm px-2 py-0.5 text-[10px] font-black uppercase tracking-wide"
              style={{
                color: biasColor(data.institutional.bias),
                background: `${biasColor(data.institutional.bias)}18`,
                border: `1px solid ${biasColor(data.institutional.bias)}44`,
              }}
            >
              {data.institutional.bias}
            </span>
            {/* Bull/Bear probability bar */}
            <div className="flex items-center gap-1.5">
              <span className="price-mono text-[10px] font-bold" style={{ color: 'var(--bull)' }}>
                {data.institutional.bull_prob}%
              </span>
              <div className="flex h-2 w-20 overflow-hidden rounded-full" style={{ background: 'var(--active)' }}>
                <div
                  className="h-full"
                  style={{ width: `${data.institutional.bull_prob}%`, background: 'var(--bull)', transition: 'width 0.5s' }}
                />
                <div
                  className="h-full"
                  style={{ width: `${data.institutional.bear_prob}%`, background: 'var(--bear)', transition: 'width 0.5s' }}
                />
              </div>
              <span className="price-mono text-[10px] font-bold" style={{ color: 'var(--bear)' }}>
                {data.institutional.bear_prob}%
              </span>
            </div>
          </>
        )}
        {loading && <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Loading SMC data…</span>}
        {error && !data && (
          <span className="text-[10px]" style={{ color: 'var(--bear)' }}>Backend offline — start backend server</span>
        )}
      </div>

      {/* Tab strip */}
      <div
        className="flex flex-shrink-0 items-center gap-0.5 overflow-x-auto border-b px-1.5"
        style={{ background: 'var(--panel2)', borderColor: 'var(--border)', minHeight: 30 }}
      >
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className="h-6 whitespace-nowrap rounded-sm px-2 text-[10px] font-semibold transition-colors"
            style={{
              color: activeTab === tab ? 'var(--text)' : 'var(--text-sub)',
              background: activeTab === tab ? 'var(--active)' : 'transparent',
              borderBottom: activeTab === tab ? `1px solid ${CYAN}` : '1px solid transparent',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-3">
        {loading && !data ? (
          <LoadingSkeleton />
        ) : error && !data ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-sub)' }}>SMC data unavailable</div>
              <div className="text-[10px]" style={{ color: 'var(--muted)' }}>Start the FastAPI backend: uvicorn backend.main:app</div>
            </div>
          </div>
        ) : data && !data.error ? (
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.15 }}
            >
              {activeTab === 'Order Blocks'      && <OrderBlocksPanel data={data} />}
              {activeTab === 'FVG'               && <FVGPanel data={data} />}
              {activeTab === 'Market Structure'  && <MarketStructurePanel data={data} />}
              {activeTab === 'Trade Setup'       && <TradeSetupPanel data={data} />}
              {activeTab === 'Signal Matrix'     && <SignalMatrixPanel data={data} />}
              {activeTab === 'AI Commentary'     && <AICommentaryPanel data={data} />}
              {activeTab === 'Volume Profile'    && <VolumeProfilePanel data={data} />}
            </motion.div>
          </AnimatePresence>
        ) : (
          <div className="flex h-full items-center justify-center">
            <span className="text-[10px]" style={{ color: 'var(--muted)' }}>No data available</span>
          </div>
        )}
      </div>
    </div>
  )
}
