import random
import re
import shutil
import sys
import time
import types
from pathlib import Path
from typing import cast
import subprocess

import pytest
import yaml as real_yaml

import test_generator
from test_generator.__main__ import main
from test_generator.core import Question, select_questions
from test_generator.report import format_report


def test_version_present() -> None:
    assert hasattr(test_generator, "__version__")


def test_filter_questions_assessment_type() -> None:
    questions: list[Question] = [
        {"id": 1, "assessment_type": "quiz"},
        {"id": 2, "assessment_type": "test"},
        {"id": 3},
    ]
    result = test_generator.filter_questions(questions, assessment_type="quiz")
    assert [q["id"] for q in result] == [1]


def test_filter_questions_no_filters_keeps_all() -> None:
    questions: list[Question] = [{"id": 1}, {"id": 2, "assessment_type": "quiz"}]
    assert test_generator.filter_questions(questions) == questions


def test_filter_questions_sections() -> None:
    questions: list[Question] = [
        {"id": 1, "sections": ["1.3"]},
        {"id": 2, "sections": ["1.3", "1.8"]},  # highest (1.8) outside range
        {"id": 3, "sections": [1.5, "1.7"]},
        {"id": 4},  # no sections listed
        {"id": 5, "sections": ["unknown"]},  # unparseable section
        {"id": 6, "sections": ["1.1", "1.5"]},  # only highest must match
    ]
    result = test_generator.filter_questions(questions, sections="1.3 - 1.7")
    assert [q["id"] for q in result] == [1, 3, 6]


def test_filter_questions_sections_multipart() -> None:
    questions = [
        {
            "id": 1,
            "sections": ["1.3"],
            "parts": [{"sections": ["1.4"]}, {"sections": ["1.5"]}],
        },
        {
            "id": 2,
            "sections": ["1.3"],
            "parts": [{"sections": ["2.1"]}],  # part outside range
        },
        {
            "id": 3,
            "parts": [{"sections": ["1.6"]}],  # sections only on parts
        },
        {
            "id": 4,
            # only each part's highest section must match
            "parts": [{"sections": ["1.1", "1.4"]}, {"sections": ["1.2", "1.6"]}],
        },
        {
            "id": 5,
            # one part's highest section outside the range
            "parts": [{"sections": ["1.4"]}, {"sections": ["1.5", "1.8"]}],
        },
        {
            "id": 6,
            # question-level sections are ignored when parts exist
            "sections": ["1.5"],
            "parts": [{"question": "no sections on parts"}],
        },
    ]
    result = test_generator.filter_questions(questions, sections="1.3 - 1.7")
    assert [q["id"] for q in result] == [1, 3, 4]


def test_filter_questions_calculator_active() -> None:
    questions = [
        {"id": 1, "calculator_active": True},
        {"id": 2, "calculator_active": False},
        {"id": 3},  # missing field means no calculator
    ]
    active = test_generator.filter_questions(questions, calculator_active=True)
    assert [q["id"] for q in active] == [1]
    inactive = test_generator.filter_questions(questions, calculator_active=False)
    assert [q["id"] for q in inactive] == [2, 3]
    assert test_generator.filter_questions(questions) == questions


def test_filter_questions_combined() -> None:
    questions = [
        {"id": 1, "assessment_type": "quiz", "sections": ["1.3"]},
        {"id": 2, "assessment_type": "test", "sections": ["1.3"]},
        {"id": 3, "assessment_type": "quiz", "sections": ["2.1"]},
    ]
    result = test_generator.filter_questions(
        questions, assessment_type="quiz", sections="1.3 - 1.7"
    )
    assert [q["id"] for q in result] == [1]


def test_generate_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors:\n"
        "      - 3\n"
        "      - 5\n"
        "    solution: Because 2+2 equals 4.\n"
    )

    fake_yaml = types.SimpleNamespace(safe_load=lambda s: {
        "questions": [
            {
                "id": 1,
                "question": "What is 2 + 2?",
                "answer": "4",
                "distractors": ["3", "5"],
                "solution": "Because 2+2 equals 4.",
            }
        ]
    })
    sys.modules["yaml"] = cast(types.ModuleType, fake_yaml)

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_path = Path(cmd[-1])
        tex_content = tex_path.read_text()
        assert "\\question" in tex_content
        assert "What is 2 + 2?" in tex_content
        assert "\\correctchoice 4" in tex_content
        assert "\\choice 3" in tex_content
        assert "\\choice 5" in tex_content
        assert "Because 2+2 equals 4." in tex_content
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()


def test_generate_test_mcq_choice_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors:\n"
        "      - 3\n"
        "      - 5\n"
        "    solution: Because 2+2 equals 4.\n"
    )

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_path = Path(cmd[-1])
        tex_content = tex_path.read_text()
        # each option is measured so TeX can pick the layout
        assert "\\measurechoice{4}" in tex_content
        assert "\\measurechoice{3}" in tex_content
        assert "\\measurechoice{5}" in tex_content
        # conditional offers both the single-column and two-column layouts
        assert "\\ifdim\\widestchoice" in tex_content
        mcq_block = tex_content.split("\\ifdim\\widestchoice")[1].split("\\fi")[0]
        assert mcq_block.count("\\begin{choices}") == 2
        assert "\\begin{multicols}{2}" in mcq_block
        assert "$MEASURE_CHOICES" not in tex_content
        assert "$CHOICES" not in tex_content
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()


def test_generate_test_nocalc_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_yaml = (
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors:\n"
        "      - 3\n"
        "    solution: Because 2+2 equals 4.\n"
        "    calculator_active: {}\n"
    )
    yaml_file = tmp_path / "q.yaml"

    tex_contents: list[str] = []

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_contents.append(Path(cmd[-1]).read_text())
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # a calculator-active question suppresses the banner everywhere
    yaml_file.write_text(question_yaml.format("true"))
    test_generator.generate_test(str(yaml_file), str(tmp_path / "calc.pdf"))
    assert "\\runningheader{}" in tex_contents[0]
    assert "\\nocalc" not in tex_contents[0].split("\\begin{document}")[1]
    assert "$NOCALC" not in tex_contents[0]

    # no calculator questions keeps the banner in header and first page
    yaml_file.write_text(question_yaml.format("false"))
    test_generator.generate_test(str(yaml_file), str(tmp_path / "nocalc.pdf"))
    assert "\\runningheader{\\nocalc}" in tex_contents[1]
    assert "\\nocalc" in tex_contents[1].split("\\begin{document}")[1]
    assert "$NOCALC" not in tex_contents[1]


def test_generate_test_frq(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Evaluate the limit.\n"
        "    solution: The limit is 2.\n"
        "    question_type: FRQ\n"
        "    work_space: 2in\n"
        "  - id: 2\n"
        "    question: Show all your steps.\n"
        "    solution: Steps shown.\n"
        "    question_type: FRQ\n"
        "  - id: 3\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because 2+2 equals 4.\n"
    )

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_path = Path(cmd[-1])
        tex_content = tex_path.read_text()
        assert "Evaluate the limit." in tex_content
        assert "\\begin{solution}[2in]" in tex_content
        assert "Show all your steps." in tex_content
        assert "\\begin{solution}[1in]" in tex_content
        # FRQ blocks must not contain a choices environment
        frq_block = tex_content.split("Evaluate the limit.")[1].split("\\fitquestion")[0]
        assert "\\begin{choices}" not in frq_block
        # question without question_type still renders as MCQ
        assert "\\correctchoice 4" in tex_content
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()


def test_generate_test_work_space_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Evaluate the limit.\n"
        "    solution: The limit is 2.\n"
        "    question_type: FRQ\n"
        "  - id: 2\n"
        "    question: Show all your steps.\n"
        "    solution: Steps shown.\n"
        "    question_type: FRQ\n"
        "    work_space: 3in\n"
        "  - id: 3\n"
        "    question: Consider the function f.\n"
        "    question_type: FRQ\n"
        "    work_space: 4in\n"
        "    parts:\n"
        "      - question: Find the vertical asymptotes.\n"
        "        solution: One at x = -3.\n"
        "      - question: Find the horizontal asymptotes.\n"
        "        solution: At y = -1 and y = 1.\n"
        "        work_space: 5in\n"
    )

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_path = Path(cmd[-1])
        tex_content = tex_path.read_text()
        # config-level default applies when the question doesn't set one
        assert "\\begin{solution}[2in]" in tex_content
        # question-level override beats the config default
        assert "\\begin{solution}[3in]" in tex_content
        # parts inherit the question-level value unless they override it
        assert "\\begin{solution}[4in]" in tex_content
        assert "\\begin{solution}[5in]" in tex_content
        assert "\\begin{solution}[1in]" not in tex_content
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf), work_space="2in")
    assert Path(result).exists()


def test_generate_test_frq_multipart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Consider the function f.\n"
        "    question_type: FRQ\n"
        "    parts:\n"
        "      - question: Find the vertical asymptotes.\n"
        "        solution: One at x = -3.\n"
        "        work_space: 4in\n"
        "      - question: Find the horizontal asymptotes.\n"
        "        solution: At y = -1 and y = 1.\n"
    )

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_path = Path(cmd[-1])
        tex_content = tex_path.read_text()
        assert "Consider the function f." in tex_content
        assert "\\begin{parts}" in tex_content
        assert "\\end{parts}" in tex_content
        assert tex_content.count("\\part") == 2
        assert "Find the vertical asymptotes." in tex_content
        assert "\\begin{solution}[4in]" in tex_content
        assert "Find the horizontal asymptotes." in tex_content
        assert "\\begin{solution}[1in]" in tex_content
        # the stem itself must not get its own solution box
        stem_block = tex_content.split("Consider the function f.")[1].split("\\part")[0]
        assert "\\begin{solution}" not in stem_block
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()


def test_generate_test_grading_rubric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Evaluate the limit.\n"
        "    solution: The limit is 2.\n"
        "    question_type: FRQ\n"
        "    grading:\n"
        "      - points: 1\n"
        "        criterion: Correct limit statement\n"
        "      - points: 2\n"
        "        criterion: Answer\n"
        "  - id: 2\n"
        "    question: Consider the function f.\n"
        "    question_type: FRQ\n"
        "    parts:\n"
        "      - question: Find the vertical asymptotes.\n"
        "        solution: One at x = -3.\n"
        "        grading:\n"
        "          - points: 1\n"
        "            criterion: Asymptote\n"
        "      - question: Find the horizontal asymptotes.\n"
        "        solution: At y = -1 and y = 1.\n"
        "  - id: 3\n"
        "    question: Ungraded question.\n"
        "    solution: Ungraded solution.\n"
        "    question_type: FRQ\n"
    )

    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()

    tex = tex_contents[0]
    # summed points are appended in bold after the question text
    q1_block = tex.split("Evaluate the limit.")[1].split("\\begin{solution}")[0]
    assert "\\textbf{(3 points)}" in q1_block
    # a 1-point total uses the singular label
    part_block = tex.split("Find the vertical asymptotes.")[1].split("\\part")[0]
    assert "\\textbf{(1 point)}" in part_block
    # the rubric rows wrap the solution in a gradedsolution environment
    assert (
        "\\begin{gradedsolution}{1 & Correct limit statement \\\\\n2 & Answer}\n"
        "The limit is 2.\n"
        "\\end{gradedsolution}" in tex
    )
    assert "\\begin{gradedsolution}{1 & Asymptote}" in part_block
    # questions/parts without grading are untouched
    ungraded = tex.split("Ungraded question.")[1].split("\\end{questions}")[0]
    assert "gradedsolution" not in ungraded
    assert "\\textbf{(" not in ungraded
    horizontal = tex.split("Find the horizontal asymptotes.")[1].split("}")[0]
    assert "gradedsolution" not in horizontal


def test_generate_test_grading_rejects_bad_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Evaluate the limit.\n"
        "    solution: The limit is 2.\n"
        "    question_type: FRQ\n"
        "    grading:\n"
        "      - points: 1\n"
    )

    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(RuntimeError, match="criterion"):
        test_generator.generate_test(str(yaml_file), str(tmp_path / "out.pdf"))


def test_generate_test_figure_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Figured MCQ stem.\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because.\n"
        "    figure: 27.tex\n"
        "    figure_width: 2.5in\n"
        "  - id: 2\n"
        "    question: Figured FRQ stem.\n"
        "    solution: Solved.\n"
        "    question_type: FRQ\n"
        "    figure: graph.png\n"
        "  - id: 3\n"
        "    question: Figured multipart stem.\n"
        "    question_type: FRQ\n"
        "    figure: stem.tex\n"
        "    parts:\n"
        "      - question: Figured part.\n"
        "        solution: Part solved.\n"
        "        figure: part.png\n"
        "        figure_width: 2in\n"
        "      - question: Plain part.\n"
        "        solution: Also solved.\n"
        "  - id: 4\n"
        "    question: Plain MCQ stem.\n"
        "    answer: 6\n"
        "    distractors: [5, 7]\n"
        "    solution: Because.\n"
    )

    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()

    tex = tex_contents[0]
    # .tex figures are \input, images \includegraphics; figure_width rescales
    assert "\\begin{figright}{\\resizebox{2.5in}{!}{\\input{figures/27.tex}}}" in tex
    assert "\\begin{figright}{\\includegraphics{figures/graph.png}}" in tex
    assert "\\begin{figright}{\\input{figures/stem.tex}}" in tex
    assert "\\begin{figright}{\\includegraphics[width=2in]{figures/part.png}}" in tex
    body = tex.split("\\begin{questions}")[1]
    assert body.count("\\begin{figright}") == 4
    assert body.count("\\end{figright}") == 4
    assert "$FIG_" not in tex
    # MCQ: the figure column spans the choices but not the solution box
    mcq_block = tex.split("Figured MCQ stem.")[1].split("\\fitquestion")[0]
    assert mcq_block.index("\\begin{choices}") < mcq_block.index("\\end{figright}")
    assert mcq_block.index("\\end{figright}") < mcq_block.index("\\begin{solution}")
    # multipart: the stem's figure column closes before the parts begin
    stem_block = tex.split("Figured multipart stem.")[1].split("\\part")[0]
    assert stem_block.index("\\end{figright}") < stem_block.index("\\begin{parts}")
    # a question without a figure gets no figright environment
    plain_block = tex.split("Plain MCQ stem.")[1].split("\\end{questions}")[0]
    assert "figright" not in plain_block


def test_generate_test_figure_placement_above_below(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Above MCQ stem.\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because.\n"
        "    figure: 27.tex\n"
        "    figure_placement: above\n"
        "  - id: 2\n"
        "    question: Below MCQ stem.\n"
        "    answer: 6\n"
        "    distractors: [5, 7]\n"
        "    solution: Because.\n"
        "    figure: graph.png\n"
        "    figure_width: 2in\n"
        "    figure_placement: below\n"
        "  - id: 3\n"
        "    question: Below FRQ stem.\n"
        "    solution: Solved.\n"
        "    question_type: FRQ\n"
        "    figure: 28.tex\n"
        "    figure_placement: below\n"
    )

    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(str(yaml_file), str(out_pdf))
    assert Path(result).exists()

    tex = tex_contents[0]
    assert "figright" not in tex.split("\\begin{questions}")[1]
    assert "$FIG_" not in tex
    # above: the centered figure precedes \question so the number stays
    # with the stem
    above_block = tex.split("Above MCQ stem.")[0].rsplit("\\fitquestion", 1)[1]
    assert "{\\centering \\input{figures/27.tex}\\par}" in above_block
    assert above_block.index("\\centering") < above_block.index("\\question")
    # below (MCQ): the centered figure sits between the stem and the choices
    below_block = tex.split("Below MCQ stem.")[1].split("\\fitquestion")[0]
    fig = "{\\centering \\includegraphics[width=2in]{figures/graph.png}\\par}"
    assert below_block.index(fig) < below_block.index("\\begin{choices}")
    # below (FRQ): the centered figure sits between the stem and the solution
    frq_block = tex.split("Below FRQ stem.")[1].split("\\end{questions}")[0]
    fig = "{\\centering \\input{figures/28.tex}\\par}"
    assert frq_block.index(fig) < frq_block.index("\\begin{solution}")


def test_generate_test_invalid_figure_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Bad placement.\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    figure: 27.tex\n"
        "    figure_placement: sideways\n"
    )

    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(RuntimeError, match="figure_placement"):
        test_generator.generate_test(str(yaml_file), str(tmp_path / "out.pdf"))


def test_generate_test_custom_figures_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because 2+2 equals 4.\n"
    )

    figures_dir = tmp_path / "custom_figures"
    figures_dir.mkdir()
    (figures_dir / "fig1.png").write_bytes(b"\x89PNG")

    fake_yaml = types.SimpleNamespace(safe_load=lambda s: {
        "questions": [
            {
                "id": 1,
                "question": "What is 2 + 2?",
                "answer": "4",
                "distractors": ["3", "5"],
                "solution": "Because 2+2 equals 4.",
            }
        ]
    })
    sys.modules["yaml"] = cast(types.ModuleType, fake_yaml)

    copied_figures: list[Path] = []

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        outdir = cmd[cmd.index("-output-directory") + 1]
        figs = Path(outdir) / "figures"
        if figs.is_dir():
            copied_figures.extend(figs.iterdir())
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(
        str(yaml_file), str(out_pdf), figures_dir=str(figures_dir)
    )
    assert Path(result).exists()
    assert any(p.name == "fig1.png" for p in copied_figures)


QUESTIONS_YAML = (
    "questions:\n"
    "  - id: 1\n"
    "    question: What is 2 + 2?\n"
    "    answer: 4\n"
    "    distractors: [3, 5]\n"
    "    solution: Because 2+2 equals 4.\n"
    "    sections: ['1.3']\n"
    "    assessment_type: quiz\n"
    "  - id: 2\n"
    "    question: What is 3 + 3?\n"
    "    answer: 6\n"
    "    distractors: [5, 7]\n"
    "    solution: Because 3+3 equals 6.\n"
    "    sections: ['2.1']\n"
    "    assessment_type: test\n"
)


def _write_cli_inputs(tmp_path: Path, config_extra: str = "") -> tuple[Path, Path, Path]:
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "title: 'Quiz 1.3'\n"
        "author: Levi\n"
        "class_name: AP Calculus AB\n"
        "class_id: APCalc\n"
        "duration: 10 min\n"
        + config_extra
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    return config_file, questions_file, figures_dir


def _manifests(out_dir: Path, prefix: str) -> list[Path]:
    """Manifests named <prefix>_<8-hex form ID>.manifest.yaml in out_dir."""
    pattern = re.compile(rf"{re.escape(prefix)}_[0-9a-f]{{8}}\.manifest\.yaml")
    return sorted(
        p for p in Path(out_dir).iterdir() if pattern.fullmatch(p.name)
    )


def _the_manifest(out_dir: Path, prefix: str) -> Path:
    """The single manifest matching the pattern."""
    matches = _manifests(out_dir, prefix)
    assert len(matches) == 1, f"expected one manifest match, got {matches}"
    return matches[0]


def _fake_pdflatex(monkeypatch: pytest.MonkeyPatch, tex_contents: list[str]) -> None:
    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        tex_contents.append(Path(cmd[-1]).read_text())
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _cli_args(
    config_file: Path, questions_file: Path, figures_dir: Path, out_dir: Path
) -> list[str]:
    return [
        str(config_file),
        "--questions", str(questions_file),
        "--out-dir", str(out_dir),
        "--figures-dir", str(figures_dir),
    ]


def test_main_generates_both_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    # PDFs have stable names; only the manifest carries the form ID
    assert (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_solutions.pdf").exists()
    _the_manifest(out_dir, "APCalc_Quiz_1.3")
    assert len(tex_contents) == 2
    student_tex, solution_tex = tex_contents
    assert "\\printanswers" not in student_tex
    assert "\\printanswers" in solution_tex
    assert "Quiz 1.3" in student_tex
    assert "AP Calculus AB" in student_tex
    assert "10 min" in student_tex


def test_main_form_id_format_and_no_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--student-only"])

    tex = tex_contents[0]
    # footer shows the grouped form ID and no date
    match = re.search(r"\\def \\formid \{([0-9a-f]{4})-([0-9a-f]{4})\}", tex)
    assert match, "grouped form ID not found in tex"
    assert "\\today" not in tex
    # the manifest filename carries the same ID ungrouped
    manifest = _the_manifest(out_dir, "APCalc_Quiz_1.3")
    assert match.group(1) + match.group(2) in manifest.name


def test_main_rejects_leftover_form_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, "form_id: A\n"
    )
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    err = capsys.readouterr().err
    assert "form_id" in err
    assert "removed" in err


def test_main_student_and_solution_choices_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: both copies must share one shuffled choice order."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "class_id: APCalc\n"
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors: [3, 5, 6, 7, 8, 9, 10]\n"
        "    solution: Because.\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    main([str(config_file), "--out-dir", str(tmp_path / "out"),
          "--figures-dir", str(figures_dir)])

    assert len(tex_contents) == 2
    student_choices = re.findall(
        r"\\begin\{choices\}(.*?)\\end\{choices\}", tex_contents[0], re.S
    )
    solution_choices = re.findall(
        r"\\begin\{choices\}(.*?)\\end\{choices\}", tex_contents[1], re.S
    )
    assert student_choices and student_choices == solution_choices


def test_main_student_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--student-only"])

    assert (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert not (out_dir / "APCalc_Quiz_1.3_solutions.pdf").exists()


def test_main_solution_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--solution-only"])

    assert not (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_solutions.pdf").exists()


def test_main_filters_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path,
        "assessment_type: quiz\n"
        "sections: 1.3 - 1.7\n",
    )
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--student-only"])

    assert "What is 2 + 2?" in tex_contents[0]
    assert "What is 3 + 3?" not in tex_contents[0]


def test_main_filters_calculator_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "class_id: APCalc\n"
        "calculator_active: true\n"
        "questions:\n"
        "  - id: 1\n"
        "    question: Calculator allowed here.\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because.\n"
        "    calculator_active: true\n"
        "  - id: 2\n"
        "    question: No calculator here.\n"
        "    answer: 6\n"
        "    distractors: [5, 7]\n"
        "    solution: Because.\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main([str(config_file), "--out-dir", str(out_dir),
          "--figures-dir", str(figures_dir), "--student-only"])

    assert "Calculator allowed here." in tex_contents[0]
    assert "No calculator here." not in tex_contents[0]


def test_main_student_and_solution_only_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(
            _cli_args(config_file, questions_file, figures_dir, tmp_path / "out")
            + ["--student-only", "--solution-only"]
        )
    assert "not allowed with" in capsys.readouterr().err


def test_main_name_defaults_to_config_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "Quiz_1.3.yaml"
    config_file.write_text("class_id: APCalc\n")  # no name
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    assert (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_solutions.pdf").exists()


CONFIG_QUESTIONS_YAML = (
    "questions:\n"
    "  - id: 10\n"
    "    question: What is 5 + 5?\n"
    "    answer: 10\n"
    "    distractors: [9, 11]\n"
    "    solution: Because 5+5 equals 10.\n"
)


def test_generate_test_questions_list_without_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(
        None,
        str(out_pdf),
        questions=[
            {
                "id": 1,
                "question": "What is 2 + 2?",
                "answer": "4",
                "distractors": ["3", "5"],
                "solution": "Because 2+2 equals 4.",
            }
        ],
    )
    assert Path(result).exists()
    assert "What is 2 + 2?" in tex_contents[0]


def test_main_config_only_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "class_id: APCalc\n"
        + CONFIG_QUESTIONS_YAML
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main([str(config_file), "--out-dir", str(out_dir), "--figures-dir", str(figures_dir)])

    assert (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert "What is 5 + 5?" in tex_contents[0]


def test_main_combines_config_and_file_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, CONFIG_QUESTIONS_YAML
    )
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    assert "What is 2 + 2?" in tex_contents[0]
    assert "What is 3 + 3?" in tex_contents[0]
    assert "What is 5 + 5?" in tex_contents[0]


def test_main_config_questions_must_be_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\nclass_id: APCalc\nquestions: nope\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main([str(config_file), "--out-dir", str(tmp_path / "out"), "--figures-dir", str(figures_dir)])
    assert "'questions' must be a list" in capsys.readouterr().err


def test_main_class_id_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "config.yaml"
    config_file.write_text("name: Quiz_1.3\n")  # no class_id
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    # without class_id, output names start with the config name only
    assert (out_dir / "Quiz_1.3.pdf").exists()
    assert (out_dir / "Quiz_1.3_solutions.pdf").exists()
    _the_manifest(out_dir, "Quiz_1.3")


def _write_manifest_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """CLI inputs with a figure-bearing question and an unreferenced figure."""
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(
        "questions:\n"
        "  - id: q-mcq\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors: [3, 5, 6]\n"
        "    solution: Because.\n"
        "    figure: used.png\n"
        "    sections: ['1.1']\n"
        "    dok: 2\n"
        "  - id: q-frq\n"
        "    question: Show your work.\n"
        "    solution: Shown.\n"
        "    question_type: FRQ\n"
        "    parts:\n"
        "      - question: Part one.\n"
        "        solution: Done.\n"
        "        figure: part.png\n"
        "        sections: ['1.2', '1.3']\n"
        "        dok: 3\n"
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text("name: Quiz_M\nclass_id: APCalc\n")
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    (figures_dir / "used.png").write_bytes(b"\x89PNG used")
    (figures_dir / "part.png").write_bytes(b"\x89PNG part")
    (figures_dir / "unreferenced.png").write_bytes(b"\x89PNG unused")
    return config_file, questions_file, figures_dir


def _md5_of(path: Path) -> str:
    import hashlib

    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def test_manifest_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    manifest = real_yaml.safe_load(manifest_file.read_text())

    assert manifest["manifest_version"] == 2
    assert re.fullmatch(r"[0-9a-f]{8}", manifest["form_id"])
    assert manifest["form_id"] in manifest_file.name
    assert manifest["generated"]
    assert manifest["generator_version"] == test_generator.__version__
    # input locations are not recorded; only content hashes matter on replay
    assert "config" not in manifest
    assert "questions_file" not in manifest
    assert "figures_dir" not in manifest

    # every recorded file hash matches a recomputation; only referenced
    # figures are hashed, and entries carry basenames only
    inputs = {
        p.name: p
        for p in [
            config_file,
            questions_file,
            figures_dir / "used.png",
            figures_dir / "part.png",
        ]
    }
    hashed = {entry["name"] for entry in manifest["files"]}
    assert hashed == set(inputs)
    for entry in manifest["files"]:
        assert "path" not in entry
        assert entry["md5"] == _md5_of(inputs[entry["name"]])

    # questions in presentation order; choice_order only on the MCQ
    assert [q["id"] for q in manifest["questions"]] == ["q-mcq", "q-frq"]
    mcq, frq = manifest["questions"]
    assert sorted(mcq["choice_order"]) == [0, 1, 2, 3]
    assert "choice_order" not in frq

    # report data is embedded: sections (union across parts) and
    # effective DOK per question; no section range in this config
    assert mcq["sections"] == ["1.1"]
    assert mcq["dok"] == 2
    assert frq["sections"] == ["1.2", "1.3"]
    assert frq["dok"] == 3
    assert "sections" not in manifest

    # the printed correct letter position matches choice_order.index(0)
    choices_match = re.search(
        r"\\begin\{choices\}(.*?)\\end\{choices\}", tex_contents[0], re.S
    )
    assert choices_match is not None
    choices_block = choices_match.group(1)
    lines = [ln.strip() for ln in choices_block.strip().splitlines()]
    correct_pos = next(
        i for i, ln in enumerate(lines) if ln.startswith("\\correctchoice")
    )
    assert correct_pos == mcq["choice_order"].index(0)


def test_main_missing_question_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_M\n"
        "class_id: APCalc\n"
        "questions:\n"
        "  - question: No id here.\n"
        "    answer: 4\n"
        "    distractors: [3]\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main([str(config_file), "--out-dir", str(tmp_path / "out"),
              "--figures-dir", str(figures_dir)])
    assert "missing an 'id'" in capsys.readouterr().err


def test_main_duplicate_question_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_M\n"
        "class_id: APCalc\n"
        "questions:\n"
        "  - id: dup\n"
        "    question: First.\n"
        "    answer: 4\n"
        "    distractors: [3]\n"
        "  - id: dup\n"
        "    question: Second.\n"
        "    answer: 6\n"
        "    distractors: [5]\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main([str(config_file), "--out-dir", str(tmp_path / "out"),
              "--figures-dir", str(figures_dir)])
    assert "Duplicate question ID(s): dup" in capsys.readouterr().err


def test_from_manifest_reproduces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    first_tex: list[str] = []
    _fake_pdflatex(monkeypatch, first_tex)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    student_pdf = out_dir / "APCalc_Quiz_M.pdf"
    solution_pdf = out_dir / "APCalc_Quiz_M_solutions.pdf"
    student_pdf.unlink()
    solution_pdf.unlink()

    second_tex: list[str] = []
    _fake_pdflatex(monkeypatch, second_tex)
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--from-manifest", str(manifest_file)])

    # identical tex (same questions, order, choices, form ID) and filenames
    assert second_tex == first_tex
    assert student_pdf.exists()
    assert solution_pdf.exists()
    # no second manifest is written
    assert _manifests(out_dir, "APCalc_Quiz_M") == [manifest_file]


def test_from_manifest_relocated_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay works from moved inputs as long as the contents match."""
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    first_tex: list[str] = []
    _fake_pdflatex(monkeypatch, first_tex)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")

    # move every input so the paths recorded in the manifest no longer exist
    moved = tmp_path / "moved"
    moved.mkdir()
    config_file = Path(shutil.move(config_file, moved / config_file.name))
    questions_file = Path(shutil.move(questions_file, moved / questions_file.name))
    figures_dir = Path(shutil.move(figures_dir, moved / "figures"))

    second_tex: list[str] = []
    _fake_pdflatex(monkeypatch, second_tex)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": pytest.fail("unexpected verification prompt"),
    )
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--from-manifest", str(manifest_file)])

    assert second_tex == first_tex


def test_from_manifest_md5_mismatch_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    (out_dir / "APCalc_Quiz_M.pdf").unlink()
    (out_dir / "APCalc_Quiz_M_solutions.pdf").unlink()

    questions_file.write_text(questions_file.read_text() + "# mutated\n")

    replay_args = (_cli_args(config_file, questions_file, figures_dir, out_dir)
                   + ["--from-manifest", str(manifest_file)])

    # answering "n" aborts with nothing generated
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit):
        main(replay_args)
    err = capsys.readouterr().err
    assert "MD5 not in manifest" in err
    assert "no loaded file matches manifest entry" in err
    assert not (out_dir / "APCalc_Quiz_M.pdf").exists()

    # answering "y" proceeds
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    main(replay_args)
    assert (out_dir / "APCalc_Quiz_M.pdf").exists()
    assert (out_dir / "APCalc_Quiz_M_solutions.pdf").exists()


def test_main_multiple_question_banks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    extra_bank = tmp_path / "more_questions.yaml"
    extra_bank.write_text(
        "questions:\n"
        "  - id: 99\n"
        "    question: What is 5 + 5?\n"
        "    answer: 10\n"
        "    distractors: [9, 11]\n"
        "    solution: Because.\n"
    )
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--questions", str(extra_bank)])

    student_tex = tex_contents[0]
    assert "What is 2 + 2?" in student_tex
    assert "What is 5 + 5?" in student_tex
    manifest = real_yaml.safe_load(
        _the_manifest(out_dir, "APCalc_Quiz_1.3").read_text()
    )
    recorded = {entry["name"] for entry in manifest["files"]}
    assert {questions_file.name, extra_bank.name} <= recorded


def test_main_duplicate_ids_across_banks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out")
             + ["--questions", str(questions_file)])
    assert "Duplicate question ID(s)" in capsys.readouterr().err


def test_main_multiple_figures_dirs_first_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_F\n"
        "class_id: APCalc\n"
        "questions:\n"
        "  - id: f1\n"
        "    question: 'See figure.'\n"
        "    answer: 1\n"
        "    distractors: [2]\n"
        "    figure: shared.png\n"
        "  - id: f2\n"
        "    question: 'See other figure.'\n"
        "    answer: 3\n"
        "    distractors: [4]\n"
        "    figure: only_second.png\n"
    )
    first_dir = tmp_path / "figs_a"
    second_dir = tmp_path / "figs_b"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "shared.png").write_bytes(b"first version")
    (second_dir / "shared.png").write_bytes(b"second version")
    (second_dir / "only_second.png").write_bytes(b"only in second")

    copied: dict[str, bytes] = {}

    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        outdir = Path(cmd[cmd.index("-output-directory") + 1])
        for f in (outdir / "figures").iterdir():
            copied[f.name] = f.read_bytes()
        (outdir / "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_dir = tmp_path / "out"
    main([str(config_file), "--out-dir", str(out_dir),
          "--figures-dir", str(first_dir), "--figures-dir", str(second_dir)])

    assert copied["shared.png"] == b"first version"
    assert copied["only_second.png"] == b"only in second"

    # the manifest records the winning copy of the shared figure
    manifest = real_yaml.safe_load(
        _the_manifest(out_dir, "APCalc_Quiz_F").read_text()
    )
    by_name = {entry["name"]: entry["md5"] for entry in manifest["files"]}
    assert by_name["shared.png"] == _md5_of(first_dir / "shared.png")
    assert by_name["only_second.png"] == _md5_of(second_dir / "only_second.png")


def test_from_manifest_with_multiple_banks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    extra_bank = tmp_path / "more_questions.yaml"
    extra_bank.write_text(
        "questions:\n"
        "  - id: 99\n"
        "    question: What is 5 + 5?\n"
        "    answer: 10\n"
        "    distractors: [9, 11]\n"
        "    solution: Because.\n"
    )
    first_tex: list[str] = []
    _fake_pdflatex(monkeypatch, first_tex)

    out_dir = tmp_path / "out"
    bank_args = ["--questions", str(extra_bank)]
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + bank_args)
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_1.3")

    second_tex: list[str] = []
    _fake_pdflatex(monkeypatch, second_tex)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": pytest.fail("unexpected verification prompt"),
    )
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + bank_args + ["--from-manifest", str(manifest_file)])
    assert second_tex == first_tex


def test_from_manifest_accepts_version_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Replay still works for manifests written before version 2."""
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    first_tex: list[str] = []
    _fake_pdflatex(monkeypatch, first_tex)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")

    # downgrade to the version-1 schema: no embedded report data
    manifest = real_yaml.safe_load(manifest_file.read_text())
    manifest["manifest_version"] = 1
    for entry in manifest["questions"]:
        entry.pop("sections", None)
        entry.pop("dok", None)
    manifest_file.write_text(real_yaml.safe_dump(manifest, sort_keys=False))

    second_tex: list[str] = []
    _fake_pdflatex(monkeypatch, second_tex)
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--from-manifest", str(manifest_file)])
    assert second_tex == first_tex


def test_new_version_from_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    first_manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    first = real_yaml.safe_load(first_manifest_file.read_text())
    (out_dir / "APCalc_Quiz_M.pdf").unlink()
    (out_dir / "APCalc_Quiz_M_solutions.pdf").unlink()

    # deterministic re-scramble: reversal instead of a random shuffle
    monkeypatch.setattr(random, "shuffle", lambda seq: seq.reverse())
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--from-manifest", str(first_manifest_file), "--new-version"])

    manifests = _manifests(out_dir, "APCalc_Quiz_M")
    assert len(manifests) == 2
    assert first_manifest_file in manifests
    second_file = next(m for m in manifests if m != first_manifest_file)
    second = real_yaml.safe_load(second_file.read_text())

    # same questions, new identity, re-scrambled order and fresh choices
    assert second["form_id"] != first["form_id"]
    first_ids = [q["id"] for q in first["questions"]]
    second_ids = [q["id"] for q in second["questions"]]
    assert second_ids == list(reversed(first_ids))
    (mcq,) = [q for q in second["questions"] if q["id"] == "q-mcq"]
    assert mcq["choice_order"] == [3, 2, 1, 0]  # reversed by the fake shuffle
    # the recorded inputs are identical (entry order follows question order)
    assert {(e["name"], e["md5"]) for e in second["files"]} == {
        (e["name"], e["md5"]) for e in first["files"]
    }
    # and the PDFs were regenerated
    assert (out_dir / "APCalc_Quiz_M.pdf").exists()
    assert (out_dir / "APCalc_Quiz_M_solutions.pdf").exists()


def test_cli_new_version_requires_from_manifest(
    capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["config.yaml", "--new-version"])
    assert "--new-version requires --from-manifest" in capsys.readouterr().err


def test_report_from_manifest_standalone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report replays from the manifest alone; nothing is generated."""
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    config_file.write_text(config_file.read_text() + "sections: '1.1 - 1.4'\n")
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    for pdf in out_dir.glob("*.pdf"):
        pdf.unlink()
    # delete every input: the report must not need them
    config_file.unlink()
    questions_file.unlink()
    shutil.rmtree(figures_dir)
    capsys.readouterr()

    main(["--report-from-manifest", str(manifest_file)])

    out = capsys.readouterr().out
    assert "Test report: 2 question(s)" in out
    assert "  1.1 █ 1" in out
    assert "  1.4 0" in out  # config's section range came from the manifest
    assert "Average DOK: 2.50" in out
    assert not list(out_dir.glob("*.pdf"))
    assert _manifests(out_dir, "APCalc_Quiz_M") == [manifest_file]


def test_report_from_manifest_rejects_version_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_manifest_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_M")
    manifest = real_yaml.safe_load(manifest_file.read_text())
    manifest["manifest_version"] = 1
    manifest_file.write_text(real_yaml.safe_dump(manifest, sort_keys=False))
    capsys.readouterr()

    with pytest.raises(SystemExit):
        main(["--report-from-manifest", str(manifest_file)])
    err = capsys.readouterr().err
    assert "predates" in err
    assert "--from-manifest" in err


def test_cli_report_from_manifest_is_standalone(
    capsys: pytest.CaptureFixture[str]
) -> None:
    for extra in (["config.yaml"], ["--from-manifest", "m.yaml"], ["--watch"]):
        with pytest.raises(SystemExit):
            main(["--report-from-manifest", "m.yaml"] + extra)
        assert "standalone" in capsys.readouterr().err


def test_cli_from_manifest_requires_one_config(
    capsys: pytest.CaptureFixture[str]
) -> None:
    for configs in ([], ["a.yaml", "b.yaml"]):
        with pytest.raises(SystemExit):
            main(configs + ["--from-manifest", "m.yaml"])
        assert "exactly one config" in capsys.readouterr().err


def test_cli_requires_config_or_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--out-dir", "out"])
    assert "--from-manifest" in capsys.readouterr().err


def test_cli_from_manifest_rejects_watch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["config.yaml", "--from-manifest", "m.yaml", "--watch"])
    assert "--watch" in capsys.readouterr().err


def test_watch_draft_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    tex_contents: list[str] = []
    _fake_pdflatex(monkeypatch, tex_contents)

    def raise_interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", raise_interrupt)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--watch"])

    # standard filenames, draft footer, and no manifest
    assert (out_dir / "APCalc_Quiz_1.3.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_solutions.pdf").exists()
    assert "\\def \\formid {draft}" in tex_contents[0]
    assert not list(out_dir.glob("*.manifest.yaml"))


def _sel_q(
    qid: str,
    sections: list[str] | None = None,
    related_to: list[str] | None = None,
) -> Question:
    q: Question = {"id": qid}
    if sections is not None:
        q["sections"] = sections
    if related_to is not None:
        q["related_to"] = related_to
    return q


def test_select_questions_count_and_order() -> None:
    pool = [_sel_q(str(i)) for i in range(6)]
    random.seed(0)
    selected = select_questions(pool, 4)
    assert len(selected) == 4
    ids = [q["id"] for q in selected]
    assert len(set(ids)) == 4
    # bank order is preserved
    assert ids == [q["id"] for q in pool if q["id"] in set(ids)]


def test_select_questions_randomness() -> None:
    pool = [_sel_q(str(i)) for i in range(6)]
    selections: set[frozenset[str]] = set()
    for seed in range(10):
        random.seed(seed)
        selections.add(frozenset(q["id"] for q in select_questions(pool, 3)))
    assert len(selections) > 1


def test_select_questions_maximizes_section_coverage() -> None:
    pool = [
        _sel_q("a1", ["1.1"]),
        _sel_q("a2", ["1.1"]),
        _sel_q("a3", ["1.1"]),
        _sel_q("b", ["1.2"]),
        _sel_q("c", ["1.3"]),
    ]
    for seed in range(10):
        random.seed(seed)
        selected = select_questions(pool, 3)
        covered = {s for q in selected for s in q["sections"]}
        assert covered == {"1.1", "1.2", "1.3"}


def test_select_questions_avoids_related_pairs() -> None:
    # the edge is declared only on "a"; avoidance must be symmetric
    pool = [
        _sel_q("a", related_to=["b"]),
        _sel_q("b"),
        _sel_q("c"),
        _sel_q("d"),
    ]
    for seed in range(10):
        random.seed(seed)
        ids = {q["id"] for q in select_questions(pool, 3)}
        assert not {"a", "b"} <= ids


def test_select_questions_relaxes_related_when_necessary() -> None:
    pool = [_sel_q("a", related_to=["b"]), _sel_q("b")]
    random.seed(0)
    assert {q["id"] for q in select_questions(pool, 2)} == {"a", "b"}


def test_select_questions_ignores_dangling_related_ids() -> None:
    pool = [_sel_q("a", related_to=["missing"]), _sel_q("b")]
    random.seed(0)
    assert len(select_questions(pool, 2)) == 2


def test_select_questions_count_exceeds_pool() -> None:
    pool = [_sel_q("a"), _sel_q("b")]
    with pytest.raises(RuntimeError, match=r"3.*2"):
        select_questions(pool, 3)


def _dok_q(qid: str, dok: int, related_to: list[str] | None = None) -> Question:
    q = _sel_q(qid, related_to=related_to)
    q["dok"] = dok
    return q


def _avg_dok(selected: list[Question]) -> float:
    doks = [int(q["dok"]) for q in selected if q.get("dok") is not None]
    return sum(doks) / len(doks)


def test_select_questions_dok_target_met_with_minimal_overshoot() -> None:
    pool = [_dok_q("a", 1), _dok_q("b", 1), _dok_q("c", 3), _dok_q("d", 4)]
    for seed in range(10):
        random.seed(seed)
        selected = select_questions(pool, 2, dok_target=3.0)
        # only {c, d} (avg 3.5) and {b/a, d}... avg 2.5 miss; {c, d} = 3.5,
        # {a/b, d} = 2.5, {a/b, c} = 2.0 — meeting the target requires {c, d}
        assert _avg_dok(selected) >= 3.0


def test_select_questions_dok_target_prefers_smallest_overshoot() -> None:
    pool = [_dok_q("a", 3), _dok_q("b", 3), _dok_q("c", 4), _dok_q("d", 4)]
    for seed in range(10):
        random.seed(seed)
        selected = select_questions(pool, 2, dok_target=3.0)
        # avg 3.0 ({a, b}) meets the target exactly; 3.5 and 4.0 overshoot
        assert _avg_dok(selected) == 3.0


def test_select_questions_dok_target_unreachable_maximizes_average() -> None:
    pool = [_dok_q("a", 1), _dok_q("b", 1), _dok_q("c", 2), _dok_q("d", 2)]
    for seed in range(10):
        random.seed(seed)
        selected = select_questions(pool, 2, dok_target=3.0)
        # the best the pool allows is {c, d} with average 2.0
        assert _avg_dok(selected) == 2.0


def test_select_questions_dok_target_never_adds_related_pair() -> None:
    # the only DOK-4 question is related to the only other high-DOK one;
    # chasing the target must not introduce a related pair
    pool = [
        _dok_q("a", 3),
        _dok_q("b", 4, related_to=["a"]),
        _dok_q("c", 1),
        _dok_q("d", 1),
    ]
    for seed in range(10):
        random.seed(seed)
        ids = {q["id"] for q in select_questions(pool, 2, dok_target=4.0)}
        assert not {"a", "b"} <= ids


def test_select_questions_dok_target_keeps_section_coverage() -> None:
    # swapping "b" out for the high-DOK "c" would drop section 1.2
    pool = [
        _dok_q("a", 1),
        _dok_q("b", 1),
        _dok_q("c", 4),
    ]
    pool[0]["sections"] = ["1.1"]
    pool[1]["sections"] = ["1.2"]
    pool[2]["sections"] = ["1.1"]
    for seed in range(10):
        random.seed(seed)
        selected = select_questions(pool, 2, dok_target=4.0)
        covered = {s for q in selected for s in q.get("sections", [])}
        assert covered == {"1.1", "1.2"}


def test_select_questions_dok_target_all_unrated_is_noop() -> None:
    pool = [_sel_q("a"), _sel_q("b"), _sel_q("c")]
    random.seed(0)
    assert len(select_questions(pool, 2, dok_target=3.0)) == 2


def test_format_report_sections_sorted_and_counted() -> None:
    questions: list[Question] = [
        {"id": 1, "sections": ["1.2", "1.10"], "dok": 1},
        {"id": 2, "sections": ["1.10"], "dok": 2},
    ]
    report = format_report(questions)
    lines = report.splitlines()
    assert lines[0] == "Test report: 2 question(s)"
    assert "  1.2  █ 1" in lines
    assert "  1.10 ██ 2" in lines
    assert lines.index("  1.2  █ 1") < lines.index("  1.10 ██ 2")


def test_format_report_multipart_and_missing_dok() -> None:
    questions: list[Question] = [
        {
            "id": 1,
            "parts": [
                {"sections": ["2.1"], "dok": 1},
                {"sections": ["2.2"], "dok": 3},
            ],
        },
        {"id": 2, "sections": ["2.1"]},  # no DOK anywhere
    ]
    report = format_report(questions)
    assert "  2.1 ██ 2" in report  # part sections counted, union per question
    assert "  2.2 █ 1" in report
    assert "  3   █ 1" in report  # multipart rated by its hardest part
    assert "  n/a █ 1" in report
    assert "Average DOK: 3.00" in report  # n/a excluded


def test_format_report_average_two_decimals() -> None:
    questions: list[Question] = [
        {"id": i, "dok": dok} for i, dok in enumerate([1, 2, 2])
    ]
    assert "Average DOK: 1.67" in format_report(questions)


def test_format_report_no_dok_at_all() -> None:
    assert "Average DOK: n/a" in format_report([{"id": 1}])


def test_format_report_dok_target_shown() -> None:
    questions: list[Question] = [{"id": 1, "dok": 3}, {"id": 2, "dok": 4}]
    report = format_report(questions, dok_target=3)
    assert "Average DOK: 3.50 (target: 3.00)" in report
    assert "\033" not in report  # target met: no highlight even with color
    assert "\033" not in format_report(questions, dok_target=3, color=True)


def test_format_report_dok_target_missed_highlights_in_yellow() -> None:
    questions: list[Question] = [{"id": 1, "dok": 1}, {"id": 2, "dok": 2}]
    plain = format_report(questions, dok_target=3)
    assert "Average DOK: 1.50 (target: 3.00)" in plain
    assert "\033" not in plain  # color off: never emit escapes
    colored = format_report(questions, dok_target=3, color=True)
    assert "Average DOK: \033[33m1.50\033[0m (target: 3.00)" in colored


def test_format_report_dok_target_with_na_average() -> None:
    colored = format_report([{"id": 1}], dok_target=2, color=True)
    assert "Average DOK: \033[33mn/a\033[0m (target: 2.00)" in colored


@pytest.mark.parametrize("value", ["0", "5", "true", "nope"])
def test_main_dok_target_rejects_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, f"dok_target: {value}\n"
    )
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    assert "dok_target" in capsys.readouterr().err


def test_main_dok_target_in_report_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, figures_dir = _write_report_config(tmp_path)
    config_file.write_text(config_file.read_text() + "dok_target: 2\n")
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main([str(config_file), "--out-dir", str(out_dir),
          "--figures-dir", str(figures_dir), "--report"])

    out = capsys.readouterr().out
    # capsys is not a TTY, so the report is plain text even below target
    assert "Average DOK: 1.50 (target: 2.00)" in out
    assert "\033" not in out

    # the target is recorded and replays in --report-from-manifest
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_R")
    assert real_yaml.safe_load(manifest_file.read_text())["dok_target"] == 2
    main(["--report-from-manifest", str(manifest_file)])
    assert "Average DOK: 1.50 (target: 2.00)" in capsys.readouterr().out


def test_main_question_count_selects_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, "question_count: 1\n"
    )
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_1.3")
    manifest = real_yaml.safe_load(manifest_file.read_text())
    assert len(manifest["questions"]) == 1
    assert manifest["questions"][0]["id"] in (1, 2)


@pytest.mark.parametrize("value", ["0", "-1", "nope", "true", "1.5"])
def test_main_question_count_rejects_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, f"question_count: {value}\n"
    )
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    assert "positive integer" in capsys.readouterr().err


def test_main_question_count_exceeds_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, "question_count: 99\n"
    )
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    err = capsys.readouterr().err
    assert "99" in err
    assert "2 question(s)" in err


def test_main_scramble_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_lines = "".join(
        f"  - id: q{i}\n"
        f"    question: 'Question {i}?'\n"
        f"    answer: {i}\n"
        f"    distractors: [{i + 100}]\n"
        for i in range(6)
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_S\n"
        "class_id: APCalc\n"
        "scramble_questions: true\n"
        "questions:\n"
        + question_lines
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    bank_order = [f"q{i}" for i in range(6)]
    orders: list[list[str]] = []
    for seed in range(5):
        random.seed(seed)
        out_dir = tmp_path / f"out{seed}"
        main([str(config_file), "--out-dir", str(out_dir),
              "--figures-dir", str(figures_dir)])
        manifest_file = _the_manifest(out_dir, "APCalc_Quiz_S")
        manifest = real_yaml.safe_load(manifest_file.read_text())
        orders.append([q["id"] for q in manifest["questions"]])

    assert all(sorted(order) == bank_order for order in orders)
    assert any(order != bank_order for order in orders)


def test_main_scramble_questions_rejects_non_bool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, "scramble_questions: maybe\n"
    )
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    assert "must be a boolean" in capsys.readouterr().err


def _write_report_config(tmp_path: Path) -> tuple[Path, Path]:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_R\n"
        "class_id: APCalc\n"
        "questions:\n"
        "  - id: r1\n"
        "    question: 'One?'\n"
        "    answer: 1\n"
        "    distractors: [2]\n"
        "    sections: ['1.1']\n"
        "    dok: 1\n"
        "  - id: r2\n"
        "    question: 'Two?'\n"
        "    answer: 2\n"
        "    distractors: [3]\n"
        "    sections: ['1.2']\n"
        "    dok: 2\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    return config_file, figures_dir


def test_main_no_report_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, figures_dir = _write_report_config(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    main([str(config_file), "--out-dir", str(tmp_path / "out"),
          "--figures-dir", str(figures_dir)])

    out = capsys.readouterr().out
    assert "Test report:" not in out
    assert "Average DOK:" not in out


def test_main_prints_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, figures_dir = _write_report_config(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    main([str(config_file), "--out-dir", str(tmp_path / "out"),
          "--figures-dir", str(figures_dir), "--report"])

    out = capsys.readouterr().out
    assert "Test report: 2 question(s)" in out
    assert "Section coverage:" in out
    assert "DOK levels:" in out
    assert "Average DOK: 1.50" in out


def test_main_from_manifest_prints_report_same_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, "question_count: 1\n"
    )
    first_tex: list[str] = []
    _fake_pdflatex(monkeypatch, first_tex)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))
    manifest_file = _the_manifest(out_dir, "APCalc_Quiz_1.3")
    manifest = real_yaml.safe_load(manifest_file.read_text())
    capsys.readouterr()

    second_tex: list[str] = []
    _fake_pdflatex(monkeypatch, second_tex)
    main(_cli_args(config_file, questions_file, figures_dir, out_dir)
         + ["--from-manifest", str(manifest_file), "--report"])

    # replay regenerates the same single question, never re-selecting
    assert second_tex == first_tex
    assert len(manifest["questions"]) == 1
    out = capsys.readouterr().out
    assert "Test report: 1 question(s)" in out
    assert "Average DOK:" in out


def test_format_report_lists_all_sections_in_range() -> None:
    questions: list[Question] = [{"id": 1, "sections": ["1.2"], "dok": 2}]
    report = format_report(questions, sections="1.1 - 1.3")
    assert "  1.1 0" in report
    assert "  1.2 █ 1" in report
    assert "  1.3 0" in report


def test_format_report_unbounded_range_shows_observed_only() -> None:
    questions: list[Question] = [{"id": 1, "sections": ["1.2"], "dok": 2}]
    report = format_report(questions, sections="1.x")
    assert "1.2" in report
    assert "1.1" not in report


def test_format_report_always_lists_dok_1_through_4() -> None:
    report = format_report([{"id": 1, "dok": 2}])
    for line in ("  1 0", "  2 █ 1", "  3 0", "  4 0"):
        assert line in report
    assert "n/a" not in report
