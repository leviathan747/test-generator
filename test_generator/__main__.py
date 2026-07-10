"""Simple CLI for generating tests from YAML files.

Usage: python -m test_generator config.yaml [config2.yaml ...] \
           [--questions questions.yaml] \
           [--figures-dir <dir>] [--out-dir <dir>] \
           [--student-only | --solution-only]

Each config file describes an assessment (title, author, class name, form
ID, duration, and question filters); the question bank comes from the
optional questions YAML file, a `questions` list in the config file
itself, or both combined.
"""
import argparse
import sys
import time
from pathlib import Path

import yaml

from .core import _quote_backslash_scalar_lines, generate_test


def _load_config(config_path):
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(config_path)

    config = yaml.safe_load(_quote_backslash_scalar_lines(config_file.read_text())) or {}
    if not isinstance(config, dict):
        raise RuntimeError(f"Config file must contain a YAML mapping: {config_path}")

    if not config.get("name"):
        config["name"] = config_file.stem

    missing = [key for key in ("class_id", "form_id") if not config.get(key)]
    if missing:
        raise RuntimeError(f"Config is missing required field(s): {', '.join(missing)}")

    if config.get("questions") is not None and not isinstance(config["questions"], list):
        raise RuntimeError(f"Config field 'questions' must be a list: {config_path}")

    return config


def _output_paths(config, out_dir, student_only=False, solution_only=False):
    """Return the (path, solution) pairs to generate for this config."""
    base = f"{config['class_id']}_{config['name']}_Form{config['form_id']}"
    out = Path(out_dir)
    paths = []
    if not solution_only:
        paths.append((out / f"{base}.pdf", False))
    if not student_only:
        paths.append((out / f"{base}_solutions.pdf", True))
    return paths


def _get_watched_mtimes(config_paths, questions_path, figures_dir):
    mtimes = {}
    watched = [Path(p) for p in config_paths]
    if questions_path:
        watched.append(Path(questions_path))
    for p in watched:
        if p.exists():
            mtimes[str(p)] = p.stat().st_mtime
    if figures_dir:
        fig_dir = Path(figures_dir)
    elif questions_path:
        fig_dir = Path(questions_path).parent / "figures"
    else:
        fig_dir = None
    if fig_dir is not None and fig_dir.is_dir():
        for f in fig_dir.rglob("*"):
            if f.is_file():
                mtimes[str(f)] = f.stat().st_mtime
    return mtimes


def _run_once(args):
    ok = True
    for config_path in args.config_yaml:
        try:
            config = _load_config(config_path)
            for output_pdf, solution in _output_paths(
                config, args.out_dir, args.student_only, args.solution_only
            ):
                out = generate_test(
                    args.questions,
                    str(output_pdf),
                    title=str(config.get("title") or ""),
                    author=str(config.get("author") or ""),
                    class_name=str(config.get("class_name") or ""),
                    form_id=str(config.get("form_id") or ""),
                    duration=str(config.get("duration") or ""),
                    figures_dir=args.figures_dir,
                    solution=solution,
                    assessment_type=config.get("assessment_type"),
                    sections=config.get("sections"),
                    questions=config.get("questions"),
                )
                print(out)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            ok = False
    return ok


def _watch_mode(args):
    configs = ", ".join(args.config_yaml)
    watched = configs if args.questions is None else f"{configs} and {args.questions}"
    print(f"Watching {watched} for changes. Press Ctrl+C to stop.")
    _run_once(args)
    last_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
    try:
        while True:
            time.sleep(1)
            current_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
            if current_mtimes != last_mtimes:
                print("Change detected, regenerating...")
                _run_once(args)
                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def main(argv=None):
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="python -m test_generator")
    p.add_argument("config_yaml", nargs="+", help="Path(s) to YAML config file(s) describing the assessment(s); each is generated in sequence")
    p.add_argument("--questions", help="Path to YAML file containing questions (combined with any 'questions' list in the config file)")
    p.add_argument("--out-dir", dest="out_dir", default=".", help="Directory where generated PDFs are written (default: current directory)")
    p.add_argument("--figures-dir", dest="figures_dir", default=".", help="Directory containing figures (default: a figures/ subdirectory next to the questions file)")
    p.add_argument("--watch", action="store_true", help="Watch for changes and regenerate automatically")
    only = p.add_mutually_exclusive_group()
    only.add_argument("--student-only", action="store_true", help="Generate only the student copy")
    only.add_argument("--solution-only", action="store_true", help="Generate only the solution copy")
    args = p.parse_args(argv)

    if args.watch:
        _watch_mode(args)
    elif not _run_once(args):
        sys.exit(1)


if __name__ == "__main__":
    main()
