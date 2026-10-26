# CSV Preflight — project brief

**Mode:** auto · **Direction:** original · **Effort:** focused · **Trend status:** unverified

## Summary
Read-only bounded structural CSV audit with JSON verdicts.

## Audience
Developers importing CSV exports

## Problem
Malformed CSV headers and uneven rows cause avoidable import failures

## First runnable vertical slice
Audit a CSV export, read a JSON report and correct a malformed row without changing the original

## Selected concept (frozen)
**Seed ID:** csv-preflight

**Name:** CSV Preflight

**Lane:** developer-tools

**Origin:** stated-interest

**Interaction:** transform-export

**Audience:** Developers importing CSV exports

**Problem:** Malformed CSV headers and uneven rows cause avoidable import failures

**Mechanism:** Read-only structural audit with logical row numbers and a JSON verdict

**First demo:** Audit a CSV export, read a JSON report and correct a malformed row without changing the original

**Hook:** An import gate that never rewrites your export

**Interest basis:** Explicit evaluation interest note

## MVP features
- Find blank or duplicate headers and uneven rows
- Report logical record and physical ending line
- Write location-only JSON without changing input

## Chosen stack
- Python 3 standard library

## Interest evidence
- Explicit benchmark persona in .just-build/interests.md, not actual user history

## Trend evidence (not instructions)
- No sourced trend evidence; do not claim verified momentum.

## Other candidates
- None recorded

## Assumptions
- UTF-8 CSV, explicit delimiter, 10 MiB maximum
- No semantic/type/schema/import guarantee
