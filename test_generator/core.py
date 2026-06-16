import importlib.resources as resources
import random
import shutil
import subprocess
import tempfile
import yaml
from pathlib import Path



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

def generate_test(
    yaml_path: str,
    output_pdf: str,
    title: str = "",
    author: str = "",
    class_name: str = "",
    form_id: str = "",
    duration: str = "",
    images_dir: str | None = None,
    solution: bool = False,
) -> str:
    """Generate a test PDF from a YAML file.

    Args:
        yaml_path: Path to a YAML file describing questions (must contain
            a top-level `questions` list of mappings with an `id` key).
        output_pdf: Path where the generated PDF will be written.
        title: Test title.
        author: Author name.
        class_name: Class name.
        form_id: Form identifier (e.g. "A", "B").
        duration: Duration string (e.g. "30 min").
        images_dir: Directory containing image files to copy into the build
            environment. Defaults to an ``images/`` subdirectory next to the
            YAML file when not specified.

    Returns:
        The path to the generated PDF (same as ``output_pdf``).

    Raises:
        RuntimeError: if YAML can't be parsed, template can't be loaded, or
            PDF generation via `pdflatex` fails.
    """
    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        raise FileNotFoundError(yaml_path)

    raw_text = yaml_file.read_text()
    data = yaml.safe_load(_quote_backslash_scalar_lines(raw_text)) or {}
    questions = data.get("questions", [])

    try:
        with resources.open_text("test_generator.templates", "Test_Template.tex") as fh:
            template = fh.read()
    except Exception as exc:  # pragma: no cover - resource packaging issues
        raise RuntimeError("Unable to load internal TeX template resource") from exc

    try:
        with resources.open_text("test_generator.templates", "Question_Template.tex") as fh:
            question_template = fh.read()
    except Exception as exc:  # pragma: no cover - resource packaging issues
        raise RuntimeError("Unable to load internal question template resource") from exc

    q_blocks = []
    for q in questions:
        question_text = str(q.get("question", ""))
        answer_text = str(q.get("answer", ""))
        solution_text = str(q.get("solution", ""))
        distractors = q.get("distractors", []) or []
        choices = [f"\\correctchoice {answer_text}"] + [f"\\choice {d}" for d in distractors]
        random.shuffle(choices)
        choices_block = "\n    ".join(choices)

        q_block = question_template
        q_block = q_block.replace("$QUESTION", question_text)
        q_block = q_block.replace("$CHOICES", choices_block)
        q_block = q_block.replace("$SOLUTION", solution_text)

        q_blocks.append(q_block)

    question_content = "\n\n".join(q_blocks)
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

        images_src = Path(images_dir) if images_dir is not None else yaml_file.parent / "images"
        if images_src.is_dir():
            shutil.copytree(str(images_src), str(td_path / "images"))

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
