import QrScanner from 'qr-scanner'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, timeOnly, type CheckinResult, type CheckinTicket, type StaffEvent } from '../api'
import './Scanner.css'

const RESULT_MS = 2500 // how long the green screen stays up
const GENDER_RESULT_MS = 4000 // pink/blue stay a bit longer so the bouncer can check the person
const GENDER_WORD = { ladies: 'Ladies', men: 'Men' } as const
const SAME_CODE_COOLDOWN_MS = 4000 // ignore the same QR while it's still in view

type Shown = CheckinResult & { code: string; error?: string }

export default function Scanner() {
  const [events, setEvents] = useState<StaffEvent[] | null>(null)
  const [eventSlug, setEventSlug] = useState(() => localStorage.getItem('soc-scan-event') ?? '')
  const [tab, setTab] = useState<'scan' | 'lookup'>('scan')
  const [shown, setShown] = useState<Shown | null>(null)
  const [stats, setStats] = useState<{ checked_in: number; total: number } | null>(null)

  useEffect(() => {
    api<StaffEvent[]>('/checkin/events').then((list) => {
      setEvents(list)
      // Default to the saved event if it's still listed, else the soonest one
      setEventSlug((saved) => (list.some((e) => e.slug === saved) ? saved : (list[0]?.slug ?? '')))
    })
  }, [])

  useEffect(() => {
    if (eventSlug) {
      try {
        localStorage.setItem('soc-scan-event', eventSlug)
      } catch {
        /* private mode: fine */
      }
    }
  }, [eventSlug])

  const refreshStats = useCallback(() => {
    if (eventSlug) api<{ checked_in: number; total: number }>(`/checkin/stats?event=${eventSlug}`).then(setStats)
  }, [eventSlug])

  // Keep the counter fresh (other doors are scanning too)
  useEffect(() => {
    refreshStats()
    const t = setInterval(refreshStats, 10_000)
    return () => clearInterval(t)
  }, [refreshStats])

  const submit = useCallback(
    async (code: string) => {
      try {
        const r = await api<CheckinResult>('/checkin', {
          method: 'POST',
          body: JSON.stringify({ event_slug: eventSlug, code }),
        })
        setShown({ ...r, code })
        if (navigator.vibrate) navigator.vibrate(r.result === 'ok' ? 80 : [120, 80, 120])
        refreshStats()
      } catch (e) {
        setShown({ result: 'not_found', ticket: null, other_event: null, code, error: (e as Error).message })
      }
    },
    [eventSlug, refreshStats],
  )

  if (events === null) return <p className="scan-msg">Loading…</p>
  if (events.length === 0) return <p className="scan-msg">No upcoming events to scan for.</p>

  return (
    <div className="scanner">
      <div className="scan-top">
        <select value={eventSlug} onChange={(e) => setEventSlug(e.target.value)} aria-label="Event">
          {events.map((e) => (
            <option key={e.slug} value={e.slug}>
              {e.name}
            </option>
          ))}
        </select>
        {stats && (
          <div className="scan-count">
            <strong>{stats.checked_in}</strong> / {stats.total} in
          </div>
        )}
      </div>

      <div className="scan-tabs">
        <button className={tab === 'scan' ? 'on' : ''} onClick={() => setTab('scan')}>
          scan
        </button>
        <button className={tab === 'lookup' ? 'on' : ''} onClick={() => setTab('lookup')}>
          lookup
        </button>
      </div>

      {tab === 'scan' ? (
        <Camera paused={!!shown} onCode={submit} />
      ) : (
        <Lookup eventSlug={eventSlug} onCheckIn={submit} />
      )}

      {shown && <ResultScreen shown={shown} eventSlug={eventSlug} onClose={() => setShown(null)} onUndone={refreshStats} />}
    </div>
  )
}

// ---------- camera ----------

function Camera({ paused, onCode }: { paused: boolean; onCode: (code: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const scannerRef = useRef<QrScanner | null>(null)
  const last = useRef<{ code: string; at: number }>({ code: '', at: 0 })
  const pausedRef = useRef(paused)
  const onCodeRef = useRef(onCode)
  const [error, setError] = useState('')

  pausedRef.current = paused
  onCodeRef.current = onCode

  useEffect(() => {
    const video = videoRef.current!
    const scanner = new QrScanner(
      video,
      ({ data }) => {
        const now = Date.now()
        if (pausedRef.current) return
        if (data === last.current.code && now - last.current.at < SAME_CODE_COOLDOWN_MS) return
        last.current = { code: data, at: now }
        onCodeRef.current(data)
      },
      { preferredCamera: 'environment', highlightScanRegion: true, highlightCodeOutline: true, maxScansPerSecond: 8 },
    )
    scannerRef.current = scanner
    scanner.start().catch(() =>
      setError('Camera blocked. Allow camera access for this site (and use https), or use Lookup.'),
    )
    return () => {
      scanner.stop()
      scanner.destroy()
    }
  }, [])

  return (
    <div className="camera">
      <video ref={videoRef} muted playsInline />
      {error && <p className="scan-msg camera-error">{error}</p>}
    </div>
  )
}

// ---------- result overlay ----------

function ResultScreen({
  shown,
  eventSlug,
  onClose,
  onUndone,
}: {
  shown: Shown
  eventSlug: string
  onClose: () => void
  onUndone: () => void
}) {
  const [undoMsg, setUndoMsg] = useState('')
  const t = shown.ticket

  // Green screens close themselves so the line keeps moving; red ones wait for a tap
  useEffect(() => {
    if (shown.result !== 'ok') return
    const timer = setTimeout(onClose, shown.ticket?.gender ? GENDER_RESULT_MS : RESULT_MS)
    return () => clearTimeout(timer)
  }, [shown, onClose])

  const undo = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api('/checkin/undo', { method: 'POST', body: JSON.stringify({ event_slug: eventSlug, code: shown.code }) })
      onUndone()
      onClose()
    } catch (err) {
      setUndoMsg((err as Error).message)
    }
  }

  const ok = shown.result === 'ok'
  const gender = ok ? t?.gender : null
  // Pink = ladies, blue = men, green = no gender on that tier, red = denied.
  // The word is always shown too: colours are hard to tell apart in the dark.
  const colour = !ok ? 'bad' : gender === 'ladies' ? 'ladies' : gender === 'men' ? 'men' : 'good'
  const title = {
    ok: 'Let them in',
    already: 'Already checked in',
    void: 'Refunded ticket',
    wrong_event: 'Wrong event',
    not_found: 'Not a valid ticket',
  }[shown.result]

  let detail = ''
  if (shown.result === 'already' && t?.checked_in_at) {
    detail = `at ${timeOnly(t.checked_in_at)}${t.checked_in_by ? ` by ${t.checked_in_by}` : ''}`
  } else if (shown.result === 'wrong_event') {
    detail = `This ticket is for ${shown.other_event}`
  } else if (shown.result === 'void') {
    detail = 'This ticket was refunded and is no longer valid'
  } else if (shown.result === 'not_found') {
    detail = shown.error ?? 'This QR isn’t one of our tickets'
  }

  return (
    <div className={`result ${colour}`} onClick={onClose} role="alert">
      <div className="result-icon" aria-hidden="true">
        {ok ? '✓' : '✕'}
      </div>
      {gender && <div className="result-gender">{GENDER_WORD[gender]}</div>}
      <div className="result-title">{title}</div>
      {t && <div className="result-name">{t.holder_name}</div>}
      {t && <div className="result-tier">{t.tier}</div>}
      {detail && <div className="result-detail">{detail}</div>}
      {ok && (
        // For Ladies/Men tickets this is how the bouncer refuses a mismatch: it undoes
        // the check-in so the ticket isn't used up
        <button className="result-undo" onClick={undo}>
          {gender ? "doesn't match" : 'undo'}
        </button>
      )}
      {undoMsg && <div className="result-detail">{undoMsg}</div>}
      <div className="result-hint">{ok ? '' : 'tap to continue'}</div>
    </div>
  )
}

// ---------- manual lookup ----------

function Lookup({ eventSlug, onCheckIn }: { eventSlug: string; onCheckIn: (code: string) => Promise<void> }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<CheckinTicket[] | null>(null)

  const search = useCallback(
    async (query: string) => {
      if (query.trim().length < 2) return setResults(null)
      setResults(await api<CheckinTicket[]>(`/checkin/search?event=${eventSlug}&q=${encodeURIComponent(query.trim())}`))
    },
    [eventSlug],
  )

  // Search as they type, with a short pause so we don't search every keystroke
  useEffect(() => {
    const t = setTimeout(() => search(q), 250)
    return () => clearTimeout(t)
  }, [q, search])

  return (
    <div className="lookup">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Name, email, or last 4 of code"
        autoCapitalize="off"
        autoCorrect="off"
        autoFocus
      />
      {results?.length === 0 && <p className="scan-msg">No tickets found.</p>}
      <ul>
        {results?.map((t) => {
          const inAlready = !!t.checked_in_at
          const voided = t.status === 'void'
          return (
            <li key={t.code}>
              <div>
                <div className="lookup-name">{t.holder_name}</div>
                <div className="lookup-meta">
                  {t.tier}
                  {t.gender ? ` · ${GENDER_WORD[t.gender]}` : ''} · …{t.code.slice(-4)} · {t.buyer_email_hint}
                </div>
                {inAlready && t.checked_in_at && (
                  <div className="lookup-meta">
                    in at {timeOnly(t.checked_in_at)}
                    {t.checked_in_by ? ` by ${t.checked_in_by}` : ''}
                  </div>
                )}
              </div>
              <button
                disabled={inAlready || voided}
                onClick={async () => {
                  await onCheckIn(t.code)
                  search(q)
                }}
              >
                {voided ? 'refunded' : inAlready ? 'in' : 'check in'}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
