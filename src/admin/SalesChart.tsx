import { useState } from 'react'
import { money } from '../api'

type Day = { day: string; tickets: number; revenue_cents: number }

const H = 160 // plot height
const BAR = 20 // max bar width (thin marks)
const GAP = 2 // surface gap between touching bars

const label = (day: string) =>
  new Date(`${day}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })

// Tickets sold per day: one series, so no legend; the title names it.
// Only the best day is labelled; every bar has a hover tooltip.
export default function SalesChart({ days }: { days: Day[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (days.length === 0) return <p className="dash-empty">No sales yet.</p>

  const max = Math.max(...days.map((d) => d.tickets))
  const best = days.findIndex((d) => d.tickets === max)
  const slot = Math.max(BAR + GAP, Math.min(48, 640 / days.length))
  const barW = Math.min(BAR, slot - GAP)
  const width = slot * days.length

  return (
    <figure className="sales-chart">
      <figcaption>Tickets sold per day</figcaption>
      <div className="sales-scroll">
        <svg width={width} height={H + 28} role="img" aria-label="Tickets sold per day">
          {/* recessive baseline */}
          <line x1={0} x2={width} y1={H} y2={H} className="sales-axis" />
          {days.map((d, i) => {
            const h = max ? Math.max(2, (d.tickets / max) * (H - 18)) : 0
            const x = i * slot + (slot - barW) / 2
            const y = H - h
            const r = Math.min(4, barW / 2, h)
            // 4px rounded top, square at the baseline
            const path = `M${x},${H} V${y + r} Q${x},${y} ${x + r},${y} H${x + barW - r} Q${x + barW},${y} ${x + barW},${y + r} V${H} Z`
            return (
              <g
                key={d.day}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onClick={() => setHover(hover === i ? null : i)}
              >
                {/* hit target bigger than the mark */}
                <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
                <path d={path} className={`sales-bar ${hover === i ? 'on' : ''}`} />
                {i === best && hover === null && (
                  <text x={x + barW / 2} y={y - 6} textAnchor="middle" className="sales-label">
                    {d.tickets}
                  </text>
                )}
                {(i === 0 || i === days.length - 1 || i === best) && (
                  <text x={x + barW / 2} y={H + 18} textAnchor="middle" className="sales-tick">
                    {label(d.day)}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
        {hover !== null && (
          <div className="sales-tip" style={{ left: hover * slot + slot / 2 }}>
            <strong>{label(days[hover].day)}</strong>
            <span>
              {days[hover].tickets} {days[hover].tickets === 1 ? 'ticket' : 'tickets'} · {money(days[hover].revenue_cents)}
            </span>
          </div>
        )}
      </div>
    </figure>
  )
}
