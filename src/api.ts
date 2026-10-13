export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type TicketEvent = {
  name: string
  venue: string | null
  starts_at: string
  ends_at: string | null
}

export type TierStatus = 'on_sale' | 'sold_out' | 'not_yet' | 'ended'

export type Tier = {
  id: number
  name: string
  description: string | null
  price_cents: number
  fee_for_one_cents: number
  max_per_order: number
  remaining: number
  status: TierStatus
  sales_start: string | null
  sales_end: string | null
}

export type SaleEvent = {
  slug: string
  name: string
  description: string | null
  venue: string | null
  poster_url: string | null
  starts_at: string
  ends_at: string | null
  currency: string
  tiers: Tier[]
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
  event: TicketEvent
  tickets: Ticket[]
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

export type StaffMe = { name: string; email: string; role: 'admin' | 'door' }
