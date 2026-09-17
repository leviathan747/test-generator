"""Tests for --archive ZIP export and YAML pruning."""
import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from test_generator.__main__ import main
from test_generator.archive import prune_questions_yaml

BANK_YAML = """\
# header comment
questions:
  - id: q1
    question: |
      Keep \\(x\\) with
      - a dash line inside a block scalar
    answer: 4
    distractors: [3, 5]
    figure: used.png
  # comment after q1
  - id: q2
    question: Drop me
    answer: 6
    distractors: [5, 7]
    figure: unused.png

  - id: q3
    question: What is \\frac{1}{2}?
    answer: 1
    distractors: [2, 3]
"""

CONFIG_YAML = """\
name: Quiz
title: 'Quiz'
class_id: C
questions:
  - id: inline1
    question: Inline kept
    answer: a
    distractors: [b]
  - id: inline2
    question: Inline dropped
    answer: a
    distractors: [b]
duration: 10 min
"""


def test_prune_keeps_selected_chunks_verbatim() -> None:
    pruned, kept = prune_questions_yaml(BANK_YAML, {"q1", "q3"})
    assert kept == 2
    assert pruned == BANK_YAML.replace(
        "  - id: q2\n"
        "    question: Drop me\n"
        "    answer: 6\n"
        "    distractors: [5, 7]\n"
        "    figure: unused.png\n"
        "\n",
        "",
    )


def test_prune_keeps_keys_after_the_list() -> None:
    pruned, kept = prune_questions_yaml(CONFIG_YAML, {"inline1"})
    assert kept == 1
    assert "Inline dropped" not in pruned
    assert "Inline kept" in pruned
    assert pruned.endswith("duration: 10 min\n")


def test_prune_nothing_kept_emits_empty_list() -> None:
    pruned, kept = prune_questions_yaml(CONFIG_YAML, set())
    assert kept == 0
    data = yaml.safe_load(pruned)
    assert data["questions"] == []
    assert data["duration"] == "10 min"


def test_prune_file_without_questions_is_unchanged() -> None:
    text = "name: Quiz\ntitle: Quiz\n"
    assert prune_questions_yaml(text, {"q1"}) == (text, 0)


def test_prune_rejects_flow_style_list() -> None:
    with pytest.raises(RuntimeError):
        prune_questions_yaml(
            "questions: [{id: q1, question: x, answer: a}]\n", {"q1"}
        )


def _fake_pdflatex(monkeypatch: pytest.MonkeyPatch, texs: list[str]) -> None:
    def fake_run(
        cmd: list[str], check: bool, stdout: int, stderr: int
    ) -> subprocess.CompletedProcess[bytes]:
        texs.append(Path(cmd[-1]).read_text())
        outdir = cmd[cmd.index("-output-directory") + 1]
        Path(outdir, "output.pdf").write_bytes(b"%PDF-1.4\n%EOF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    src = tmp_path / "src"
    figures = src / "figures"
    figures.mkdir(parents=True)
    (figures / "used.png").write_bytes(b"used")
    (figures / "unused.png").write_bytes(b"unused")
    # only q1 lists a section, so the sections filter selects exactly it
    bank = src / "bank.yaml"
    bank.write_text(
        BANK_YAML.replace("  - id: q1\n", "  - id: q1\n    sections: ['1.1']\n")
    )
    config = src / "quiz.yaml"
    config.write_text(
        "name: Quiz\ntitle: Quiz\nclass_id: C\nsections: '1.1'\n"
        "question_count: 1\n"
    )
    return config, bank, figures


def _run_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, texs: list[str]
) -> tuple[Path, zipfile.ZipFile]:
    config, bank, figures = _inputs(tmp_path)
    _fake_pdflatex(monkeypatch, texs)
    out = tmp_path / "out"
    main([
        str(config), "--questions", str(bank), "--figures-dir", str(figures),
        "--out-dir", str(out), "--archive",
    ])
    zips = list(out.glob("C_Quiz_*.zip"))
    assert len(zips) == 1
    return out, zipfile.ZipFile(zips[0])


def test_archive_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texs: list[str] = []
    out, zf = _run_archive(tmp_path, monkeypatch, texs)
    outer_manifest = next(out.glob("C_Quiz_*.manifest.yaml"))
    root = outer_manifest.name.removesuffix(".manifest.yaml")
    names = sorted(zf.namelist())
    assert names == sorted(
        f"{root}/{n}" for n in [
            "README.md", f"{root}.manifest.yaml", "quiz.yaml",
            "questions/bank.yaml", "figures/used.png",
            "C_Quiz.tex", "C_Quiz_solutions.tex",
        ]
    )
    # standalone outputs are still written
    assert (out / "C_Quiz.pdf").exists()
    assert (out / "C_Quiz_solutions.pdf").exists()

    bank = zf.read(f"{root}/questions/bank.yaml").decode()
    assert "id: q1" in bank and "q2" not in bank and "q3" not in bank

    # the archived sources are exactly what pdflatex compiled
    assert len(texs) == 2
    assert zf.read(f"{root}/C_Quiz.tex").decode() == texs[0]
    assert zf.read(f"{root}/C_Quiz_solutions.tex").decode() == texs[1]

    inner = yaml.safe_load(zf.read(f"{root}/{root}.manifest.yaml"))
    outer = yaml.safe_load(outer_manifest.read_text())
    assert {k: v for k, v in inner.items() if k != "files"} == {
        k: v for k, v in outer.items() if k != "files"
    }
    archived = ["quiz.yaml", "questions/bank.yaml", "figures/used.png"]
    assert inner["files"] == [
        {
            "name": Path(n).name,
            "md5": hashlib.md5(zf.read(f"{root}/{n}")).hexdigest(),
        }
        for n in archived
    ]

    readme = zf.read(f"{root}/README.md").decode()
    assert "Test report: 1 question(s)" in readme
    assert f"--from-manifest {root}.manifest.yaml" in readme
    assert "pdflatex -interaction=nonstopmode -halt-on-error C_Quiz.tex" in readme


def test_archive_round_trip_replays_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texs: list[str] = []
    _, zf = _run_archive(tmp_path, monkeypatch, texs)
    extract = tmp_path / "extract"
    zf.extractall(extract)
    root = next(extract.iterdir())

    def no_prompt(prompt: str = "") -> str:
        raise AssertionError(f"unexpected prompt: {prompt}")

    monkeypatch.setattr("builtins.input", no_prompt)
    monkeypatch.chdir(root)
    manifest = next(root.glob("*.manifest.yaml")).name
    main([
        "quiz.yaml", "--from-manifest", manifest,
        "--questions", "questions/bank.yaml", "--figures-dir", "figures",
        "--out-dir", "rebuilt",
    ])
    assert texs[-2] == (root / "C_Quiz.tex").read_text()
    assert texs[-1] == (root / "C_Quiz_solutions.tex").read_text()


def test_archive_rejected_with_watch(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(tmp_path / "c.yaml"), "--watch", "--archive"])
