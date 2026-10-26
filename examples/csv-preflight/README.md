# CSV Preflight

Audit a UTF-8 CSV before importing it. Python 3 standard library only; no installation, login or network. Source files are opened read-only. Reports contain counts and locations, never header or cell values.

```powershell
python -B app.py --help
python -B app.py examples/bad.csv --json
python -B app.py examples/good.csv --report report.json
python -B -m unittest discover -s tests
python -B smoke.py
```

The fictional bad sample exits 1 with `row-width`; the good sample exits 0. Correct a separate copy and rerun. Existing report paths are refused: choose a fresh filename. `--delimiter ";"` audits semicolon exports without guessing. Input and argument errors exit 2 with guidance.

After creating `report.json`, repeat with another unused report filename, for example:

```powershell
python -B app.py examples/good.csv --report report-2.json
```

Checks: empty files, blank or duplicate headers (trimmed whitespace, case-sensitive), uneven records, and CSV parser syntax errors. Logical records start at 1 for the header; physical ending lines account for quoted newlines. Blank lines are treated as zero-cell records. BOM is accepted. No coercion or automatic repair.

Bounds: 10 MiB input, 100000 data records, first 100 issue details with a full issue count. Python's parser field-size limit also applies. UTF-8 only. This is structural preflight, not type/schema validation, formula safety or a guarantee that a destination importer accepts a file. No measured market demand or trend claim: the project was chosen against an explicit evaluation persona. csvclean, qsv and Frictionless already offer overlapping validation.

See [generation and verification notes](GENERATION.md) for this example's provenance.
