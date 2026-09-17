"""Self-contained ZIP archives of a generated test version.

An archive bundles everything needed to recreate one version: the config
and question bank(s) pruned to the selected questions, the referenced
figures, the manifest, the rendered ``.tex`` sources, and a README with the
coverage report and rebuild commands.
"""
import re
import zipfile
from pathlib import Path
from typing import Any

import yaml

from .core import _quote_backslash_scalar_lines

_QUESTIONS_KEY_RE = re.compile(r"questions:\s*(#.*)?")


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def prune_questions_yaml(text: str, keep_ids: set[Any]) -> tuple[str, int]:
    """Drop unselected questions from a YAML file's top-level ``questions``.

    Pruning is done on the raw text so kept questions (and everything
    outside the list, such as other config keys and comments) stay
    byte-for-byte identical. Comment and blank lines between items travel
    with the preceding item. When no question is kept, the list is
    replaced by ``questions: []``.

    Returns:
        The pruned text and the number of questions kept.

    Raises:
        RuntimeError: If the list can't be split into one text chunk per
            parsed question (e.g. a flow-style ``questions: [...]`` list).
    """
    data = yaml.safe_load(_quote_backslash_scalar_lines(text)) or {}
    parsed = (data.get("questions") or []) if isinstance(data, dict) else []
    if not parsed:
        return text, 0

    lines = text.splitlines(keepends=True)
    key_index = next(
        (
            i for i, line in enumerate(lines)
            if _QUESTIONS_KEY_RE.fullmatch(line.rstrip("\r\n"))
        ),
        None,
    )
    if key_index is None:
        raise RuntimeError(
            "can't locate a block-style top-level 'questions:' list to prune"
        )

    prefix = lines[: key_index + 1]
    chunks: list[list[str]] = []
    list_indent: int | None = None
    end = len(lines)
    for i in range(key_index + 1, len(lines)):
        line = lines[i]
        if _is_blank_or_comment(line):
            if chunks:
                chunks[-1].append(line)
            else:
                prefix.append(line)
            continue
        indent = _indent(line)
        body = line.lstrip(" ")
        starts_item = body.startswith("-") and body[1:2] in ("", " ", "\n", "\r")
        if list_indent is None:
            if not starts_item:
                break
            list_indent = indent
        if indent == list_indent and starts_item:
            chunks.append([line])
        elif indent > list_indent and chunks:
            chunks[-1].append(line)
        else:
            end = i
            break

    # trailing blank/comment lines belong after the list, not to the last item
    suffix = lines[end:]
    if chunks:
        trailing: list[str] = []
        while chunks[-1] and _is_blank_or_comment(chunks[-1][-1]):
            trailing.insert(0, chunks[-1].pop())
        suffix = trailing + suffix

    if len(chunks) != len(parsed):
        raise RuntimeError(
            f"found {len(chunks)} question item(s) in the text but parsed "
            f"{len(parsed)}; can't prune this file"
        )

    kept = [
        "".join(chunk)
        for chunk, q in zip(chunks, parsed)
        if isinstance(q, dict) and q.get("id") in keep_ids
    ]
    if not kept:
        key_line = lines[key_index]
        newline = key_line[len(key_line.rstrip("\r\n")):] or "\n"
        prefix[key_index] = "questions: []" + newline
    return "".join(prefix) + "".join(kept) + "".join(suffix), len(kept)


def _command_block(program: str, args: list[str]) -> str:
    """Format a shell command with each ``--option value`` on its own line."""
    lines = [program]
    for arg in args:
        if arg.startswith("--"):
            lines.append(arg)
        else:
            lines[-1] += f" {arg}"
    return " \\\n    ".join(lines)


def format_readme(
    root: str,
    manifest: dict[str, Any],
    title: str,
    replay_args: list[str],
    tex_names: list[str],
    file_names: list[str],
    report: str,
) -> str:
    """Return the archive's README.md (markdownlint-clean)."""
    version = manifest.get("generator_version")
    command = _command_block("python -m test_generator", replay_args)
    pdflatex = "\n".join(
        f"pdflatex -interaction=nonstopmode -halt-on-error {name}"
        for name in tex_names
    )
    files = "\n".join(f"- `{name}`" for name in file_names)
    sections = [
        f"# {root}",
        "\n".join([
            f"- Title: {title}" if title else "- Title: (none)",
            f"- Form ID: `{manifest['form_id']}`",
            f"- Generated: {manifest['generated']}",
            f"- Generator version: {version}",
        ]),
        "## Contents",
        files,
        "The question YAML files contain only the questions selected for this\n"
        "version, so their MD5 sums in the enclosed manifest differ from the\n"
        "standalone manifest written alongside the original PDFs.",
        "## Rebuild with the generator",
        f"Install `test-generator` {version}, then run from this directory:",
        f"```sh\n{command}\n```",
        "## Rebuild with pdflatex",
        "No generator needed; run from this directory:",
        f"```sh\n{pdflatex}\n```",
        "PDFs rebuilt either way match in content but not byte-for-byte:\n"
        "`pdflatex` embeds the build time in each PDF.",
        "## Report",
        f"```text\n{report}\n```",
    ]
    return "\n\n".join(sections) + "\n"


def write_archive(zip_path: str | Path, root: str, entries: dict[str, bytes]) -> str:
    """Write ``entries`` (archive-relative path -> bytes) under ``root/``."""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(f"{root}/{name}", data)
    return str(zip_path)
