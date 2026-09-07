# Platform Foundation (Week 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the monorepo skeleton — a FastAPI gateway with stub routes for all 5 domains, a Next.js frontend shell, and a CI pipeline that actually blocks bad code — deployed live on free-tier infrastructure.

**Architecture:** `apps/api` is a FastAPI app exposing `/health` and one `/api/v1/{domain}/status` stub per domain, packaged for Fly.io's remote Docker builder. `apps/web` is a minimal Next.js app listing the 5 domains, deployed to Vercel. GitHub Actions runs lint/type-check/test on every PR for both.

**Tech Stack:** Python 3.12 (container) / 3.11+ (source-compatible), FastAPI, pytest, ruff, black, mypy, Next.js 15, TypeScript, GitHub Actions, Fly.io, Vercel.

**Spec:** `docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md` (see §3.1-3.3 for the monorepo layout this plan builds, §9 for the code-quality gate, §11 for the infra choices, §13 Week 1 row for exit criteria).

## Global Constraints

- Python source targets `>=3.11`; container base image is `python:3.12-slim` (spec §11 infra table; existing repo README already requires Python 3.11+).
- Code-quality gate is zero-tolerance: `ruff check`, `black --check`, and `mypy` must all be clean in CI before merge (spec §9).
- Infra is free-tier only: Vercel for `apps/web`, Fly.io for `apps/api` (spec §11).
- No secrets or `.env` files are ever committed — the existing root `.gitignore` already excludes them; do not weaken it.
- Any step that pushes to a remote Git host (GitHub) or deploys to a third-party platform (Fly.io, Vercel) is a **visible, external action** — pause and get the user's explicit go-ahead immediately before running it, even if earlier steps in this plan were pre-approved.
- No Docker is installed locally in this environment — container build correctness is verified via Fly.io's remote builder at deploy time (Task 7), not a local `docker build`.

---

### Task 1: FastAPI gateway skeleton with health check

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/gateway/__init__.py`
- Create: `apps/api/src/gateway/main.py`
- Test: `apps/api/tests/test_health.py`

**Interfaces:**
- Produces: `gateway.main.create_app() -> fastapi.FastAPI` — the app factory every later task (domain routers, tests, Docker entrypoint) imports and calls.
- Produces: `gateway.main.app` — module-level `FastAPI` instance (`create_app()` result) used as the ASGI entrypoint (`gateway.main:app`) by uvicorn/Fly.

- [ ] **Step 1: Create the package skeleton and tooling config**

Create `apps/api/pyproject.toml`:

```toml
[project]
name = "gateway"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "httpx>=0.27",
    "ruff>=0.7",
    "black>=24.10",
    "mypy>=1.13",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gateway"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
disallow_incomplete_defs = true
warn_return_any = true
warn_unused_ignores = true
mypy_path = "src"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create empty `apps/api/src/gateway/__init__.py`.

- [ ] **Step 2: Write the failing test**

Create `apps/api/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from gateway.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Install and run test to verify it fails**

Run:
```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```
Expected: FAIL / collection error — `gateway.main` does not exist yet.

- [ ] **Step 4: Write the minimal implementation**

Create `apps/api/src/gateway/main.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Portfolio Gateway", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest -v`
Expected: `test_health_returns_ok` PASSES.

- [ ] **Step 6: Run quality gates locally**

Run:
```bash
ruff check .
black --check .
mypy src
```
Expected: all three report no issues. Fix any findings before continuing (this is the zero-tolerance gate from Global Constraints).

- [ ] **Step 7: Commit**

```bash
git add apps/api/pyproject.toml apps/api/src apps/api/tests
git commit -m "feat(api): add FastAPI gateway skeleton with health check"
```

---

### Task 2: Domain router stubs for all 5 domains

**Files:**
- Create: `apps/api/src/gateway/domains/__init__.py`
- Create: `apps/api/src/gateway/domains/registry.py`
- Modify: `apps/api/src/gateway/main.py`
- Test: `apps/api/tests/test_domains.py`

**Interfaces:**
- Consumes: `gateway.main.create_app` (Task 1).
- Produces: `gateway.domains.registry.DOMAIN_NAMES: list[str]` — the canonical list of the 5 domain slugs (`hr_policy`, `contract_review`, `marketing_hub`, `techdocs`, `it_helpdesk`), imported by `apps/web`'s landing page content (Task 4) and by every later week's domain-porting plans.
- Produces: `gateway.domains.registry.make_domain_router(name: str) -> fastapi.APIRouter` — factory later tasks/plans replace piece-by-piece with real domain logic.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_domains.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gateway.domains.registry import DOMAIN_NAMES
from gateway.main import create_app


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_domain_status_endpoint(domain: str) -> None:
    client = TestClient(create_app())
    response = client.get(f"/api/v1/{domain}/status")
    assert response.status_code == 200
    assert response.json() == {"domain": domain, "status": "scaffolded"}


def test_domain_names_match_spec() -> None:
    assert DOMAIN_NAMES == [
        "hr_policy",
        "contract_review",
        "marketing_hub",
        "techdocs",
        "it_helpdesk",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `gateway.domains` module does not exist.

- [ ] **Step 3: Write the minimal implementation**

Create `apps/api/src/gateway/domains/__init__.py` (empty).

Create `apps/api/src/gateway/domains/registry.py`:

```python
from fastapi import APIRouter

DOMAIN_NAMES: list[str] = [
    "hr_policy",
    "contract_review",
    "marketing_hub",
    "techdocs",
    "it_helpdesk",
]


def make_domain_router(name: str) -> APIRouter:
    router = APIRouter(prefix=f"/api/v1/{name}", tags=[name])

    @router.get("/status")
    def status() -> dict[str, str]:
        return {"domain": name, "status": "scaffolded"}

    return router
```

Modify `apps/api/src/gateway/main.py` to mount the routers:

```python
from fastapi import FastAPI

from gateway.domains.registry import DOMAIN_NAMES, make_domain_router


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Portfolio Gateway", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for name in DOMAIN_NAMES:
        app.include_router(make_domain_router(name))

    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (6 parametrized domain tests + 1 name-list test + health test).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/gateway/domains apps/api/src/gateway/main.py apps/api/tests/test_domains.py
git commit -m "feat(api): add stub routers for all 5 domains"
```

---

### Task 3: Containerize the API for Fly.io

**Files:**
- Create: `apps/api/Dockerfile`
- Create: `apps/api/.dockerignore`
- Create: `apps/api/fly.toml`

**Interfaces:**
- Consumes: `gateway.main:app` (Task 1/2) as the uvicorn ASGI target.
- Produces: a buildable container image and a Fly app config consumed by Task 7's deploy step.

- [ ] **Step 1: Write the Dockerfile**

Create `apps/api/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Write .dockerignore**

Create `apps/api/.dockerignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
tests/
```

- [ ] **Step 3: Write the Fly app config**

Create `apps/api/fly.toml`:

```toml
app = "CHANGE-ME-rag-portfolio-api"
primary_region = "iad"

[build]

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  memory = "256mb"
  cpu_kind = "shared"
  cpus = 1
```

`app` is a placeholder — Fly app names are globally unique, so Task 7 will replace `CHANGE-ME-rag-portfolio-api` with the real name `fly launch` assigns (or that you choose interactively).

- [ ] **Step 4: Verify Dockerfile syntax without a local Docker daemon**

Docker isn't installed in this environment, so full build verification happens via Fly's remote builder in Task 7. As a lightweight local sanity check, confirm the files reference only paths that exist:

```bash
cd apps/api
test -f Dockerfile && test -f pyproject.toml && test -d src/gateway && echo "OK: Dockerfile inputs present"
```
Expected output: `OK: Dockerfile inputs present`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/Dockerfile apps/api/.dockerignore apps/api/fly.toml
git commit -m "feat(api): add Dockerfile and Fly.io config"
```

---

### Task 4: Next.js frontend shell

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/next.config.ts`
- Create: `apps/web/app/layout.tsx`
- Create: `apps/web/app/page.tsx`
- Create: `apps/web/app/globals.css`
- Create: `apps/web/.gitignore`

**Interfaces:**
- Produces: a buildable Next.js app (`npm run build`) at `apps/web`, deployed by Task 7. No other task in this plan consumes its internals — it's a leaf for Week 1 (later weeks wire it to the API).

- [ ] **Step 1: Write package.json**

Create `apps/web/package.json`:

```json
{
  "name": "web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "15.1.0",
    "react": "19.0.0",
    "react-dom": "19.0.0"
  },
  "devDependencies": {
    "typescript": "5.7.2",
    "@types/node": "22.10.0",
    "@types/react": "19.0.0",
    "@types/react-dom": "19.0.0"
  }
}
```

- [ ] **Step 2: Write tsconfig.json**

Create `apps/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Write next.config.ts**

Create `apps/web/next.config.ts`:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {};

export default nextConfig;
```

- [ ] **Step 4: Write the app shell and landing page**

Create `apps/web/app/globals.css`:

```css
:root {
  color-scheme: light dark;
}

body {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  background: canvas;
  color: canvastext;
}

main {
  max-width: 720px;
  margin: 0 auto;
  padding: 3rem 1.5rem;
}
```

Create `apps/web/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

Create `apps/web/app/page.tsx`. The `DOMAINS` list mirrors `gateway.domains.registry.DOMAIN_NAMES` from Task 2 — kept in sync manually for now; a later plan may generate this from the API instead:

```tsx
const DOMAINS = [
  { slug: "hr_policy", name: "HR Policy Q&A" },
  { slug: "contract_review", name: "Contract Review Assistant" },
  { slug: "marketing_hub", name: "Marketing Content Hub" },
  { slug: "techdocs", name: "TechDocs RAG Pipeline" },
  { slug: "it_helpdesk", name: "IT Helpdesk Agent" },
];

export default function HomePage() {
  return (
    <main>
      <h1>RAG Portfolio Platform</h1>
      <p>A governed, cost-controlled agentic AI platform.</p>
      <ul>
        {DOMAINS.map((domain) => (
          <li key={domain.slug}>{domain.name} — coming online</li>
        ))}
      </ul>
    </main>
  );
}
```

Create `apps/web/.gitignore`:

```
node_modules/
.next/
out/
.env*.local
```

- [ ] **Step 5: Install dependencies and verify the build**

Run:
```bash
cd apps/web
npm install
npm run build
```
Expected: build completes successfully with no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add apps/web
git commit -m "feat(web): add Next.js frontend shell with domain landing page"
```

---

### Task 5: GitHub Actions CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `apps/api` (`pyproject.toml` dev extras from Task 1) and `apps/web` (`package.json` from Task 4).
- Produces: two required CI status checks (`API (lint, type-check, test)`, `Web (build)`) that Task 6 uses to prove the gate blocks bad code, and that branch protection (also Task 6) will require.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  api:
    name: "API (lint, type-check, test)"
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/api
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Ruff lint
        run: ruff check .
      - name: Black format check
        run: black --check .
      - name: mypy
        run: mypy src
      - name: pytest
        run: pytest -v

  web:
    name: "Web (build)"
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "24"
      - name: Install dependencies
        run: npm ci
      - name: Build
        run: npm run build
```

- [ ] **Step 2: Validate YAML syntax locally**

Run:
```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK: valid YAML')"
```
Expected: `OK: valid YAML`. (If `pyyaml` isn't installed, run `pip install pyyaml` first — dev-only, not added to any app's dependencies.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint/type-check/test/build pipeline for api and web"
```

---

### Task 6: Push to GitHub and prove the CI gate actually blocks bad code

**Files:** none created — this task operates on the GitHub remote and repo settings.

**Interfaces:** none (verification task).

> **Stop and confirm with the user before Step 1.** Creating a GitHub repo and pushing this code makes it visible outside this machine — do not proceed without explicit go-ahead, even if earlier tasks were pre-approved.

- [ ] **Step 1: Create the GitHub repo and push (after user confirms)**

Run (replace `rag-portfolio` with the user's chosen repo name/visibility if different):
```bash
gh repo create rag-portfolio --private --source=. --remote=origin
git push -u origin main
```
Expected: push succeeds; `gh repo view --web` opens the new repo.

- [ ] **Step 2: Confirm the CI workflow ran and passed on main**

Run:
```bash
gh run list --branch main --limit 3
```
Expected: the most recent run for the push shows both `API (lint, type-check, test)` and `Web (build)` as `success`.

- [ ] **Step 3: Require the checks before merging (branch protection)**

This is a GitHub UI/API step — enable it via `gh`:
```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=API (lint, type-check, test)' \
  -f 'required_status_checks.contexts[]=Web (build)' \
  -f enforce_admins=true \
  -f required_pull_request_reviews=null \
  -f restrictions=null
```
(Replace `{owner}/{repo}` with the actual values, e.g. from `gh repo view --json owner,name`.)
Expected: command returns the updated protection JSON with both contexts listed under `required_status_checks.contexts`.

- [ ] **Step 4: Prove the gate blocks a broken PR**

```bash
git checkout -b ci-gate-check
```
Deliberately break `apps/api/src/gateway/main.py` — add an obviously unused import at the top:
```python
import os  # deliberately unused, to trigger ruff F401 — proves the gate blocks bad code
```
```bash
git add apps/api/src/gateway/main.py
git commit -m "test: deliberately break lint to verify CI gate"
git push -u origin ci-gate-check
gh pr create --title "CI gate check (throwaway)" --body "Verifying the required status checks block a lint failure. Will be closed without merging." --base main
gh pr checks --watch
```
Expected: the `API (lint, type-check, test)` check FAILS (ruff reports `F401 'os' imported but unused`), and the PR shows as not mergeable due to failing required checks.

- [ ] **Step 5: Clean up the throwaway branch**

```bash
gh pr close --delete-branch
git checkout main
git branch -D ci-gate-check
```
Expected: PR closed, remote and local throwaway branches deleted, `main` unaffected.

---

### Task 7: Deploy both apps to free-tier hosting and link from firstbloc.in

**Files:**
- Modify: `apps/api/fly.toml` (replace the placeholder app name)
- Modify: `README.md` (add live URLs)
- Modify: a nav/projects file in the separate `firstbloc.in` repo (outside this monorepo — see Step 5)

**Interfaces:** none new — this wires Tasks 3 and 4's artifacts to public URLs, and points the user's existing firstbloc.in site at the Vercel URL from Step 3. No DNS or subdomain changes to firstbloc.in — per the user's decision, this platform stays on its own Vercel URL and firstbloc.in just adds an outbound nav link to it.

> **Stop and confirm with the user before Step 1 and before Step 3.** Deploying to Fly.io and Vercel provisions real (even if free-tier) third-party resources under the user's accounts — confirm before each provider's first deploy.

- [ ] **Step 1: Install flyctl and deploy the API (after user confirms)**

```bash
brew install flyctl
fly auth login
cd apps/api
fly launch --no-deploy   # generates/updates fly.toml interactively, including a unique app name
```
Edit `apps/api/fly.toml` if needed so the `app` value matches what `fly launch` assigned (replacing the `CHANGE-ME-rag-portfolio-api` placeholder from Task 3).
```bash
fly deploy
```
Expected: deploy succeeds; note the URL Fly prints (e.g. `https://<app-name>.fly.dev`).

- [ ] **Step 2: Verify the deployed API**

```bash
curl https://<app-name>.fly.dev/health
curl https://<app-name>.fly.dev/api/v1/hr_policy/status
```
Expected: `{"status":"ok"}` and `{"domain":"hr_policy","status":"scaffolded"}` respectively.

- [ ] **Step 3: Deploy the frontend to Vercel (after user confirms)**

```bash
cd apps/web
vercel login
vercel link
vercel deploy --prod
```
Expected: deploy succeeds; note the production URL Vercel prints.

- [ ] **Step 4: Update the README with live URLs and commit**

Modify root `README.md`: add a new section near the top titled `## Live Platform` linking the Fly.io API URL and Vercel frontend URL, and a one-line note that the platform is being rebuilt per `docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md`.

```bash
git add apps/api/fly.toml README.md
git commit -m "docs: record live platform URLs after Week 1 deploy"
git push
```
Expected: push triggers CI on `main`, both checks pass (confirmed via `gh run list --branch main --limit 1`).

- [ ] **Step 5: Add a nav link from firstbloc.in to the deployed platform**

`firstbloc.in` is a separate repo/project from this monorepo, so the exact file isn't known here — this step is done directly in that repo, not `rag-portfolio`. General shape (adapt to firstbloc.in's actual nav/projects component):

1. Open the firstbloc.in project locally (it's already on Vercel per the user).
2. In its nav (or a "Projects"/"Work" section, whichever the site already uses for outbound links to other work), add an entry pointing to the Task 3 Vercel production URL from Step 3 above, e.g.:
   ```tsx
   { label: "RAG Platform", href: "https://<your-vercel-app>.vercel.app", external: true }
   ```
   matching whatever link/array pattern firstbloc.in's nav already uses.
3. Commit and deploy firstbloc.in through its own normal workflow (`vercel deploy --prod` or its existing CI, whichever firstbloc.in already uses).
4. Verify: visit firstbloc.in, click the new nav link, confirm it opens the platform landing page from Task 4.

Expected: firstbloc.in live site shows a working outbound link to the platform; no changes to firstbloc.in's DNS or domain config.

---

## Week 1 Exit Criteria (from spec §13)

- [ ] Empty-but-live platform reachable at a public URL (both API and frontend).
- [ ] CI blocks a deliberately broken PR (proven in Task 6, not just configured).
