import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import './Chat.css'

type Message = { role: 'user' | 'assistant'; content: string }

const MAX_TURNS = 11 // the API takes 12, and the next question makes one more

// A quiet line in the corner that opens into a small support chat.
// Nothing is saved: closing the tab ends the conversation.
export default function Chat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const log = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) input.current?.focus()
  }, [open])

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [messages, busy, error])

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    const asked: Message[] = [...messages, { role: 'user', content: text }]
    setMessages(asked)
    setDraft('')
    setError(null)
    setBusy(true)
    try {
      // An odd count from the end always starts on a question, as the API requires
      const r = await api<{ reply: string }>('/chat', {
        method: 'POST',
        body: JSON.stringify({ messages: asked.slice(-MAX_TURNS) }),
      })
      setMessages([...asked, { role: 'assistant', content: r.reply }])
    } catch (err) {
      // Put the question back so it can be tried again
      setMessages(messages)
      setDraft(text)
      // Rate limits and the off switch have their own wording. Anything else, like a
      // dropped connection, shouldn't show people a raw error.
      const worded = err instanceof ApiError && (err.status === 429 || err.status === 503)
      setError(worded ? err.message : "Couldn't reach us. Try again, or DM @socfrvr.")
    }
    setBusy(false)
    input.current?.focus()
  }

  if (!open) {
    return (
      <button className="chat-toggle" onClick={() => setOpen(true)}>
        questions?
      </button>
    )
  }

  return (
    <section
      className="chat"
      aria-label="Support chat"
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <header className="chat-head">
        <span>questions</span>
        <button aria-label="Close chat" onClick={() => setOpen(false)}>
          ×
        </button>
      </header>

      <div className="chat-log" ref={log} aria-live="polite">
        {messages.length === 0 && (
          <p className="chat-hello">Tickets, the door, refunds. Ask away.</p>
        )}
        {messages.map((m, i) => (
          <p key={i} className={`chat-msg ${m.role}`}>
            {m.content}
          </p>
        ))}
        {busy && (
          <p className="chat-typing" role="status" aria-label="Replying">
            <span />
            <span />
            <span />
          </p>
        )}
        {error && <p className="chat-error">{error}</p>}
      </div>

      <form className="chat-form" onSubmit={send}>
        <input
          ref={input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type here"
          aria-label="Your question"
          maxLength={1000}
          autoComplete="off"
        />
        <button disabled={busy || !draft.trim()}>send</button>
      </form>
      <p className="chat-note">
        AI assistant, so it can get things wrong. Chats are saved for 30 days. Real person:{' '}
        <a href="https://instagram.com/socfrvr" target="_blank" rel="noreferrer">
          @socfrvr
        </a>
      </p>
    </section>
  )
}
