"""Offline CSV intake validation; no input writes or network operations."""
import argparse
import csv
import json
from pathlib import Path
import sys


def check(path):
    errors = []
    rows = 0
    reader = None
    start_line = 1
    header = None

    def error(line, code, message):
        errors.append({'line': line, 'code': code, 'message': message})

    try:
        with Path(path).open('r', encoding='utf-8-sig', newline='') as source:
            reader = csv.reader(source, strict=True)
            while True:
                start_line = reader.line_num + 1
                try:
                    record = next(reader)
                except StopIteration:
                    break
                # Ignore physically empty rows only; whitespace and quoted empties are data.
                if not record:
                    continue
                if header is None:
                    header = record
                    seen = set()
                    for column, name in enumerate(header, 1):
                        key = name.strip().casefold()
                        if not key:
                            error(start_line, 'empty-header', f'Header column {column} is empty; give every column a name.')
                        elif key in seen:
                            error(start_line, 'duplicate-header', f'Header column {column} duplicates an earlier name after trimming spaces and ignoring case.')
                        seen.add(key)
                else:
                    rows += 1
                    if len(record) != len(header):
                        error(start_line, 'row-width', f'Expected {len(header)} columns but found {len(record)}; check delimiters and quoting.')
            if header is None:
                error(1, 'empty-header', 'No header found; add at least one nonempty column name.')
    except UnicodeDecodeError:
        error(start_line, 'read-error', 'Cannot decode input as UTF-8; save the CSV as UTF-8 and retry.')
    except csv.Error as exc:
        error(start_line, 'read-error', f'Cannot parse CSV: {exc}. Check quoting and field size.')
    except (OSError, ValueError) as exc:
        # Avoid OS-specific details, tracebacks and potentially sensitive file content.
        reason = 'file not found' if isinstance(exc, FileNotFoundError) else 'input cannot be opened or read'
        error(0, 'read-error', f'Cannot read input: {reason}; check the path and read permissions.')
    return {'valid': not errors, 'rows': rows, 'errors': errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check CSV headers and row widths without changing the input.', epilog='Example: python app.py check examples/valid.csv --json\nExit codes: 0 valid; 2 validation or read failure.', formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('check', help='validate one UTF-8 CSV and print JSON')
    command.add_argument('input', metavar='INPUT.csv', help='CSV path; UTF-8 with an optional BOM')
    command.add_argument('--json', action='store_true', help='print deterministic JSON (also the default)')
    args = parser.parse_args(argv)
    result = check(args.input)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['valid'] else 2


if __name__ == '__main__':
    sys.exit(main())
