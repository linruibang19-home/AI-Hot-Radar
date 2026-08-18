-- The generation provider's address and key become editable from the console.
--
-- Until now both lived only in `LLM_BASE_URL` / `LLM_API_KEY`, so rotating a key
-- meant editing `.env` on the server and recreating three containers. The model
-- *choice* was already database-backed (V024); this puts the credential beside
-- it so one page answers "which model, from where, with what key".
--
-- Single row by construction. There is one generation provider at a time — the
-- same constraint V024 put on the model — and a table that can hold two would
-- need an "active" flag, which is a second source of truth for something that
-- has exactly one answer.
CREATE TABLE generation_provider_config (
    singleton_key      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_key = 1),
    base_url           TEXT NOT NULL,
    -- NULL means "use LLM_API_KEY". Kept as a real state rather than seeding a
    -- copy of the environment value: copying it would put the production key in
    -- the database and in every backup taken from that moment, for a feature
    -- nobody had used yet.
    api_key_ciphertext TEXT,
    key_fingerprint    VARCHAR(16),
    version            BIGINT NOT NULL DEFAULT 1,
    updated_by         UUID REFERENCES admin_principal(id),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_generation_provider_secret_shape CHECK (
        (api_key_ciphertext IS NULL AND key_fingerprint IS NULL)
        OR (api_key_ciphertext IS NOT NULL AND key_fingerprint IS NOT NULL)
    )
);

-- Seeded to the environment on both fields, so applying this migration changes
-- nothing about which provider is called. The console only starts to matter
-- once an operator saves over it.
INSERT INTO generation_provider_config (singleton_key, base_url, version)
VALUES (1, 'env://LLM_BASE_URL', 1);
