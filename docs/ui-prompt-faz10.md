# Dispatch Engine — Operations Console (Faz 10) — build brief

> Paste everything below the line into Lovable (or hand it to a coding agent working
> in `dispatch-helper-ui/`). It is written for a senior frontend engineer/agent that
> has never seen this project. Backend contract verified against
> `src/dispatch_engine/api/` on 2026-09-20.

---

## 0. Read this first

You are the senior frontend engineer for **Dispatch Engine**, a field-service
dispatch backend that assigns jobs to technicians by **skill** and **capacity**.
The backend is finished and running; it exposes a small, strict REST API. Your job
is to redesign the existing admin UI in `dispatch-helper-ui/` into a professional
**operations console** — the screen a dispatcher keeps open all day.

The product's one differentiating fact, which the UI must make visible:
**the engine decides, humans trigger and audit.** There are two ways to assign:

- **Quick dispatch** (`POST /v1/jobs/{id}/dispatch`): one job, synchronous, greedy —
  "least-loaded technician who has the skill". Fast, but order-dependent.
- **Optimize** (`POST /v1/dispatch-runs`): every pending job at once, asynchronous,
  solved globally with OR-Tools (min-cost max-flow) so that the **maximum number of
  jobs is placed** and the **resulting load is as even as possible**. It catches
  assignments the greedy path misses (a job losing its only technician to an
  earlier job that had another option).

There is no scheduling time, no location, no travel, no priority in the model.
Do not invent them. Do not build a Gantt, a map, or drag-and-drop placement —
there is no API to place a job on a chosen technician, so such a UI would lie.

## 1. Hard constraints (non-negotiable)

1. **Frontend only.** No Supabase, no database, no server-side data store, no auth
   provider, no mock/seed data fallback. Every byte of data comes from the API
   below. If the API is unreachable, the UI says so — it never fabricates.
2. **Keep the existing stack; redesign the product.** The repo is a Lovable-generated
   TanStack Start app: React 19, TypeScript strict, TanStack Router + Query v5,
   shadcn/ui (Radix), Tailwind v4, react-hook-form + zod, sonner, lucide-react,
   date-fns. Do not add a state library, a CSS framework, a component kit, or a
   charting library beyond what is installed (recharts is present; use it only if a
   chart genuinely earns its place — see §5).
3. **All API calls run in the browser.** Never fetch the API from TanStack Start
   server functions or SSR loaders: the API key lives in the browser env and the
   API is `localhost` from the browser's point of view. Route loaders that touch the
   API must be client-only (`ssr: false`) or the fetching must live in React Query
   hooks inside components.
4. **Config via env only:** `VITE_API_BASE_URL` (default `http://localhost:8000/v1`)
   and `VITE_API_KEY`. Keep the existing `src/lib/api.ts` contract semantics (root
   `/health` outside `/v1`, `X-API-Key` on every `/v1` request, FastAPI error
   extraction) — extend it, do not fork it.
5. **Honesty in labels.** Use the words the backend uses: `pending / assigned /
   completed`, `queued / running / succeeded / failed`, "Quick dispatch (greedy)",
   "Optimize (global)". No marketing copy, no "AI".

## 2. API contract (source of truth)

Base: `${VITE_API_BASE_URL}` = `http://localhost:8000/v1`. Header on every `/v1`
request: `X-API-Key: <VITE_API_KEY>`. JSON in, JSON out. Every response carries
`X-Request-ID` (CORS-exposed) — surface it in error toasts ("copy request id").

### Types (exact)

```ts
type Technician = { id: string; name: string; max_jobs: number; skills: string[]; load: number };
type JobStatus = "pending" | "assigned" | "completed";
type Job = { id: string; title: string; skill: string; status: JobStatus; technician_id: string | null };
type JobEvent = {
  id: string; job_id: string; from_status: JobStatus; to_status: JobStatus;
  technician_id: string | null; actor: string; created_at: string; // ISO 8601, UTC
};
type RunStatus = "queued" | "running" | "succeeded" | "failed";
type Assignment = { job_id: string; technician_id: string };
type DispatchRun = { id: string; status: RunStatus; assignments: Assignment[]; error: string | null };
type Health = { status: string; version: string };
```

Note what is **absent**: no `created_at` on Job/Technician responses, no run
timestamps, no run list endpoint, no DELETE endpoints, no PATCH, no job priority,
no technician availability. Design around these, do not fake them.

### Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/technicians?limit=&cursor=` | array body; keyset-paginated (see below) |
| POST | `/technicians` | `{name, max_jobs (1..100), skills: string[] (≥1)}` → 201 Technician |
| GET | `/jobs?limit=&cursor=` | array body; paginated |
| GET | `/jobs/{id}` | 404 if unknown |
| POST | `/jobs` | `{title (1..200 chars), skill}` → 201 Job |
| POST | `/jobs/{id}/dispatch` | greedy single dispatch → Job; 409 with `detail` if nobody can take it / wrong status |
| POST | `/jobs/{id}/complete` | frees the technician's slot → Job; 409 if not assigned |
| GET | `/jobs/{id}/events` | JobEvent[] oldest→newest; `actor` is `"api"` for manual actions or `"worker:<run_id>"` for optimizer runs |
| POST | `/dispatch-runs` | **202** `{id, status:"queued", assignments:[], error:null}`; the worker picks it up asynchronously |
| GET | `/dispatch-runs/{id}` | poll; 404 once swept (terminal runs are deleted after 30 days) |
| GET | `/dispatch-runs/{id}/events` | Server-Sent Events, see below |
| GET | `${root}/health` | root, unauthenticated: `{status, version}` |
| GET | `${root}/ready` | root, unauthenticated: 200 only if Postgres + Redis answer |

### Pagination

`limit` default 50, silently capped at 200. When another page exists the response has
an `X-Next-Cursor` header; pass it back as `?cursor=`. The body stays a plain array.
An undecodable cursor → 422. Implement "load more" (or auto-follow up to a sane cap)
so that >50 records are not silently invisible — the current UI has this bug.

### Errors

FastAPI shapes: `{detail: string}` (401/404/409/429) or `{detail: [{loc, msg, type}]}`
(422 validation). Handle explicitly:

- **401** → the key is missing/wrong. Show a full-page blocking state explaining
  `VITE_API_KEY`, not a toast per request.
- **409** → business rule ("capacity exceeded", "skill mismatch", "invalid
  transition"). Toast with the server's `detail` verbatim; refetch the affected lists.
- **422** → validation. Map `loc` to form fields when it came from a form; otherwise toast.
- **429** → `Retry-After` header (seconds). Toast with a countdown, pause background
  polling until it elapses. Limit is 120 requests / 60 min per key — design polling
  budgets accordingly (see §6).
- **Network failure** → persistent top banner "API unreachable at <base>" with a
  retry button; queries retry with backoff; the health pill goes red.

### Idempotency

`POST /technicians`, `/jobs`, `/dispatch-runs` accept `Idempotency-Key`. Generate
`crypto.randomUUID()` **per user intent** (per click), reuse the same key on automatic
retry of that intent, discard it on success. Same key + same body replays the original
2xx; same key + different body → 422; still in flight → 409.

### SSE (live run status)

`GET /dispatch-runs/{id}/events` streams `data: <DispatchRun JSON>\n\n` — the current
state first, then one event per status change, and the server closes after
`succeeded`/`failed` (or after 10 minutes). **`EventSource` cannot send `X-API-Key`**,
so consume it with `fetch` + `ReadableStream` and a small SSE line parser (or
`@microsoft/fetch-event-source` if you must add one dependency — justify it in the PR).
Fall back to polling `GET /dispatch-runs/{id}` every 2s if the stream errors.

## 3. Product model & information architecture

Three surfaces plus a global chrome. Left rail (icon + label, collapsible), no
top-level tabs beyond these:

1. **Board** — the default screen. Left: **Unassigned queue** (pending jobs). Right:
   **Technician capacity lanes**. Top: the action bar. This is where a dispatcher lives.
2. **Runs** — start an optimization run, watch it live, read the result, browse
   history.
3. **Technicians** — roster management (table + create).

Jobs have no page of their own: a job opens as a right-side **sheet** from anywhere
(queue, lane, run result) with its details, actions and audit timeline.

Global chrome: app name + environment (base URL host), health/ready pill, theme
toggle, "New job" and "New technician" always reachable (`N`, `T` shortcuts).

## 4. Screen specifications

### 4.1 Board

**Action bar** (sticky):
- `Optimize all pending` — primary. Disabled with a reason when there are 0 pending
  jobs or 0 technicians with free capacity. Click → confirm popover: "Place up to
  *N* pending jobs across *M* technicians with *K* free slots" → `POST /dispatch-runs`
  → navigate to Runs with the live panel focused (or open it inline as a drawer —
  pick one and keep it).
- Search (filters both columns by title/skill/name), skill filter chips derived
  from the data, "show completed" toggle (off by default).
- Counts as tabular numerals: pending · assigned · completed · free slots.

**Unassigned queue** (left, ~40%): a dense list, one row per pending job:
title, skill chip, and an **eligibility indicator** computed client-side:
`eligible = technicians.filter(t => t.skills.includes(job.skill) && t.load < t.max_jobs).length`.
- `eligible > 0` → plain grey row, "3 can take it".
- `eligible == 0` and some technician *has* the skill → amber "all <skill> technicians are full".
- `eligible == 0` and nobody has the skill → red "no technician has <skill>".
  This is the only colour on a healthy board (see §5).
- Row actions: `Quick dispatch` (greedy, per row, with a tooltip that says exactly
  that) and open sheet. Optimistic UI is **not** required; refetch on settle.
- Group by skill when the skill filter is empty and the list exceeds ~20 rows.
- Empty state: "No pending jobs. Create one or wait for intake." with the New job CTA.

**Technician capacity lanes** (right, ~60%): one lane per technician:
name, skill chips, capacity as a **segmented bar** (one segment per slot, filled
segments = load) with `load / max_jobs` in tabular numerals, then the assigned jobs
inline as compact chips (title, `Complete` action on hover/focus). A full technician
is muted, not red — full is normal. Sort: free slots desc, then name.
Empty state: "No technicians yet" with CTA.

### 4.2 Runs

**Live panel** (top): the latest run. A four-step status strip
`queued → running → succeeded | failed` driven by SSE, with elapsed time (client
clock from the moment of the POST — the API has no timestamps). While
`queued`/`running` show a calm indeterminate indicator, not a spinner storm.
Announce status changes via `aria-live="polite"`.

**Result** (when terminal):
- Headline: "Placed **A** of **P** pending jobs" where `P` is the pending count
  captured client-side right before the POST (the API only returns assignments).
- Assignments table: job title · skill · technician name · technician load before → after
  (before = load at POST time, after = before + assignments to that technician).
  Names are joined client-side from the cached lists; unknown ids render as truncated
  ids, never crash.
- **Unplaced** list: pending jobs not in `assignments`, with the client-computed reason
  (`no technician has <skill>` / `all <skill> technicians were full`).
- `failed` → the `error` string verbatim, plus a "Run again" action.
- Copy: one sentence under the headline: "Global optimization (OR-Tools min-cost
  flow): maximum number of placements first, most even load second." Nothing more.

**History** (below): the backend has no list endpoint. Keep `{id, startedAt,
pendingBefore}` in `localStorage` (cap 50), render as a compact list; click →
fetch by id. A 404 renders as "expired (runs are swept after 30 days)", not an error.

### 4.3 Job sheet

Header: title, status badge, skill chip, technician name (link scrolls the Board to
that lane). Actions match status: pending → Quick dispatch; assigned → Complete;
completed → none. Body: **Audit timeline** from `/jobs/{id}/events`: each event as
`from → to`, actor rendered as "Manual (API)" or "Optimizer run <short id>" (the
latter links to Runs with that id), technician name, absolute timestamp with relative
hint (`date-fns`), newest first. Keyboard: `Esc` closes, focus returns to the trigger.

### 4.4 Technicians

Data table (shadcn `Table`, not a heavy grid): name, skills (chips, click = filter),
capacity bar + `load / max_jobs`, assigned jobs count. Client-side sort on name/free
slots; search box. "New technician" opens a dialog: name (required), max_jobs
(integer 1..100, default 3), skills as a tag input (≥1, trim, dedupe, lower-case is
**not** applied — the backend is case-sensitive, say so in helper text). Validation
with zod mirroring the backend limits so 422 is rare; when it still happens, map it.

### 4.5 Global states

- Health pill: polls `/health` every 30s (unauthenticated, unlimited), shows version on
  hover; `/ready` checked on demand when the pill is clicked.
- Every list has skeletons (not spinners) on first load and a subtle "refreshing"
  indicator on background refetch.
- Toasts (sonner): bottom-right, success is quiet (short, no icon spam), errors persist
  until dismissed and include "copy request id".

## 5. Design language — different on purpose

We looked at the category (ServiceTitan/Jobber/Salesforce Field Service dispatch
boards, the open-source `fieldboard` component). Borrow **principles**, not screens:

- **Colour means trouble; a healthy board is grey.** Status is conveyed by
  position, typography and muted badges. Red/amber appear only for "cannot be
  placed" and failures. No green celebration states, no gradient cards.
- **The unassigned queue is a first-class surface**, not a sidebar afterthought.
- **Density over decoration.** Row height 36–40px, 13–14px body text, tabular
  numerals (`font-variant-numeric: tabular-nums`) for every count, 8px spacing grid,
  1px borders on `--border`, no drop shadows except the sheet/dialog.
- **Explain the machine.** Where the engine made a choice, say which engine and why
  in one line. That is our differentiator; Gantt/map/drag-drop are not — do not build
  them.
- Typography: a single humanist/grotesk UI face (system stack or Inter/Geist),
  600 for headings, 500 for labels, mono for ids and request ids.
- Tokens in `styles.css` via Tailwind v4 `@theme`: `--background --surface --border
  --muted --foreground --accent --warning --danger` with light and dark values;
  dark mode via `class="dark"` toggle persisted in `localStorage`, respects
  `prefers-color-scheme` on first visit.
- Motion: 120–160ms ease-out for sheet/dialog and status strip; none on lists.
- Charts: at most one — a small horizontal capacity chart on Runs (before/after per
  technician) **only if** it reads better than the table. Default to no chart.
- It must look nothing like the Lovable default (large gradient hero, purple accent,
  big rounded cards). Accent is a single restrained hue used for primary actions and
  focus rings only.

## 6. Engineering standards

- **Structure:** `src/lib/api.ts` (client + types + SSE reader), `src/lib/queries.ts`
  (React Query hooks + key factory: `['technicians']`, `['jobs']`, `['job', id]`,
  `['job-events', id]`, `['run', id]`), `src/features/{board,runs,technicians,jobs}/`
  (components + local hooks), `src/routes/` (thin route files). Delete dead
  Lovable scaffolding you no longer use.
- **Data layer:** React Query only. `staleTime` 10s for lists, refetch on window
  focus, background `refetchInterval` **only** on Board (15s) and only while the tab
  is visible — respect the 120/60 min key limit; SSE replaces polling on Runs.
  Mutations invalidate `technicians` + `jobs` (+ `job-events` for the job).
- **Forms:** react-hook-form + zod, schemas mirror backend limits, submit disabled
  while pending, server 422 mapped to fields via `setError`.
- **Accessibility:** WCAG AA contrast in both themes, visible focus rings, every
  icon button has a label, dialogs/sheets trap focus, tables use real `<table>`
  semantics, status strip uses `aria-live`. Keyboard: `/` focuses search, `N` new
  job, `T` new technician, `Esc` closes overlays.
- **Performance:** lists of ≤200 rows render plainly (no virtualization); if a page
  follows cursors beyond 200 rows, virtualize with a lightweight approach or stop and
  show "load more". No layout shift on data arrival (skeleton sizes match rows).
- **Quality gates:** `tsc --noEmit` clean, ESLint clean, Vitest + Testing Library
  with MSW for: API error mapping (401/409/422/429), pagination cursor following,
  SSE parser (multi-line, split chunks, terminal close), eligibility computation,
  run result diff (before/after loads, unplaced reasons). No snapshot tests.
- **Docs:** README section "Run against the backend": `docker compose up -d --wait`
  in `dispatch-engine/`, `.env` with the two vars, `npm i && npm run dev`, and the
  curl seed for the greedy-trap scenario (below).

## 7. Definition of done (verify, do not assume)

Against the real backend (`docker compose up --build -d --wait`, key `dev-local-key`):

1. Seed the **greedy-trap** scenario via the UI: technicians Ada `{hvac, electrical}`
   max 1 and Bob `{hvac}` max 1; jobs "AC" (hvac) then "Wiring" (electrical).
   Board shows both pending, eligibility "2 can take it" / "1 can take it".
2. `Optimize all pending` → Runs live panel walks `queued → running → succeeded`
   via SSE without a page refresh; result reads "Placed 2 of 2", AC → Bob,
   Wiring → Ada, load 0→1 for both; the Board lanes reflect it after invalidation.
3. Job sheet for "Wiring" shows one audit event `pending → assigned` by
   "Optimizer run <id>" linking to that run.
4. `Complete` on AC frees Bob's slot; the lane bar and counts update; the audit
   timeline gains `assigned → completed` by "Manual (API)".
5. Create a job with an unknown skill → red "no technician has <skill>" in the
   queue; `Quick dispatch` on it → 409 toast with the server's message and a
   request id.
6. Wrong `VITE_API_KEY` → the 401 blocking page; stopped backend → the unreachable
   banner and red pill; restart → recovers without reload.
7. 60+ jobs → the list is complete (cursor followed), not truncated at 50.
8. Lighthouse accessibility ≥ 95 on Board and Runs in both themes; no console
   errors or React warnings; `tsc`, ESLint, Vitest green.

## 8. Non-goals (do not build)

Gantt/timeline, map, drag-and-drop placement, job priority/weight, scheduling
dates, technician availability/shifts, multi-user auth or roles, notifications,
CSV export, i18n, offline mode, Supabase or any backend of your own, seed/mock data
in the app. If you believe one of these is required to meet §7, stop and ask.
