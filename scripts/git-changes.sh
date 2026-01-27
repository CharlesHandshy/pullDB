#!/bin/bash
# Smart git changes script - filters out binary files from diff output
# Usage: ./scripts/git-changes.sh [--diff] [--stat]

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Get list of changed files (staged + unstaged + untracked)
get_changed_files() {
    {
        # Unstaged modifications
        git diff --name-only 2>/dev/null
        # Staged modifications  
        git diff --name-only --cached 2>/dev/null
        # Untracked files
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u
}

# Filter to only text files using `file` command
filter_text_files() {
    while IFS= read -r filepath; do
        [[ -z "$filepath" ]] && continue
        [[ ! -e "$filepath" ]] && continue
        
        # Use file command to check if it's text
        filetype=$(file --brief --mime-type "$filepath" 2>/dev/null || echo "unknown")
        
        case "$filetype" in
            text/*|application/json|application/javascript|application/xml)
                echo "$filepath"
                ;;
            application/octet-stream|application/x-executable|application/x-sharedlib)
                # Skip binaries silently
                ;;
            *)
                # Check if file thinks it's binary
                if file "$filepath" 2>/dev/null | grep -q "text"; then
                    echo "$filepath"
                fi
                ;;
        esac
    done
}

# Main
MODE="${1:---stat}"

echo "=== Changed Text Files ==="
TEXT_FILES=$(get_changed_files | sort -u | filter_text_files)

if [[ -z "$TEXT_FILES" ]]; then
    echo "No text file changes detected."
    exit 0
fi

echo "$TEXT_FILES"
echo ""

case "$MODE" in
    --diff)
        echo "=== Diffs ==="
        for f in $TEXT_FILES; do
            if git ls-files --error-unmatch "$f" &>/dev/null; then
                # Tracked file - show diff
                git diff --color=always -- "$f" 2>/dev/null || true
            else
                # Untracked file - show first 50 lines
                echo ">>> NEW FILE: $f (first 50 lines)"
                head -50 "$f"
                echo "---"
            fi
        done
        ;;
    --stat)
        echo "=== Stats ==="
        git diff --stat -- $TEXT_FILES 2>/dev/null || true
        ;;
    *)
        echo "Usage: $0 [--diff|--stat]"
        ;;
esac
