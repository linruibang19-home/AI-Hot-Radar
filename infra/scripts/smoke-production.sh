#!/bin/sh
# Public-edge smoke after Caddy/TLS is live. No credentials are sent.

set -eu

BASE_URL=${1:-${PUBLIC_BASE_URL:-}}
if [ -z "$BASE_URL" ]; then
	echo "smoke ERROR: pass https://domain or set PUBLIC_BASE_URL" >&2
	exit 1
fi
case "$BASE_URL" in
	https://*) ;;
	*) echo "smoke ERROR: production URL must use HTTPS" >&2; exit 1 ;;
esac
BASE_URL=${BASE_URL%/}

fetch() {
	path=$1
	curl --fail --silent --show-error --location \
		--connect-timeout 5 --max-time 30 --retry 2 "$BASE_URL$path"
}

for path in /health / /items /reports /ask /eval /ops /robots.txt /sitemap.xml /api/items; do
	fetch "$path" >/dev/null
	echo "smoke ok: $path"
done

headers=$(curl --fail --silent --show-error --head --connect-timeout 5 --max-time 20 "$BASE_URL/")
printf '%s' "$headers" | grep -Eiq '^strict-transport-security:' || {
	echo "smoke ERROR: HSTS header missing" >&2
	exit 1
}
printf '%s' "$headers" | grep -Eiq '^x-content-type-options:[[:space:]]*nosniff' || {
	echo "smoke ERROR: X-Content-Type-Options missing" >&2
	exit 1
}
printf '%s' "$headers" | grep -Eiq '^x-frame-options:[[:space:]]*DENY' || {
	echo "smoke ERROR: X-Frame-Options missing" >&2
	exit 1
}

fetch /sitemap.xml | grep -Fq "$BASE_URL" || {
	echo "smoke ERROR: sitemap does not use PUBLIC_BASE_URL" >&2
	exit 1
}

# The production edge intentionally exposes only Next.js. Admin APIs live on
# core-api inside the Compose network; a public 401 would mean the route exists
# at the edge, while 404 proves there is no public management surface.
admin_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
	--connect-timeout 5 --max-time 20 "$BASE_URL/api/v1/admin/sources")
if [ "$admin_status" != "404" ]; then
	echo "smoke ERROR: public admin path must be 404, got $admin_status" >&2
	exit 1
fi

echo "production smoke OK: pages, security headers, sitemap and private admin boundary"
