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

# Each entry: (course_dir_name, yaml_stem)
EXAMPLE_CASES = [
    ("appc", "unit1a"),
    ("appc", "unit1b"),
    ("appc", "unit2a"),
    ("appc", "unit2b"),
    ("appc", "unit3a"),
    ("appc", "unit3b"),
    ("appc", "unit3c"),
    ("apcalc", "unit1"),
    ("apcalc", "unit2"),
    ("apcalc", "unit3"),
    ("apcalc", "unit4"),
    ("apcalc", "unit5"),
    ("apcalc", "unit6"),
    ("apcalc", "unit7"),
    ("apcalc", "unit8"),
]


@pytest.mark.parametrize("course,unit", EXAMPLE_CASES, ids=[f"{c}/{u}" for c, u in EXAMPLE_CASES])
def test_example_builds_pdf(course, unit):
    yaml_path = EXAMPLE_DIR / course / f"{unit}.yaml"
    images_dir = EXAMPLE_DIR / course / "images" / unit

    assert yaml_path.exists(), f"YAML not found: {yaml_path}"

    out_dir = OUTPUT_DIR / course
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{unit}.pdf"

    result = test_generator.generate_test(
        str(yaml_path),
        str(out_pdf),
        images_dir=str(images_dir) if images_dir.is_dir() else None,
    )

    assert Path(result).exists(), f"PDF was not created: {result}"
    assert Path(result).stat().st_size > 0, f"PDF is empty: {result}"
