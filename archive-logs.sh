#!/bin/bash
# archive-logs.sh — compress past-month API logs into monthly tarballs.
#
# The logs/ folder is a retained usage & agent-behaviour dataset (see the README
# section "Why these logs are kept"). This script keeps the *live* directory
# small — so tools like the off-box mirror (doc/debian-migration/sync_vps_docker.py
# in the tmdb-front repo) don't choke listing tens of thousands of files —
# WITHOUT deleting any data: every past month's *.json files are packed into
# logs/archive/<YYYYMM>.tar.gz, the archive is verified, then the loose
# originals are removed. The CURRENT (and any future) month is left untouched so
# in-flight logging is never disturbed.
#
# Idempotent / re-runnable: only files strictly older than the current month are
# touched; an existing monthly archive is merged with any stragglers.
#
# Usage:
#   ./archive-logs.sh [LOGS_DIR ...]
# With no args it processes the three deployed log dirs on the VPS (below).
# Run as the user that owns logs/ (or via sudo) so it can remove the originals.
#
# Cron (1st of each month, 03:30):
#   30 3 1 * * /home/debian/docker/fastapi-text2sql-blue/archive-logs.sh \
#     >> /home/debian/docker/fastapi-text2sql-blue/logs/archive/archive.log 2>&1

set -euo pipefail

DEFAULT_DIRS=(
  /home/debian/docker/fastapi-text2sql-blue/logs
  /home/debian/docker/fastapi-text2sql-green/logs
  /home/debian/docker/fastapi-text2sql/logs
)

dirs=("$@")
if [ "${#dirs[@]}" -eq 0 ]; then
  dirs=("${DEFAULT_DIRS[@]}")
fi

current_month=$(date +%Y%m)

for logs_dir in "${dirs[@]}"; do
  if [ ! -d "$logs_dir" ]; then
    echo "skip (no dir): $logs_dir"
    continue
  fi
  archive_dir="$logs_dir/archive"
  mkdir -p "$archive_dir"

  # Distinct YYYYMM prefixes among loose log files (names start YYYYMMDD-...).
  months=$(find "$logs_dir" -maxdepth 1 -type f -name '[0-9]*.json' -printf '%f\n' \
             | cut -c1-6 | sort -u || true)

  for m in $months; do
    # Leave the current and any future month loose (numeric YYYYMM compare).
    [ "$m" -lt "$current_month" ] || continue

    arc="$archive_dir/${m}.tar.gz"
    filelist=$(mktemp)
    find "$logs_dir" -maxdepth 1 -type f -name "${m}*.json" -printf '%f\0' > "$filelist"
    count=$(tr -cd '\0' < "$filelist" | wc -c)
    if [ "$count" -eq 0 ]; then
      rm -f "$filelist"
      continue
    fi

    if [ -f "$arc" ]; then
      # Merge stragglers into the existing archive (tar can't append to a .gz).
      tmptar="$archive_dir/${m}.tar"
      rm -f "$tmptar"
      gzip -dc "$arc" > "$tmptar"
      tar -rf "$tmptar" -C "$logs_dir" --null --no-recursion -T "$filelist"
      gzip -f "$tmptar"            # -> ${m}.tar.gz (replaces $arc)
    else
      tar -czf "$arc" -C "$logs_dir" --null --no-recursion -T "$filelist"
    fi

    # Only delete the loose originals once the archive is verified readable.
    if gzip -t "$arc"; then
      ( cd "$logs_dir" && xargs -0 -a "$filelist" rm -f )
      echo "$(date +%F_%T) archived $count file(s) -> $arc"
    else
      echo "$(date +%F_%T) !! archive verify FAILED, kept loose files: $arc" >&2
    fi
    rm -f "$filelist"
  done
done
