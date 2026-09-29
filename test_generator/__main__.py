"""Simple CLI for generating tests from YAML files.

Usage: python -m test_generator config.yaml [config2.yaml ...] \
           [--questions questions.yaml]... \
           [--figures-dir <dir>]... [--out-dir <dir>] \
           [--exclude-manifest <manifest.yaml>]... \
           [--report] [--archive]

       python -m test_generator config.yaml --from-manifest <manifest.yaml> \
           [--new-version] [--questions questions.yaml]... \
           [--figures-dir <dir>]... [--out-dir <dir>] \
           [--report] [--archive]

       python -m test_generator config.yaml [config2.yaml ...] --watch \
           [--from-manifest <manifest.yaml>] \
           [--questions questions.yaml]... [--figures-dir <dir>]... \
           [--out-dir <dir>] [--student-only | --solution-only] [--report]

       python -m test_generator --report-from-manifest <manifest.yaml>

Each config file describes an assessment (title, author, class name,
duration, and question filters); the question bank comes from the
optional questions YAML file(s), a `questions` list in the config file
itself, or all combined. `--questions` and `--figures-dir` may each be
given multiple times; on figure filename collisions the earliest-listed
directory wins. A `question_count` config field randomly
selects that many questions from the filtered pool (maximizing section
coverage and avoiding `related_to` pairs when possible), and
`scramble_questions: true` shuffles the question order; both re-randomize
on every run, including draft/watch regeneration. Each run mints a fresh
hex form ID and writes a manifest alongside the PDFs; `--from-manifest`
replays a manifest to exactly recreate that version, and with
`--new-version` instead reissues the same questions as a fresh version
(new form ID, re-scrambled question and choice order) with its own
manifest. A replay writes its manifest too (prompting before it would
overwrite the old one); if the config now asks for more questions than
the manifest holds, the manifest's questions are kept and the normal
picker tops up the rest. Adding `--watch` to a replay iterates on that
version's questions in draft mode: the manifest's question and choice
order are kept, but the footer shows `draft`, no manifest is written, and
the MD5 mismatches caused by editing the watched files are reported as
warnings instead of prompting. Replay takes the
same config, question bank, and figures arguments as a normal run — the
input files may live anywhere, as long as their contents (MD5 sums)
match the manifest. `--exclude-manifest` (repeatable) drops the
questions recorded in earlier manifests from the pool, so a follow-up
assessment reuses nothing from those versions.
A `dok_target` config field steers the selection's
average DOK to at least — and as close as possible to — the target.
With `--report`, a report of section coverage and DOK levels is printed
after each generation; it shows the average DOK against the target,
highlighting the average in yellow when the target was missed. Manifests also record each
question's sections and DOK, so `--report-from-manifest` prints that
report for an existing version on its own, without any other inputs and
without regenerating anything. Manifests also record each MCQ's answer
letter and a top-level `answer_key` summary, and the solution copy prints
each question's DOK, sections, and id for review. An `instructions` config
field (raw LaTeX) renders a framed box at the top of the first page.
`--archive` also writes a self-contained ZIP of the version (pruned
sources, referenced figures, manifest, .tex sources, and a README with the
report and rebuild commands); it is not available in watch mode.
"""
import argparse
import hashlib
import os
import random
import secrets
import string
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ._version import __version__
from .archive import format_readme, prune_questions_yaml, write_archive
from .core import (
    Question,
    _effective_dok,
    _question_sections,
    _quote_backslash_scalar_lines,
    compile_tex,
    filter_questions,
    load_question_pool,
    make_choice_orders,
    render_tex,
    select_questions,
)
from .report import format_report
from .validation import validate_config, validate_manifest

# Version 2 embeds per-question sections/DOK (and the config's section
# range) so a report can be printed from the manifest alone. Version 3
# adds each MCQ's answer letter and a top-level answer_key summary.
MANIFEST_VERSION = 3
SUPPORTED_MANIFEST_VERSIONS = (1, 2, 3)


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

    # Field types and value ranges (question_count, scramble_questions,
    # dok_target, instructions, questions-is-a-list, and unknown keys) are
    # enforced by the config JSON Schema.
    validate_config(config, config_path)

    return config


def _use_color() -> bool:
    """Use ANSI color only on a terminal, honoring the NO_COLOR convention."""
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _new_form_id() -> str:
    return secrets.token_hex(4)


def _display_form_id(form_id: str) -> str:
    """Group an 8-hex form ID for the page footer (draft passes through)."""
    if len(form_id) == 8:
        return f"{form_id[:4]}-{form_id[4:]}"
    return form_id


def _output_base(config: dict[str, Any]) -> str:
    """Output filename base: `<class_id>_<name>`, or `<name>` if no class_id."""
    class_id = config.get("class_id")
    name = config["name"]
    return f"{class_id}_{name}" if class_id else str(name)


def _output_paths(
    config: dict[str, Any],
    form_id: str,
    out_dir: str,
    student_only: bool = False,
    solution_only: bool = False,
) -> list[tuple[Path, bool]]:
    """Return the (path, solution) pairs to generate for this config."""
    base = _output_base(config)
    out = Path(out_dir)
    paths: list[tuple[Path, bool]] = []
    if not solution_only:
        paths.append((out / f"{base}.pdf", False))
    if not student_only:
        paths.append((out / f"{base}_solutions.pdf", True))
    return paths


def _manifest_path(config: dict[str, Any], form_id: str, out_dir: str) -> Path:
    return Path(out_dir) / f"{_output_base(config)}_{form_id}.manifest.yaml"


def _archive_path(config: dict[str, Any], form_id: str, out_dir: str) -> Path:
    return Path(out_dir) / f"{_output_base(config)}_{form_id}.zip"


def _validate_question_ids(questions: list[Question]) -> None:
    """Every included question must have a unique `id` for manifest lookup.

    Presence and type of `id` are enforced by the question JSON Schema, so
    only uniqueness is checked here.
    """
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


def _answer_letter(order: list[int]) -> str:
    """Letter of the correct choice given a display->canonical permutation.

    Canonical index 0 is always the correct answer, so its display
    position determines the letter (A, B, C, ...).
    """
    return string.ascii_uppercase[order.index(0)]


def _figure_files(
    figures_dirs: list[str], questions: list[Question]
) -> list[tuple[str, Path]]:
    """Referenced figures as unique ``(figure name, resolved path)`` pairs.

    Each figure resolves to the first directory in ``figures_dirs`` that
    contains it (falling back to the first directory, so a missing figure
    still fails when it is read).
    """
    figures: dict[str, Path] = {}
    for q in questions:
        items = [q] + list(q.get("parts") or [])
        for item in items:
            figure = item.get("figure")
            if figure and str(figure) not in figures:
                candidates = [Path(d) / str(figure) for d in figures_dirs]
                found = next((c for c in candidates if c.exists()), candidates[0])
                figures[str(figure)] = found
    return list(figures.items())


def _manifest_files(
    config_path: str,
    questions_paths: list[str] | None,
    figures_dirs: list[str],
    questions: list[Question],
) -> list[str]:
    """Input files to record: config, question bank(s), and referenced figures."""
    paths = [str(config_path)]
    paths.extend(str(p) for p in questions_paths or [])
    paths.extend(str(path) for _, path in _figure_files(figures_dirs, questions))
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _build_manifest(
    form_id: str,
    config_path: str,
    questions_paths: list[str] | None,
    figures_dirs: list[str],
    questions: list[Question],
    choice_orders: dict[Any, list[int]],
    sections_spec: str | None = None,
    dok_target: float | None = None,
) -> dict[str, Any]:
    file_paths = _manifest_files(config_path, questions_paths, figures_dirs, questions)
    question_entries: list[dict[str, Any]] = []
    answer_letters: list[str] = []
    for q in questions:
        entry: dict[str, Any] = {"id": q["id"]}
        if q["id"] in choice_orders:
            entry["choice_order"] = choice_orders[q["id"]]
        is_mcq = str(q.get("question_type", "MCQ")).upper() == "MCQ"
        if is_mcq and q["id"] in choice_orders:
            letter = _answer_letter(choice_orders[q["id"]])
            entry["answer"] = letter
            answer_letters.append(letter)
        covered = sorted(_question_sections(q))
        if covered:
            entry["sections"] = [f"{major}.{minor}" for major, minor in covered]
        dok = _effective_dok(q)
        if dok is not None:
            entry["dok"] = dok
        question_entries.append(entry)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "form_id": form_id,
        "generated": datetime.now().astimezone().isoformat(),
        "generator_version": __version__,
        "files": [{"name": Path(p).name, "md5": _md5(p)} for p in file_paths],
    }
    if answer_letters:
        manifest["answer_key"] = ", ".join(answer_letters)
    manifest["questions"] = question_entries
    if sections_spec is not None:
        manifest["sections"] = str(sections_spec)
    if dok_target is not None:
        manifest["dok_target"] = dok_target
    return manifest


def _write_manifest(manifest_path: str | Path, manifest: dict[str, Any]) -> str:
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return str(manifest_path)


def _generate_copies(
    args: argparse.Namespace,
    config: dict[str, Any],
    form_id: str,
    questions_paths: list[str] | None,
    figures_dirs: list[str],
    question_order: list[Any],
    choice_orders: dict[Any, list[int]],
) -> dict[bool, str]:
    """Compile the requested copies; return their ``.tex`` keyed by solution.

    Only watch mode can limit the copies (``--student-only`` /
    ``--solution-only``); archives are never written there, so they
    always receive both sources.
    """
    texs: dict[bool, str] = {}
    for output_pdf, solution in _output_paths(
        config, form_id, args.out_dir, args.student_only, args.solution_only
    ):
        texs[solution] = render_tex(
            questions_paths,
            title=str(config.get("title") or ""),
            author=str(config.get("author") or ""),
            class_name=str(config.get("class_name") or ""),
            form_id=_display_form_id(form_id),
            duration=str(config.get("duration") or ""),
            solution=solution,
            questions=config.get("questions"),
            work_space=config.get("work_space"),
            question_order=question_order,
            choice_orders=choice_orders,
            instructions=str(config.get("instructions") or ""),
        )
        print(compile_tex(
            texs[solution], str(output_pdf), figures_dirs, questions_paths
        ))
    return texs


def _unique_name(name: str, taken: set[str]) -> str:
    """``name``, or ``stem-2.ext``, ``stem-3.ext``, ... if already taken."""
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while candidate in taken:
        candidate = f"{stem}-{n}{suffix}"
        n += 1
    taken.add(candidate)
    return candidate


def _write_archive(
    args: argparse.Namespace,
    config: dict[str, Any],
    config_path: str,
    form_id: str,
    figures_dirs: list[str],
    questions: list[Question],
    manifest: dict[str, Any],
    texs: dict[bool, str],
) -> str | None:
    """Write the version's self-contained ZIP archive; see archive.py.

    Sources are pruned to the selected questions, so the enclosed manifest
    matches ``manifest`` except for its ``files`` entries. Returns the
    archive path, or None when the user declines to overwrite one.
    """
    zip_path = _archive_path(config, form_id, args.out_dir)
    if zip_path.exists() and not _confirm(
            f"Overwrite existing archive {zip_path}? [y/N] "):
        print("Archive not overwritten.", file=sys.stderr)
        return None

    keep_ids = {q["id"] for q in questions}
    base = _output_base(config)
    root = f"{base}_{form_id}"
    manifest_name = f"{root}.manifest.yaml"
    config_name = Path(config_path).name
    sources: dict[str, bytes] = {}

    config_text, _ = prune_questions_yaml(Path(config_path).read_text(), keep_ids)
    sources[config_name] = config_text.encode()
    replay_args = [config_name, "--from-manifest", manifest_name]

    taken = {config_name}
    seen_banks: set[str] = set()
    for bank in args.questions or []:
        if str(bank) in seen_banks:
            continue
        seen_banks.add(str(bank))
        bank_text, kept = prune_questions_yaml(Path(bank).read_text(), keep_ids)
        if not kept:
            continue
        name = "questions/" + _unique_name(Path(bank).name, taken)
        sources[name] = bank_text.encode()
        replay_args += ["--questions", name]

    figures = _figure_files(figures_dirs, questions)
    for figure, path in figures:
        sources[f"figures/{figure}"] = path.read_bytes()
    if figures:
        replay_args += ["--figures-dir", "figures"]
    replay_args += ["--out-dir", "rebuilt"]

    inner = dict(manifest)
    inner["files"] = [
        {"name": Path(name).name, "md5": hashlib.md5(data).hexdigest()}
        for name, data in sources.items()
    ]
    tex_names = [f"{base}.tex", f"{base}_solutions.tex"]
    readme = format_readme(
        root,
        inner,
        title=str(config.get("title") or ""),
        replay_args=replay_args,
        tex_names=tex_names,
        file_names=[manifest_name, *sources, *tex_names],
        report=format_report(
            questions, config.get("sections"),
            dok_target=config.get("dok_target"), color=False,
        ),
    )
    entries: dict[str, bytes] = {
        "README.md": readme.encode(),
        manifest_name: yaml.safe_dump(inner, sort_keys=False).encode(),
        **sources,
        tex_names[0]: texs[False].encode(),
        tex_names[1]: texs[True].encode(),
    }
    return write_archive(zip_path, root, entries)


def _load_excluded_ids(manifest_paths: list[str]) -> set[Any]:
    """Union of question ids recorded in the given manifests.

    Exclusion is by id only — no MD5 verification — since the question
    banks typically evolve after a version is generated.
    """
    excluded: set[Any] = set()
    for path in manifest_paths:
        manifest = _load_manifest(path, warn_version=False)
        excluded.update(entry["id"] for entry in manifest.get("questions") or [])
    return excluded


def _run_once(args: argparse.Namespace, draft: bool = False) -> bool:
    ok = True
    figures_dirs = args.figures_dir or ["."]
    try:
        excluded = _load_excluded_ids(args.exclude_manifests or [])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False
    for config_path in args.config_yaml:
        try:
            config = _load_config(config_path)
            pool = load_question_pool(args.questions, config.get("questions"))
            if excluded:
                pool = [q for q in pool if q.get("id") not in excluded]
            included = filter_questions(
                pool,
                assessment_type=config.get("assessment_type"),
                sections=config.get("sections"),
                calculator_active=config.get("calculator_active"),
            )
            _validate_question_ids(included)
            question_count = config.get("question_count")
            if question_count is not None:
                try:
                    included = select_questions(
                        included, question_count,
                        dok_target=config.get("dok_target"),
                    )
                except RuntimeError as e:
                    if excluded:
                        raise RuntimeError(
                            f"{e} ({len(excluded)} question id(s) excluded "
                            f"via --exclude-manifest)"
                        ) from e
                    raise
            if config.get("scramble_questions"):
                random.shuffle(included)
            form_id = "draft" if draft else _new_form_id()
            question_order = [q["id"] for q in included]
            choice_orders = make_choice_orders(included)
            texs = _generate_copies(
                args, config, form_id, args.questions, figures_dirs,
                question_order, choice_orders,
            )
            if not draft:
                manifest = _build_manifest(
                    form_id, config_path, args.questions, figures_dirs,
                    included, choice_orders,
                    sections_spec=config.get("sections"),
                    dok_target=config.get("dok_target"),
                )
                print(_write_manifest(
                    _manifest_path(config, form_id, args.out_dir), manifest
                ))
                if args.archive:
                    archive = _write_archive(
                        args, config, config_path, form_id, figures_dirs,
                        included, manifest, texs,
                    )
                    if archive:
                        print(archive)
            if args.report:
                print(format_report(
                    included, config.get("sections"),
                    dok_target=config.get("dok_target"), color=_use_color(),
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


def _load_manifest(manifest_path: str, warn_version: bool = True) -> dict[str, Any]:
    """Load and version-check a manifest file."""
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise FileNotFoundError(manifest_path)
    manifest = yaml.safe_load(manifest_file.read_text()) or {}
    if manifest.get("manifest_version") not in SUPPORTED_MANIFEST_VERSIONS:
        supported = ", ".join(map(str, SUPPORTED_MANIFEST_VERSIONS))
        raise RuntimeError(
            f"Unsupported manifest_version {manifest.get('manifest_version')!r} "
            f"(this generator supports version(s) {supported}); the manifest "
            f"may have been written by a newer generator"
        )
    validate_manifest(manifest, manifest_path)
    if warn_version and manifest.get("generator_version") != __version__:
        print(
            f"Warning: manifest was written by generator "
            f"{manifest.get('generator_version')}, running {__version__}",
            file=sys.stderr,
        )
    return manifest


def _report_from_manifest(manifest_path: str) -> bool:
    """Print the coverage/DOK report recorded in a manifest; generate nothing."""
    manifest = _load_manifest(manifest_path)
    # Version 2 onward embeds the per-question report data; version 1 does not.
    if manifest.get("manifest_version") not in (2, 3):
        raise RuntimeError(
            f"manifest_version {manifest.get('manifest_version')} predates "
            f"embedded report data; replay it instead with "
            f"'<config.yaml> --from-manifest {manifest_path} --report'"
        )
    questions: list[Question] = [
        {
            "id": entry.get("id"),
            "sections": entry.get("sections") or [],
            "dok": entry.get("dok"),
        }
        for entry in manifest.get("questions") or []
    ]
    print(format_report(
        questions, manifest.get("sections"),
        dok_target=manifest.get("dok_target"), color=_use_color(),
    ))
    return True


def _run_from_manifest(args: argparse.Namespace, draft: bool = False) -> bool:
    """Replay a manifest; in draft mode nothing is recorded.

    A draft replay keeps the manifest's question set, order, and choice
    orders, but stamps ``draft`` instead of the manifest's form ID and
    writes no manifest, so watch mode can loop over it. Editing a watched
    file necessarily breaks the manifest's MD5s, so drafts report the
    mismatches as a warning instead of prompting.
    """
    manifest = _load_manifest(args.from_manifest)

    config_path = args.config_yaml[0]
    config = _load_config(config_path)
    figures_dirs = args.figures_dir or ["."]
    question_order = [entry["id"] for entry in manifest.get("questions") or []]
    choice_orders = {
        entry["id"]: entry["choice_order"]
        for entry in manifest.get("questions") or []
        if "choice_order" in entry
    }

    pool = load_question_pool(args.questions, config.get("questions"))
    by_id = {q.get("id"): q for q in pool}
    selected = [by_id[qid] for qid in question_order if qid in by_id]
    loaded_paths = _manifest_files(config_path, args.questions, figures_dirs, selected)

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
        label = (
            "Manifest verification failed (draft, continuing):" if draft
            else "Manifest verification failed:"
        )
        print(label, file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        if not draft and not _confirm("Continue anyway? [y/N] "):
            print("Aborted.", file=sys.stderr)
            return False

    # If the config now wants more questions than the manifest recorded,
    # keep the manifest's questions and top up the rest with the normal
    # picker. Verification above intentionally covers only the manifest's
    # original inputs, so the newly picked questions are exempt.
    question_count = config.get("question_count")
    if question_count is not None and question_count > len(selected):
        selected_ids = {q.get("id") for q in selected}
        candidates = filter_questions(
            [q for q in pool if q.get("id") not in selected_ids],
            assessment_type=config.get("assessment_type"),
            sections=config.get("sections"),
            calculator_active=config.get("calculator_active"),
        )
        needed = question_count - len(selected)
        try:
            extra = select_questions(
                candidates, needed, dok_target=config.get("dok_target")
            )
        except RuntimeError as e:
            raise RuntimeError(
                f"{e} to top up the {len(selected)} question(s) from the "
                f"manifest to question_count {question_count}"
            ) from e
        print(
            f"Manifest has {len(selected)} question(s); config wants "
            f"{question_count}, adding {needed}.",
            file=sys.stderr,
        )
        selected.extend(extra)
        question_order = [q["id"] for q in selected]
        choice_orders.update(make_choice_orders(extra))

    if draft:
        form_id = "draft"
    elif args.new_version:
        # a fresh version of the same test: new form ID, re-scrambled
        # question and choice order (scrambling is the point, regardless
        # of the config's scramble_questions), and its own manifest
        form_id = _new_form_id()
        random.shuffle(selected)
        question_order = [q["id"] for q in selected]
        choice_orders = make_choice_orders(selected)
    else:
        form_id = manifest["form_id"]

    texs = _generate_copies(
        args, config, form_id, args.questions,
        figures_dirs, question_order, choice_orders,
    )
    if not draft:
        manifest = _build_manifest(
            form_id, config_path, args.questions, figures_dirs,
            selected, choice_orders,
            sections_spec=config.get("sections"),
            dok_target=config.get("dok_target"),
        )
        # Always record a manifest for the replay; a plain replay reuses the
        # manifest's form ID, so its path matches the original — confirm
        # before overwriting it.
        manifest_out = _manifest_path(config, form_id, args.out_dir)
        if manifest_out.exists() and not _confirm(
                f"Overwrite existing manifest {manifest_out}? [y/N] "):
            print("Manifest not overwritten.", file=sys.stderr)
        else:
            print(_write_manifest(manifest_out, manifest))
        if args.archive:
            archive = _write_archive(
                args, config, config_path, form_id, figures_dirs,
                selected, manifest, texs,
            )
            if archive:
                print(archive)
    if args.report:
        print(format_report(
            selected, config.get("sections"),
            dok_target=config.get("dok_target"), color=_use_color(),
        ))
    return True


def _get_watched_mtimes(
    config_paths: list[str],
    questions_paths: list[str] | None,
    figures_dirs: list[str] | None,
) -> dict[str, float]:
    mtimes: dict[str, float] = {}
    watched = [Path(p) for p in config_paths]
    watched.extend(Path(p) for p in questions_paths or [])
    for p in watched:
        if p.exists():
            mtimes[str(p)] = p.stat().st_mtime
    fig_dirs: list[Path]
    if figures_dirs:
        fig_dirs = [Path(d) for d in figures_dirs]
    elif questions_paths:
        fig_dirs = [Path(questions_paths[0]).parent / "figures"]
    else:
        fig_dirs = []
    for fig_dir in fig_dirs:
        if fig_dir.is_dir():
            for f in fig_dir.rglob("*"):
                if f.is_file():
                    mtimes[str(f)] = f.stat().st_mtime
    return mtimes


def _watch_regenerate(args: argparse.Namespace) -> None:
    """Generate one draft round for watch mode, plain or from a manifest.

    Errors are reported but never stop the loop: a half-saved YAML file
    should leave the watcher running for the next save.
    """
    if args.from_manifest:
        try:
            _run_from_manifest(args, draft=True)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
    else:
        _run_once(args, draft=True)


def _watch_mode(args: argparse.Namespace) -> None:
    watched = ", ".join(args.config_yaml + (args.questions or []))
    print(f"Watching {watched} for changes. Press Ctrl+C to stop.")
    print("Draft mode: the footer shows 'draft' in place of a form ID and no manifest is written.")
    if args.from_manifest:
        print(
            f"Replaying {args.from_manifest}: its question and choice order "
            "are kept, and edits to the watched files are expected, so MD5 "
            "mismatches are reported as warnings."
        )
    _watch_regenerate(args)
    last_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
    try:
        while True:
            time.sleep(1)
            current_mtimes = _get_watched_mtimes(args.config_yaml, args.questions, args.figures_dir)
            if current_mtimes != last_mtimes:
                print("Change detected, regenerating...")
                _watch_regenerate(args)
                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="python -m test_generator")
    p.add_argument("config_yaml", nargs="*", help="Path(s) to YAML config file(s) describing the assessment(s); each is generated in sequence")
    p.add_argument("--from-manifest", dest="from_manifest", metavar="PATH", help="Recreate an existing version from its manifest file; provide the config (and --questions/--figures-dir) as in a normal run")
    p.add_argument("--report-from-manifest", dest="report_from_manifest", metavar="PATH", help="Print the coverage/DOK report recorded in a manifest and exit; no other arguments are needed and nothing is generated")
    p.add_argument("--new-version", dest="new_version", action="store_true", help="With --from-manifest: generate a new version of the same test (same questions, new form ID, re-scrambled question and choice order) and write a new manifest (not available with --watch)")
    p.add_argument("--exclude-manifest", dest="exclude_manifests", action="append", metavar="PATH", help="Exclude the questions recorded in this manifest from the pool (matched by id only; may be given multiple times)")
    p.add_argument("--questions", action="append", metavar="PATH", help="Path to a YAML file containing questions; may be given multiple times to combine banks (also combined with any 'questions' list in the config file)")
    p.add_argument("--out-dir", dest="out_dir", default=".", help="Directory where generated PDFs are written (default: current directory)")
    p.add_argument("--figures-dir", dest="figures_dir", action="append", metavar="DIR", help="Directory containing figures; may be given multiple times, earlier directories win on filename collisions (default: current directory)")
    p.add_argument("--watch", action="store_true", help="Watch for changes and regenerate drafts automatically (no manifest is written); may be combined with --from-manifest to iterate on an existing version's questions")
    p.add_argument("--archive", action="store_true", help="Also write <class_id>_<name>_<form_id>.zip: the manifest, the config and question bank(s) pruned to the selected questions, referenced figures, the .tex sources, and a README with the report and rebuild commands (not available with --watch)")
    p.add_argument("--report", action="store_true", help="Print a section-coverage and DOK report after each generation")
    only = p.add_mutually_exclusive_group()
    only.add_argument("--student-only", action="store_true", help="With --watch: regenerate only the student copy")
    only.add_argument("--solution-only", action="store_true", help="With --watch: regenerate only the solution copy")
    args = p.parse_args(argv)

    if args.new_version and not args.from_manifest:
        p.error("--new-version requires --from-manifest")
    if args.new_version and args.watch:
        p.error(
            "--new-version cannot be used with --watch (a draft has no form "
            "ID to reissue and writes no manifest)"
        )
    if args.exclude_manifests and args.from_manifest:
        p.error(
            "--exclude-manifest cannot be used with --from-manifest "
            "(replay keeps the manifest's question set)"
        )
    if (args.student_only or args.solution_only) and not args.watch:
        p.error(
            "--student-only and --solution-only are only valid with --watch "
            "(normal runs and replays always generate both copies)"
        )
    if args.archive and args.watch:
        p.error("--archive cannot be used with --watch (drafts are not archived)")
    if args.report_from_manifest:
        if args.config_yaml or args.from_manifest or args.watch or args.archive:
            p.error(
                "--report-from-manifest is standalone; do not combine it "
                "with config files, --from-manifest, --watch, or --archive"
            )
        try:
            ok = _report_from_manifest(args.report_from_manifest)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            ok = False
        if not ok:
            sys.exit(1)
    elif args.from_manifest:
        if len(args.config_yaml) != 1:
            p.error("--from-manifest requires exactly one config file")
        if args.watch:
            _watch_mode(args)
            return
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
