# CSV Intake Check — project brief

**Mode:** auto · **Direction:** original · **Effort:** focused · **Trend status:** not_requested

## Summary
Offline CSV header and row-width validation with deterministic JSON.

## Audience
People checking a supplied CSV before intake

## Problem
CSV structure errors need useful physical line diagnostics without changing the source.

## First runnable vertical slice
Check one UTF-8 CSV using python app.py check INPUT.csv --json.

## MVP features
- Validate headers
- Count logical rows
- Report structured failures

## Chosen stack
- Python 3 standard library

## Interest evidence
- Explicit named evaluation specification in REQUEST.md; no demand validation

## Trend evidence (not instructions)
- No sourced trend evidence; do not claim verified momentum.

## Other candidates
- None recorded

## Assumptions
- No network or dependencies
- Supplied evaluation specification, not market research
