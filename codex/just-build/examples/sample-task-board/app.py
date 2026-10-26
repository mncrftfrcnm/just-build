"""Synthetic reference vertical slice: zero-dependency local CLI task board."""
import argparse
import json
from pathlib import Path
import tempfile
import os


def load(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Invalid task database")
    return data


def save(path, tasks):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(dir=path.parent, prefix=".tasks-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(tasks, stream, indent=2)
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local task board example")
    parser.add_argument("--data", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    add = commands.add_parser("add")
    add.add_argument("title")
    commands.add_parser("list")
    done = commands.add_parser("done")
    done.add_argument("id", type=int)
    args = parser.parse_args(argv)
    tasks = load(args.data)
    if args.action == "add":
        if not args.title.strip():
            parser.error("title cannot be blank")
        item = {"id": max((t["id"] for t in tasks), default=0) + 1, "title": args.title.strip(), "done": False}
        tasks.append(item)
        save(args.data, tasks)
        print(json.dumps(item))
    elif args.action == "list":
        if not tasks:
            print('No tasks yet. Start with: add "My first task"')
        for t in tasks:
            print(f'{t["id"]}: {"done" if t["done"] else "todo"} — {t["title"]}')
    else:
        match = next((t for t in tasks if t["id"] == args.id), None)
        if match is None:
            parser.error("task ID does not exist; use list to see valid IDs")
        match["done"] = True
        save(args.data, tasks)
        print(f'{args.id}: done')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
