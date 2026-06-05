import importlib.resources as resources
import shutil
import subprocess
import tempfile
import yaml
from pathlib import Path



def _quote_backslash_scalar_lines(text: str) -> str:
    """Wrap plain YAML scalar values containing backslashes in single quotes."""
    output_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue

        if stripped.startswith("-"):
            item = stripped[1:].lstrip()
            if item and "\\" in item and not item.startswith(("'", '"', "|", ">")):
                prefix = line[: line.index("-")] + "- "
                escaped = item.replace("'", "''")
                line = f"{prefix}'{escaped}'"
        elif ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.lstrip()
            if value and "\\" in value and not value.startswith(("'", '"', "|", ">")):
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
        question_text = q.get("question", "")
        answer_text = q.get("answer", "")
        solution_text = q.get("solution", "")
        distractors = q.get("distractors", []) or []
        distractor_lines = "\n    ".join(f"\\choice {d}" for d in distractors)

        q_block = question_template
        q_block = q_block.replace("$QUESTION", question_text)
        q_block = q_block.replace("$ANSWER", answer_text)
        q_block = q_block.replace("$SOLUTION", solution_text)
        q_block = q_block.replace("$DISTRACTORS", distractor_lines)

        q_blocks.append(q_block)

    question_content = "\n\n".join(q_blocks)
    tex_content = template.replace("$QUESTION_CONTENT", question_content)
    tex_content = tex_content.replace("$TITLE", title)
    tex_content = tex_content.replace("$AUTHOR", author)
    tex_content = tex_content.replace("$CLASSNAME", class_name)
    tex_content = tex_content.replace("$FORMID", form_id)
    tex_content = tex_content.replace("$DURATION", duration)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        tex_path = td_path / "output.tex"
        tex_path.write_text(tex_content)

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
            out = err.stdout.decode() if getattr(err, "stdout", None) else ""
            raise RuntimeError(f"pdflatex failed:\n{out}") from err

        generated_pdf = td_path / "output.pdf"
        outp = Path(output_pdf)
        outp.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated_pdf), str(outp))

    return str(outp)
