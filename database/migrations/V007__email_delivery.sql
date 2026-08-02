-- Report email delivery log (TASK-M2-004).
--
-- AHR-ARCH-200 §5 requires a `delivery_key` guard on email. A page render can
-- be repeated harmlessly; a send cannot, so the key is UNIQUE and checked
-- before dispatch rather than only recorded after it.

CREATE TABLE IF NOT EXISTS email_delivery (
    id                  UUID PRIMARY KEY,
    delivery_key        VARCHAR(64) NOT NULL UNIQUE,
    recipient           VARCHAR(320) NOT NULL,
    report_period_key   VARCHAR(32),
    status              VARCHAR(24) NOT NULL,
    error_detail        TEXT,
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_email_status CHECK (status IN ('SENT', 'FAILED', 'SKIPPED'))
);

CREATE INDEX IF NOT EXISTS idx_email_delivery_report
    ON email_delivery (report_period_key, attempted_at DESC);
