import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  api,
  API_URL,
  formatWhen,
  money,
  timeOnly,
  type AdminEvent,
  type AdminEventListItem,
  type AdminTier,
  type Attendee,
} from '../api'
import SalesChart from './SalesChart'
import './Dashboard.css'

type Tab = 'overview' | 'attendees' | 'settings'

export default function Dashboard() {
  const [events, setEvents] = useState<AdminEventListItem[] | null>(null)
  const [slug, setSlug] = useState('')
  const [event, setEvent] = useState<AdminEvent | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [creating, setCreating] = useState(false)

  const loadList = useCallback(
    (select?: string) =>
      api<AdminEventListItem[]>('/admin/events').then((list) => {
        setEvents(list)
        // Default: the next upcoming event, else the most recent
        const upcoming = [...list].reverse().find((e) => new Date(e.starts_at) > new Date())
        setSlug((s) => select ?? (s || upcoming?.slug || list[0]?.slug || ''))
      }),
    [],
  )

  const loadEvent = useCallback(() => {
    if (slug) api<AdminEvent>(`/admin/events/${slug}`).then(setEvent)
  }, [slug])

  useEffect(() => {
    loadList()
  }, [loadList])
  useEffect(() => {
    loadEvent()
  }, [loadEvent])

  if (events === null) return <p className="dash-empty">Loading…</p>

  if (creating || events.length === 0) {
    return (
      <NewEvent
        onCancel={events.length ? () => setCreating(false) : undefined}
        onCreated={(s) => {
          setCreating(false)
          setTab('settings')
          loadList(s)
        }}
      />
    )
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <select value={slug} onChange={(e) => setSlug(e.target.value)} aria-label="Event">
          {events.map((e) => (
            <option key={e.slug} value={e.slug}>
              {e.name} · {new Date(e.starts_at).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' })}
            </option>
          ))}
        </select>
        <button className="dash-ghost" onClick={() => setCreating(true)}>
          + new event
        </button>
        <Link to="/admin/scan" className="dash-ghost">
          scanner
        </Link>
      </div>

      <nav className="dash-tabs">
        {(['overview', 'attendees', 'settings'] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      {!event ? (
        <p className="dash-empty">Loading…</p>
      ) : tab === 'overview' ? (
        <Overview event={event} />
      ) : tab === 'attendees' ? (
        <Attendees event={event} onChange={loadEvent} />
      ) : (
        <Settings
          event={event}
          onSaved={(e) => {
            setEvent(e)
            loadList()
          }}
        />
      )}
    </div>
  )
}

// ---------- overview ----------

function Overview({ event }: { event: AdminEvent }) {
  const pct = event.capacity ? Math.round((event.tickets_sold / event.capacity) * 100) : 0
  return (
    <>
      <div className="dash-head">
        <h1>{event.name}</h1>
        <p>
          {formatWhen(event.starts_at)}
          {event.venue ? ` · ${event.venue}` : ''} ·{' '}
          <span className={event.on_sale ? 'pill on' : 'pill'}>{event.on_sale ? 'on sale' : 'not on sale'}</span>
        </p>
      </div>

      <div className="tiles">
        <Tile label="Tickets sold" value={`${event.tickets_sold}`} sub={`of ${event.capacity} · ${pct}%`} />
        <Tile label="Ticket revenue" value={money(event.revenue_cents)} sub="what you keep" />
        <Tile label="Orders" value={`${event.orders}`} sub={event.refunded_orders ? `${event.refunded_orders} refunded` : 'no refunds'} />
        <Tile label="Checked in" value={`${event.checked_in}`} sub={`of ${event.tickets_sold}`} />
      </div>

      <SalesChart days={event.sales_by_day} />

      <table className="dash-table tiers-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th className="num">Price</th>
            <th>Sold</th>
            <th className="num">Held now</th>
            <th className="num">Left</th>
            <th className="num">Revenue</th>
          </tr>
        </thead>
        <tbody>
          {event.tiers.map((t) => {
            const left = Math.max(t.quantity - t.sold - t.held, 0)
            return (
              <tr key={t.id} className={t.active ? '' : 'muted'}>
                <td>
                  {t.name}
                  {!t.active && <span className="dash-note"> hidden</span>}
                </td>
                <td className="num">{money(t.price_cents)}</td>
                <td>
                  <div className="meter" title={`${t.sold} of ${t.quantity}`}>
                    <div style={{ width: `${t.quantity ? (t.sold / t.quantity) * 100 : 0}%` }} />
                  </div>
                  <span className="meter-text">
                    {t.sold} / {t.quantity}
                  </span>
                </td>
                <td className="num">{t.held || '—'}</td>
                <td className="num">{left === 0 ? 'sold out' : left}</td>
                <td className="num">{money(t.revenue_cents)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="dash-note">
        Service fees collected: {money(event.fees_cents)} (these cover Stripe's processing, roughly break-even). "Held now"
        = people on the payment page this moment.
      </p>
    </>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      <div className="tile-sub">{sub}</div>
    </div>
  )
}

// ---------- attendees ----------

type Filter = 'all' | 'in' | 'not_in' | 'void'

function Attendees({ event, onChange }: { event: AdminEvent; onChange: () => void }) {
  const [rows, setRows] = useState<Attendee[] | null>(null)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [tier, setTier] = useState('')

  const load = useCallback(() => {
    api<Attendee[]>(`/admin/events/${event.slug}/attendees`).then(setRows)
  }, [event.slug])
  useEffect(() => {
    load()
  }, [load])

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (rows ?? []).filter((a) => {
      if (tier && a.tier !== tier) return false
      if (filter === 'in' && !(a.status === 'valid' && a.checked_in_at)) return false
      if (filter === 'not_in' && !(a.status === 'valid' && !a.checked_in_at)) return false
      if (filter === 'void' && a.status !== 'void') return false
      if (!needle) return true
      return [a.holder_name, a.buyer_name, a.buyer_email, a.holder_email ?? '', a.code].some((f) =>
        f.toLowerCase().includes(needle),
      )
    })
  }, [rows, q, filter, tier])

  const toggleVoid = async (a: Attendee) => {
    const restoring = a.status === 'void'
    const msg = restoring
      ? `Make ${a.holder_name}'s ticket valid again?`
      : `Void ${a.holder_name}'s ticket? It will be rejected at the door. (This doesn't refund money; do that in Stripe.)`
    if (!window.confirm(msg)) return
    try {
      await api(`/admin/tickets/${a.code}/void${restoring ? '?restore=true' : ''}`, { method: 'POST' })
      load()
      onChange()
    } catch (e) {
      window.alert((e as Error).message)
    }
  }

  if (!rows) return <p className="dash-empty">Loading…</p>

  return (
    <>
      <div className="dash-filters">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email, code" />
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} aria-label="Status">
          <option value="all">All tickets</option>
          <option value="in">Checked in</option>
          <option value="not_in">Not checked in</option>
          <option value="void">Refunded / void</option>
        </select>
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Tier">
          <option value="">All tiers</option>
          {event.tiers.map((t) => (
            <option key={t.id}>{t.name}</option>
          ))}
        </select>
        <a className="dash-ghost" href={`${API_URL}/admin/events/${event.slug}/attendees.csv`}>
          download csv
        </a>
      </div>
      <p className="dash-note">
        {shown.length} of {rows.length} tickets
      </p>

      <div className="dash-scroll">
        <table className="dash-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Tier</th>
              <th>Status</th>
              <th>Bought by</th>
              <th>Code</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.code} className={a.status === 'void' ? 'muted' : ''}>
                <td>
                  {a.holder_name}
                  {a.holder_email && <div className="dash-sub">{a.holder_email}</div>}
                </td>
                <td>{a.tier}</td>
                <td>
                  {a.status === 'void' ? (
                    'void'
                  ) : a.checked_in_at ? (
                    <>
                      in {timeOnly(a.checked_in_at)}
                      {a.checked_in_by && <div className="dash-sub">by {a.checked_in_by}</div>}
                    </>
                  ) : (
                    '—'
                  )}
                </td>
                <td>
                  {a.buyer_name}
                  <div className="dash-sub">{a.buyer_email}</div>
                </td>
                <td className="mono">…{a.code.slice(-4)}</td>
                <td>
                  <button className="dash-link" onClick={() => toggleVoid(a)}>
                    {a.status === 'void' ? 'restore' : 'void'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

// ---------- settings ----------

// <input type="datetime-local"> works in the browser's local time
const toLocalInput = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null)
const dollars = (cents: number) => (cents / 100).toFixed(2)
const toCents = (v: string) => Math.round(parseFloat(v || '0') * 100)

function Settings({ event, onSaved }: { event: AdminEvent; onSaved: (e: AdminEvent) => void }) {
  const [form, setForm] = useState({
    name: event.name,
    venue: event.venue ?? '',
    description: event.description ?? '',
    poster_url: event.poster_url ?? '',
    starts_at: toLocalInput(event.starts_at),
    ends_at: toLocalInput(event.ends_at),
  })
  const [msg, setMsg] = useState('')
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value })

  const save = async (patch: object, done = 'Saved.') => {
    setMsg('')
    try {
      onSaved(await api<AdminEvent>(`/admin/events/${event.slug}`, { method: 'PATCH', body: JSON.stringify(patch) }))
      setMsg(done)
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  return (
    <div className="settings">
      <section className="settings-block">
        <div className="settings-row">
          <h2>Sales</h2>
          <button
            className={`toggle ${event.on_sale ? 'on' : ''}`}
            onClick={() => {
              const next = !event.on_sale
              if (window.confirm(next ? 'Open ticket sales for this event?' : 'Stop ticket sales for this event?'))
                save({ on_sale: next }, next ? 'Sales are open.' : 'Sales are closed.')
            }}
          >
            {event.on_sale ? 'on sale' : 'not on sale'}
          </button>
        </div>
      </section>

      <form
        className="settings-block"
        onSubmit={(e) => {
          e.preventDefault()
          save({
            name: form.name,
            venue: form.venue || null,
            description: form.description || null,
            poster_url: form.poster_url || null,
            starts_at: fromLocalInput(form.starts_at),
            ends_at: fromLocalInput(form.ends_at),
          })
        }}
      >
        <h2>Event</h2>
        <label>
          <span>Name</span>
          <input value={form.name} onChange={set('name')} required />
        </label>
        <div className="settings-pair">
          <label>
            <span>Starts</span>
            <input type="datetime-local" value={form.starts_at} onChange={set('starts_at')} required />
          </label>
          <label>
            <span>Ends (optional)</span>
            <input type="datetime-local" value={form.ends_at} onChange={set('ends_at')} />
          </label>
        </div>
        <label>
          <span>Venue</span>
          <input value={form.venue} onChange={set('venue')} />
        </label>
        <label>
          <span>Poster image URL (optional)</span>
          <input value={form.poster_url} onChange={set('poster_url')} placeholder="https://media.sonsofcaesar.xyz/…" />
        </label>
        <label>
          <span>Description (optional)</span>
          <textarea value={form.description} onChange={set('description')} rows={3} />
        </label>
        <button className="enter settings-save">save event</button>
        {msg && <p className="dash-note">{msg}</p>}
      </form>

      <section className="settings-block">
        <h2>Tiers</h2>
        {event.tiers.map((t) => (
          <TierEditor key={t.id} tier={t} onSaved={onSaved} />
        ))}
        <TierEditor eventSlug={event.slug} onSaved={onSaved} />
      </section>
    </div>
  )
}

function TierEditor({
  tier,
  eventSlug,
  onSaved,
}: {
  tier?: AdminTier
  eventSlug?: string
  onSaved: (e: AdminEvent) => void
}) {
  const blank = { name: '', price: '', quantity: '', max: '4', sales_end: '' }
  const initial = tier
    ? {
        name: tier.name,
        price: dollars(tier.price_cents),
        quantity: String(tier.quantity),
        max: String(tier.max_per_order),
        sales_end: toLocalInput(tier.sales_end),
      }
    : blank
  const [f, setF] = useState(initial)
  const [msg, setMsg] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })
  const dirty = JSON.stringify(f) !== JSON.stringify(initial)

  const submit = async (e: React.FormEvent, extra: object = {}) => {
    e.preventDefault()
    setMsg('')
    const body = {
      name: f.name,
      price_cents: toCents(f.price),
      quantity: Number(f.quantity),
      max_per_order: Number(f.max),
      sales_end: fromLocalInput(f.sales_end),
      ...extra,
    }
    try {
      const updated = tier
        ? await api<AdminEvent>(`/admin/tiers/${tier.id}`, { method: 'PATCH', body: JSON.stringify(body) })
        : await api<AdminEvent>(`/admin/events/${eventSlug}/tiers`, { method: 'POST', body: JSON.stringify(body) })
      onSaved(updated)
      if (!tier) setF(blank)
      setMsg(tier ? 'Saved.' : '')
    } catch (err) {
      setMsg((err as Error).message)
    }
  }

  return (
    <form className={`tier-edit ${tier && !tier.active ? 'muted' : ''}`} onSubmit={submit}>
      <label className="grow">
        <span>{tier ? `Tier · ${tier.sold} sold` : 'New tier'}</span>
        <input value={f.name} onChange={set('name')} placeholder="e.g. Early Bird" required />
      </label>
      <label>
        <span>Price $</span>
        <input value={f.price} onChange={set('price')} inputMode="decimal" required pattern="\d+(\.\d{1,2})?" />
      </label>
      <label>
        <span>Quantity</span>
        <input value={f.quantity} onChange={set('quantity')} inputMode="numeric" required pattern="\d+" />
      </label>
      <label>
        <span>Max / order</span>
        <input value={f.max} onChange={set('max')} inputMode="numeric" required pattern="\d+" />
      </label>
      <label>
        <span>Sales end</span>
        <input type="datetime-local" value={f.sales_end} onChange={set('sales_end')} />
      </label>
      <div className="tier-actions">
        {(dirty || !tier) && <button className="dash-ghost">{tier ? 'save' : 'add tier'}</button>}
        {tier && (
          <button type="button" className="dash-link" onClick={(e) => submit(e, { active: !tier.active })}>
            {tier.active ? 'hide' : 'show'}
          </button>
        )}
      </div>
      {msg && <p className="dash-note tier-msg">{msg}</p>}
    </form>
  )
}

// ---------- new event ----------

function NewEvent({ onCreated, onCancel }: { onCreated: (slug: string) => void; onCancel?: () => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [starts, setStarts] = useState('')
  const [msg, setMsg] = useState('')
  const autoSlug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const s = slugTouched ? slug : autoSlug
    try {
      await api('/admin/events', {
        method: 'POST',
        body: JSON.stringify({ slug: s, name, starts_at: fromLocalInput(starts) }),
      })
      onCreated(s)
    } catch (err) {
      setMsg((err as Error).message === 'Check the form' ? 'Check the link name: lowercase letters, numbers and dashes.' : (err as Error).message)
    }
  }

  return (
    <form className="settings settings-block new-event" onSubmit={submit}>
      <h2>New event</h2>
      <label>
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="VOL III" required />
      </label>
      <label>
        <span>Link name</span>
        <input
          value={slugTouched ? slug : autoSlug}
          onChange={(e) => {
            setSlugTouched(true)
            setSlug(e.target.value)
          }}
          required
        />
      </label>
      <label>
        <span>Starts</span>
        <input type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} required />
      </label>
      <p className="dash-note">You'll add tiers next. It won't be on sale until you switch it on.</p>
      {msg && <p className="dash-note">{msg}</p>}
      <div className="settings-row">
        <button className="enter settings-save">create</button>
        {onCancel && (
          <button type="button" className="dash-link" onClick={onCancel}>
            cancel
          </button>
        )}
      </div>
    </form>
  )
}
