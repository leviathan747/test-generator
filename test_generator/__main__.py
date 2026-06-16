"""Simple CLI for generating tests from YAML files.

Usage: python -m test_generator input.yaml output.pdf --images-dir <dir>
"""
import argparse
import sys
import time
from pathlib import Path
from .core import generate_test


def _get_watched_mtimes(yaml_path, images_dir):
    mtimes = {}
    yaml_p = Path(yaml_path)
    if yaml_p.exists():
        mtimes[str(yaml_p)] = yaml_p.stat().st_mtime
    img_dir = Path(images_dir) if images_dir else yaml_p.parent / "images"
    if img_dir.is_dir():
        for f in img_dir.rglob("*"):
            if f.is_file():
                mtimes[str(f)] = f.stat().st_mtime
    return mtimes


def _run_once(args):
    try:
        out = generate_test(
            args.input_yaml,
            args.output_pdf,
            title=args.title,
            author=args.author,
            class_name=args.class_name,
            form_id=args.form_id,
            duration=args.duration,
            images_dir=args.images_dir,
            solution=args.solution,
        )
        print(out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)


def _watch_mode(args):
    print(f"Watching {args.input_yaml} for changes. Press Ctrl+C to stop.")
    _run_once(args)
    last_mtimes = _get_watched_mtimes(args.input_yaml, args.images_dir)
    try:
        while True:
            time.sleep(1)
            current_mtimes = _get_watched_mtimes(args.input_yaml, args.images_dir)
            if current_mtimes != last_mtimes:
                print("Change detected, regenerating...")
                _run_once(args)
                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def main(argv=None):
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="python -m test_generator")
    p.add_argument("input_yaml", help="Path to YAML file containing questions")
    p.add_argument("output_pdf", help="Path where the generated PDF will be written")
    p.add_argument("--title", default="", help="Test title")
    p.add_argument("--author", default="", help="Author name")
    p.add_argument("--class-name", dest="class_name", default="", help="Class name")
    p.add_argument("--form-id", dest="form_id", default="", help="Form identifier (e.g. A, B)")
    p.add_argument("--duration", default="", help="Duration string (e.g. '30 min')")
    p.add_argument("--images-dir", dest="images_dir", required=True, help="Directory containing images")
    p.add_argument("--solution", action="store_true", help="Generate solution/answer-key copy with answers shown")
    p.add_argument("--watch", action="store_true", help="Watch for changes and regenerate automatically")
    args = p.parse_args(argv)

    if args.watch:
        _watch_mode(args)
    else:
        _run_once(args)


if __name__ == "__main__":
    main()
