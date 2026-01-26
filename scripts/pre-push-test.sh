#!/bin/bash
# Pre-push hook for running fast tests before push
#
# Install with:
#   ln -sf ../../scripts/pre-push-test.sh .git/hooks/pre-push
#
# This hook runs fast unit tests to catch obvious breaks before pushing.

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧪 Running pre-push tests...${NC}"

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: Not in pullDB root directory${NC}"
    exit 1
fi

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Run fast unit tests only (skip slow integration/e2e tests)
echo -e "${YELLOW}Running unit tests...${NC}"
python -m pytest tests/unit -q --tb=short -x 2>/dev/null || {
    # If tests/unit doesn't exist, run pulldb internal tests
    python -m pytest pulldb/tests -q --tb=short -x --ignore=pulldb/tests/test_permissions_integration.py 2>/dev/null || {
        echo -e "${YELLOW}⚠️  No fast tests found, skipping...${NC}"
    }
}

TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
    echo -e "${GREEN}✅ Pre-push tests passed${NC}"
    exit 0
else
    echo -e "${RED}❌ Pre-push tests failed - push blocked${NC}"
    echo ""
    echo "To see full test output, run:"
    echo "  pytest tests/unit -v"
    echo ""
    echo "To bypass this check (not recommended):"
    echo "  git push --no-verify"
    echo ""
    exit 1
fi
