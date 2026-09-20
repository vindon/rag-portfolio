# Web Frontend Redesign — Design Spec

## 1. Overview & Goals

`apps/web` is currently a single static page: a title, a one-line description,
and a bare `<ul>` listing all 5 domains as "coming online" — plus, as of the
`hr-policy-web-demo` PR, one working client-side form for `hr_policy` bolted
onto the bottom of that same page. There is no visual identity, no shared
layout, and no per-domain routing — sharing "here's my RAG portfolio" today
means sharing a page that looks unfinished even though the `hr_policy` domain
is a real, live, working RAG endpoint.

This plan gives the frontend a deliberate visual identity ("Signal Mono" —
true black/white base, one sharp orange accent spent only on what needs
attention, grounded in the Vercel/shadcn AI Elements design lineage) and
restructures it from one page into a real small product suite: a landing
catalog plus one route per domain.

**Goals:**
- Establish design tokens (color, type) as CSS variables in `globals.css`,
  replacing the current ad hoc plain styles.
- Restructure `apps/web` from a single page into 6 routes: a landing catalog
  (`/`) plus one route per domain (`/hr-policy`, `/contract-review`,
  `/marketing-hub`, `/techdocs`, `/it-helpdesk`).
- Extract `SourceCard` (the citation display) out of `hr-policy-demo.tsx`
  into a reusable component — the same visual pattern any future working
  domain will need.
- Give the 4 not-yet-wired domains an honest, real-copy "not wired yet"
  page instead of a one-line list item — using the actual concepts from
  each domain's README description, not filler text.

## 2. Non-Goals / Explicit Scope Boundaries

- **No backend changes.** `hr_policy`'s fetch/answer logic (`hr-policy-demo.tsx`'s
  `handleSubmit`) does not change — only where it lives (`/hr-policy` route)
  and how it's styled.
- **No dark/light mode toggle.** Signal Mono is one deliberate, fixed visual
  identity for the whole site — not something that adapts to OS
  light/dark preference. Revisit only if explicitly asked later.
- **No test framework.** `apps/web` has never had one; CI gates on
  `next build` + `eslint` only. This plan doesn't introduce one.
- **No animation/motion system.** Static layout, no page-transition or
  micro-interaction work — YAGNI until the site actually needs it.
- **No CMS or dynamic content.** The 4 stub pages' copy is hand-written
  once from the README, not pulled from any data source.
- **No changes to `apps/api`** beyond what's already merged (CORS).

## 3. Decision Record (from brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Visual theme | "Signal Mono" (black/white, orange accent) | User's explicit pick after reviewing 5 real-rendered options against actual HR policy content |
| Accent color | `#FF5A1F`, kept as shown | User confirmed, declined seeing alternates |
| Site structure | Landing catalog + one route per domain (Approach C) | User's explicit pick over single-page (A) or routes-with-no-landing (B); matches how real multi-tool SaaS suites present themselves, and lets individual domains be shared as standalone links |
| Scope of visual pass | All 5 domains restyled now, not just `hr_policy` | User's explicit pick — a hiring manager clicking through sees one coherent product suite, not one polished page next to 4 bare placeholders |
| Font loading | `next/font/google` (Sora + IBM Plex Mono) | Real Next.js font optimization, replacing the artifact mockup's `@import` (which was fine for a throwaway comparison page, not for production) |
| Stub page copy | Real text from `README.md`'s "Concepts" column per domain | Matches artifact-design guidance and this project's own convention: real content, never lorem/filler |

## 4. Architecture

### 4.1 Route layout

```
apps/web/app/
├── layout.tsx                  # root layout — fonts, metadata (existing, extended)
├── globals.css                 # design tokens + component styles (existing, replaced)
├── page.tsx                    # landing catalog — 5 DomainCards
├── components/
│   ├── AppShell.tsx             # top nav, wraps every route below
│   ├── DomainCard.tsx           # landing page catalog tile
│   ├── StatusBadge.tsx          # "Live" / "Not wired yet" pill
│   ├── SourceCard.tsx           # citation card (extracted from hr-policy-demo)
│   └── StubDomainPage.tsx       # shared template for the 4 unwired domains
├── hr-policy/
│   ├── page.tsx                 # wraps AppShell + HrPolicyDemo
│   └── hr-policy-demo.tsx       # moved from app/ root, restyled, uses SourceCard
├── contract-review/page.tsx     # AppShell + StubDomainPage
├── marketing-hub/page.tsx       # AppShell + StubDomainPage
├── techdocs/page.tsx            # AppShell + StubDomainPage
└── it-helpdesk/page.tsx         # AppShell + StubDomainPage
```

Domain slugs in routes match `apps/api`'s actual `DOMAIN_NAMES`
(`hr_policy`, `contract_review`, `marketing_hub`, `techdocs`, `it_helpdesk`)
with underscores replaced by hyphens for URL convention (`/hr-policy`, not
`/hr_policy`) — Next.js route segments are kebab-case by convention; the
API domain slug itself is unchanged.

### 4.2 Design tokens (`globals.css`)

```css
:root {
  --font-ui: 'Sora', system-ui, -apple-system, sans-serif;
  --font-mono: 'IBM Plex Mono', 'SF Mono', monospace;
  --bg: #FFFFFF; --surface: #FAFAFA; --surface-2: #F2F2F2; --border: #E4E4E4;
  --text: #0A0A0A; --muted: #6B6B6B; --accent: #FF5A1F; --accent-soft: #FFE4D6;
  --accent-ink: #FFFFFF; --warn: #B8860B; --warn-soft: #F5E9CC;
}
```

Single fixed palette — no `@media (prefers-color-scheme)` or `[data-theme]`
blocks, per the Non-Goals above. Fonts loaded via `next/font/google` in
`layout.tsx` and exposed as CSS variables on `<html>`, matching Next.js's
standard font-optimization pattern (avoids the render-blocking `@import`
used in the throwaway comparison artifact).

### 4.3 Components

- **`AppShell`** — props: `active: DomainSlug`. Renders the top nav (site
  title + 5 links, current one visually marked via `StatusBadge`-adjacent
  styling) and wraps `children`. Used by all 6 routes' `page.tsx`.
- **`DomainCard`** — props: `name`, `description`, `status: "live" | "stub"`,
  `href`. Landing-page catalog tile; whole card is a `<Link>`.
- **`StatusBadge`** — props: `status: "live" | "stub"`. Small pill: filled
  accent for "Live", muted outline ring for "Not wired yet".
- **`SourceCard`** — props: `index: number`, `header: string`,
  `excerpt: string`, `relevance: number`. Pulled out of `hr-policy-demo.tsx`
  verbatim (same markup/logic, just parameterized) so it's the shared
  citation pattern any future wired domain reuses.
- **`StubDomainPage`** — props: `name`, `description`, `concepts: string[]`.
  Renders a `StatusBadge status="stub"`, the description, and a small list
  of what the domain's concepts are (from the README) — honest "not wired
  yet" state, not a fake demo.

### 4.4 Content for the 4 stub pages

Pulled directly from `README.md`'s existing "Projects at a Glance" table —
not newly invented:

| Route | Description | Concepts |
|---|---|---|
| `/contract-review` | Multi-document chat with memory. | `ChatMemoryBuffer`, `CondensePlusContextChatEngine`, streaming |
| `/marketing-hub` | Qdrant-backed content generation with metadata filtering. | Qdrant collections, metadata filtering, template routing |
| `/techdocs` | Hybrid search — BM25 + vector search, reranked for precision. | Milvus Lite, BM25, RRF hybrid search, CrossEncoder reranking |
| `/it-helpdesk` | Multi-tool agent orchestrating a knowledge base, search, and calendar. | LangGraph supervisor pattern, Weaviate embedded, DuckDuckGo, SQLite, Google Calendar |

### 4.5 Data flow

- **`/hr-policy`**: unchanged — client-side `fetch` to
  `https://rag-portfolio-api-w57v.onrender.com/api/v1/hr_policy/ask`,
  now rendering results through `SourceCard` instead of inline markup.
- **`/`, and the 4 stub routes**: fully static, no fetch, server-rendered.

## 5. Error Handling

No new error paths — `hr-policy-demo.tsx`'s existing `try/catch` around the
`fetch` (showing `err.message` or the API's `detail` field) carries over
unchanged into the new route. Stub pages have nothing to fail since they're
static.

## 6. Testing Strategy

Matches existing convention: `next build` (catches type/compile errors
across all 6 new routes) and `eslint .` are the CI gates, same as today. No
new test framework introduced (see Non-Goals).

## 7. Success Criteria

- `https://rag-portfolio-web.vercel.app/` shows a landing catalog of 5
  `DomainCard`s in the Signal Mono theme, not the current plain bullet list.
- `https://rag-portfolio-web.vercel.app/hr-policy` has the working Q&A form,
  restyled, with citations rendered via `SourceCard`.
- The other 4 routes render their real README-sourced description and a
  "Not wired yet" `StatusBadge` — no fake demos, no lorem ipsum.
- `next build` and `eslint .` both pass in CI.
- Manually verified in a browser (not just `curl`/build success) — this is
  the same lesson from the last round of this project: a build passing and
  a page actually looking right are two different checks.

## Self-Review Notes

- **Placeholder scan:** no TBD/TODO — the 4 stub domains' copy is fully
  specified in §4.4, sourced from the existing README rather than invented
  in the plan.
- **Scope check:** single, focused change (frontend only); doesn't touch
  `apps/api` beyond what's already merged, doesn't introduce new
  infrastructure or dependencies beyond two Google Fonts already selected.
- **Ambiguity check:** route naming (kebab-case URLs vs the API's
  underscore domain slugs) explicitly called out in §4.1 so an implementer
  doesn't guess wrong and break API calls by mismatching the two.
