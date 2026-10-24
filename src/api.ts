export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type TicketEvent = {
  name: string
  venue: string | null
  starts_at: string
  ends_at: string | null
  address?: string | null // secret address: only sent to valid ticket holders
}

export type TierStatus = 'on_sale' | 'sold_out' | 'not_yet' | 'ended'

export type Tier = {
  id: number
  name: string
  description: string | null
  price_cents: number
  fee_for_one_cents: number
  max_per_order: number
  buyable: number // most you can buy now (capped at the per-order limit)
  status: TierStatus
  sales_start: string | null
  sales_end: string | null
  // Priced by gender: Ladies and Men share this tier's tickets
  gendered?: boolean
  price_ladies_cents?: number | null
  price_men_cents?: number | null
}

export type SaleEvent = {
  slug: string
  name: string
  description: string | null
  venue: string | null
  poster_url: string | null
  starts_at: string
  ends_at: string | null
  sales_start: string | null // tickets can't be bought before this
  currency: string
  tiers: Tier[]
  combos?: Combo[] // passes that include this event ("Going to both?")
}

export type ComboPart = {
  event_slug: string
  event_name: string
  starts_at: string
  venue: string | null
  poster_url: string | null
  tier: string
}

export type Combo = {
  slug: string
  name: string
  description: string | null
  poster_url: string | null
  price_cents: number
  fee_for_one_cents: number
  max_per_order: number
  buyable: number
  status: TierStatus
  sales_end: string | null
  parts: ComboPart[]
}

export type EventCard = {
  slug: string
  name: string
  venue: string | null
  poster_url: string | null
  starts_at: string
  sales_start: string | null
  status: TierStatus
  from_price_cents: number | null
}

// Mirrors the backend (app/pricing.py) so the total shows before checkout.
// The server recalculates it; Stripe charges the server's number.
export function serviceFeeCents(subtotalCents: number) {
  if (subtotalCents <= 0) return 0
  return Math.ceil((subtotalCents + 30) / (1 - 0.029)) - subtotalCents
}

export type Ticket = {
  code: string
  tier: string
  holder_name: string
  gender?: 'ladies' | 'men' | null
  status: 'valid' | 'void'
  checked_in_at: string | null
}

export type TicketPage = Ticket & { event: TicketEvent }

export type OrderPage = {
  id: string
  status: 'pending' | 'paid' | 'expired' | 'refunded'
  buyer_name: string
  email_hint: string
  resends_left: number
  total_cents: number
  title?: string
  is_combo?: boolean
  event: TicketEvent | null
  tickets: Ticket[]
  // Tickets grouped by event (one group, or one per night for a combo pass)
  groups?: { event: TicketEvent; tickets: Ticket[] }[]
}

export class ApiError extends Error {
  status: number
  // For 422s: which fields the server rejected, e.g. ["body","items",0,"emails",1]
  fields: (string | number)[][]
  constructor(status: number, message: string, fields: (string | number)[][] = []) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    // Send the staff login cookie (it only exists for logged-in staff)
    credentials: 'include',
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body?.detail
    if (Array.isArray(detail)) {
      throw new ApiError(res.status, 'Check the form', detail.map((d: { loc: (string | number)[] }) => d.loc))
    }
    throw new ApiError(res.status, detail ?? 'Something went wrong')
  }
  return body as T
}

export const qrUrl = (code: string) => `${API_URL}/tickets/${code}/qr.svg`

export function formatWhen(iso: string) {
  return new Date(iso).toLocaleString('en-CA', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/Toronto',
  })
}

export const money = (cents: number) => `$${(cents / 100).toFixed(2)}`

export type StaffMe = { name: string; email: string; role: 'admin' | 'door' | 'partner' }

export type CheckinTicket = {
  code: string
  holder_name: string
  tier: string
  gender?: 'ladies' | 'men' | null
  status: 'valid' | 'void'
  checked_in_at: string | null
  checked_in_by: string | null
  buyer_email_hint: string
}

export type CheckinResult = {
  result: 'ok' | 'already' | 'void' | 'wrong_event' | 'not_found'
  ticket: CheckinTicket | null
  other_event: string | null
}

export type StaffEvent = { slug: string; name: string; starts_at: string }

export const timeOnly = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })

// ---------- admin ----------

export type AdminTier = {
  id: number
  name: string
  description: string | null
  price_cents: number
  quantity: number
  max_per_order: number
  sales_start: string | null
  sales_end: string | null
  active: boolean
  sold: number
  held: number
  checked_in: number
  revenue_cents: number
  gendered: boolean
  price_ladies_cents: number | null
  price_men_cents: number | null
  sold_ladies: number
  sold_men: number
  sold_combo: number
}

export type AdminEvent = {
  slug: string
  name: string
  description: string | null
  venue: string | null
  poster_url: string | null
  starts_at: string
  ends_at: string | null
  on_sale: boolean
  sales_start: string | null
  secret_address: boolean
  address: string | null
  address_emailed_at: string | null
  tickets_sold: number
  capacity: number
  checked_in: number
  orders: number
  revenue_cents: number
  fees_cents: number
  refunded_orders: number
  tiers: AdminTier[]
  sales_by_day: { day: string; tickets: number; revenue_cents: number }[]
}

export type AdminEventListItem = {
  slug: string
  name: string
  starts_at: string
  on_sale: boolean
  tickets_sold: number
  capacity: number
}

export type Attendee = {
  code: string
  holder_name: string
  holder_email: string | null
  tier: string
  gender?: 'ladies' | 'men' | null
  status: 'valid' | 'void'
  checked_in_at: string | null
  checked_in_by: string | null
  order_id: string
  buyer_name: string
  buyer_email: string
  paid_at: string | null
  combo?: string | null
}

export type AdminCombo = {
  id: number
  slug: string
  name: string
  description: string | null
  poster_url: string | null
  price_cents: number
  quantity: number
  max_per_order: number
  sales_end: string | null
  on_sale: boolean
  tier_ids: number[]
  parts: ComboPart[]
  sold: number
  held: number
  revenue_cents: number
  fees_cents: number
  orders: number
}

export type TierChoice = { id: number; label: string; event_slug: string }
