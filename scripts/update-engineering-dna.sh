#!/usr/bin/env bash
set -euo pipefail

# Update engineering-dna submodule to latest remote main and optionally push.
# Usage:
#   scripts/update-engineering-dna.sh            # update submodule only
#   scripts/update-engineering-dna.sh --push     # commit & push submodule pointer

SUB_PATH="engineering-dna"
BRANCH="main"

if [[ ! -d "$SUB_PATH/.git" ]]; then
  echo "FAIL HARD DIAGNOSTIC"
  echo "GOAL: Update engineering-dna submodule"
  echo "PROBLEM: Submodule directory '$SUB_PATH' not initialized"
  echo "ROOT CAUSE: Missing submodule clone or incorrect path"
  echo "SOLUTIONS:"
  echo "1. Run: git submodule update --init --recursive"
  echo "2. Verify path in .gitmodules matches '$SUB_PATH'"
  echo "3. Re-add submodule: git submodule add https://github.com/CharlesHandshy/engineering-dna.git $SUB_PATH"
  exit 1
fi

echo "[update] fetching remote refs"
git -C "$SUB_PATH" fetch origin "$BRANCH" --quiet

REMOTE_SHA=$(git -C "$SUB_PATH" rev-parse origin/$BRANCH)
LOCAL_SHA=$(git -C "$SUB_PATH" rev-parse HEAD)

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  echo "[update] already at latest $BRANCH ($LOCAL_SHA)"
else
  echo "[update] advancing submodule from $LOCAL_SHA to $REMOTE_SHA"
  git -C "$SUB_PATH" checkout "$BRANCH" --quiet
  git -C "$SUB_PATH" reset --hard "$REMOTE_SHA" --quiet
  git add "$SUB_PATH"
  echo "[update] staged new submodule pointer"
fi

if [[ "${1:-}" == "--push" ]]; then
  if git diff --cached --quiet; then
    echo "[push] No changes to commit (already latest)"
  else
    git commit -m "pullDB: update engineering-dna submodule to $REMOTE_SHA" || true
    git push origin "$(git rev-parse --abbrev-ref HEAD)"
    echo "[push] pushed updated submodule pointer"
  fi
fi

echo "[update] complete"#!/usr/bin/env bash
set -euo pipefail

# Update engineering-dna submodule to latest main
# Usage: scripts/update-engineering-dna.sh [--push]
# If --push is supplied, commit and push the updated submodule reference.

cd "$(dirname "$0")/.."  # enter pullDB root

log() { printf "[engineering-dna-update] %s\n" "$*"; }
fail() {
  echo "\nFAIL HARD DIAGNOSTIC" >&2
  echo "GOAL: Update engineering-dna submodule to latest main" >&2
  echo "PROBLEM: $1" >&2
  echo "ROOT CAUSE: See preceding command output" >&2
  echo "SOLUTIONS:" >&2
  echo "1. Check network/GitHub availability" >&2
  echo "2. Verify permissions for repository access" >&2
  echo "3. Manually run: git submodule update --remote Tools/pullDB/engineering-dna" >&2
  exit 1
}

SUB_PATH="Tools/pullDB/engineering-dna"
if [[ ! -d "$SUB_PATH" ]]; then
  fail "Submodule directory missing at $SUB_PATH" "ls $SUB_PATH"
fi

log "Fetching latest submodule commits"
if ! git submodule update --remote "$SUB_PATH"; then
  fail "git submodule update failed" "git submodule update --remote $SUB_PATH"
fi

LATEST=$(git -C "$SUB_PATH" rev-parse --short HEAD)
log "Submodule updated to commit $LATEST"

git add "$SUB_PATH"

if [[ "${1:-}" == "--push" ]]; then
  log "Committing submodule update"
  git commit -m "pullDB: update engineering-dna submodule to $LATEST"
  log "Pushing pulldb branch"
  git push origin pulldb || fail "Push failed" "git push origin pulldb"
fi

log "Done"
