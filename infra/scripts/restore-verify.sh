#!/bin/sh
# Restore one custom-format dump into an isolated database, compare critical
# table counts with the live source, then remove only that verified target.

set -eu

BACKUP_FILE=${BACKUP_FILE:-}
SOURCE_DB=${PGDATABASE:-ai_hot_radar}
TARGET_DB=${RESTORE_TARGET_DATABASE:-ai_hot_radar_restore_verify}

if [ -z "$BACKUP_FILE" ]; then
	echo "restore verify ERROR: BACKUP_FILE is required" >&2
	exit 1
fi
if [ ! -f "$BACKUP_FILE" ]; then
	echo "restore verify ERROR: backup not found: $BACKUP_FILE" >&2
	exit 1
fi
case "$TARGET_DB" in
	ai_hot_radar_restore_verify|ai_hot_radar_restore_verify_*) ;;
	*)
		echo "restore verify ERROR: target must start with ai_hot_radar_restore_verify" >&2
		exit 1
		;;
esac
if [ "$TARGET_DB" = "$SOURCE_DB" ]; then
	echo "restore verify ERROR: target must differ from source" >&2
	exit 1
fi

if [ -f "$BACKUP_FILE.sha256" ]; then
	(cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
fi
pg_restore --list "$BACKUP_FILE" >/dev/null

cleanup() {
	dropdb --if-exists --force "$TARGET_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# The guarded name above makes this cleanup narrow and recoverable from the
# original dump. A failed prior rehearsal must not poison the next one.
cleanup
createdb "$TARGET_DB"
pg_restore --no-owner --no-privileges --exit-on-error -d "$TARGET_DB" "$BACKUP_FILE"

count_query="SELECT
  (SELECT count(*) FROM source)::text || '|' ||
  (SELECT count(*) FROM content_item)::text || '|' ||
  (SELECT count(*) FROM content_chunk)::text || '|' ||
  (SELECT count(*) FROM story)::text || '|' ||
  (SELECT count(*) FROM report)::text || '|' ||
  COALESCE((SELECT max(version) FROM flyway_schema_history WHERE success), 'none');"

source_snapshot=$(psql -X -At -d "$SOURCE_DB" -c "$count_query")
restored_snapshot=$(psql -X -At -d "$TARGET_DB" -c "$count_query")

snapshot_counts() {
	printf '%s\n' "$1" | cut -d'|' -f1-5 | tr '|' ' '
}

snapshot_version() {
	printf '%s\n' "$1" | cut -d'|' -f6
}

source_counts=$(snapshot_counts "$source_snapshot")
restored_counts=$(snapshot_counts "$restored_snapshot")
source_version=$(snapshot_version "$source_snapshot")
restored_version=$(snapshot_version "$restored_snapshot")

if [ "$source_version" != "$restored_version" ]; then
	echo "restore verify ERROR: Flyway version mismatch" >&2
	exit 1
fi

# A live source can advance after pg_dump's consistent snapshot was taken.
# Therefore the safe default requires every restored count to be positive and
# no greater than the current source. A controlled rehearsal can stop writers
# and set RESTORE_REQUIRE_EXACT=true for a byte-in-time count comparison.
set -- $source_counts
source_1=$1 source_2=$2 source_3=$3 source_4=$4 source_5=$5
set -- $restored_counts
restored_1=$1 restored_2=$2 restored_3=$3 restored_4=$4 restored_5=$5

for pair in \
	"$restored_1:$source_1" "$restored_2:$source_2" \
	"$restored_3:$source_3" "$restored_4:$source_4" \
	"$restored_5:$source_5"; do
	restored_count=${pair%%:*}
	source_count=${pair##*:}
	if [ "$restored_count" -le 0 ] || [ "$restored_count" -gt "$source_count" ]; then
		echo "restore verify ERROR: restored critical counts are invalid" >&2
		exit 1
	fi
done

if [ "${RESTORE_REQUIRE_EXACT:-false}" = "true" ] && [ "$source_counts" != "$restored_counts" ]; then
	echo "restore verify ERROR: controlled rehearsal snapshot mismatch" >&2
	exit 1
fi

echo "restore verify OK: restored snapshot is complete and migration-compatible ($restored_snapshot)"
