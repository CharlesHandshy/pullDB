#!/bin/bash
# Post-commit hook for SESSION-LOG prompts
#
# Install with:
#   ln -sf ../../scripts/post-commit-session-log.sh .git/hooks/post-commit
#
# This hook reminds you to update SESSION-LOG after significant commits.

# Colors
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get the last commit message
COMMIT_MSG=$(git log -1 --pretty=%B)

# Check if commit seems significant (not just formatting, deps, etc.)
is_significant() {
    # Significant if it's a feature, fix, or refactor
    echo "$COMMIT_MSG" | grep -qiE "^(feat|fix|refactor|perf)(\(|:)" && return 0
    
    # Significant if it touches many files
    FILE_COUNT=$(git diff-tree --no-commit-id --name-only -r HEAD | wc -l)
    [ "$FILE_COUNT" -gt 5 ] && return 0
    
    # Significant if commit message is long (likely detailed work)
    MSG_LEN=${#COMMIT_MSG}
    [ "$MSG_LEN" -gt 100 ] && return 0
    
    return 1
}

# Only prompt for significant commits
if is_significant; then
    echo ""
    echo -e "${YELLOW}📝 SESSION-LOG Reminder${NC}"
    echo -e "This looks like significant work. Consider updating:"
    echo -e "  ${CYAN}.pulldb/SESSION-LOG.md${NC}"
    echo ""
    echo "Quick entry format:"
    echo "  ## $(date +%Y-%m-%d) | Brief Topic"
    echo "  - What you did"
    echo "  - Why (reference principles)"
    echo ""
    
    # Offer to open the file
    if command -v code &> /dev/null; then
        echo -e "Open in VS Code? Run: ${CYAN}code .pulldb/SESSION-LOG.md${NC}"
    fi
    echo ""
fi

exit 0
