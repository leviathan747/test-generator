"""Simple CLI for generating tests from YAML files.

Usage: python -m test_generator config.yaml [config2.yaml ...] \
           [--questions questions.yaml] \
           [--figures-dir <dir>] [--out-dir <dir>] \
           [--student-only | --solution-only]

       python -m test_generator config.yaml --from-manifest <manifest.yaml> \
           [--questions questions.yaml] [--figures-dir <dir>] \
           [--out-dir <dir>] [--student-only | --solution-only]

Each config file describes an assessment (title, author, class name,
duration, and question filters); the question bank comes from the
optional questions YAML file, a `questions` list in the config file
itself, or both combined. Each run mints a fresh hex form ID and writes
a manifest alongside the PDFs; `--from-manifest` replays a manifest to
exactly recreate that version. Replay takes the same config, question
bank, and figures arguments as a normal run — the input files may live
anywhere, as long as their contents (MD5 sums) match the manifest.
"""
import argparse
import hashlib
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ._version import __version__
from .core import (
    Question,
    _quote_backslash_scalar_lines,
    filter_questions,
    generate_test,
    load_question_pool,
    make_choice_orders,
)

MANIFEST_VERSION = 1


def _load_config(config_path: str) -> dict[str, Any]:
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(config_path)

    config = yaml.safe_load(_quote_backslash_scalar_lines(config_file.read_text())) or {}
    if not isinstance(config, dict):
        raise RuntimeError(f"Config file must contain a YAML mapping: {config_path}")

    if not config.get("name"):
        config["name"] = config_file.stem

    if "form_id" in config:
        raise RuntimeError(
            f"Config field 'form_id' has been removed (form IDs are now "
            f"generated automatically) — delete it from {config_path}"
        )

    if not config.get("class_id"):
        raise RuntimeError("Config is missing required field(s): class_id")

    if config.get("questions") is not None and not isinstance(config["questions"], list):
        raise RuntimeError(f"Config field 'questions' must be a list: {config_path}")

    return config


def _new_form_id() -> str:
    return secrets.token_hex(4)


def _display_form_id(form_id: str) -> str:
    """Group an 8-hex form ID for the page footer (draft passes through)."""
    if len(form_id) == 8:
        return f"{form_id[:4]}-{form_id[4:]}"
    return form_id


def _output_paths(
    config: dict[str, Any],
    form_id: str,
    out_dir: str,
    student_only: bool = False,
    solution_only: bool = False,
) -> list[tuple[Path, bool]]:
    """Return the (path, solution) pairs to generate for this config."""
    base = f"{config['class_id']}_{config['name']}"
    out = Path(out_dir)
    paths: list[tuple[Path, bool]] = []
    if not solution_only:
        paths.append((out / f"{base}.pdf", False))
    if not student_only:
        paths.append((out / f"{base}_solutions.pdf", True))
    return paths


def _manifest_path(config: dict[str, Any], form_id: str, out_dir: str) -> Path:
    return Path(out_dir) / f"{config['class_id']}_{config['name']}_{form_id}.manifest.yaml"


def _validate_question_ids(questions: list[Question]) -> None:
    """Every included question must have a unique `id` for manifest lookup."""
    missing = [i + 1 for i, q in enumerate(questions) if not q.get("id")]
    if missing:
        raise RuntimeError(
            f"Question(s) missing an 'id' (position {', '.join(map(str, missing))} "
            f"of the included questions); every question needs a unique id"
        )
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for q in questions:
        qid = q["id"]
        if qid in seen:
            duplicates.append(qid)
        seen.add(qid)
    if duplicates:
        raise RuntimeError(
            f"Duplicate question ID(s): {', '.join(map(str, duplicates))}"
        )


def _md5(path: str | Path) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _manifest_files(
    config_path: str,
    questions_path: str | None,
    figures_dir: str,
    questions: list[Question],
) -> list[str]:
    """Input files to record: config, question bank, and referenced figures."""
    paths = [str(config_path)]
    if questions_path:
        paths.append(str(questions_path))
    for q in questions:
        items = [q] + list(q.get("parts") or [])
        for item in items:
            figure = item.get("figure")
            if figure:
                paths.append(str(Path(figures_dir) / str(figure)))
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _write_manifest(
    manifest_path: str | Path,
    form_id: str,
    config_path: str,
    questions_path: str | None,
    figures_dir: str,
    questions: list[Question],
    choice_orders: dict[Any, list[int]],
) -> str:
    file_paths = _manifest_files(config_path, questions_path, figures_dir, questions)
    question_entries: list[dict[str, Any]] = []
    for q in questions:
        entry = {"id": q["id"]}
        if q["id"] in choice_orders:
            entry["choice_order"] = choice_orders[q["id"]]
        question_entries.append(entry)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "form_id": form_id,
        "generated": datetime.now().astimezone().isoformat(),
        "generator_version": __version__,
        "files": [{"name": Path(p).name, "md5": _md5(p)} for p in file_paths],
        "questions": question_entries,
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return str(manifest_path)


def _generate_copies(
    args: argparse.Namespace,
    config: dict[str, Any],
    form_id: str,
    questions_path: str | None,
    figures_dir: str,
    question_order: list[Any],
    choice_orders: dict[Any, list[int]],
) -> None:
    for output_pdf, solution in _output_paths(
        config, form_id, args.out_dir, args.student_only, args.solution_only
    ):
        out = generate_test(
            questions_path,
            str(output_pdf),
            title=str(config.get("title") or ""),
            author=str(config.get("author") or ""),
            class_name=str(config.get("class_name") or ""),
            form_id=_display_form_id(form_id),
            duration=str(config.get("duration") or ""),
            figures_dir=figures_dir,
            solution=solution,
            questions=config.get("questions"),
            work_space=config.get("work_space"),
            question_order=question_order,
            choice_orders=choice_orders,
        )
        print(out)


def _run_once(args: argparse.Namespace, draft: bool = False) -> bool:
    ok = True
    figures_dir = args.figures_dir if args.figures_dir is not None else "."
    for config_path in args.config_yaml:
        try:
            config = _load_config(config_path)
            pool = load_question_pool(args.questions, config.get("questions"))
            included = filter_questions(
                pool,
                assessment_type=config.get("assessment_type"),
                sections=config.get("sections"),
                calculator_active=config.get("calculator_active"),
            )
            _validate_question_ids(included)
            form_id = "draft" if draft else _new_form_id()
            question_order = [q["id"] for q in included]
            choice_orders = make_choice_orders(included)
            _generate_copies(
                args, config, form_id, args.questions, figures_dir,
                question_order, choice_orders,
            )
            if not draft:
                print(_write_manifest(
                    _manifest_path(config, form_id, args.out_dir),
                    form_id, config_path, args.questions, figures_dir,
                    included, choice_orders,
                ))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            ok = False
    return ok


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _run_from_manifest(args: argparse.Namespace) -> bool:
    manifest_file = Path(args.from_manifest)
    if not manifest_file.exists():
        raise FileNotFoundError(args.from_manifest)
    manifest = yaml.safe_load(manifest_file.read_text()) or {}
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise RuntimeError(
            f"Unsupported manifest_version {manifest.get('manifest_version')!r} "
            f"(this generator supports version {MANIFEST_VERSION}); the manifest "
            f"may have been written by a newer generator"
        )
    if manifest.get("generator_version") != __version__:
        print(
            f"Warning: manifest was written by generator "
            f"{manifest.get('generator_version')}, running {__version__}",
            file=sys.stderr,
        )

    config_path = args.config_yaml[0]
    config = _load_config(config_path)
    figures_dir = args.figures_dir if args.figures_dir is not None else "."
    question_order = [entry["id"] for entry in manifest.get("questions") or []]
    choice_orders = {
        entry["id"]: entry["choice_order"]
        for entry in manifest.get("questions") or []
        if "choice_order" in entry
    }

    pool = load_question_pool(args.questions, config.get("questions"))
    by_id = {q.get("id"): q for q in pool}
    selected = [by_id[qid] for qid in question_order if qid in by_id]
    loaded_paths = _manifest_files(config_path, args.questions, figures_dir, selected)

    problems: list[str] = []
    loaded_md5s: set[str] = set()
    manifest_md5s = {entry["md5"] for entry in manifest.get("files") or []}
    for p in loaded_paths:
        path = Path(p)
        if not path.exists():
            problems.append(f"missing file: {path}")
            continue
        md5 = _md5(path)
        loaded_md5s.add(md5)
        if md5 not in manifest_md5s:
            problems.append(f"MD5 not in manifest: {path}")
    for entry in manifest.get("files") or []:
        if entry["md5"] not in loaded_md5s:
            # older version-1 manifests labeled entries "path"
            label = entry.get("name") or entry.get("path") or "?"
            problems.append(
                f"no loaded file matches manifest entry: {label} "
                f"(md5 {entry['md5']})"
            )
    if problems:
        print("Manifest verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        if not _confirm("Continue anyway? [y/N] "):
            print("Aborted.", file=sys.stderr)
            return False

    _generate_copies(
        args, config, manifest["form_id"], args.questions,
        figures_dir, question_order, choice_orders,
    )
    return True


def _get_watched_mtimes(
    config_paths: list[str],
    questions_path: str | None,
    figures_dir: str | None,
) -> dict[str, float]:
    mtimes: dict[str, float] = {}
    watched = [Path(p) for p in config_paths]
    if questions_path:
        watched.append(Path(questions_path))
    for p in watched:
        if p.exists():
            mtimes[str(p)] = p.stat().st_mtime
    fig_dir: Path | None
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


def _watch_mode(args: argparse.Namespace) -> None:
    configs = ", ".join(args.config_yaml)
    watched = configs if args.questions is None else f"{configs} and {args.questions}"
    print(f"Watching {watched} for changes. Press Ctrl+C to stop.")
    print("Draft mode: the footer shows 'draft' in place of a form ID and no manifest is written.")
    _run_once(args, draft=True)
    last_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
    try:
        while True:
            time.sleep(1)
            current_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
            if current_mtimes != last_mtimes:
                print("Change detected, regenerating...")
                _run_once(args, draft=True)
                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="python -m test_generator")
    p.add_argument("config_yaml", nargs="*", help="Path(s) to YAML config file(s) describing the assessment(s); each is generated in sequence")
    p.add_argument("--from-manifest", dest="from_manifest", metavar="PATH", help="Recreate an existing version from its manifest file; provide the config (and --questions/--figures-dir) as in a normal run")
    p.add_argument("--questions", help="Path to YAML file containing questions (combined with any 'questions' list in the config file)")
    p.add_argument("--out-dir", dest="out_dir", default=".", help="Directory where generated PDFs are written (default: current directory)")
    p.add_argument("--figures-dir", dest="figures_dir", default=None, help="Directory containing figures (default: current directory)")
    p.add_argument("--watch", action="store_true", help="Watch for changes and regenerate drafts automatically (no manifest is written)")
    only = p.add_mutually_exclusive_group()
    only.add_argument("--student-only", action="store_true", help="Generate only the student copy")
    only.add_argument("--solution-only", action="store_true", help="Generate only the solution copy")
    args = p.parse_args(argv)

    if args.from_manifest:
        if len(args.config_yaml) != 1:
            p.error("--from-manifest requires exactly one config file")
        if args.watch:
            p.error("--watch cannot be used with --from-manifest")
        try:
            ok = _run_from_manifest(args)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            ok = False
        if not ok:
            sys.exit(1)
    elif not args.config_yaml:
        p.error("provide config file(s) or --from-manifest")
    elif args.watch:
        _watch_mode(args)
    elif not _run_once(args):
        sys.exit(1)


if __name__ == "__main__":
    main()
