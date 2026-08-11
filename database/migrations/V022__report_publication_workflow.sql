-- Non-blocking report publication workflow (ADR-0025).

-- Existing report rows only use DRAFT. The additional values distinguish an
-- automated quality hold from an explicit operator withdrawal.
ALTER TABLE report
    ADD CONSTRAINT ck_report_status
    CHECK (status IN ('DRAFT', 'REVIEW_REQUIRED', 'PUBLISHED', 'WITHDRAWN'));

-- AHR-API-500 requires every admin mutation to carry an Idempotency-Key.
-- Persisting the result prevents a client retry from duplicating an audit or
-- applying the same key to a different report after a timeout.
CREATE TABLE admin_idempotency (
    principal_id       UUID NOT NULL REFERENCES admin_principal(id),
    idempotency_key    VARCHAR(200) NOT NULL,
    action             TEXT NOT NULL,
    target             TEXT NOT NULL,
    request_hash       CHAR(64) NOT NULL,
    response_status    INTEGER,
    response_body      JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    PRIMARY KEY (principal_id, idempotency_key)
);

CREATE INDEX admin_idempotency_created_idx ON admin_idempotency (created_at DESC);
