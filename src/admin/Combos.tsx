import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, money, type AdminCombo, type TierChoice } from '../api'
import './Dashboard.css'

// <input type="datetime-local"> works in the browser's local time
const toLocalInput = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null)
const toCents = (v: string) => Math.round(parseFloat(v || '0') * 100)
const MONEY_PATTERN = String.raw`\d+(\.\d{1,2})?`

// Combo passes (e.g. club + house party for $25). Their sales are shown here,
// separately from each event's own numbers.
export default function Combos() {
  const [combos, setCombos] = useState<AdminCombo[] | null>(null)
  const [tiers, setTiers] = useState<TierChoice[]>([])
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => api<AdminCombo[]>('/admin/combos').then(setCombos), [])
  useEffect(() => {
    load()
    api<TierChoice[]>('/admin/combos/tiers').then(setTiers)
  }, [load])

  if (!combos) return <p className="dash-empty">Loading…</p>

  return (
    <div className="dash">
      <div className="dash-top">
        <Link to="/admin" className="dash-ghost">
          ← events
        </Link>
        <h1 className="combos-title">Combos</h1>
        {!creating && (
          <button className="dash-ghost" onClick={() => setCreating(true)}>
            + new combo
          </button>
        )}
      </div>

      {creating && (
        <ComboEditor
          tiers={tiers}
          onSaved={() => {
            setCreating(false)
            load()
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      {combos.length === 0 && !creating && (
        <p className="dash-empty">No combos yet. A combo sells one ticket for several events at one price.</p>
      )}

      {combos.map((c) => (
        <ComboCard key={c.id} combo={c} tiers={tiers} onChange={load} />
      ))}
    </div>
  )
}

function ComboCard({ combo, tiers, onChange }: { combo: AdminCombo; tiers: TierChoice[]; onChange: () => void }) {
  const [editing, setEditing] = useState(false)
  const [msg, setMsg] = useState('')

  const toggleListed = async () => {
    const next = !combo.on_sale
    if (!window.confirm(next ? `Show "${combo.name}" on the tickets page?` : `Hide "${combo.name}"?`)) return
    try {
      await api(`/admin/combos/${combo.slug}`, { method: 'PATCH', body: JSON.stringify({ on_sale: next }) })
      onChange()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  return (
    <section className="settings-block combo-admin">
      <div className="settings-row">
        <div>
          <h2>{combo.name}</h2>
          <p className="dash-note">
            {combo.parts.map((p) => `${p.event_name} · ${p.tier}`).join('  +  ')} · {money(combo.price_cents)} ·
            sonsofcaesar.xyz/tickets/{combo.slug}
          </p>
        </div>
        <button className={`toggle ${combo.on_sale ? 'on' : ''}`} onClick={toggleListed}>
          {combo.on_sale ? 'listed' : 'hidden'}
        </button>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Passes sold</div>
          <div className="tile-value">{combo.sold}</div>
          <div className="tile-sub">
            of {combo.quantity}
            {combo.held ? ` · ${combo.held} in checkout` : ''}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Combo revenue</div>
          <div className="tile-value">{money(combo.revenue_cents)}</div>
          <div className="tile-sub">what you keep</div>
        </div>
        <div className="tile">
          <div className="tile-label">Orders</div>
          <div className="tile-value">{combo.orders}</div>
          <div className="tile-sub">fees {money(combo.fees_cents)}</div>
        </div>
      </div>

      {editing ? (
        <ComboEditor
          combo={combo}
          tiers={tiers}
          onSaved={() => {
            setEditing(false)
            onChange()
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <button className="dash-link" onClick={() => setEditing(true)}>
          edit
        </button>
      )}
      {msg && <p className="dash-note">{msg}</p>}
    </section>
  )
}

function ComboEditor({
  combo,
  tiers,
  onSaved,
  onCancel,
}: {
  combo?: AdminCombo
  tiers: TierChoice[]
  onSaved: () => void
  onCancel: () => void
}) {
  const [f, setF] = useState({
    name: combo?.name ?? '',
    slug: combo?.slug ?? '',
    price: combo ? (combo.price_cents / 100).toFixed(2) : '',
    quantity: combo ? String(combo.quantity) : '',
    max: combo ? String(combo.max_per_order) : '4',
    sales_end: toLocalInput(combo?.sales_end ?? null),
    poster_url: combo?.poster_url ?? '',
    description: combo?.description ?? '',
  })
  const [parts, setParts] = useState<number[]>(combo?.tier_ids ?? [0, 0])
  const [slugTouched, setSlugTouched] = useState(!!combo)
  const [msg, setMsg] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value })
  const autoSlug = f.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  const slug = slugTouched ? f.slug : autoSlug
  const soldAlready = (combo?.sold ?? 0) + (combo?.held ?? 0) > 0

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg('')
    const chosen = parts.filter(Boolean)
    if (chosen.length < 2) return setMsg('Pick a tier from at least two events.')
    const body = {
      slug,
      name: f.name,
      price_cents: toCents(f.price),
      quantity: Number(f.quantity),
      max_per_order: Number(f.max),
      sales_end: fromLocalInput(f.sales_end),
      poster_url: f.poster_url || null,
      description: f.description || null,
      tier_ids: chosen,
    }
    try {
      if (combo) await api(`/admin/combos/${combo.slug}`, { method: 'PATCH', body: JSON.stringify(body) })
      else await api('/admin/combos', { method: 'POST', body: JSON.stringify(body) })
      onSaved()
    } catch (err) {
      setMsg(
        (err as Error).message === 'Check the form'
          ? 'Check the link name: lowercase letters, numbers and dashes.'
          : (err as Error).message,
      )
    }
  }

  return (
    <form className="settings combo-editor" onSubmit={submit}>
      {!combo && <h2>New combo</h2>}
      <div className="settings-pair">
        <label>
          <span>Name</span>
          <input value={f.name} onChange={set('name')} placeholder="Combo pass" required />
        </label>
        <label>
          <span>Link name · /tickets/{slug || '…'}</span>
          <input
            value={slug}
            onChange={(e) => {
              setSlugTouched(true)
              setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') })
            }}
            required
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
          />
        </label>
      </div>

      <div className="combo-parts-edit">
        <span className="dash-note">
          Includes one ticket from each:
          {soldAlready && " (locked: passes are already sold, so the events can't change)"}
        </span>
        {parts.map((id, i) => (
          <select
            key={i}
            value={id}
            disabled={soldAlready}
            onChange={(e) => setParts(parts.map((p, j) => (j === i ? Number(e.target.value) : p)))}
          >
            <option value={0}>Choose a tier…</option>
            {tiers.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        ))}
        {!soldAlready && parts.length < 5 && (
          <button type="button" className="dash-link" onClick={() => setParts([...parts, 0])}>
            + another event
          </button>
        )}
      </div>

      <div className="combo-numbers">
        <label>
          <span>Price $ (everyone)</span>
          <input value={f.price} onChange={set('price')} inputMode="decimal" required pattern={MONEY_PATTERN} />
        </label>
        <label>
          <span>Cap (passes)</span>
          <input value={f.quantity} onChange={set('quantity')} inputMode="numeric" required pattern="\d+" />
        </label>
        <label>
          <span>Max / order</span>
          <input value={f.max} onChange={set('max')} inputMode="numeric" required pattern="\d+" />
        </label>
        <label>
          <span>Sales end (optional)</span>
          <input type="datetime-local" value={f.sales_end} onChange={set('sales_end')} />
        </label>
      </div>
      <label>
        <span>Flyer image URL (optional, else each night's flyer is shown)</span>
        <input value={f.poster_url} onChange={set('poster_url')} placeholder="/images/…" />
      </label>
      <label>
        <span>Description (optional)</span>
        <textarea value={f.description} onChange={set('description')} rows={2} />
      </label>
      <p className="dash-note">
        Each pass uses one ticket from each tier above, so it counts against those tiers' quantities too. New combos
        start hidden.
      </p>
      {msg && <p className="dash-note">{msg}</p>}
      <div className="settings-row">
        <button className="enter settings-save">{combo ? 'save combo' : 'create combo'}</button>
        <button type="button" className="dash-link" onClick={onCancel}>
          cancel
        </button>
      </div>
    </form>
  )
}
