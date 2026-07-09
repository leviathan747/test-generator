"""Integration tests that build a real PDF from each example YAML file.

Output PDFs are written to tests/output_pdfs/ (git-ignored) so they can
be inspected after the test run.
"""

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
    ("apcalc", "tests", "unit1"),
    ("apcalc", "tests", "unit2"),
    ("apcalc", "tests", "unit3"),
    ("apcalc", "tests", "unit4"),
    ("apcalc", "tests", "unit5"),
    ("apcalc", "tests", "unit6"),
    ("apcalc", "tests", "unit7"),
    ("apcalc", "tests", "unit8"),
    ("apcalc", "quizzes", "unit1"),
]


@pytest.mark.parametrize(
    "course,subdir,unit",
    EXAMPLE_CASES,
    ids=[f"{c}/{s + '/' if s else ''}{u}" for c, s, u in EXAMPLE_CASES],
)
def test_example_builds_pdf(course, subdir, unit):
    # apcalc keeps its YAML files in tests/ and quizzes/ subdirectories and
    # uses a single flat figures/ directory; other courses keep YAML files at
    # the course root and per-unit image subdirectories under images/.
    if course == "apcalc":
        yaml_path = EXAMPLE_DIR / course / subdir / f"{unit}.yaml"
        images_dir = EXAMPLE_DIR / course / "figures"
    else:
        yaml_path = EXAMPLE_DIR / course / f"{unit}.yaml"
        images_dir = EXAMPLE_DIR / course / "images" / unit

    assert yaml_path.exists(), f"YAML not found: {yaml_path}"

    out_dir = OUTPUT_DIR / course
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / (f"{subdir}-{unit}.pdf" if subdir else f"{unit}.pdf")

    result = test_generator.generate_test(
        str(yaml_path),
        str(out_pdf),
        images_dir=str(images_dir) if images_dir.is_dir() else None,
    )

    assert Path(result).exists(), f"PDF was not created: {result}"
    assert Path(result).stat().st_size > 0, f"PDF is empty: {result}"
