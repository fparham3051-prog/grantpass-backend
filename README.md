# Frankly Inspired — Backend

A small Node/Express service with three jobs: receive the Contact form from `index.html`, receive the "email my results" form from `assessment.html`, and generate the assessment's AI result summary — sending email through [Resend](https://resend.com) and text generation through the [Claude API](https://console.anthropic.com).

```
frankly-inspired-backend/
├── server.js            the whole service — three routes, validation, rate limiting
├── emailTemplates.js     the actual email copy (kept separate so it's easy to edit without touching server logic)
├── aiNarrative.js        the Claude API call + prompt for the assessment's personalized summary
├── package.json
├── .env.example          copy to .env for local testing; never commit real secrets
└── .gitignore
```

No database. Every submission either sends successfully or the visitor sees an error and can email Franklin directly — see "What this doesn't do yet" below if that stops being enough.

## What I could not do for you

I don't have a way to create a GitHub repository or sign up for a third-party service on your behalf — both require an account only you can create. Everything else (the code, the Render deployment, wiring the frontend to it) I can finish once these things exist:

1. **A GitHub repo containing this `frankly-inspired-backend` folder.**
   Easiest path if you don't already have one: go to github.com → New repository → give it any name (e.g. `frankly-inspired-backend`) → skip adding a README (we already have one) → Create. Then use GitHub's "Upload files" button in the browser to drag in everything from this folder — you don't need git installed locally for this. Send me the repo URL when it's up.

2. **A Resend API key.**
   Go to [resend.com](https://resend.com) → sign up free (no credit card required for the free tier, which covers far more volume than this site will see) → API Keys → Create API Key. Send me the key (starts with `re_`) and I'll set it as a secret environment variable on the Render service — it won't sit in any file I write.

3. **An Anthropic API key** (for the assessment's AI-generated result summary — see "AI narrative" below).
   Go to [console.anthropic.com](https://console.anthropic.com) → sign up → API Keys → Create Key. Send me the key (starts with `sk-ant-`) and I'll set it the same way. This one is optional in the sense that the site works fine without it — the assessment just shows its static band description instead of a personalized one — so skip it for now if you'd rather launch without it and add it later.

Once I have these, I'll deploy the service to your Render workspace and wire `js/main.js` and `js/assessment.js` on the live site to call it. The frontend files already have the fetch calls written and ready.

## AI narrative

`POST /api/assessment-narrative` takes the visitor's five pillar scores and composite score and asks Claude for a 3-4 sentence personalized read of their results — which pillar is strongest, which is the priority area, framed in the same voice as the rest of the site.

The important design choice: **the model only ever receives the numeric scores** — never the organization's name, size, or any other detail, because it doesn't have any of that. It's structurally unable to invent facts about a visitor's organization, which matters given every other guardrail on this site is built around never fabricating claims. The full prompt is in `aiNarrative.js` if you want to read exactly what it's told.

If the API key is missing, the call times out, or Anthropic's API errors, the function returns `null` and `server.js` responds `{ ok: true, narrative: null }` — the frontend already falls back to the static band description in that case, so a flaky API call never breaks the assessment. Cost is small: a few hundred input/output tokens per completed assessment.

## Domain email (optional but recommended)

Until `franklyinspired.associates` is added and verified as a sending domain in Resend, emails will send from `onboarding@resend.dev` — they'll work, but won't say your domain. To fix that: Resend dashboard → Domains → Add Domain → add the DNS records it gives you wherever `franklyinspired.associates`'s DNS is managed. This is the same kind of step as setting up the branded email address the main site's README already flags as an open item — worth doing at the same time.

## Local testing (optional)

```
npm install
cp .env.example .env   # fill in a real RESEND_API_KEY
npm start
```

Then `curl localhost:3000/api/health` should return `{"ok":true,...}`.

## Deploying (what I'll do once I have the repo URL + API key)

- Create a Render web service pointed at your repo, Node runtime, build command `npm install`, start command `npm start`.
- Set `RESEND_API_KEY`, `FROM_EMAIL`, `TO_EMAIL`, `ALLOWED_ORIGIN`, and (if you want the AI narrative live) `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` as environment variables on the service (not committed to the repo).
- Once deployed, the service gets a URL like `https://frankly-inspired-api.onrender.com`. I'll update the `API_BASE` constant in `js/main.js` and `js/assessment.js` to point at it.

**Free-tier note:** Render's free web services spin down after ~15 minutes of no traffic and take 30-60 seconds to wake back up on the next request. The first form submission after a quiet period will feel slow. If that's a problem once the site has real traffic, upgrading that one service to the Starter plan removes the spin-down — nothing else about the setup changes.

## Locking down CORS

`ALLOWED_ORIGIN` defaults to `*` (any site can call this API) so testing isn't blocked before a domain is chosen. Once `franklyinspired.associates` (or whatever domain is chosen) is live, set `ALLOWED_ORIGIN` to that exact domain so only your site can submit to these endpoints.

## Assessment benchmark data (new)

Every completed self-assessment already calls `/api/assessment-narrative` to fetch its AI summary. That same call now also logs an anonymized copy of the scores — no email, no organization, just the numeric scores and a timestamp — to a Postgres database, if `DATABASE_URL` is set. `GET /api/benchmarks` returns the aggregate: total responses, average overall score, and the average for each of the five pillars. That's the raw material for eventually showing a visitor "the average nonprofit scores X here, yours scores Y" — a real, growing dataset nobody else has, instead of just a one-off individual result.

This is entirely optional and additive: if `DATABASE_URL` isn't set, `db.js` no-ops and every existing form and email flow behaves exactly as before.

A free Postgres instance (`frankly-inspired-assessments`) has already been created in your Render workspace. Two things left to finish wiring it up:

1. Open its page in the [Render dashboard](https://dashboard.render.com/d/dpg-d9tk50pt0dsc73bg9evg-a), copy the **Internal Connection String**, and send it to me — I'll set it as `DATABASE_URL` on the backend service, the same way as the other keys.
2. **Free Postgres on Render expires 30 days after creation** (this one expires around September 10, 2026) unless upgraded to a paid plan. Fine for testing the idea now; worth upgrading before you're relying on the data.

## What this doesn't do yet

- **Contact form and lead-notification emails still have no persistence.** If Resend is down or misconfigured, a submission is lost except for whatever error the visitor sees. Acceptable tradeoff for now — the same Postgres instance above could log these too if it becomes worth doing.
- **Spam protection is basic.** A honeypot field plus a 5-requests-per-15-minutes rate limit per IP. Fine for now; if spam becomes a real problem, adding something like hCaptcha to both forms is the next step.
