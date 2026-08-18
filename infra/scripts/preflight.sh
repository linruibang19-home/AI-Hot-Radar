#!/bin/sh
# Fail-closed production configuration audit. This reads .env as data; it never
# sources it, so a malformed or hostile value cannot execute on the host.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE=${1:-"$REPO_ROOT/infra/compose/.env"}
COMPOSE_FILE="$REPO_ROOT/infra/compose/docker-compose.prod.yml"

failures=0

fail() {
	echo "preflight ERROR: $*" >&2
	failures=$((failures + 1))
}

value() {
	awk -F= -v wanted="$1" '
		$0 !~ /^[[:space:]]*#/ && $1 == wanted {
			sub(/^[^=]*=/, "")
			found = $0
		}
		END { gsub(/\r$/, "", found); print found }
	' "$ENV_FILE"
}

require_value() {
	name=$1
	resolved=$(value "$name")
	if [ -z "$resolved" ]; then
		fail "$name is required"
	fi
}

require_min_length() {
	name=$1
	minimum=$2
	resolved=$(value "$name")
	if [ "${#resolved}" -lt "$minimum" ]; then
		fail "$name must be at least $minimum characters"
	fi
	case "$resolved" in
		change-me|*local-development*|*do-not-deploy*) fail "$name still contains a development placeholder" ;;
	esac
}

if [ ! -f "$ENV_FILE" ]; then
	echo "preflight ERROR: environment file not found: $ENV_FILE" >&2
	exit 1
fi

if [ "$(value PREFLIGHT_EXAMPLE)" = "true" ] && [ "${PREFLIGHT_ALLOW_EXAMPLE:-false}" != "true" ]; then
	fail "the structural example cannot be used for a deployment"
fi

for name in IMAGE_REPO IMAGE_TAG SITE_DOMAIN PUBLIC_BASE_URL ACME_EMAIL \
	POSTGRES_DB POSTGRES_USER LLM_API_KEY EMBEDDING_API_KEY GITHUB_TOKEN \
	SMTP_HOST EMAIL_FROM; do
	require_value "$name"
done

require_min_length POSTGRES_PASSWORD 24
require_min_length INTERNAL_SERVICE_TOKEN 32
require_min_length AHR_ADMIN_BOOTSTRAP_TOKEN 32
require_min_length AHR_ADMIN_VIEWER_TOKEN 32
require_min_length AHR_SUBSCRIPTION_TOKEN_SECRET 32
# Base64 of 32 random bytes is 44 characters, or 43 unpadded. Checked here as
# well as by Compose's `:?` so the failure names the variable and its shape
# before any container is started.
require_min_length LLM_CREDENTIAL_MASTER_KEY 43

operator_token=$(value AHR_ADMIN_BOOTSTRAP_TOKEN)
viewer_token=$(value AHR_ADMIN_VIEWER_TOKEN)
if [ -n "$operator_token" ] && [ "$operator_token" = "$viewer_token" ]; then
	fail "operator and viewer tokens must be different"
fi

image_tag=$(value IMAGE_TAG)
if ! printf '%s' "$image_tag" | grep -Eq '^sha-[0-9a-f]{40}$'; then
	fail "IMAGE_TAG must pin release.yml's immutable sha-<40 hex> tag"
fi

site_domain=$(value SITE_DOMAIN)
public_base=$(value PUBLIC_BASE_URL)
if [ "$public_base" != "https://$site_domain" ]; then
	fail "PUBLIC_BASE_URL must equal https://SITE_DOMAIN with no trailing path"
fi

acme_email=$(value ACME_EMAIL)
if ! printf '%s' "$acme_email" | grep -Eq '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'; then
	fail "ACME_EMAIL is not a valid operational address"
fi

alert_url=$(value ALERT_WEBHOOK_URL)
alert_email=$(value ALERT_EMAIL_TO)
if [ -z "$alert_url" ] && [ -z "$alert_email" ]; then
	fail "ALERT_WEBHOOK_URL or ALERT_EMAIL_TO is required"
fi
if [ -n "$alert_url" ]; then
	case "$alert_url" in
		https://*) ;;
		*) fail "ALERT_WEBHOOK_URL must use HTTPS" ;;
	esac
fi
if [ -n "$alert_email" ] && ! printf '%s' "$alert_email" | grep -Eq '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'; then
	fail "ALERT_EMAIL_TO is not a valid recipient address"
fi

for name in LLM_DAILY_TOKEN_LIMIT RAG_RATE_PER_MINUTE RAG_RATE_PER_DAY \
	ALERT_FAILURE_THRESHOLD MONITOR_INTERVAL_SECONDS BACKUP_MAX_AGE_SECONDS BACKUP_KEEP_DAYS \
	SMTP_PORT EMAIL_DISPATCH_INTERVAL_MS; do
	resolved=$(value "$name")
	if ! printf '%s' "$resolved" | grep -Eq '^[1-9][0-9]*$'; then
		fail "$name must be a positive integer"
	fi
done

for name in SMTP_AUTH SMTP_STARTTLS; do
	resolved=$(value "$name")
	case "$resolved" in
		true|false) ;;
		*) fail "$name must be true or false" ;;
	esac
done

if [ "$(value SMTP_AUTH)" = "true" ]; then
	require_value SMTP_USERNAME
	require_value SMTP_PASSWORD
fi

email_from=$(value EMAIL_FROM)
if ! printf '%s' "$email_from" | grep -Eq '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'; then
	fail "EMAIL_FROM is not a valid sender address"
fi

if [ "$(value PROVIDER_BUDGET_CAP_CONFIRMED)" != "true" ]; then
	fail "provider-side spending caps have not been confirmed"
fi
if [ "$(value BACKUP_OFFSITE_CONFIRMED)" != "true" ]; then
	fail "off-host backup ownership has not been confirmed"
fi

# The real production file contains spend-capable credentials. Enforce a
# private host mode where GNU stat is available; Windows development uses the
# structural fixture and validates this again on the Linux target.
if command -v stat >/dev/null 2>&1 && [ "$(value PREFLIGHT_EXAMPLE)" != "true" ]; then
	mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)
	case "$mode" in
		600|400) ;;
		*) fail "$ENV_FILE must have mode 600 or 400 (found ${mode:-unknown})" ;;
	esac
fi

if [ "$failures" -ne 0 ]; then
	echo "preflight FAILED: $failures problem(s)" >&2
	exit 1
fi

if command -v docker >/dev/null 2>&1; then
	case "$ENV_FILE" in
		/*) absolute_env=$ENV_FILE ;;
		*) absolute_env=$(CDPATH= cd -- "$(dirname -- "$ENV_FILE")" && pwd)/$(basename -- "$ENV_FILE") ;;
	esac
	AHR_ENV_FILE="$absolute_env" docker compose --env-file "$absolute_env" \
		-f "$COMPOSE_FILE" config --quiet
else
	echo "preflight WARNING: docker is unavailable; Compose rendering was not checked" >&2
fi

echo "preflight OK: immutable images, secrets, budget attestations, TLS origin and Compose syntax"
