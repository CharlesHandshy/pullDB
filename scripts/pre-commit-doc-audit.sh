#!/bin/bash
# Pre-commit hook for documentation audit
#
# Install with:
#   ln -sf ../../scripts/pre-commit-doc-audit.sh .git/hooks/pre-commit
#
# This hook runs the documentation audit agent on staged changes
# and blocks commits if critical documentation discrepancies are found.

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}📚 Running documentation audit...${NC}"

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: Not in pullDB root directory${NC}"
    exit 1
fi

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Run the audit agent in pre-commit mode
python -m pulldb.audit --pre-commit

AUDIT_EXIT=$?

if [ $AUDIT_EXIT -eq 0 ]; then
    echo -e "${GREEN}✅ Documentation audit passed${NC}"
else
    echo -e "${RED}❌ Documentation audit failed - commit blocked${NC}"
    echo ""
    echo "To see detailed findings, run:"
    echo "  python -m pulldb.audit --pre-commit --verbose"
    echo ""
    echo "To auto-fix issues, run:"
    echo "  python -m pulldb.audit --pre-commit --auto-fix"
    echo ""
    exit 1
fi
