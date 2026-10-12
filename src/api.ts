export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type TicketEvent = {
  name: string
  venue: string | null
  starts_at: string
  ends_at: string | null
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
  total_cents: number
  event: TicketEvent
  tickets: Ticket[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? 'Something went wrong')
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
