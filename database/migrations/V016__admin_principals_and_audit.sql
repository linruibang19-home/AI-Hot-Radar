-- Authentication and an audit trail for the admin surface (AHR-QSO-700 §3).
--
-- The source console has been read-only since M1 for one reason, written in
-- `SourceHealthController`: least-privilege RBAC does not exist, so shipping a
-- start/stop control would have created an unauthenticated write surface on a
-- service reachable from the internet. That reason is what this migration
-- removes, and it is what has been blocking three separate features —
-- source enable/disable, background task re-runs, and manual story
-- merge/split.
--
-- Two tables, because authentication and accountability are different
-- questions. "May this request mutate?" is answered by `admin_principal`.
-- "Who disabled that source three weeks ago, and did it work?" is answered by
-- `admin_audit`, and no permission model answers it.

-- --- who may act -----------------------------------------------------------
--
-- Tokens are stored as SHA-256 hex and never in plaintext, so a database dump
-- does not hand over the admin surface. There is no password column and no
-- login form: this is a machine-to-machine credential held by one operator,
-- and a password table would be a liability invented to look conventional.
--
-- Revocation is `disabled_at`, not DELETE, so an audit row can still name the
-- principal that made a change after that principal is gone.
CREATE TABLE admin_principal (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Human-facing name for the credential, not the person: "laptop",
    -- "deploy-runner". What you look at when deciding which one to revoke.
    label        TEXT NOT NULL,

    -- SHA-256 of the bearer token, lowercase hex. UNIQUE so the same token
    -- cannot be registered twice under different roles, which would make the
    -- effective role depend on row order.
    token_hash   TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),

    -- VIEWER may read the admin views. OPERATOR may also mutate.
    -- Two roles rather than one because least privilege is only a real
    -- property if reading does not imply writing; a single ADMIN role would
    -- make the phrase decorative.
    role         TEXT NOT NULL CHECK (role IN ('VIEWER', 'OPERATOR')),

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    disabled_at  TIMESTAMPTZ
);

COMMENT ON TABLE admin_principal IS
    'Bearer credentials for the admin API. Tokens are stored hashed; revoke by setting disabled_at.';

-- The authentication lookup, on every admin request. Partial: a disabled
-- credential must never be found by it.
CREATE INDEX admin_principal_active_token_idx
    ON admin_principal (token_hash)
    WHERE disabled_at IS NULL;

-- --- what was done ---------------------------------------------------------
--
-- Written for denied attempts as well as successful ones. An audit log that
-- only records what worked cannot show someone trying keys against the
-- console, which is most of what an audit log is for.
CREATE TABLE admin_audit (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Nullable, and that is the point: an unauthenticated attempt has no
    -- principal and is exactly the row worth keeping. ON DELETE SET NULL
    -- rather than CASCADE — deleting a credential must not delete the record
    -- of what it did.
    principal_id  UUID REFERENCES admin_principal(id) ON DELETE SET NULL,

    -- Denormalised so the row still reads after the credential is revoked and
    -- relabelled. An audit row that needs a join to a mutable table to be
    -- legible is not a record of what happened.
    principal_label TEXT,
    role            TEXT,

    -- What was attempted, in the verb_noun form the endpoints use:
    -- 'source.disable', 'source.enable', 'source.reprobe'.
    action        TEXT NOT NULL,

    -- What it was attempted on: a source id, a story id. Free text because
    -- the targets live in tables with different key types.
    target        TEXT,

    -- ALLOWED / DENIED_NO_TOKEN / DENIED_BAD_TOKEN / DENIED_ROLE /
    -- DENIED_UNCONFIRMED / FAILED. Distinguishing the denials is the whole
    -- value: "wrong key" and "right key, wrong role" are different incidents.
    outcome       TEXT NOT NULL,

    -- Anything worth keeping that is not a column: the previous and new
    -- runtime_state, the reason given, the error if it failed.
    -- Never the token, and never a header dump (AHR-QSO-700 §3: logs redact
    -- Authorization).
    detail        JSONB NOT NULL DEFAULT '{}'::jsonb,

    at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE admin_audit IS
    'Every admin mutation attempt, allowed or denied. Never contains credentials.';

-- The two questions asked of it: "what happened recently" and "what has been
-- done to this source".
CREATE INDEX admin_audit_at_idx ON admin_audit (at DESC);
CREATE INDEX admin_audit_target_idx ON admin_audit (target, at DESC) WHERE target IS NOT NULL;

-- --- what an operator may change ------------------------------------------
--
-- `configured_enabled` comes from config/sources.yaml and is resynchronised on
-- every registry import, so an operator switching a source off through the
-- console would be silently switched back on by the next sync. The override is
-- therefore a separate column that the importer does not touch.
--
-- NULL means "follow the registry", which is different from both true and
-- false: it is how an operator undoes their own change rather than pinning the
-- opposite of it.
ALTER TABLE source
    ADD COLUMN operator_enabled BOOLEAN,
    ADD COLUMN operator_note    TEXT;

COMMENT ON COLUMN source.operator_enabled IS
    'Operator override of configured_enabled. NULL = follow the registry. Never written by the registry importer.';

-- The value every caller should actually poll on, computed once here rather
-- than as `COALESCE(...)` repeated at five call sites in the scheduler, the
-- pipeline, the probe and the admin view. Repeating it is how one of them ends
-- up disagreeing after a later edit — this project has already shipped that
-- bug once, where a source could be healthy by every counter and invisible to
-- retrieval (see docs/status §3.12).
ALTER TABLE source
    ADD COLUMN effective_enabled BOOLEAN
        GENERATED ALWAYS AS (COALESCE(operator_enabled, configured_enabled)) STORED;

COMMENT ON COLUMN source.effective_enabled IS
    'configured_enabled with the operator override applied. Poll on this, never on configured_enabled.';

CREATE INDEX source_effective_enabled_idx ON source (effective_enabled) WHERE effective_enabled;
