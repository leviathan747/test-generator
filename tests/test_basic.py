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
