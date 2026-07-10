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


def test_generate_test_frq(tmp_path, monkeypatch):
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: Evaluate the limit.\n"
        "    solution: The limit is 2.\n"
        "    question_type: FRQ\n"
        "    size: 2in\n"
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
        "        size: 4in\n"
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
