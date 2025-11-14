#!/usr/bin/env bash
set -euo pipefail

# Update the engineering-dna submodule to the latest origin/main commit.
# Optional --push flag commits the new pointer on the current branch and pushes.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUB_PATH="engineering-dna"
BRANCH="main"
PUSH=0

if [[ "${1:-}" == "--push" ]]; then
  PUSH=1
fi

cd "$ROOT_DIR"

if [[ ! -d "$SUB_PATH/.git" ]]; then
  cat <<'EOF'
FAIL HARD DIAGNOSTIC
GOAL: Update engineering-dna submodule to latest main
PROBLEM: Submodule directory 'engineering-dna' not initialized
ROOT CAUSE: Missing submodule checkout or incorrect path
SOLUTIONS:
 1. Run: git submodule update --init --recursive
 2. Verify .gitmodules entry points to engineering-dna
 3. If path changed, adjust this script and tooling references
EOF
  exit 1
fi

if [[ $PUSH -eq 1 ]]; then
  if ! git diff --cached --quiet; then
    extra_paths=$(git diff --cached --name-only | grep -v "^${SUB_PATH}$" || true)
    if [[ -n "$extra_paths" ]]; then
      cat <<'EOF'
FAIL HARD DIAGNOSTIC
GOAL: Commit engineering-dna submodule update with --push
PROBLEM: Staged changes detected outside engineering-dna/
ROOT CAUSE: Git index already contains other staged files
SOLUTIONS:
 1. Stash or commit existing staged changes before rerunning with --push
 2. Re-run the script without --push to just advance the submodule pointer
 3. Manually commit desired files and run this script again on a clean index
EOF
      exit 1
    fi
  fi
fi

echo "[update] fetching origin/$BRANCH"
git -C "$SUB_PATH" fetch origin "$BRANCH" --quiet

REMOTE_SHA=$(git -C "$SUB_PATH" rev-parse "origin/$BRANCH")
LOCAL_SHA=$(git -C "$SUB_PATH" rev-parse HEAD)

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  echo "[update] submodule already at $REMOTE_SHA"
else
  echo "[update] advancing submodule from $LOCAL_SHA to $REMOTE_SHA"
  git -C "$SUB_PATH" reset --hard "$REMOTE_SHA" --quiet
  git add "$SUB_PATH"
fi

if [[ $PUSH -eq 1 ]]; then
  if git diff --cached --quiet; then
    echo "[push] no changes to commit"
  else
    COMMIT_MSG="pullDB: update engineering-dna submodule to ${REMOTE_SHA}"
    git commit -m "$COMMIT_MSG"
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    git push origin "$CURRENT_BRANCH"
    echo "[push] committed and pushed submodule update"
  fi
fi

echo "[update] complete"
