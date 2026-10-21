import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  api,
  ApiError,
  formatWhen,
  money,
  serviceFeeCents,
  type Combo,
} from "../api";
import Chevron from "../Chevron";
import "./Tickets.css";

// A combo pass page (e.g. club + house party for $25). Each pass becomes one ticket
// per night, emailed together; the door scans each night's QR as normal.
export default function ComboTickets({ combo: initial }: { combo: Combo }) {
  const [params] = useSearchParams();
  const [combo, setCombo] = useState(initial);
  const [qty, setQty] = useState(0);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [names, setNames] = useState<string[]>([]);
  const [emails, setEmails] = useState<string[]>([]);
  const [openSends, setOpenSends] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reload = useCallback(
    () =>
      api<Combo>(`/combos/${initial.slug}`)
        .then((c) => {
          setCombo(c);
          setQty((q) => (c.status === "on_sale" ? Math.min(q, c.buyable) : 0));
        })
        .catch(() => {}),
    [initial.slug],
  );

  // Back from Stripe: release the held passes right away, then refresh availability
  const cancelledOrder = params.get("cancelled");
  useEffect(() => {
    if (!cancelledOrder) return;
    api(`/checkout/${cancelledOrder}/cancel`, { method: "POST" })
      .catch(() => {})
      .then(reload);
  }, [cancelledOrder, reload]);

  const available = combo.status === "on_sale";
  const subtotal = combo.price_cents * qty;
  const fee = serviceFeeCents(subtotal);
  const setAt = (setter: typeof setNames, i: number, v: string) =>
    setter((list) => {
      const next = [...list];
      next[i] = v;
      return next;
    });
  const toggleSend = (i: number) =>
    setOpenSends((open) => {
      const next = new Set(open);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  const note =
    combo.status === "sold_out"
      ? "Sold out"
      : combo.status === "ended"
        ? "Sales ended"
        : combo.status === "not_yet"
          ? "Not on sale yet"
          : combo.sales_end
            ? `until ${formatWhen(combo.sales_end)}`
            : "";

  const buy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (qty === 0) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await api<{ checkout_url: string }>("/checkout/combo", {
        method: "POST",
        body: JSON.stringify({
          combo_slug: combo.slug,
          quantity: qty,
          name: name.trim(),
          email: email.trim(),
          names: Array.from({ length: qty }, (_, i) => names[i] ?? ""),
          emails: Array.from({ length: qty }, (_, i) => {
            const v = emails[i]?.trim();
            return openSends.has(i) && v ? v : null;
          }),
        }),
      });
      window.location.href = res.checkout_url;
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.status === 422) {
        const flat = err.fields.map((loc) => loc.join("."));
        if (flat.some((f) => f.startsWith("body.emails")))
          setError("One of your friends' emails doesn't look right.");
        else if (flat.some((f) => f === "body.email"))
          setError("Your email doesn't look right.");
        else setError("Something in the form needs fixing.");
      } else {
        setError((err as Error).message);
        reload();
      }
    }
  };

  // The combo's own flyer, or each night's flyer side by side
  const flyers = combo.poster_url
    ? [combo.poster_url]
    : combo.parts.map((p) => p.poster_url).filter((u): u is string => !!u);

  return (
    <section className={`tickets ${flyers.length ? "with-poster" : ""}`}>
      {flyers.length > 0 && (
        <div className="tickets-poster-col">
          <div className={`combo-flyers n${flyers.length}`}>
            {flyers.map((src) => (
              <img
                key={src}
                className="tickets-poster"
                src={src}
                alt="Event flyer"
              />
            ))}
          </div>
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
            <p className="tickets-kicker">combo pass</p>
            <h1>{combo.name}</h1>
            {combo.description && (
              <p className="tickets-desc">{combo.description}</p>
            )}
          </div>
        </header>

        <ul className="combo-parts">
          {combo.parts.map((p) => (
            <li key={p.event_slug}>
              <Link to={`/tickets/${p.event_slug}`} className="combo-part-name">
                {p.event_name}
              </Link>
              <div className="combo-part-meta">
                {formatWhen(p.starts_at)}
                {p.venue ? ` · ${p.venue}` : ""}
              </div>
              <div className="combo-part-meta">{p.tier} ticket</div>
            </li>
          ))}
        </ul>

        <form className="tickets-form" onSubmit={buy}>
          <ul className="tiers">
            <li className={`tier ${available ? "" : "unavailable"}`}>
              <div className="tier-info">
                <div className="tier-name">{combo.name}</div>
                <div className="tier-desc">One ticket for each event</div>
                <div className="tier-note">{note}</div>
              </div>
              <div className="tier-price">{money(combo.price_cents)}</div>
              <div className="stepper" aria-label={`${combo.name} quantity`}>
                <button
                  type="button"
                  onClick={() => setQty((q) => Math.max(0, q - 1))}
                  disabled={!available || qty === 0}
                  aria-label="Fewer"
                >
                  −
                </button>
                <span>{qty}</span>
                <button
                  type="button"
                  onClick={() => {
                    setError("");
                    setQty((q) => Math.min(q + 1, combo.buyable));
                  }}
                  disabled={!available || qty >= combo.buyable}
                  aria-label="More"
                >
                  +
                </button>
              </div>
            </li>
          </ul>

          {qty > 0 && (
            <div className="checkout">
              <dl className="totals">
                <dt>Passes</dt>
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
                <legend>Names on passes</legend>
                {Array.from({ length: qty }, (_, i) => {
                  const first = i === 0;
                  const sending = openSends.has(i);
                  return (
                    <div className="holder" key={i}>
                      <label>
                        <span>pass {i + 1}</span>
                        <input
                          value={names[i] ?? ""}
                          onChange={(e) => setAt(setNames, i, e.target.value)}
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
                            onClick={() => toggleSend(i)}
                            aria-expanded={sending}
                          >
                            <Chevron />
                            send it to them too
                          </button>
                          {sending && (
                            <input
                              type="email"
                              className="send-email"
                              value={emails[i] ?? ""}
                              onChange={(e) =>
                                setAt(setEmails, i, e.target.value)
                              }
                              placeholder="Their email"
                              aria-label={`Email for pass ${i + 1}`}
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
                  Each pass gets a ticket for every night, under its name.
                </p>
              </fieldset>

              {error && <p className="checkout-error">{error}</p>}

              <button className="enter checkout-btn" disabled={submitting}>
                {submitting
                  ? "One sec…"
                  : `Checkout · ${money(subtotal + fee)}`}
              </button>
              <p className="checkout-hint">
                Secure payment by Stripe. All sales are final; if an event is
                cancelled you'll get a refund for it. We only use your details
                to send your tickets (<a href="/privacy">privacy</a>).
              </p>
            </div>
          )}
        </form>
      </div>
    </section>
  );
}
