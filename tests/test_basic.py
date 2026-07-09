import sys
import types
from pathlib import Path
import subprocess

import test_generator


def test_version_present():
    assert hasattr(test_generator, "__version__")


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


def test_generate_test_custom_images_dir(tmp_path, monkeypatch):
    yaml_file = tmp_path / "q.yaml"
    yaml_file.write_text(
        "questions:\n"
        "  - id: 1\n"
        "    question: What is 2 + 2?\n"
        "    answer: 4\n"
        "    distractors: [3, 5]\n"
        "    solution: Because 2+2 equals 4.\n"
    )

    images_dir = tmp_path / "custom_images"
    images_dir.mkdir()
    (images_dir / "fig1.png").write_bytes(b"\x89PNG")

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

    copied_images = []

    def fake_run(cmd, check, stdout, stderr):
        outdir = cmd[cmd.index("-output-directory") + 1]
        imgs = Path(outdir) / "images"
        if imgs.is_dir():
            copied_images.extend(imgs.iterdir())
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_pdf = tmp_path / "out.pdf"
    result = test_generator.generate_test(
        str(yaml_file), str(out_pdf), images_dir=str(images_dir)
    )
    assert Path(result).exists()
    assert any(p.name == "fig1.png" for p in copied_images)
