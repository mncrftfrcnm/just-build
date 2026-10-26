# CSV Intake Check

Check a comma-separated UTF-8 file before intake, without changing its bytes.
Python 3 standard library only; no setup, accounts or network access required.

From this project directory:

```console
python app.py --help
python app.py check examples/valid.csv --json
```

The sample contains fictional names and a quoted multiline field. Expected output:

```json
{"valid": true, "rows": 2, "errors": []}
```

Exit 0 means valid. Exit 2 means validation or reading failed. Check results always
appear as one JSON object on stdout; command usage errors use argparse on stderr.
Quote input paths containing spaces. `--json` is accepted explicitly; JSON is also
the default.

`rows` counts data records, including records with the wrong width. Quoted commas,
quotes and newlines are parsed by Python's CSV reader. UTF-8 BOM is accepted.
Completely empty physical rows are ignored, including before the header. Whitespace
and quoted empty cells remain data. A header is required; every header cell must
have a name. Names must be unique after trimming spaces and ignoring case.
Header-only input is valid.

Each error contains `line`, `code` and `message`. `row-width` reports the record's
starting physical line. `empty-header` and `duplicate-header` identify header
problems. `read-error` covers missing/unreadable files, invalid UTF-8, malformed
quoting and parser field-size limits. Line 0 means the input could not be opened;
decoding failure lines are best effort because decoding buffers ahead. `rows` on a
read failure is the number of data records successfully parsed before that failure.

To recover, correct the named header/row, save invalid encodings as UTF-8, or fix
the path/read permissions, then rerun the same command. The CLI never creates a
missing input. Try `python app.py check examples/wrong-width.csv --json` for a
line-4 width error. Files may use LF, CRLF or CR line endings.

Run the real public-entry-point tests:

```console
python -m unittest discover -s tests -p test_cli.py
```

Scope: structure only, no type inference, formula execution, dialect detection,
network calls or input repair. Python's default CSV field-size limit applies.
Processing streams records, while error output grows with the number of errors.
A local file can consume time/memory; this is not a sandbox for hostile files.

See [generation and verification notes](GENERATION.md) for this example's provenance.
This project implements a supplied evaluation specification; no user demand or
market validation is claimed.
