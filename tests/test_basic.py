import sys
import types
from pathlib import Path
import subprocess

import pytest

import test_generator
from test_generator.__main__ import main


def test_version_present():
    assert hasattr(test_generator, "__version__")


def test_filter_questions_assessment_type():
    questions = [
        {"id": 1, "assessment_type": "quiz"},
        {"id": 2, "assessment_type": "test"},
        {"id": 3},
    ]
    result = test_generator.filter_questions(questions, assessment_type="quiz")
    assert [q["id"] for q in result] == [1]


def test_filter_questions_no_filters_keeps_all():
    questions = [{"id": 1}, {"id": 2, "assessment_type": "quiz"}]
    assert test_generator.filter_questions(questions) == questions


def test_filter_questions_sections():
    questions = [
        {"id": 1, "sections": ["1.3"]},
        {"id": 2, "sections": ["1.3", "1.8"]},  # highest (1.8) outside range
        {"id": 3, "sections": [1.5, "1.7"]},
        {"id": 4},  # no sections listed
        {"id": 5, "sections": ["unknown"]},  # unparseable section
        {"id": 6, "sections": ["1.1", "1.5"]},  # only highest must match
    ]
    result = test_generator.filter_questions(questions, sections="1.3 - 1.7")
    assert [q["id"] for q in result] == [1, 3, 6]


def test_filter_questions_sections_multipart():
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


def test_filter_questions_combined():
    questions = [
        {"id": 1, "assessment_type": "quiz", "sections": ["1.3"]},
        {"id": 2, "assessment_type": "test", "sections": ["1.3"]},
        {"id": 3, "assessment_type": "quiz", "sections": ["2.1"]},
    ]
    result = test_generator.filter_questions(
        questions, assessment_type="quiz", sections="1.3 - 1.7"
    )
    assert [q["id"] for q in result] == [1]


def test_generate_test(tmp_path, monkeypatch):
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
    sys.modules["yaml"] = fake_yaml

    def fake_run(cmd, check, stdout, stderr):
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


def test_generate_test_mcq_choice_measurement(tmp_path, monkeypatch):
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

    def fake_run(cmd, check, stdout, stderr):
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


def test_generate_test_frq(tmp_path, monkeypatch):
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

    def fake_run(cmd, check, stdout, stderr):
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


def test_generate_test_work_space_default(tmp_path, monkeypatch):
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

    def fake_run(cmd, check, stdout, stderr):
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


def test_generate_test_frq_multipart(tmp_path, monkeypatch):
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

    def fake_run(cmd, check, stdout, stderr):
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


def test_generate_test_figure_placement(tmp_path, monkeypatch):
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

    tex_contents = []
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


def test_generate_test_figure_placement_above_below(tmp_path, monkeypatch):
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

    tex_contents = []
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


def test_generate_test_invalid_figure_placement(tmp_path, monkeypatch):
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


def test_generate_test_custom_figures_dir(tmp_path, monkeypatch):
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
    sys.modules["yaml"] = fake_yaml

    copied_figures = []

    def fake_run(cmd, check, stdout, stderr):
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


def _write_cli_inputs(tmp_path, config_extra=""):
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "title: 'Quiz 1.3'\n"
        "author: Levi\n"
        "class_name: AP Calculus AB\n"
        "class_id: APCalc\n"
        "form_id: A\n"
        "duration: 10 min\n"
        + config_extra
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    return config_file, questions_file, figures_dir


def _fake_pdflatex(monkeypatch, tex_contents):
    def fake_run(cmd, check, stdout, stderr):
        tex_contents.append(Path(cmd[-1]).read_text())
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _cli_args(config_file, questions_file, figures_dir, out_dir):
    return [
        str(config_file),
        "--questions", str(questions_file),
        "--out-dir", str(out_dir),
        "--figures-dir", str(figures_dir),
    ]


def test_main_generates_both_copies(tmp_path, monkeypatch):
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    tex_contents = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    assert (out_dir / "APCalc_Quiz_1.3_FormA.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_FormA_solutions.pdf").exists()
    assert len(tex_contents) == 2
    student_tex, solution_tex = tex_contents
    assert "\\printanswers" not in student_tex
    assert "\\printanswers" in solution_tex
    assert "Quiz 1.3" in student_tex
    assert "AP Calculus AB" in student_tex
    assert "10 min" in student_tex


def test_main_student_only(tmp_path, monkeypatch):
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--student-only"])

    assert (out_dir / "APCalc_Quiz_1.3_FormA.pdf").exists()
    assert not (out_dir / "APCalc_Quiz_1.3_FormA_solutions.pdf").exists()


def test_main_solution_only(tmp_path, monkeypatch):
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--solution-only"])

    assert not (out_dir / "APCalc_Quiz_1.3_FormA.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_FormA_solutions.pdf").exists()


def test_main_filters_questions(tmp_path, monkeypatch):
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path,
        "assessment_type: quiz\n"
        "sections: 1.3 - 1.7\n",
    )
    tex_contents = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir) + ["--student-only"])

    assert "What is 2 + 2?" in tex_contents[0]
    assert "What is 3 + 3?" not in tex_contents[0]


def test_main_student_and_solution_only_conflict(tmp_path, monkeypatch, capsys):
    config_file, questions_file, figures_dir = _write_cli_inputs(tmp_path)
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(
            _cli_args(config_file, questions_file, figures_dir, tmp_path / "out")
            + ["--student-only", "--solution-only"]
        )
    assert "not allowed with" in capsys.readouterr().err


def test_main_name_defaults_to_config_basename(tmp_path, monkeypatch):
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "Quiz_1.3.yaml"
    config_file.write_text("class_id: APCalc\nform_id: A\n")  # no name
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    assert (out_dir / "APCalc_Quiz_1.3_FormA.pdf").exists()
    assert (out_dir / "APCalc_Quiz_1.3_FormA_solutions.pdf").exists()


CONFIG_QUESTIONS_YAML = (
    "questions:\n"
    "  - id: 10\n"
    "    question: What is 5 + 5?\n"
    "    answer: 10\n"
    "    distractors: [9, 11]\n"
    "    solution: Because 5+5 equals 10.\n"
)


def test_generate_test_questions_list_without_yaml(tmp_path, monkeypatch):
    tex_contents = []
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


def test_main_config_only_questions(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\n"
        "class_id: APCalc\n"
        "form_id: A\n"
        + CONFIG_QUESTIONS_YAML
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    tex_contents = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main([str(config_file), "--out-dir", str(out_dir), "--figures-dir", str(figures_dir)])

    assert (out_dir / "APCalc_Quiz_1.3_FormA.pdf").exists()
    assert "What is 5 + 5?" in tex_contents[0]


def test_main_combines_config_and_file_questions(tmp_path, monkeypatch):
    config_file, questions_file, figures_dir = _write_cli_inputs(
        tmp_path, CONFIG_QUESTIONS_YAML
    )
    tex_contents = []
    _fake_pdflatex(monkeypatch, tex_contents)

    out_dir = tmp_path / "out"
    main(_cli_args(config_file, questions_file, figures_dir, out_dir))

    assert "What is 2 + 2?" in tex_contents[0]
    assert "What is 3 + 3?" in tex_contents[0]
    assert "What is 5 + 5?" in tex_contents[0]


def test_main_config_questions_must_be_list(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "name: Quiz_1.3\nclass_id: APCalc\nform_id: A\nquestions: nope\n"
    )
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main([str(config_file), "--out-dir", str(tmp_path / "out"), "--figures-dir", str(figures_dir)])
    assert "'questions' must be a list" in capsys.readouterr().err


def test_main_missing_required_config_field(tmp_path, monkeypatch, capsys):
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(QUESTIONS_YAML)
    config_file = tmp_path / "config.yaml"
    config_file.write_text("name: Quiz_1.3\nform_id: A\n")  # no class_id
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    _fake_pdflatex(monkeypatch, [])

    with pytest.raises(SystemExit):
        main(_cli_args(config_file, questions_file, figures_dir, tmp_path / "out"))
    assert "class_id" in capsys.readouterr().err
