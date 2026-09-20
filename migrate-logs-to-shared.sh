#!/bin/bash
# migrate-logs-to-shared.sh: merge the three per-stack log directories into the single
# shared one (FASTAPI-TEXT2SQL-276). One-shot, but safe to re-run.
#
# Until this ran, the log corpus was split in three, because the docker run lines mounted
# only the code (-v $(pwd):/app) and LOGS_FOLDER is relative: each deployment wrote into
# its own stack directory.
#
#   /home/debian/docker/fastapi-text2sql-blue/logs
#   /home/debian/docker/fastapi-text2sql-green/logs
#   /home/debian/docker/fastapi-text2sql/logs
#
# They all become /home/debian/docker/shared_data/fastapi-text2sql/logs, bind-mounted on
# /app/logs by restart-blue.sh and restart-green.sh.
#
# THE MERGE IS THE WORK, NOT THE MOUNT. Two things collide, one of them destructively:
#
#   1. The monthly archives share their names. archive-logs.sh writes
#      logs/archive/<YYYYMM>.tar.gz in every directory, so blue's 202608.tar.gz and
#      green's are two different files carrying one name. A naive mv or cp destroys one
#      of them. This script concatenates their members into a single archive per month
#      and verifies the member count before anything is removed.
#   2. The loose files can in principle collide. Their name is
#      YYYYMMDD-HHMMSS_<endpoint>_<version>_<md5>.json and the colours run different
#      versions, so the version component separates them naturally. A genuine collision
#      means same second, same version and same payload hash, i.e. the same request, and
#      is harmless, but it is checked rather than assumed, by comparing the contents.
#
# Usage:
#   ./migrate-logs-to-shared.sh                        # dry run: inventory + collisions
#   ./migrate-logs-to-shared.sh --apply                # merge archives, move loose files
#   ./migrate-logs-to-shared.sh --prune-sources        # remove the source archives, only
#                                                      # after re-reading them out of the
#                                                      # target
#   ./migrate-logs-to-shared.sh --target DIR SOURCE... # override the paths
#
# WHO CAN RUN IT. Removing or renaming a file is governed by write permission on its
# DIRECTORY, not by ownership of the file, so the log files being root-owned (the
# container runs as root) changes nothing. What decides is who owns the source logs/
# directories. Measured on the VPS 2026-09-20: both are debian:debian drwxr-xr-x, so
# debian runs this unaided. Check before assuming, and prefix with sudo if any of them
# came back root:
#   ls -ld /home/debian/docker/fastapi-text2sql{-blue,-green,}/logs
#
# Create the target as debian BEFORE any sudo run, or the mkdir -p below makes it
# root-owned and archive-logs.sh needs sudo for ever after.
#
# MEASURED ON THE VPS, 2026-09-20, and it corrects two assumptions of the ticket.
# There are TWO source directories, not three: the colourless fastapi-text2sql/ deployment
# has no logs/ at all. And there is not a single monthly archive on either colour, so the
# name collision above, the dangerous half of this script, does not arise in practice: the
# migration is a plain move of 24 940 loose files (20 656 blue, 4 284 green). The archive
# code stays because it is what makes the script safe to re-run after archive-logs.sh
# finally runs, which on that date it never had.
#
# Idempotent. A month is merged into a temp file and moved into place only once verified,
# so it is either complete or absent; a second run skips the months already done and moves
# whatever loose files are left.

set -euo pipefail

TARGET=/home/debian/docker/shared_data/fastapi-text2sql/logs
SOURCES=(
  /home/debian/docker/fastapi-text2sql-blue/logs
  /home/debian/docker/fastapi-text2sql-green/logs
  /home/debian/docker/fastapi-text2sql/logs
)

APPLY=0
PRUNE=0
explicit_sources=()

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)          APPLY=1 ;;
    --prune-sources)  PRUNE=1 ;;
    --target)         TARGET="$2"; shift ;;
    -h|--help)        sed -n '2,50p' "$0"; exit 0 ;;
    -*)               echo "unknown option: $1" >&2; exit 2 ;;
    *)                explicit_sources+=("$1") ;;
  esac
  shift
done
if [ "${#explicit_sources[@]}" -gt 0 ]; then
  SOURCES=("${explicit_sources[@]}")
fi

# Never let the target be one of the sources: every count below would be read twice and
# the loose-file move would be a no-op that reads as a success.
for s in "${SOURCES[@]}"; do
  if [ "$(readlink -m "$s")" = "$(readlink -m "$TARGET")" ]; then
    echo "ERROR: $s is the target. The target must be a directory of its own." >&2
    exit 2
  fi
done

# Written as a full if rather than `[ -d "$s" ] && ...`: under `set -e` a trailing test
# that is false makes the whole loop exit non-zero, and the script would stop here simply
# because the last directory of the list is absent.
present_sources=()
for s in "${SOURCES[@]}"; do
  if [ -d "$s" ]; then present_sources+=("$s"); fi
done
if [ "${#present_sources[@]}" -eq 0 ]; then
  echo "ERROR: none of the source directories exist." >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

loose_count() { find "$1" -maxdepth 1 -type f -name '[0-9]*.json' | wc -l; }
arc_members() { tar -tzf "$1" | wc -l; }

inventory() {
  printf '%-58s %10s %8s %10s\n' "directory" "loose" "archives" "members"
  for s in "${present_sources[@]}" "$TARGET"; do
    if [ ! -d "$s" ]; then
      printf '%-58s %10s %8s %10s\n' "$s" "(absent)" "-" "-"
      continue
    fi
    local n a m arc
    n=$(loose_count "$s")
    a=0; m=0
    if [ -d "$s/archive" ]; then
      while IFS= read -r arc; do
        a=$((a + 1)); m=$((m + $(arc_members "$arc")))
      done < <(find "$s/archive" -maxdepth 1 -type f -name '*.tar.gz' | sort)
    fi
    printf '%-58s %10s %8s %10s\n' "$s" "$n" "$a" "$m"
  done
}

# ---------------------------------------------------------------- 1. inventory (before)

echo "=== BEFORE ==="
inventory
total_loose_before=0
total_arc_members_before=0
for s in "${present_sources[@]}"; do
  total_loose_before=$((total_loose_before + $(loose_count "$s")))
  if [ -d "$s/archive" ]; then
    while IFS= read -r arc; do
      total_arc_members_before=$((total_arc_members_before + $(arc_members "$arc")))
    done < <(find "$s/archive" -maxdepth 1 -type f -name '*.tar.gz' | sort)
  fi
done
echo "sources total: $total_loose_before loose file(s), $total_arc_members_before archived member(s)"
echo

# ------------------------------------------------- 2. collisions among the loose files

echo "=== LOOSE-FILE NAME COLLISIONS ==="
: > "$work/loose_names"
for s in "${present_sources[@]}"; do
  find "$s" -maxdepth 1 -type f -name '[0-9]*.json' -printf '%f\n' >> "$work/loose_names"
done
sort "$work/loose_names" | uniq -d > "$work/loose_dups" || true
dup_n=$(wc -l < "$work/loose_dups")
unsafe=0
if [ "$dup_n" -eq 0 ]; then
  echo "none, the version component of the filename separates the colours, as expected."
else
  echo "$dup_n name(s) appear in more than one directory; comparing contents:"
  while IFS= read -r name; do
    sums=$(for s in "${present_sources[@]}"; do
             if [ -f "$s/$name" ]; then md5sum < "$s/$name" | cut -d' ' -f1; fi
           done | sort -u | wc -l)
    if [ "$sums" -eq 1 ]; then
      echo "  same content, safe: $name"
    else
      echo "  !! DIFFERENT CONTENT, merging would lose one: $name"
      unsafe=$((unsafe + 1))
    fi
  done < "$work/loose_dups"
fi
if [ "$unsafe" -gt 0 ]; then
  echo "ABORT: $unsafe colliding file(s) differ. Rename them by hand before merging." >&2
  exit 1
fi
echo

# ------------------------------------------------------- 3. the monthly archive merge

months=$(for s in "${present_sources[@]}"; do
           [ -d "$s/archive" ] && find "$s/archive" -maxdepth 1 -type f -name '*.tar.gz' -printf '%f\n'
         done | sed -e 's/[.]tar[.]gz$//' | sort -u || true)

echo "=== MONTHLY ARCHIVES ==="
if [ -z "$months" ]; then
  echo "no archive to merge."
else
  for m in $months; do
    srcs=()
    for s in "${present_sources[@]}"; do
      if [ -f "$s/archive/$m.tar.gz" ]; then srcs+=("$s/archive/$m.tar.gz"); fi
    done
    expected=0
    for a in "${srcs[@]}"; do expected=$((expected + $(arc_members "$a"))); done
    if [ -f "$TARGET/archive/$m.tar.gz" ]; then
      have=$(arc_members "$TARGET/archive/$m.tar.gz")
      echo "$m: already in the target ($have member(s)), skipped; ${#srcs[@]} source(s) hold $expected"
      continue
    fi
    echo "$m: ${#srcs[@]} source archive(s), $expected member(s) to merge"
    [ "$APPLY" -eq 1 ] || continue

    mkdir -p "$TARGET/archive"
    rm -f "$work/$m.tar"
    i=0
    for a in "${srcs[@]}"; do
      if [ "$i" -eq 0 ]; then
        gzip -dc "$a" > "$work/$m.tar"
      else
        gzip -dc "$a" > "$work/part.tar"
        tar --concatenate --file="$work/$m.tar" "$work/part.tar"
        rm -f "$work/part.tar"
      fi
      i=$((i + 1))
    done
    got=$(tar -tf "$work/$m.tar" | wc -l)
    if [ "$got" -ne "$expected" ]; then
      echo "  !! member count mismatch: merged $got, expected $expected, target untouched" >&2
      exit 1
    fi
    same_name=$(tar -tf "$work/$m.tar" | sort | uniq -d | wc -l)
    if [ "$same_name" -ne 0 ]; then
      echo "  note: $same_name member name(s) appear twice (one request logged by two colours)"
    fi
    gzip -f "$work/$m.tar"
    gzip -t "$work/$m.tar.gz"
    final=$(arc_members "$work/$m.tar.gz")
    if [ "$final" -ne "$expected" ]; then
      echo "  !! recompressed archive holds $final member(s), expected $expected, aborting" >&2
      exit 1
    fi
    mv "$work/$m.tar.gz" "$TARGET/archive/$m.tar.gz"
    echo "  merged -> $TARGET/archive/$m.tar.gz ($final member(s))"
  done
fi
echo

# ------------------------------------------------------------- 4. move the loose files

echo "=== LOOSE FILES ==="
if [ "$APPLY" -eq 1 ]; then
  mkdir -p "$TARGET"
  moved=0
  dropped=0
  for s in "${present_sources[@]}"; do
    while IFS= read -r f; do
      name=$(basename "$f")
      if [ -e "$TARGET/$name" ]; then
        if cmp -s "$f" "$TARGET/$name"; then
          rm -f "$f"
          dropped=$((dropped + 1))
        else
          echo "  !! $name differs from the copy already in the target, left in $s" >&2
          exit 1
        fi
      else
        mv "$f" "$TARGET/$name"
        moved=$((moved + 1))
      fi
    done < <(find "$s" -maxdepth 1 -type f -name '[0-9]*.json')
  done
  echo "moved $moved file(s), dropped $dropped duplicate(s) already present"
else
  echo "dry run: $total_loose_before file(s) would be moved"
fi
echo

# --------------------------------------------- 5. prune the source archives (opt-in)

if [ "$PRUNE" -eq 1 ]; then
  echo "=== PRUNE SOURCES ==="
  for m in $months; do
    if [ ! -f "$TARGET/archive/$m.tar.gz" ]; then
      echo "  !! $m is not in the target, nothing pruned for that month" >&2
      continue
    fi
    tar -tzf "$TARGET/archive/$m.tar.gz" | sort -u > "$work/target_members"
    for s in "${present_sources[@]}"; do
      a="$s/archive/$m.tar.gz"
      [ -f "$a" ] || continue
      if tar -tzf "$a" | sort -u | comm -23 - "$work/target_members" | grep -q .; then
        echo "  !! $a holds member(s) absent from the target, kept" >&2
      else
        rm -f "$a"
        echo "  removed $a"
      fi
    done
  done
  echo
fi

# ---------------------------------------------------------------- 6. inventory (after)

echo "=== AFTER ==="
inventory
echo
echo "Acceptance: the target's loose count plus its archived members must equal the"
echo "sources' $total_loose_before + $total_arc_members_before measured above, minus any duplicate reported."
if [ "$APPLY" -eq 0 ] && [ "$PRUNE" -eq 0 ]; then
  echo
  echo "Nothing was written. Re-run with --apply to perform the merge."
fi
