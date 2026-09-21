# Web Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `apps/web` from one static placeholder page into a 6-route product suite (landing catalog + one route per domain) in the "Signal Mono" visual theme, with the `hr_policy` live demo restyled in place.

**Architecture:** A shared `DOMAINS` data module feeds both the landing catalog and every route's nav/content. A shared `AppShell` wraps every route with a top nav built from that same data. `hr_policy` keeps its existing fetch logic unchanged, moved into its own route and restyled through a new `SourceCard` component. The other 4 domains get an honest `StubDomainPage` instead of a fake demo.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, plain global CSS (no CSS modules/Tailwind — matches existing convention), `next/font/google`.

**Spec:** `docs/superpowers/specs/2026-09-20-web-frontend-redesign-design.md`

## Global Constraints

- No test framework exists in `apps/web` and none is introduced here (spec §2, §6) — verification per task is `npm run build` (type-checks every file under `app/`, even ones not yet imported by a page) plus `npm run lint`.
- No dark/light mode adaptation — one fixed palette (spec §2).
- Design tokens are exact values from spec §4.2: `--bg:#FFFFFF; --surface:#FAFAFA; --surface-2:#F2F2F2; --border:#E4E4E4; --text:#0A0A0A; --muted:#6B6B6B; --accent:#FF5A1F; --accent-soft:#FFE4D6; --accent-ink:#FFFFFF; --warn:#B8860B; --warn-soft:#F5E9CC`.
- Route slugs are kebab-case (`/hr-policy`), API domain names keep underscores (`hr_policy`) — never conflate the two (spec §4.1).
- All work happens on branch `feat/web-frontend-redesign`, created before Task 1 from an up-to-date `main`. Each task commits to it. The final task pushes and opens a PR against `main` (protected, requires the 4 existing CI checks + `Web (build)`/lint to pass) — it does not merge; report back for confirmation, matching this project's established pattern.
- All commands in this plan run from `/Users/vinoth/project/rag-portfolio` unless a task says otherwise.

---

### Task 1: Branch setup + domain data module

**Files:**
- Create: `apps/web/app/domains.ts`

**Interfaces:**
- Produces: `type DomainSlug = "hr-policy" | "contract-review" | "marketing-hub" | "techdocs" | "it-helpdesk"`; `interface Domain { slug: DomainSlug; apiName: string; name: string; description: string; status: "live" | "stub"; concepts: string[] }`; `export const DOMAINS: Domain[]` (5 entries, in this exact order: hr-policy, contract-review, marketing-hub, techdocs, it-helpdesk)

- [ ] **Step 1: Create the branch**

```bash
git checkout main
git pull origin main --ff-only
git checkout -b feat/web-frontend-redesign
```

- [ ] **Step 2: Write `apps/web/app/domains.ts`**

```typescript
export type DomainSlug =
  | "hr-policy"
  | "contract-review"
  | "marketing-hub"
  | "techdocs"
  | "it-helpdesk";

export interface Domain {
  slug: DomainSlug;
  apiName: string;
  name: string;
  description: string;
  status: "live" | "stub";
  concepts: string[];
}

export const DOMAINS: Domain[] = [
  {
    slug: "hr-policy",
    apiName: "hr_policy",
    name: "HR Policy Q&A",
    description: "Ask a question and get an answer cited against the real policy document.",
    status: "live",
    concepts: [
      "SimpleDirectoryReader",
      "SentenceSplitter",
      "VectorStoreIndex",
      "source attribution",
    ],
  },
  {
    slug: "contract-review",
    apiName: "contract_review",
    name: "Contract Review Assistant",
    description: "Multi-document chat with memory.",
    status: "stub",
    concepts: ["ChatMemoryBuffer", "CondensePlusContextChatEngine", "streaming"],
  },
  {
    slug: "marketing-hub",
    apiName: "marketing_hub",
    name: "Marketing Content Hub",
    description: "Qdrant-backed content generation with metadata filtering.",
    status: "stub",
    concepts: ["Qdrant collections", "metadata filtering", "template routing"],
  },
  {
    slug: "techdocs",
    apiName: "techdocs",
    name: "TechDocs RAG Pipeline",
    description: "Hybrid search — BM25 + vector search, reranked for precision.",
    status: "stub",
    concepts: ["Milvus Lite", "BM25", "RRF hybrid search", "CrossEncoder reranking"],
  },
  {
    slug: "it-helpdesk",
    apiName: "it_helpdesk",
    name: "IT Helpdesk Agent",
    description: "Multi-tool agent orchestrating a knowledge base, search, and calendar.",
    status: "stub",
    concepts: [
      "LangGraph supervisor pattern",
      "Weaviate embedded",
      "DuckDuckGo",
      "SQLite",
      "Google Calendar",
    ],
  },
];
```

- [ ] **Step 3: Verify it compiles**

```bash
cd apps/web && npm run build
```

Expected: build succeeds (this file isn't imported anywhere yet, but `next build` type-checks every file under `app/`).

- [ ] **Step 4: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/domains.ts
git commit -m "feat(web): add shared domain data module"
```

---

### Task 2: Design tokens and base styles

**Files:**
- Modify: `apps/web/app/globals.css` (full replace)

**Interfaces:**
- Produces: CSS custom properties (`--bg`, `--surface`, `--surface-2`, `--border`, `--text`, `--muted`, `--accent`, `--accent-soft`, `--accent-ink`, `--warn`, `--warn-soft`) and classes consumed by later tasks: `.shell-nav`, `.status-badge`/`.status-badge--live`/`.status-badge--stub`, `.domain-grid`, `.domain-card`, `.demo-card`, `.demo-error`, `.answer`, `.provider-tag`, `.sources`, `.sources-label`, `.source-card`, `.source-num`, `.source-body`, `.source-title`, `.source-excerpt`, `.confidence`/`.confidence--high`/`.confidence--mid`, `.stub-page`, `.stub-concepts`.

- [ ] **Step 1: Replace the full contents of `apps/web/app/globals.css`**

```css
:root {
  --bg: #FFFFFF;
  --surface: #FAFAFA;
  --surface-2: #F2F2F2;
  --border: #E4E4E4;
  --text: #0A0A0A;
  --muted: #6B6B6B;
  --accent: #FF5A1F;
  --accent-soft: #FFE4D6;
  --accent-ink: #FFFFFF;
  --warn: #B8860B;
  --warn-soft: #F5E9CC;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
}

body {
  font-family: var(--font-ui, system-ui, -apple-system, sans-serif);
}

main {
  max-width: 880px;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
}

/* App shell nav */
.shell-nav {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border);
}

.shell-nav a {
  padding: 0.4rem 0.85rem;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 500;
  text-decoration: none;
  border: 1px solid var(--border);
  color: var(--muted);
  background: var(--surface);
}

.shell-nav a[data-active="true"] {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

/* Status badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.7rem;
  font-weight: 500;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
}

.status-badge--live {
  color: var(--accent-ink);
  background: var(--accent);
}

.status-badge--stub {
  color: var(--muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
}

/* Domain catalog */
.domain-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.85rem;
  margin-top: 1.5rem;
}

.domain-card {
  display: block;
  padding: 1rem 1.1rem;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  text-decoration: none;
  color: var(--text);
}

.domain-card h3 {
  margin: 0.5rem 0 0.3rem;
  font-size: 1rem;
}

.domain-card p {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
  line-height: 1.45;
}

/* Q&A demo */
.demo-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.demo-card form {
  display: flex;
  gap: 0.5rem;
}

.demo-card input {
  flex: 1;
  padding: 0.55rem 0.8rem;
  font-size: 1rem;
  font-family: var(--font-ui, sans-serif);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
}

.demo-card button {
  padding: 0.55rem 1.1rem;
  font-size: 0.95rem;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: var(--accent-ink);
  cursor: pointer;
}

.demo-card button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.demo-error {
  color: #B3261E;
  font-size: 0.9rem;
  margin-top: 0.75rem;
}

.answer {
  margin: 1.1rem 0 0;
  font-size: 1rem;
  line-height: 1.6;
}

.provider-tag {
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  color: var(--muted);
  margin-top: 0.5rem;
}

/* Sources / citations */
.sources {
  margin-top: 1.25rem;
  display: grid;
  gap: 0.6rem;
}

.sources-label {
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}

.source-card {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  padding: 0.7rem 0.85rem;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}

.source-num {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.source-body {
  flex: 1;
  min-width: 0;
}

.source-title {
  font-size: 0.88rem;
  font-weight: 600;
  margin: 0 0 0.15rem;
}

.source-excerpt {
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0;
  line-height: 1.45;
}

.confidence {
  flex-shrink: 0;
  font-family: var(--font-mono, monospace);
  font-size: 0.68rem;
  font-weight: 600;
  padding: 0.15rem 0.4rem;
  border-radius: 5px;
}

.confidence--high {
  color: var(--accent);
  background: var(--accent-soft);
}

.confidence--mid {
  color: var(--warn);
  background: var(--warn-soft);
}

/* Stub domain page */
.stub-page p {
  color: var(--muted);
  max-width: 60ch;
  line-height: 1.55;
}

.stub-concepts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 1rem;
  padding: 0;
  list-style: none;
}

.stub-concepts li {
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--muted);
}

@media (max-width: 480px) {
  main {
    padding: 1.5rem 1rem 3rem;
  }
}
```

- [ ] **Step 2: Verify build still passes**

```bash
cd apps/web && npm run build
```

Expected: succeeds. (The page will look unstyled/broken if opened right now since `page.tsx` still references old classes — that's expected until Task 9; this step only checks CSS is valid and the build pipeline doesn't choke on it.)

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/globals.css
git commit -m "feat(web): replace styles with Signal Mono design tokens"
```

---

### Task 3: Font loading

**Files:**
- Modify: `apps/web/app/layout.tsx`

**Interfaces:**
- Produces: CSS variables `--font-ui` and `--font-mono` available globally via classes on `<html>`.

- [ ] **Step 1: Replace `apps/web/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import { Sora, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const sora = Sora({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-ui",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "RAG Portfolio Platform",
  description: "A governed, cost-controlled agentic AI platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sora.variable} ${plexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds, no font-loading errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/layout.tsx
git commit -m "feat(web): load Sora + IBM Plex Mono via next/font"
```

---

### Task 4: StatusBadge component

**Files:**
- Create: `apps/web/app/components/StatusBadge.tsx`

**Interfaces:**
- Consumes: CSS classes `.status-badge`, `.status-badge--live`, `.status-badge--stub` (Task 2)
- Produces: `function StatusBadge({ status }: { status: "live" | "stub" }): JSX.Element`

- [ ] **Step 1: Write `apps/web/app/components/StatusBadge.tsx`**

```tsx
interface StatusBadgeProps {
  status: "live" | "stub";
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${status}`}>
      {status === "live" ? "Live" : "Not wired yet"}
    </span>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/components/StatusBadge.tsx
git commit -m "feat(web): add StatusBadge component"
```

---

### Task 5: SourceCard component

**Files:**
- Create: `apps/web/app/components/SourceCard.tsx`

**Interfaces:**
- Consumes: CSS classes `.source-card`, `.source-num`, `.source-body`, `.source-title`, `.source-excerpt`, `.confidence`, `.confidence--high`, `.confidence--mid` (Task 2)
- Produces: `function SourceCard({ index, header, excerpt, relevance }: { index: number; header: string; excerpt: string; relevance: number }): JSX.Element`

- [ ] **Step 1: Write `apps/web/app/components/SourceCard.tsx`**

```tsx
interface SourceCardProps {
  index: number;
  header: string;
  excerpt: string;
  relevance: number;
}

export function SourceCard({ index, header, excerpt, relevance }: SourceCardProps) {
  const confidenceClass = relevance >= 0.7 ? "confidence--high" : "confidence--mid";
  return (
    <div className="source-card">
      <div className="source-num">{index}</div>
      <div className="source-body">
        <p className="source-title">{header}</p>
        <p className="source-excerpt">{excerpt}</p>
      </div>
      <div className={`confidence ${confidenceClass}`}>{relevance.toFixed(2)}</div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/components/SourceCard.tsx
git commit -m "feat(web): add SourceCard citation component"
```

---

### Task 6: AppShell component

**Files:**
- Create: `apps/web/app/components/AppShell.tsx`

**Interfaces:**
- Consumes: `DOMAINS` from `../domains` (Task 1); CSS class `.shell-nav` (Task 2)
- Produces: `function AppShell({ children }: { children: React.ReactNode }): JSX.Element`

- [ ] **Step 1: Write `apps/web/app/components/AppShell.tsx`**

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOMAINS } from "../domains";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <nav className="shell-nav">
        <Link href="/" data-active={pathname === "/" ? "true" : "false"}>
          RAG Portfolio
        </Link>
        {DOMAINS.map((d) => (
          <Link
            key={d.slug}
            href={`/${d.slug}`}
            data-active={pathname === `/${d.slug}` ? "true" : "false"}
          >
            {d.name}
          </Link>
        ))}
      </nav>
      <main>{children}</main>
    </>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/components/AppShell.tsx
git commit -m "feat(web): add AppShell nav component"
```

---

### Task 7: DomainCard component

**Files:**
- Create: `apps/web/app/components/DomainCard.tsx`

**Interfaces:**
- Consumes: `StatusBadge` (Task 4); CSS class `.domain-card` (Task 2)
- Produces: `function DomainCard({ name, description, status, href }: { name: string; description: string; status: "live" | "stub"; href: string }): JSX.Element`

- [ ] **Step 1: Write `apps/web/app/components/DomainCard.tsx`**

```tsx
import Link from "next/link";
import { StatusBadge } from "./StatusBadge";

interface DomainCardProps {
  name: string;
  description: string;
  status: "live" | "stub";
  href: string;
}

export function DomainCard({ name, description, status, href }: DomainCardProps) {
  return (
    <Link href={href} className="domain-card">
      <StatusBadge status={status} />
      <h3>{name}</h3>
      <p>{description}</p>
    </Link>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/components/DomainCard.tsx
git commit -m "feat(web): add DomainCard component"
```

---

### Task 8: StubDomainPage component

**Files:**
- Create: `apps/web/app/components/StubDomainPage.tsx`

**Interfaces:**
- Consumes: `StatusBadge` (Task 4); CSS classes `.stub-page`, `.stub-concepts` (Task 2)
- Produces: `function StubDomainPage({ name, description, concepts }: { name: string; description: string; concepts: string[] }): JSX.Element`

- [ ] **Step 1: Write `apps/web/app/components/StubDomainPage.tsx`**

```tsx
import { StatusBadge } from "./StatusBadge";

interface StubDomainPageProps {
  name: string;
  description: string;
  concepts: string[];
}

export function StubDomainPage({ name, description, concepts }: StubDomainPageProps) {
  return (
    <div className="stub-page">
      <StatusBadge status="stub" />
      <h2>{name}</h2>
      <p>{description}</p>
      <ul className="stub-concepts">
        {concepts.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/components/StubDomainPage.tsx
git commit -m "feat(web): add StubDomainPage component"
```

---

### Task 9: Landing catalog page

**Files:**
- Modify: `apps/web/app/page.tsx` (full replace)

**Interfaces:**
- Consumes: `AppShell` (Task 6), `DomainCard` (Task 7), `DOMAINS` (Task 1)

- [ ] **Step 1: Replace `apps/web/app/page.tsx`**

```tsx
import { AppShell } from "./components/AppShell";
import { DomainCard } from "./components/DomainCard";
import { DOMAINS } from "./domains";

export default function HomePage() {
  return (
    <AppShell>
      <h1>RAG Portfolio Platform</h1>
      <p>A governed, cost-controlled agentic AI platform.</p>
      <div className="domain-grid">
        {DOMAINS.map((d) => (
          <DomainCard
            key={d.slug}
            name={d.name}
            description={d.description}
            status={d.status}
            href={`/${d.slug}`}
          />
        ))}
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Verify rendered content locally**

```bash
cd apps/web && npm run build && npx next start -p 3100 &
sleep 3
curl -s http://localhost:3100 | grep -o "HR Policy Q&amp;A\|Contract Review Assistant\|Not wired yet\|Live" | sort | uniq -c
kill %1
```

Expected: shows 1 "Live" badge (hr-policy) and 4 "Not wired yet" badges, plus all 5 domain names present.

- [ ] **Step 4: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/page.tsx
git commit -m "feat(web): rebuild landing page as domain catalog"
```

---

### Task 10: `/hr-policy` route

**Files:**
- Create: `apps/web/app/hr-policy/page.tsx`
- Create: `apps/web/app/hr-policy/hr-policy-demo.tsx` (moved + restyled from `apps/web/app/hr-policy-demo.tsx`)
- Delete: `apps/web/app/hr-policy-demo.tsx`

**Interfaces:**
- Consumes: `AppShell` (Task 6), `SourceCard` (Task 5), `DOMAINS` (Task 1, for `apiName` — the fetch URL derives the API domain name from data rather than a hardcoded string, since spec §4.1 explicitly calls out never conflating route slugs and API domain names)
- Produces: `HrPolicyDemo` component (same fetch behavior as before, restyled render)

- [ ] **Step 1: Delete the old file**

```bash
git rm apps/web/app/hr-policy-demo.tsx
```

- [ ] **Step 2: Write `apps/web/app/hr-policy/hr-policy-demo.tsx`**

```tsx
"use client";

import { useState } from "react";
import { SourceCard } from "../components/SourceCard";
import { DOMAINS } from "../domains";

const API_BASE_URL = "https://rag-portfolio-api-w57v.onrender.com";
const domain = DOMAINS.find((d) => d.slug === "hr-policy")!;

interface Source {
  header: string;
  excerpt: string;
  relevance: number;
}

interface AskResponse {
  answer: string;
  sources: Source[];
  provider_used: string;
}

export function HrPolicyDemo() {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;

    setStatus("loading");
    setErrorMessage("");
    setResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/${domain.apiName}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Request failed (${response.status})`);
      }

      const data: AskResponse = await response.json();
      setResult(data);
      setStatus("idle");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  return (
    <div className="demo-card">
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about HR policy..."
          disabled={status === "loading"}
        />
        <button type="submit" disabled={status === "loading" || !question.trim()}>
          {status === "loading" ? "Asking..." : "Ask"}
        </button>
      </form>

      {status === "error" && <p className="demo-error">{errorMessage}</p>}

      {result && (
        <div>
          <p className="answer">{result.answer}</p>
          <p className="provider-tag">answered via {result.provider_used}</p>
          <div className="sources">
            <div className="sources-label">{result.sources.length} source(s)</div>
            {result.sources.map((source, i) => (
              <SourceCard
                key={i}
                index={i + 1}
                header={source.header}
                excerpt={source.excerpt}
                relevance={source.relevance}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write `apps/web/app/hr-policy/page.tsx`**

```tsx
import { AppShell } from "../components/AppShell";
import { HrPolicyDemo } from "./hr-policy-demo";

export default function HrPolicyPage() {
  return (
    <AppShell>
      <h1>HR Policy Q&amp;A</h1>
      <p>Ask a question and get an answer cited against the real policy document.</p>
      <HrPolicyDemo />
    </AppShell>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds — no references to the deleted top-level `hr-policy-demo.tsx` remain (the old `page.tsx` that imported it was already replaced in Task 9).

- [ ] **Step 5: Manually verify in a browser**

Run `npm run dev` in `apps/web`, open `http://localhost:3000/hr-policy`, ask "How many vacation days do employees get?", confirm a real cited answer renders with `SourceCard`s and a relevance score on each. Stop the dev server after.

- [ ] **Step 6: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/hr-policy/page.tsx apps/web/app/hr-policy/hr-policy-demo.tsx apps/web/app/hr-policy-demo.tsx
git commit -m "feat(web): move hr_policy demo to /hr-policy route, restyle with SourceCard"
```

---

### Task 11: Four stub domain routes

**Files:**
- Create: `apps/web/app/contract-review/page.tsx`
- Create: `apps/web/app/marketing-hub/page.tsx`
- Create: `apps/web/app/techdocs/page.tsx`
- Create: `apps/web/app/it-helpdesk/page.tsx`

**Interfaces:**
- Consumes: `AppShell` (Task 6), `StubDomainPage` (Task 8), `DOMAINS` (Task 1)

- [ ] **Step 1: Write `apps/web/app/contract-review/page.tsx`**

```tsx
import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "contract-review")!;

export default function ContractReviewPage() {
  return (
    <AppShell>
      <StubDomainPage
        name={domain.name}
        description={domain.description}
        concepts={domain.concepts}
      />
    </AppShell>
  );
}
```

- [ ] **Step 2: Write `apps/web/app/marketing-hub/page.tsx`**

```tsx
import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "marketing-hub")!;

export default function MarketingHubPage() {
  return (
    <AppShell>
      <StubDomainPage
        name={domain.name}
        description={domain.description}
        concepts={domain.concepts}
      />
    </AppShell>
  );
}
```

- [ ] **Step 3: Write `apps/web/app/techdocs/page.tsx`**

```tsx
import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "techdocs")!;

export default function TechDocsPage() {
  return (
    <AppShell>
      <StubDomainPage
        name={domain.name}
        description={domain.description}
        concepts={domain.concepts}
      />
    </AppShell>
  );
}
```

- [ ] **Step 4: Write `apps/web/app/it-helpdesk/page.tsx`**

```tsx
import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "it-helpdesk")!;

export default function ItHelpdeskPage() {
  return (
    <AppShell>
      <StubDomainPage
        name={domain.name}
        description={domain.description}
        concepts={domain.concepts}
      />
    </AppShell>
  );
}
```

- [ ] **Step 5: Verify build**

```bash
cd apps/web && npm run build
```

Expected: succeeds, build output lists all 6 routes (`/`, `/hr-policy`, `/contract-review`, `/marketing-hub`, `/techdocs`, `/it-helpdesk`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vinoth/project/rag-portfolio
git add apps/web/app/contract-review apps/web/app/marketing-hub apps/web/app/techdocs apps/web/app/it-helpdesk
git commit -m "feat(web): add stub pages for the 4 unwired domains"
```

---

### Task 12: Final verification, push, and PR

**Files:** none (verification + git operations only)

- [ ] **Step 1: Full build + lint**

```bash
cd apps/web && npm run build && npm run lint
```

Expected: both pass with no errors.

- [ ] **Step 2: Manual browser walkthrough**

Run `npm run dev`, and in a browser check each of the 6 routes against spec §7's success criteria:
- `/` shows the domain-catalog grid with 5 cards (1 "Live", 4 "Not wired yet"), Signal Mono styling (white/black, orange accent), not the old bullet list
- `/hr-policy` — ask a real question, confirm answer + `SourceCard`s render correctly
- `/contract-review`, `/marketing-hub`, `/techdocs`, `/it-helpdesk` — each shows its real description + concept tags, "Not wired yet" badge, no fake demo
- Nav bar present and highlights the current route on all 6 pages
- Resize to a narrow (~400px) width and confirm no horizontal scroll or broken layout

Stop the dev server after.

- [ ] **Step 3: Push and open PR**

```bash
cd /Users/vinoth/project/rag-portfolio
git push -u origin feat/web-frontend-redesign
gh pr create --title "feat: Signal Mono redesign — landing catalog + per-domain routes" --body "$(cat <<'EOF'
## Summary
- Implements docs/superpowers/specs/2026-09-20-web-frontend-redesign-design.md
- Replaces the single static placeholder page with a landing catalog + one route per domain
- New Signal Mono design tokens (black/white base, single orange accent) via globals.css + next/font
- hr_policy demo moved to /hr-policy, restyled, citations now render through a shared SourceCard component
- The 4 unwired domains get an honest StubDomainPage with real README-sourced descriptions instead of a placeholder list item

## Test plan
- [x] npm run build (apps/web) — all 6 routes compile
- [x] npm run lint (apps/web) — clean
- [x] Manual browser walkthrough of all 6 routes against spec success criteria
- [x] hr-policy route verified against the live API with a real question
EOF
)"
```

- [ ] **Step 4: Report CI status back**

Watch the PR's checks (`gh pr checks <number>`) until all pass, then report back — do not merge without explicit confirmation, matching this project's established pattern.

---

## Self-Review Notes

- **Spec coverage:** §4.1 (routes) → Tasks 9-11. §4.2 (tokens) → Task 2. §4.3 (components) → Tasks 4-8. §4.4 (stub content) → Task 1 (data) + Task 11 (usage). §4.5 (data flow) → Task 10 (hr_policy unchanged fetch) + Tasks 9/11 (static). §5 (error handling) → Task 10 preserves the existing try/catch unchanged. §6 (testing) → every task's build-verification step, no new framework. §7 (success criteria) → Task 12.
- **Placeholder scan:** no TBD/TODO; every task has complete, runnable code.
- **Type consistency:** `DomainSlug`/`Domain` (Task 1) used identically by `AppShell` (Task 6), `DomainCard`'s `status`/`href` props (Task 7, matches `Domain.status`/`` `/${d.slug}` ``), and all 4 stub pages (Task 11, `DOMAINS.find((d) => d.slug === "...")`). `SourceCard`'s props (Task 5) match exactly how `hr-policy-demo.tsx` calls it (Task 10). `StatusBadge`'s `status: "live" | "stub"` (Task 4) matches `Domain.status`'s type (Task 1) and `StubDomainPage`'s hardcoded `status="stub"` (Task 8).
- **Route/slug consistency:** every `href`/`Link` in `AppShell`, `DomainCard` usage, and the 4 stub pages' self-lookups all derive from `DOMAINS[].slug`, never a separately hand-typed string — eliminates the risk of a nav link and a route folder name drifting apart.
