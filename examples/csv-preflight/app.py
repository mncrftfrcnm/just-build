"""Read-only structural CSV preflight. No third-party dependencies."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100000
MAX_ISSUES = 100

def audit(path, delimiter=','):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('File exceeds 10 MiB limit; split a copy before auditing.')
    text = raw.decode('utf-8-sig')
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    issues = []
    total_issues = 0
    rows = 0
    header = []
    current_record = 1
    def issue(code, record, line, **extra):
        nonlocal total_issues
        total_issues += 1
        if len(issues) < MAX_ISSUES:
            issues.append(dict(code=code, record=record, physical_line_end=line, **extra))
    try:
        header = next(reader, None)
        if header is None:
            issue('empty-file', 1, 0)
            header = []
        else:
            seen = set()
            for n, cell in enumerate(header, 1):
                name = cell.strip()
                if not name:
                    issue('blank-header', 1, reader.line_num, column=n)
                elif name in seen:
                    issue('duplicate-header', 1, reader.line_num, column=n)
                seen.add(name)
            if not header:
                issue('blank-header', 1, reader.line_num)
            while True:
                current_record = rows + 2
                row = next(reader, None)
                if row is None:
                    break
                rows += 1
                if rows > MAX_ROWS:
                    raise ValueError('File exceeds 100000 data rows; split a copy before auditing.')
                if len(row) != len(header):
                    issue('row-width', current_record, reader.line_num, expected=len(header), actual=len(row))
    except csv.Error:
        issue('csv-syntax', current_record, reader.line_num)
    return dict(version=1, valid=total_issues == 0, data_rows=rows, columns=len(header), issue_count=total_issues, issues=issues, issues_truncated=total_issues > len(issues))

def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only CSV structural audit; original files are never rewritten.', epilog='Example: python -B app.py examples/bad.csv --json. Exit 0: structure passes; 1: issues found; 2: input/output error. Fix a copy and rerun.')
    parser.add_argument('input', type=Path, help='UTF-8 CSV, optional BOM; at most 10 MiB')
    parser.add_argument('--delimiter', default=',', help='One explicit character (default: comma); no guessing')
    parser.add_argument('--json', action='store_true', help='Print location-only JSON instead of summary')
    parser.add_argument('--report', type=Path, help='Create a new JSON report; existing paths are refused')
    args = parser.parse_args(argv)
    if len(args.delimiter) != 1 or args.delimiter in '\r\n\0"':
        parser.error('--delimiter must be one character other than newline, NUL or double quote')
    try:
        result = audit(args.input, args.delimiter)
        output = json.dumps(result, indent=2)
        if args.report:
            with args.report.open('x', encoding='utf-8', newline='\n') as target:
                target.write(output + '\n')
    except (OSError, UnicodeError, ValueError) as exc:
        # Never echo source cell contents or decoder excerpts into diagnostics.
        if isinstance(exc, FileExistsError):
            message = 'Report already exists; choose a new --report path.'
        elif isinstance(exc, UnicodeError):
            message = 'Input must be UTF-8; export a UTF-8 copy and retry.'
        elif isinstance(exc, OSError):
            message = 'Cannot read input or create report; check paths and permissions.'
        else:
            message = str(exc)
        print('Error: ' + message, file=sys.stderr)
        return 2
    if args.json:
        print(output)
    else:
        print(f"{'PASS' if result['valid'] else 'FAIL'}: {result['data_rows']} data rows, {result['columns']} columns, {result['issue_count']} issues")
        for item in result['issues']:
            print(f"  {item['code']}: record {item['record']}, ending line {item['physical_line_end']}")
        if not result['valid']:
            print('Correct a copy, then rerun. Use --json for details.')
    return 0 if result['valid'] else 1

if __name__ == '__main__':
    sys.exit(main())
