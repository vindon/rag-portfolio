CREATE TABLE IF NOT EXISTS budget_ledger (
    id BIGSERIAL PRIMARY KEY,
    domain TEXT NOT NULL,
    provider TEXT NOT NULL,
    cost_usd NUMERIC(12, 6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_budget_ledger_created_at ON budget_ledger (created_at);

CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    provider TEXT PRIMARY KEY,
    consecutive_failures INT NOT NULL DEFAULT 0,
    tripped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS global_breaker_state (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tripped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
