# Dispatch Engine — Operations Console (Faz 10, v2 — visual redesign)

> Paste everything below the line into Lovable.dev (or hand it to a coding agent
> working in `dispatch-helper-ui/`). This replaces the earlier Faz 10 build, which
> was functionally correct (verified end-to-end against the real backend, 100/100
> Lighthouse accessibility) but looked generic and cramped. This version keeps every
> product and API requirement, and replaces only the visual language.

---

## Context

"Dispatch Engine" is a field-service dispatch backend that assigns jobs to
technicians by **skill** and **capacity**. The backend is finished and running; you
are building the operator console a dispatcher keeps open all day. This is a
**frontend only** project — no backend, no Supabase, no database, no auth provider,
no mock data. Every byte of data comes from the REST API described below. If the
API is unreachable, say so — never fabricate data.

The product's one differentiating fact, which the UI must make visible:
**the engine decides, humans trigger and audit.** Two ways to assign a job:

- **Quick dispatch** (`POST /jobs/{id}/dispatch`): one job, synchronous, greedy —
  "least-loaded technician who has the skill." Fast, but order-dependent.
- **Optimize** (`POST /dispatch-runs`): every pending job at once, solved globally
  with OR-Tools (min-cost max-flow) so the maximum number of jobs is placed and the
  resulting load is as even as possible. Async — poll or stream for the result.

There is no scheduling time, no location, no travel time, no priority in the data
model. Don't invent them. Don't build a Gantt, a map, or drag-and-drop placement —
there's no API to place a job on a chosen technician, so that UI would lie.

## Visual direction — read this before the screens

The single biggest thing to get right: **this must look like a well-funded B2B
SaaS tool a dispatcher would trust with real jobs**, not a generic admin template
and not a cramped spreadsheet. Calibrate against **Linear, Height, Vercel's
dashboard, Attio, and Retool's newer surfaces** — calm, confident, a little bit of
craft, generous whitespace, one deliberate accent color, real typographic
hierarchy. Specifically:

- **Type scale with real hierarchy.** Page/section titles at 20–24px, 600 weight,
  a touch tighter letter-spacing. Body text at 14px, not 12–13px — this is an
  operator's tool used for hours, not a data grid crammed onto one screen.
  Secondary/meta text at 13px, muted. Use one typeface family (a clean grotesk —
  Inter, Geist, or similar) for everything; don't mix a "display" face in.
- **Breathing room, not brutal density.** Rows in lists/tables should be
  44–52px tall with 12–16px horizontal padding, not 36px. Panels/cards get
  16–24px internal padding. A page's outer margins should feel generous
  (24–32px), with clear vertical rhythm between sections (24–32px gaps). The goal
  is a screen that still shows a lot of information, but never feels like it's
  fighting the eye. If in doubt, add space rather than remove it.
- **Depth, subtly.** Cards and panels may have a soft 1px border AND a very
  faint shadow (barely-there, like `0 1px 2px rgba(0,0,0,0.04)` in light mode) to
  lift them off the page — total flatness is part of why the last version read as
  generic. Reserve a stronger shadow for the slide-over sheet and dialogs only.
- **One real accent color with presence.** Pick a single confident accent (a
  saturated indigo, violet, or blue — something with a bit of character, not a
  washed-out corporate blue) for primary buttons, active nav state, links, and
  focus rings. Neutrals should be genuinely neutral-warm greys (not cold
  blue-greys) so the accent has something to pop against. Status colors (amber for
  "at risk," red for "blocked/failed") are used sparingly and only where the brief
  below says so — this is still a calm, mostly-grey product, not a colorful one;
  the difference between "calm" and "cramped/lifeless" is the type scale, spacing,
  and depth above, not extra color.
- **Rounded corners, consistent radius** (8–10px for cards/inputs/buttons, 12px
  for the sheet/dialog) — soft but not bubbly.
- **Real empty and loading states** — skeletons matched to actual row height (no
  layout shift), and empty states with a short sentence plus a clear call to
  action, not a bare "No data."
- **Micro-interactions**: hover states that lift a card or tint a row, a smooth
  120–180ms transition on the slide-over sheet and status changes, a calm
  indeterminate progress indicator (not a spinner) while a run is in flight.
- Dark mode is a first-class second pass, not an afterthought — same hierarchy,
  same warmth, inverted.
- **Anti-patterns to avoid, explicitly:**
  - The generic "AI dashboard template" look: big rounded gradient hero cards,
    purple-to-pink gradients, oversized stat tiles with glow effects, decorative
    icons everywhere.
  - The opposite failure: a flat, dense, spreadsheet-grey wall of 12px text with
    no shadows, no accent, no hierarchy — technically information-dense but
    unpleasant to look at for hours. (This is what the previous build shipped —
    don't repeat it.)
  - Never use the word "AI" anywhere in the UI. Use the backend's own words:
    `pending / assigned / completed`, `queued / running / succeeded / failed`,
    "Quick dispatch (greedy)", "Optimize (global)".

## Hard constraints

1. **Frontend only.** No Supabase, no database, no server-side data store, no auth
   provider, no mock/seed data fallback. If you (Lovable) would normally reach for
   Supabase, don't — this connects to the existing REST API below with `fetch`.
2. Config via env: `VITE_API_BASE_URL` (default `http://localhost:8000/v1`) and
   `VITE_API_KEY`. Send `X-API-Key: <VITE_API_KEY>` on every `/v1` request.
   `/health` and `/ready` live at the API root (outside `/v1`) and need no key.
3. All API calls run in the browser (the API is `localhost` from the browser's
   point of view, and the key lives in the browser env).
4. No scheduling time, no location, no travel, no priority — don't invent them.
   No Gantt, no map, no drag-and-drop placement.

## API contract

```ts
type Technician = { id: string; name: string; max_jobs: number; skills: string[]; load: number };
type JobStatus = "pending" | "assigned" | "completed";
type Job = { id: string; title: string; skill: string; status: JobStatus; technician_id: string | null };
type JobEvent = { id: string; job_id: string; from_status: JobStatus; to_status: JobStatus; technician_id: string | null; actor: string; created_at: string };
type RunStatus = "queued" | "running" | "succeeded" | "failed";
type Assignment = { job_id: string; technician_id: string };
type DispatchRun = { id: string; status: RunStatus; assignments: Assignment[]; error: string | null };
```

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/technicians?limit=&cursor=` | array body; `X-Next-Cursor` response header when another page exists — follow it, don't silently show only the first 50 |
| POST | `/technicians` | `{name, max_jobs (1..100), skills: string[] (≥1, case-sensitive)}` → 201 |
| GET | `/jobs?limit=&cursor=` | same pagination |
| POST | `/jobs` | `{title (1..200 chars), skill}` → 201 |
| POST | `/jobs/{id}/dispatch` | greedy single dispatch → Job; 409 with `{detail}` if nobody can take it |
| POST | `/jobs/{id}/complete` | frees the technician's slot → Job; 409 if not assigned |
| GET | `/jobs/{id}/events` | `JobEvent[]` oldest→newest; `actor` is `"api"` (manual) or `"worker:<run_id>"` (optimizer) |
| POST | `/dispatch-runs` | 202, `{id, status:"queued", assignments:[], error:null}` |
| GET | `/dispatch-runs/{id}` | poll this every ~2s while not terminal |
| GET | `${root}/health` | unauthenticated: `{status, version}` |

Errors: `{detail: string}` on 401/404/409, or `{detail: [{loc, msg, type}]}` on 422.
Show the server's own message on 409/422 in toasts — never a generic "Error."

## Screens

Left rail (collapsible) + top bar (app name, a small environment/health
indicator, theme toggle). Three screens:

### 1. Board (default screen)

- **Unassigned queue** (left): one row per pending job — title, a skill pill, and
  an eligibility line computed from the technician list: how many technicians
  could take it right now (`skills.includes(job.skill) && load < max_jobs`); if
  none currently have capacity but someone has the skill, say so calmly (amber
  accent, small dot); if literally nobody has the skill, say so more firmly (red
  accent). This is the only place color signals a problem — everywhere else stays
  neutral. Each row: a "Quick dispatch" action and a click-to-open job detail.
- **Technician capacity** (right): one card per technician — name, skill pills, a
  clean capacity indicator (a short segmented bar or a simple "2 of 3 slots" read-
  out — pick whichever reads calmer, not a jammed row of tiny boxes), and their
  currently assigned jobs as small removable chips (hover reveals "Complete"). A
  technician at capacity is visually quieter (not red) — muted background tint,
  not reduced text opacity (text must stay fully legible — don't dim it below
  readable contrast).
- **Action bar** (sticky top): search, skill filter chips, and the primary
  "Optimize all pending" button — on click, show a short confirm ("place up to N
  jobs across M technicians with K free slots") before firing `POST
  /dispatch-runs`, then take the user to Runs.

### 2. Runs

- A **live panel** showing the current/most recent run: a calm status strip
  (`queued → running → succeeded/failed`), polling `GET /dispatch-runs/{id}`
  every ~2s while not terminal.
- On completion: "Placed **A** of **P** pending jobs" as the headline, a one-line
  explanation ("Global optimization: places the most jobs possible, then balances
  the resulting load"), a results table (job → technician → load before/after),
  and an "unplaced" list with a plain-language reason per job.
- A short history list below (client-side only — the API has no run-list
  endpoint; keep the last ~50 in `localStorage`).

### 3. Technicians

A clean, roomy table: name, skills, capacity, assigned-job count, sortable by
name or free capacity. "New technician" opens a form: name, max jobs (1–100),
skills as a tag input (Enter/comma to add). Mention skills are case-sensitive.

### Job detail

A right-side slide-over (not a full navigation) with the job's status, technician,
actions matching its status (Quick dispatch / Complete), and a chronological audit
timeline from `GET /jobs/{id}/events` — each entry showing the transition, who did
it ("Manual" for `actor:"api"`, "Optimizer run" linking to that run for
`actor:"worker:<id>"`), and a timestamp.

## Definition of done

Seed two technicians (Ada: skills `{hvac, electrical}`, max 1; Bob: skills
`{hvac}`, max 1) and two jobs ("AC", skill `hvac`; "Wiring", skill `electrical`).
The Board should show both correctly with eligibility text. Running "Optimize all
pending" should place both (AC → Bob, Wiring → Ada — the greedy path would instead
give both to Ada's first-come job and strand the second), and the job detail's
audit trail should show the optimizer as the actor, linking back to that run.
