-- TASK-M5-004: confirmed report subscriptions and retryable scheduled delivery.
-- PostgreSQL remains the source of truth; Redis is not used for subscription state.

CREATE TABLE report_subscription (
    id                  UUID PRIMARY KEY,
    email_normalized    VARCHAR(320) NOT NULL UNIQUE,
    status              VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
    timezone            VARCHAR(64) NOT NULL,
    token_version       INTEGER NOT NULL DEFAULT 1,
    confirmed_at        TIMESTAMPTZ NOT NULL,
    unsubscribed_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_report_subscription_status
        CHECK (status IN ('ACTIVE', 'UNSUBSCRIBED')),
    CONSTRAINT ck_report_subscription_email_normalized
        CHECK (email_normalized = lower(btrim(email_normalized))),
    CONSTRAINT ck_report_subscription_token_version
        CHECK (token_version > 0)
);

CREATE TABLE report_subscription_period (
    subscription_id     UUID NOT NULL REFERENCES report_subscription(id) ON DELETE CASCADE,
    period_type         VARCHAR(16) NOT NULL,
    delivery_local_time TIME NOT NULL DEFAULT TIME '08:30',
    PRIMARY KEY (subscription_id, period_type),
    CONSTRAINT ck_report_subscription_period
        CHECK (period_type IN ('daily', 'weekly', 'monthly'))
);

CREATE TABLE report_subscription_request (
    id                  UUID PRIMARY KEY,
    email_normalized    VARCHAR(320) NOT NULL,
    timezone            VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    token_version       INTEGER NOT NULL DEFAULT 1,
    expires_at          TIMESTAMPTZ NOT NULL,
    confirmation_sent_at TIMESTAMPTZ,
    confirmed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_report_subscription_request_status
        CHECK (status IN ('PENDING', 'CONFIRMED', 'EXPIRED')),
    CONSTRAINT ck_report_subscription_request_email_normalized
        CHECK (email_normalized = lower(btrim(email_normalized))),
    CONSTRAINT ck_report_subscription_request_token_version
        CHECK (token_version > 0)
);

CREATE UNIQUE INDEX report_subscription_request_pending_email_idx
    ON report_subscription_request (email_normalized)
    WHERE status = 'PENDING';

CREATE INDEX report_subscription_request_expiry_idx
    ON report_subscription_request (expires_at)
    WHERE status = 'PENDING';

CREATE TABLE report_subscription_request_period (
    request_id          UUID NOT NULL REFERENCES report_subscription_request(id) ON DELETE CASCADE,
    period_type         VARCHAR(16) NOT NULL,
    PRIMARY KEY (request_id, period_type),
    CONSTRAINT ck_report_subscription_request_period
        CHECK (period_type IN ('daily', 'weekly', 'monthly'))
);

ALTER TABLE email_delivery
    DROP CONSTRAINT ck_email_status;

ALTER TABLE email_delivery
    ADD COLUMN subscription_id UUID REFERENCES report_subscription(id) ON DELETE SET NULL,
    ADD COLUMN report_id UUID REFERENCES report(id) ON DELETE SET NULL,
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN sent_at TIMESTAMPTZ,
    ADD CONSTRAINT ck_email_status CHECK (
        status IN (
            'PENDING', 'SENDING', 'SENT', 'RETRYABLE_FAILED',
            'PERMANENT_FAILED', 'FAILED', 'SKIPPED'
        )
    ),
    ADD CONSTRAINT ck_email_delivery_attempt_count CHECK (attempt_count >= 0);

CREATE INDEX email_delivery_subscription_idx
    ON email_delivery (subscription_id, attempted_at DESC);

CREATE INDEX email_delivery_report_id_idx
    ON email_delivery (report_id);

CREATE UNIQUE INDEX email_delivery_subscription_report_uidx
    ON email_delivery (subscription_id, report_id)
    WHERE subscription_id IS NOT NULL AND report_id IS NOT NULL;

CREATE INDEX email_delivery_due_idx
    ON email_delivery (next_attempt_at, attempted_at)
    WHERE status IN ('PENDING', 'RETRYABLE_FAILED');
