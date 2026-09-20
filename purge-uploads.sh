#!/bin/bash
# purge-uploads.sh: delete vision-mode images older than the retention window
# (FASTAPI-TEXT2SQL-275). Default: 30 days.
#
# THIS IS NOT archive-logs.sh, AND IT MUST NOT BECOME IT. That script's promise, written at
# the top of its own header, is that it archives "WITHOUT deleting any data": logs/ is a
# retained dataset, kept without limit and backed up. This one deletes, on purpose, because a
# visitor's photo is not a request log and Philippe set its retention at 30 days on 2026-09-19.
# Mixing a deletion into a tool whose advertised promise is that it loses nothing would be a
# trap laid for the next reader, so the two stay separate files with separate crons.
#
# WHAT IT DELETES, AND WHAT IT MUST NEVER REACH
#   deletes   uploads/vision/*.jpg and *.png older than the window, by modification time
#   never     logs/ and its archives (other folder, opposite regime, refused by the guard below)
#   never     the evaluation fixtures of the vision bench: they live versioned in the
#             voice-agent repo (VOICE-AGENT-179), never under uploads/, which is one more
#             reason not to drop them here "just for now"
#   never     uploads/purge-run.log itself: the run log sits in uploads/, the images in
#             uploads/vision/, which is what the vision/ level is for
#
# THE GUARD IS NOT DECORATION. A directory is only ever purged if its path ends in
# uploads/vision. A typo, an unset variable or a copy-paste that aims this at a log directory
# stops here rather than at the first rm.
#
# Usage:
#   ./purge-uploads.sh                       # purge the shared VPS dir, 30 days
#   ./purge-uploads.sh --dry-run             # list what would go, delete nothing
#   ./purge-uploads.sh --days 7 /tmp/uploads/vision
#
# Cron (daily, 03:50, twenty minutes after the monthly archiver's slot so the two never
# overlap on the 1st). The run log is written in uploads/, a directory the restart scripts
# create, NEVER in a directory this script has yet to create: the shell opens a redirect
# before running the command, and that mistake is exactly why archive-logs.sh never ran once
# before 2026-08-21.
#   50 3 * * * /home/debian/docker/fastapi-text2sql-blue/purge-uploads.sh \
#     >> /home/debian/docker/shared_data/fastapi-text2sql/uploads/purge-run.log 2>&1
#
# One cron for the machine, not one per colour: the folder is shared by blue, green and the
# colourless third deployment, so a cron in each stack would purge the same files three times.

set -euo pipefail

DEFAULT_DIRS=(
  /home/debian/docker/shared_data/fastapi-text2sql/uploads/vision
)

days=30
dry_run=0
dirs=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --days)
      days="${2:?--days needs a number}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      sed -n '2,38p' "$0"
      exit 0
      ;;
    *)
      dirs+=("$1")
      shift
      ;;
  esac
done

case "$days" in
  ''|*[!0-9]*)
    echo "!! --days must be a whole number of days, got: $days" >&2
    exit 2
    ;;
esac

if [ "${#dirs[@]}" -eq 0 ]; then
  dirs=("${DEFAULT_DIRS[@]}")
fi

for uploads_dir in "${dirs[@]}"; do
  # Strip any trailing slash before the guard, so ".../uploads/vision/" passes and
  # ".../logs" cannot.
  clean_dir="${uploads_dir%/}"
  case "$clean_dir" in
    */uploads/vision|uploads/vision) ;;
    *)
      echo "$(date +%F_%T) !! refused (not an uploads/vision directory): $clean_dir" >&2
      exit 2
      ;;
  esac

  if [ ! -d "$clean_dir" ]; then
    echo "$(date +%F_%T) skip (no dir): $clean_dir"
    continue
  fi

  # -mtime +N is "strictly more than N 24-hour periods old", which is the sliding window
  # wanted here. The deposit time is also in the filename, but mtime survives a copy that
  # a name-based rule would mis-read, and it is what find can act on in one pass.
  filelist=$(mktemp)
  find "$clean_dir" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' \) \
       -mtime +"$days" -print0 > "$filelist"
  count=$(tr -cd '\0' < "$filelist" | wc -c)

  if [ "$count" -eq 0 ]; then
    echo "$(date +%F_%T) nothing older than ${days}d in $clean_dir"
    rm -f "$filelist"
    continue
  fi

  if [ "$dry_run" -eq 1 ]; then
    echo "$(date +%F_%T) dry run: $count file(s) older than ${days}d in $clean_dir"
    xargs -0 -a "$filelist" -n 1 echo "  would delete"
  else
    xargs -0 -a "$filelist" rm -f
    echo "$(date +%F_%T) purged $count file(s) older than ${days}d from $clean_dir"
  fi
  rm -f "$filelist"

  remaining=$(find "$clean_dir" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' \) | wc -l)
  echo "$(date +%F_%T) remaining: $remaining image(s) in $clean_dir"
done
