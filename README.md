# sonsofcaesar

backend: .venv/bin/uvicorn app.main:app --reload --port 8000

stripe: stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,charge.refunded --forward-to localhost:8000/webhooks/stripe

frontend: npm run dev
