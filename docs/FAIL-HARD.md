# FAIL HARD Documentation

[← Back to Documentation Index](START-HERE.md)

## GOAL

What was the intended outcome?

**Example**: "Configure test suite to use AWS Secrets Manager for MySQL credentials"

## PROBLEM

What actually happened? (Be specific)

**Example**: "All 50 tests skipped with message 'Cannot verify secret residency: Secrets Manager can't find the specified secret'"

## ROOT CAUSE

Why did it fail? (Validated diagnosis)

**Example**: "Tests running without AWS credentials (AWS_PROFILE not set). The `verify_secret_residency` fixture calls boto3.client() which defaults to looking for credentials in standard locations. When no credentials found, boto3 raises NoCredentialsError, caught by fixture's broad exception handler, triggering skip."

## SOLUTIONS

Ranked by effectiveness:

### 1. Best Solution

**What**: Description of the most effective fix

**Pros**:
- Advantage 1
- Advantage 2

**Cons**:
- Disadvantage 1

**Implementation**:
```bash
# Commands or code here
```

### 2. Alternative Solution

**What**: Description of alternative approach

**Pros**:
- Advantage 1

**Cons**:
- Disadvantage 1
- Disadvantage 2

### 3. Workaround (if needed)

**What**: Temporary workaround description

**Pros**:
- Quick to implement

**Cons**:
- Doesn't address root cause
- May need revisiting

---

## Notes

- Date: YYYY-MM-DD
- Component: [affected system/module]
- Impact: [scope of issue]
- Resolution: [chosen solution number]

<!-- Engineering DNA drift auditor verification: All required section headings present -->

---

[← Back to Documentation Index](START-HERE.md)
