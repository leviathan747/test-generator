import importlib.resources as resources
import random
import shutil
import subprocess
import tempfile
import yaml
from pathlib import Path

from .sections import parse_range, parse_version



def _quote_backslash_scalar_lines(text: str) -> str:
    """Wrap plain YAML scalar values containing backslashes in single quotes."""
    output_lines = []
    block_scalar_indent = None  # tracks indentation of key that opened a block scalar

    for line in text.splitlines():
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)

        # Inside a block scalar: skip modification until indentation returns to the key level
        if block_scalar_indent is not None:
            if stripped and current_indent <= block_scalar_indent:
                block_scalar_indent = None  # exited the block scalar; fall through
            else:
                output_lines.append(line)
                continue

        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue

        if stripped.startswith("-"):
            item = stripped[1:].lstrip()
            if item and item[0] in ("|", ">"):
                block_scalar_indent = current_indent
            elif item and "\\" in item and not item.startswith(("'", '"')):
                prefix = line[: line.index("-")] + "- "
                escaped = item.replace("'", "''")
                line = f"{prefix}'{escaped}'"
        elif ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.lstrip()
            if value and value[0] in ("|", ">"):
                block_scalar_indent = current_indent
            elif value and "\\" in value and not value.startswith(("'", '"')):
                prefix = line[: line.index(key)] + f"{key}:"
                escaped = value.replace("'", "''")
                line = f"{prefix} '{escaped}'"

        output_lines.append(line)
    return "\n".join(output_lines) + "\n"

def filter_questions(questions, assessment_type=None, sections=None):
    """Filter questions by assessment type and/or section range.

    Args:
        questions: List of question mappings.
        assessment_type: When set, keep only questions whose
            ``assessment_type`` equals this value; questions missing the
            field are dropped.
        sections: When set, a SemVer-style section range (see
            :mod:`test_generator.sections`). A question without parts is
            kept only when the highest section it lists falls within the
            range. A question with parts is kept only when the highest
            section listed on each part falls within the range;
            question-level sections are ignored. Questions with no
            applicable sections listed are dropped.

    Returns:
        The filtered list of questions.
    """
    section_range = parse_range(sections) if sections is not None else None

    filtered = []
    for q in questions:
        if assessment_type is not None:
            if "assessment_type" not in q:
                continue
            if str(q.get("assessment_type")) != str(assessment_type):
                continue

        if section_range is not None:
            parts = q.get("parts") or []
            try:
                if parts:
                    highest = [
                        max(p_sections, key=parse_version)
                        for part in parts
                        if (p_sections := list(part.get("sections") or []))
                    ]
                else:
                    q_sections = list(q.get("sections") or [])
                    highest = [max(q_sections, key=parse_version)] if q_sections else []
                if not highest or not all(section_range.match(s) for s in highest):
                    continue
            except ValueError:
                continue

        filtered.append(q)
    return filtered


def _figure_include(figure, figure_width=None):
    """LaTeX snippet including a figure file from the figures/ build dir."""
    name = str(figure)
    if name.lower().endswith(".tex"):
        include = f"\\input{{figures/{name}}}"
        if figure_width:
            include = f"\\resizebox{{{figure_width}}}{{!}}{{{include}}}"
    else:
        opts = f"[width={figure_width}]" if figure_width else ""
        include = f"\\includegraphics{opts}{{figures/{name}}}"
    return include


def _apply_figure_placeholders(block, item):
    """Fill a template's $FIG_* placeholders from the item's figure fields."""
    above = begin = end = below = ""
    figure = item.get("figure")
    if figure:
        placement = str(item.get("figure_placement", "right"))
        include = _figure_include(figure, item.get("figure_width"))
        if placement == "right":
            begin = "\\begin{figright}{%s}" % include
            end = "\\end{figright}"
        # above/below use \centering rather than the center environment:
        # a trivlist before \part inside the parts list breaks with
        # "perhaps a missing \item". The leading \par keeps the figure
        # out of the preceding text's paragraph.
        elif placement == "above":
            above = "\\par{\\centering %s\\par}" % include
        elif placement == "below":
            below = "\\par{\\centering %s\\par}" % include
        else:
            raise RuntimeError(f"Unknown figure_placement: {placement!r}")
    return (
        block.replace("$FIG_ABOVE", above)
        .replace("$FIG_BEGIN", begin)
        .replace("$FIG_END", end)
        .replace("$FIG_BELOW", below)
    )


def generate_test(
    yaml_path: str | None,
    output_pdf: str,
    title: str = "",
    author: str = "",
    class_name: str = "",
    form_id: str = "",
    duration: str = "",
    figures_dir: str | None = None,
    solution: bool = False,
    assessment_type: str | None = None,
    sections: str | None = None,
    questions: list | None = None,
    work_space: str | None = None,
) -> str:
    """Generate a test PDF from a YAML file.

    Args:
        yaml_path: Path to a YAML file describing questions (must contain
            a top-level `questions` list of mappings with an `id` key).
            May be None when ``questions`` supplies the questions directly.
        output_pdf: Path where the generated PDF will be written.
        title: Test title.
        author: Author name.
        class_name: Class name.
        form_id: Form identifier (e.g. "A", "B").
        duration: Duration string (e.g. "30 min").
        figures_dir: Directory containing figure files to copy into the build
            environment. Defaults to a ``figures/`` subdirectory next to the
            YAML file when not specified.
        solution: When True, render the solution/answer-key copy.
        assessment_type: Optional filter; see :func:`filter_questions`.
        sections: Optional section range filter; see :func:`filter_questions`.
        questions: Optional list of question mappings appended to those
            loaded from ``yaml_path``.
        work_space: Default height of the answer work space for FRQ
            questions (e.g. "2in"). Questions and parts may override it
            with their own ``work_space`` field. Defaults to "1in".

    Returns:
        The path to the generated PDF (same as ``output_pdf``).

    Raises:
        RuntimeError: if YAML can't be parsed, template can't be loaded, or
            PDF generation via `pdflatex` fails.
    """
    all_questions = []
    yaml_file = None
    if yaml_path is not None:
        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            raise FileNotFoundError(yaml_path)

        raw_text = yaml_file.read_text()
        data = yaml.safe_load(_quote_backslash_scalar_lines(raw_text)) or {}
        all_questions.extend(data.get("questions") or [])
    all_questions.extend(questions or [])

    questions = filter_questions(
        all_questions,
        assessment_type=assessment_type,
        sections=sections,
    )

    try:
        with resources.open_text("test_generator.templates", "Test_Template.tex") as fh:
            template = fh.read()
    except Exception as exc:  # pragma: no cover - resource packaging issues
        raise RuntimeError("Unable to load internal TeX template resource") from exc

    template_names = {
        "MCQ": "MCQ_Template.tex",
        "FRQ": "FRQ_Template.tex",
        "FRQ_MULTIPART": "FRQ_Multipart_Template.tex",
        "FRQ_PART": "FRQ_Part_Template.tex",
    }
    question_templates = {}
    for key, template_name in template_names.items():
        try:
            with resources.open_text("test_generator.templates", template_name) as fh:
                question_templates[key] = fh.read()
        except Exception as exc:  # pragma: no cover - resource packaging issues
            raise RuntimeError("Unable to load internal question template resource") from exc

    default_work_space = str(work_space) if work_space is not None else "1in"

    q_blocks = []
    for q in questions:
        question_text = str(q.get("question", ""))
        solution_text = str(q.get("solution", ""))
        q_type = str(q.get("question_type", "MCQ")).upper()
        if q_type not in ("MCQ", "FRQ"):
            raise RuntimeError(f"Unknown question_type: {q_type!r}")

        parts = q.get("parts") or []
        if q_type == "FRQ" and parts:
            part_blocks = []
            for part in parts:
                p_block = _apply_figure_placeholders(question_templates["FRQ_PART"], part)
                p_block = p_block.replace("$QUESTION", str(part.get("question", "")))
                p_block = p_block.replace("$SOLUTION", str(part.get("solution", "")))
                p_block = p_block.replace(
                    "$SIZE", str(part.get("work_space", q.get("work_space", default_work_space)))
                )
                part_blocks.append(p_block)
            q_block = _apply_figure_placeholders(question_templates["FRQ_MULTIPART"], q)
            q_block = q_block.replace("$PARTS", "\n\n".join(part_blocks))
            q_block = q_block.replace("$QUESTION", question_text)
            q_blocks.append(q_block)
            continue

        q_block = _apply_figure_placeholders(question_templates[q_type], q)
        q_block = q_block.replace("$QUESTION", question_text)
        q_block = q_block.replace("$SOLUTION", solution_text)
        q_block = q_block.replace("$SIZE", str(q.get("work_space", default_work_space)))

        if q_type == "MCQ":
            answer_text = str(q.get("answer", ""))
            distractors = q.get("distractors", []) or []
            choices = [f"\\correctchoice {answer_text}"] + [f"\\choice {d}" for d in distractors]
            random.shuffle(choices)
            choices_block = "\n    ".join(choices)
            measure_block = "\n  ".join(
                f"\\measurechoice{{{text}}}" for text in [answer_text, *map(str, distractors)]
            )
            q_block = q_block.replace("$MEASURE_CHOICES", measure_block)
            q_block = q_block.replace("$CHOICES", choices_block)

        q_blocks.append(q_block)

    question_content = "\n\\vspace{\\stretch{1}}\n".join(q_blocks) + "\\vspace{\\stretch{1}}"
    tex_content = template.replace("$QUESTION_CONTENT", question_content)
    tex_content = tex_content.replace("$TITLE", title)
    tex_content = tex_content.replace("$AUTHOR", author)
    tex_content = tex_content.replace("$CLASSNAME", class_name)
    tex_content = tex_content.replace("$FORMID", form_id)
    tex_content = tex_content.replace("$DURATION", duration)
    if solution:
        tex_content = tex_content.replace("\\begin{document}", "\\printanswers\n\\begin{document}")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        tex_path = td_path / "output.tex"
        tex_path.write_text(tex_content)

        if figures_dir is not None:
            figures_src = Path(figures_dir)
        elif yaml_file is not None:
            figures_src = yaml_file.parent / "figures"
        else:
            figures_src = None
        if figures_src is not None and figures_src.is_dir():
            shutil.copytree(str(figures_src), str(td_path / "figures"))

        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(td_path),
            str(tex_path),
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            out = err.stdout.decode("utf-8", errors="replace") if getattr(err, "stdout", None) else ""
            raise RuntimeError(f"pdflatex failed:\n{out}") from err

        generated_pdf = td_path / "output.pdf"
        outp = Path(output_pdf)
        outp.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated_pdf), str(outp))

    return str(outp)
