#!/bin/sh
# Nightly database backup with a retention window (AHR-QSO-700 §4).
#
# The stack can be rebuilt from the repository in minutes. The corpus cannot:
# it is the result of days of polling 140 sources on their own cadences, plus
# the LLM enrichment that was paid for once per item. Losing it means waiting,
# not just redeploying — which is why this is the one piece of state that gets
# a backup rather than being treated as reproducible.
#
# `pg_dump -Fc` rather than plain SQL: the custom format is compressed and
# restores selectively with `pg_restore`, which matters when the thing being
# recovered is one table rather than the whole database.
#
# Runs in the foreground on a sleep loop rather than under cron. A cron daemon
# inside a container needs its own logging and its own supervision, and the
# question this has to answer — "did last night's backup run?" — is answered by
# `docker compose logs backup`.

set -eu

BACKUP_DIR=${BACKUP_DIR:-/backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-7}
INTERVAL=${BACKUP_INTERVAL_SECONDS:-86400}

mkdir -p "$BACKUP_DIR"

run_backup() {
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	target="$BACKUP_DIR/ai_hot_radar-$stamp.dump"

	# Write to a temporary name and rename on success. A dump interrupted
	# halfway would otherwise sit in the directory looking exactly like a good
	# one, and would be found only when it was needed.
	if pg_dump -Fc -f "$target.partial" && pg_restore --list "$target.partial" >/dev/null; then
		mv "$target.partial" "$target"
		sha256sum "$target" > "$target.sha256"
		echo "backup ok and catalog verified: $target ($(du -h "$target" | cut -f1))"
	else
		rm -f "$target.partial"
		echo "backup FAILED at $stamp" >&2
		return 1
	fi

	# Retention last, and only after a success: pruning first would let a run
	# of failures quietly delete the last good copy.
	find "$BACKUP_DIR" \( -name 'ai_hot_radar-*.dump' -o -name 'ai_hot_radar-*.dump.sha256' \) \
		-mtime "+$KEEP_DAYS" -print -delete
}

echo "backup worker started: every ${INTERVAL}s, keeping ${KEEP_DAYS} days in ${BACKUP_DIR}"

if [ "${BACKUP_RUN_ONCE:-false}" = "true" ]; then
	run_backup
	exit 0
fi

while true; do
	# A failure must not kill the loop; tomorrow's attempt may well succeed, and
	# an exited container stops trying entirely.
	run_backup || echo "continuing after failed backup" >&2
	sleep "$INTERVAL"
done
