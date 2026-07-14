"""Integration tests that build a real PDF from each example YAML file.

Output PDFs are written to tests/output_pdfs/ (git-ignored) so they can
be inspected after the test run.
"""

import re

import pytest
from pathlib import Path
import test_generator

REPO_ROOT = Path(__file__).parent.parent
EXAMPLE_DIR = REPO_ROOT / "example"
OUTPUT_DIR = Path(__file__).parent / "output_pdfs"

# Each entry: (course_dir_name, subdir, yaml_stem); subdir is None when the
# YAML files live at the course root.
EXAMPLE_CASES = [
    ("appc", None, "unit1a"),
    ("appc", None, "unit1b"),
    ("appc", None, "unit2a"),
    ("appc", None, "unit2b"),
    ("appc", None, "unit3a"),
    ("appc", None, "unit3b"),
    ("appc", None, "unit3c"),
    ("apcalc", "test_questions", "unit1"),
    ("apcalc", "test_questions", "unit2"),
    ("apcalc", "test_questions", "unit3"),
    ("apcalc", "test_questions", "unit4"),
    ("apcalc", "test_questions", "unit5"),
    ("apcalc", "test_questions", "unit6"),
    ("apcalc", "test_questions", "unit7"),
    ("apcalc", "test_questions", "unit8"),
]


@pytest.mark.parametrize(
    "course,subdir,unit",
    EXAMPLE_CASES,
    ids=[f"{c}/{s + '/' if s else ''}{u}" for c, s, u in EXAMPLE_CASES],
)
def test_example_builds_pdf(course, subdir, unit):
    # apcalc keeps its YAML files in test_questions/ and quiz_questions/
    # subdirectories and uses a single flat figures/ directory; other courses
    # keep YAML files at the course root and per-unit figure subdirectories
    # under figures/.
    if course == "apcalc":
        yaml_path = EXAMPLE_DIR / course / subdir / f"{unit}.yaml"
        figures_dir = EXAMPLE_DIR / course / "figures"
    else:
        yaml_path = EXAMPLE_DIR / course / f"{unit}.yaml"
        figures_dir = EXAMPLE_DIR / course / "figures" / unit

    assert yaml_path.exists(), f"YAML not found: {yaml_path}"

    out_dir = OUTPUT_DIR / course
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / (f"{subdir}-{unit}.pdf" if subdir else f"{unit}.pdf")

    result = test_generator.generate_test(
        str(yaml_path),
        str(out_pdf),
        figures_dir=str(figures_dir) if figures_dir.is_dir() else None,
    )

    assert Path(result).exists(), f"PDF was not created: {result}"
    assert Path(result).stat().st_size > 0, f"PDF is empty: {result}"


def _new_outputs(out_dir, prefix, suffix, before):
    """Files matching <prefix>_<8 hex><suffix> created since ``before``."""
    pattern = re.compile(rf"{re.escape(prefix)}_[0-9a-f]{{8}}{re.escape(suffix)}")
    return sorted(
        p for p in out_dir.iterdir()
        if pattern.fullmatch(p.name) and p not in before
    )


def test_quiz_configs_build_pdfs():
    """End-to-end CLI run driven by multiple quiz config files in sequence."""
    from test_generator.__main__ import main

    quizzes_dir = EXAMPLE_DIR / "apcalc" / "quizzes"
    configs = [quizzes_dir / "Quiz_1.3.yaml", quizzes_dir / "Quiz_1.8.yaml"]
    figures_dir = EXAMPLE_DIR / "apcalc" / "figures"
    out_dir = OUTPUT_DIR / "apcalc" / "quizzes"
    out_dir.mkdir(parents=True, exist_ok=True)
    before = set(out_dir.iterdir())

    main([str(c) for c in configs] + [
        "--out-dir", str(out_dir),
        "--figures-dir", str(figures_dir),
    ])

    for prefix in ("APCalc_Quiz_1.3", "APCalc_Quiz_1.8"):
        for suffix in (".pdf", "_solutions.pdf"):
            new = _new_outputs(out_dir, prefix, suffix, before)
            assert len(new) == 1, f"expected one new {prefix}*{suffix}, got {new}"
            assert new[0].stat().st_size > 0, f"PDF is empty: {new[0]}"
        manifests = _new_outputs(out_dir, prefix, ".manifest.yaml", before)
        assert len(manifests) == 1, f"expected one manifest for {prefix}"


def test_from_manifest_recreates_pdf(tmp_path):
    """Deleting a PDF and rerunning from its manifest recreates it."""
    from test_generator.__main__ import main

    config = EXAMPLE_DIR / "apcalc" / "quizzes" / "Quiz_1.3.yaml"
    figures_dir = EXAMPLE_DIR / "apcalc" / "figures"

    main([str(config), "--out-dir", str(tmp_path), "--figures-dir", str(figures_dir)])

    manifest = next(tmp_path.glob("*.manifest.yaml"))
    student_pdf = next(
        p for p in tmp_path.glob("APCalc_Quiz_1.3_*.pdf")
        if not p.name.endswith("_solutions.pdf")
    )
    student_pdf.unlink()

    main(["--from-manifest", str(manifest), "--out-dir", str(tmp_path), "--student-only"])

    assert student_pdf.exists(), f"PDF was not recreated: {student_pdf}"
    assert student_pdf.stat().st_size > 0, f"PDF is empty: {student_pdf}"
