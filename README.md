# sonsofcaesar

backend: .venv/bin/uvicorn app.main:app --reload --port 8000

stripe: stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,charge.refunded --forward-to localhost:8000/webhooks/stripe

frontend: npm run dev

## Support agent

The site's questions chat answers from the docs in `backend/knowledge`, and can look up events, check an order and resend tickets.

- **Search:** docs are split into pieces, embedded with Voyage and stored in Postgres with pgvector. After changing a doc, run `index-knowledge` in `backend` (and on the production API service).
- **Agent:** a manual tool loop on the Anthropic API (`backend/app/agent.py`). Tools live in `backend/app/agent_tools.py`, and order lookups and resends are enforced in code, not left to the prompt.
- **Limits:** off unless `CHAT_ENABLED=true`, a daily spend cap (`CHAT_DAILY_BUDGET_USD`), 6 messages a minute and 30 an hour per IP. Saved chats have emails and order ids removed and are deleted after 30 days.

### Evals

`backend/evals` has 38 cases, including prompt-injection and data-leak tests. It uses real API calls against a throwaway database, so each run costs money:

```
cd backend && .venv/bin/python -m evals.run --label check
```

| Run | Passed |
|---|---|
| First baseline | 32/35 |
| Corrected cases and added re-entry policy, 3 runs | 112/114 |
| After telling the agent not to infer unstated rules, 3 runs | 114/114, no data leaks |

The suite caught the agent inventing policy, which led to the prompt fix. These cases are self-written and there's no held-out set, so this shows the known cases pass, not how it does on every real question.
