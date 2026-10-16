import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  api,
  ApiError,
  formatWhen,
  money,
  serviceFeeCents,
  type EventCard,
  type SaleEvent,
  type Tier,
} from "../api";
import Chevron from "../Chevron";
import "./Tickets.css";

const shortDate = (iso: string) =>
  new Date(iso).toLocaleString("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Toronto",
  });

// Most you can pick right now. (Falls back for the minute after a deploy when the
// API may still be the previous version, which sent the raw stock count.)
const buyable = (t: Tier & { remaining?: number }) =>
  t.buyable ?? Math.min(t.remaining ?? 0, t.max_per_order);

function tierNote(t: Tier) {
  if (t.status === "sold_out") return "Sold out";
  if (t.status === "ended") return "Sales ended";
  if (t.status === "not_yet")
    return t.sales_start
      ? `On sale ${shortDate(t.sales_start)}`
      : "Not on sale yet";
  const notes = [];
  if (t.sales_end) notes.push(`until ${shortDate(t.sales_end)}`);
  return notes.join(" · ");
}

// /tickets and /tickets/:slug. With one event listed, /tickets goes straight to
// it; with several, people pick one first.
export default function Tickets() {
  const { slug } = useParams();
  const [params] = useSearchParams();
  const [events, setEvents] = useState<EventCard[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (slug) return;
    api<EventCard[]>("/events")
      .then(setEvents)
      .catch((e) => setError(e.message));
  }, [slug]);

  if (slug) return <EventTickets key={slug} slug={slug} />;
  if (error) return <p className="tickets-status">{error}</p>;
  if (!events) return <p className="tickets-status">Loading…</p>;
  if (events.length === 0) return <NothingOnSale />;
  // One event: show it right here (and keep ?cancelled working)
  if (events.length === 1) return <EventTickets slug={events[0].slug} />;

  return (
    <section className="event-choice">
      {params.get("cancelled") && (
        <p className="tickets-banner">Checkout cancelled. You weren't charged.</p>
      )}
      <p className="tickets-kicker">tickets</p>
      <div className="event-cards">
        {events.map((e) => (
          <Link key={e.slug} to={`/tickets/${e.slug}`} className="event-card">
            <div className="event-card-flyer">
              {e.poster_url ? (
                <img src={e.poster_url} alt={`${e.name} flyer`} loading="lazy" />
              ) : (
                <span>{e.name}</span>
              )}
            </div>
            <div className="event-card-info">
              <h2>{e.name}</h2>
              <p>{formatWhen(e.starts_at)}</p>
              {e.venue && <p>{e.venue}</p>}
              <p className="event-card-cta">
                {e.status === "sold_out"
                  ? "sold out"
                  : e.status === "not_yet" && e.sales_start
                    ? `on sale ${shortDate(e.sales_start)}`
                    : e.from_price_cents !== null
                      ? `from ${money(e.from_price_cents)} →`
                      : "tickets →"}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function NothingOnSale() {
  return (
    <section className="tickets-empty">
      <p className="tickets-kicker">tickets</p>
      <h1>nothing on sale right now</h1>
      <a href="https://instagram.com/socfrvr" target="_blank" rel="noreferrer">
        @socfrvr for the next one
      </a>
    </section>
  );
}

function EventTickets({ slug }: { slug: string }) {
  const [params] = useSearchParams();
  const [event, setEvent] = useState<SaleEvent | null>(null);
  const [loadError, setLoadError] = useState("");
  const [qty, setQty] = useState<Record<number, number>>({});
  const [name, setName] = useState("");
  // Names on tickets, per tier: holderNames[tierId][i]. Ticket 1 overall defaults to the buyer.
  const [holderNames, setHolderNames] = useState<Record<number, string[]>>({});
  // Optional "send it to them too" email per ticket, same shape as holderNames
  const [holderEmails, setHolderEmails] = useState<Record<number, string[]>>(
    {},
  );
  const [openSends, setOpenSends] = useState<Set<string>>(new Set());
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(() => {
    return api<SaleEvent>(`/events/${slug}`)
      .then((e) => {
        setEvent(e);
        // Keep chosen quantities within what's still available
        setQty((q) =>
          Object.fromEntries(
            e.tiers.map((t) => [
              t.id,
              t.status === "on_sale" ? Math.min(q[t.id] ?? 0, buyable(t)) : 0,
            ]),
          ),
        );
      })
      .catch((e) =>
        setLoadError(
          e instanceof ApiError && e.status === 404 ? "none" : e.message,
        ),
      );
  }, [slug]);

  // Coming back from Stripe's "back" link: release their held tickets right away,
  // then load (so the stock shown includes the tickets they just let go)
  const cancelledOrder = params.get("cancelled");
  useEffect(() => {
    const release = cancelledOrder
      ? api(`/checkout/${cancelledOrder}/cancel`, { method: "POST" }).catch(
          () => {},
        )
      : Promise.resolve();
    release.then(load);
  }, [cancelledOrder, load]);

  const subtotal = useMemo(
    () =>
      event
        ? event.tiers.reduce(
            (sum, t) => sum + t.price_cents * (qty[t.id] ?? 0),
            0,
          )
        : 0,
    [event, qty],
  );
  const fee = serviceFeeCents(subtotal);
  const count = Object.values(qty).reduce((a, b) => a + b, 0);

  // One slot per ticket being bought, in tier order. The very first one may be
  // left blank: it's the buyer's own ticket.
  const ticketSlots = (event?.tiers ?? []).flatMap((tier) =>
    Array.from({ length: qty[tier.id] ?? 0 }, (_, index) => ({
      tier,
      index,
      first: false,
    })),
  );
  if (ticketSlots.length) ticketSlots[0].first = true;

  const setIn =
    (setter: typeof setHolderNames) =>
    (tierId: number, index: number, value: string) =>
      setter((h) => {
        const list = [...(h[tierId] ?? [])];
        list[index] = value;
        return { ...h, [tierId]: list };
      });
  const setHolder = setIn(setHolderNames);
  const setHolderEmail = setIn(setHolderEmails);

  const toggleSend = (key: string) =>
    setOpenSends((open) => {
      const next = new Set(open);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const change = (t: Tier, delta: number) => {
    setError("");
    setQty((q) => {
      const next = Math.max(0, Math.min((q[t.id] ?? 0) + delta, buyable(t)));
      return { ...q, [t.id]: next };
    });
  };

  const buy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!event || count === 0) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await api<{ checkout_url: string }>("/checkout", {
        method: "POST",
        body: JSON.stringify({
          event_slug: event.slug,
          items: Object.entries(qty)
            .filter(([, n]) => n > 0)
            .map(([tier_id, quantity]) => ({
              tier_id: Number(tier_id),
              quantity,
              // Blank (never typed) names are sent as "", which means "use the buyer's name"
              names: Array.from(
                { length: quantity },
                (_, i) => holderNames[Number(tier_id)]?.[i] ?? "",
              ),
              // Only send emails the buyer actually opened the field for and filled in
              emails: Array.from({ length: quantity }, (_, i) => {
                const value = holderEmails[Number(tier_id)]?.[i]?.trim();
                return openSends.has(`${tier_id}-${i}`) && value ? value : null;
              }),
            })),
          name: name.trim(),
          email: email.trim(),
        }),
      });
      window.location.href = res.checkout_url;
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.status === 422) {
        // Say which field the server didn't like
        const flat = err.fields.map((loc) => loc.join("."));
        if (flat.some((f) => f.includes(".emails.")))
          setError("One of your friends' emails doesn't look right.");
        else if (flat.some((f) => f === "body.email"))
          setError("Your email doesn't look right.");
        else if (flat.some((f) => f === "body.name"))
          setError("Add your name.");
        else setError("Something in the form needs fixing.");
      } else {
        setError((err as Error).message);
        load(); // stock may have changed (e.g. "Only 2 left")
      }
    }
  };

  if (loadError === "none") {
    return (
      <section className="tickets-empty">
        <p className="tickets-kicker">tickets</p>
        <h1>that event isn't on sale</h1>
        <Link to="/tickets">see what's on</Link>
      </section>
    );
  }
  if (loadError) return <p className="tickets-status">{loadError}</p>;
  if (!event) return <p className="tickets-status">Loading…</p>;

  return (
    <section className={`tickets ${event.poster_url ? "with-poster" : ""}`}>
      {/* The flyer: left column on desktop (stays in view), full width on top on phones */}
      {event.poster_url && (
        <div className="tickets-poster-col">
          <img
            className="tickets-poster"
            src={event.poster_url}
            alt={`${event.name} flyer`}
          />
        </div>
      )}

      <div className="tickets-main">
        {cancelledOrder && (
          <p className="tickets-banner">
            Checkout cancelled. You weren't charged.
          </p>
        )}

        <header className="tickets-head">
          <div>
            <p className="tickets-kicker">tickets</p>
            <h1>{event.name}</h1>
            <p className="tickets-when">{formatWhen(event.starts_at)}</p>
            {event.venue && <p className="tickets-when">{event.venue}</p>}
            {event.description && (
              <p className="tickets-desc">{event.description}</p>
            )}
          </div>
        </header>

      {event.sales_start && new Date(event.sales_start) > new Date() && (
        <p className="tickets-soon-banner">
          Tickets go on sale <strong>{formatWhen(event.sales_start)}</strong>
        </p>
      )}

        <form className="tickets-form" onSubmit={buy}>
          <ul className="tiers">
            {event.tiers.map((t) => {
              const n = qty[t.id] ?? 0;
              const available = t.status === "on_sale";
              return (
                <li
                  key={t.id}
                  className={`tier ${available ? "" : "unavailable"}`}
                >
                  <div className="tier-info">
                    <div className="tier-name">{t.name}</div>
                    {t.description && (
                      <div className="tier-desc">{t.description}</div>
                    )}
                    <div className="tier-note">{tierNote(t)}</div>
                  </div>
                  <div className="tier-price">{money(t.price_cents)}</div>
                  <div className="stepper" aria-label={`${t.name} quantity`}>
                    <button
                      type="button"
                      onClick={() => change(t, -1)}
                      disabled={!available || n === 0}
                      aria-label="Fewer"
                    >
                      −
                    </button>
                    <span>{n}</span>
                    <button
                      type="button"
                      onClick={() => change(t, 1)}
                      disabled={!available || n >= buyable(t)}
                      aria-label="More"
                    >
                      +
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>

          {count > 0 && (
            <div className="checkout">
              <dl className="totals">
                <dt>Tickets</dt>
                <dd>{money(subtotal)}</dd>
                <dt>Service fee</dt>
                <dd>{money(fee)}</dd>
                <dt className="total">Total</dt>
                <dd className="total">{money(subtotal + fee)}</dd>
              </dl>

              <label>
                <span>Name</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  required
                  maxLength={200}
                />
              </label>
              <label>
                <span>Email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </label>
              <p className="checkout-hint">Your tickets are emailed here.</p>

              <fieldset className="holders">
                <legend>Names on tickets</legend>
                {ticketSlots.map(({ tier, index, first }) => {
                  const key = `${tier.id}-${index}`;
                  const sending = openSends.has(key);
                  return (
                    <div className="holder" key={key}>
                      <label>
                        <span>
                          {tier.name} · ticket {index + 1}
                        </span>
                        <input
                          value={holderNames[tier.id]?.[index] ?? ""}
                          onChange={(e) =>
                            setHolder(tier.id, index, e.target.value)
                          }
                          placeholder={
                            first ? name || "Your name" : "Full name"
                          }
                          required={!first}
                          maxLength={200}
                        />
                      </label>
                      {!first && (
                        <>
                          <button
                            type="button"
                            className={`send-toggle ${sending ? "open" : ""}`}
                            onClick={() => toggleSend(key)}
                            aria-expanded={sending}
                          >
                            <Chevron />
                            send it to them too
                          </button>
                          {sending && (
                            <input
                              type="email"
                              className="send-email"
                              value={holderEmails[tier.id]?.[index] ?? ""}
                              onChange={(e) =>
                                setHolderEmail(tier.id, index, e.target.value)
                              }
                              placeholder="Their email"
                              aria-label={`Email for ${tier.name} ticket ${index + 1}`}
                              autoComplete="off"
                              required
                            />
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
                <p className="checkout-hint">
                  Each ticket is checked in under its name.
                </p>
              </fieldset>

              {error && <p className="checkout-error">{error}</p>}

              <button className="enter checkout-btn" disabled={submitting}>
                {submitting
                  ? "One sec…"
                  : `Checkout · ${money(subtotal + fee)}`}
              </button>
              <p className="checkout-hint">
                Secure payment by Stripe. All sales are final; if the event is
                cancelled you'll get a full refund. We only use your details to
                send your tickets (<a href="/privacy">privacy</a>).
              </p>
            </div>
          )}
        </form>
      </div>
    </section>
  );
}
