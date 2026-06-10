"""Simple CLI for generating tests from YAML files.

Usage: python -m test_generator input.yaml output.pdf
"""
import argparse
import sys
from .core import generate_test


def main(argv=None):
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(prog="python -m test_generator")
    p.add_argument("input_yaml", help="Path to YAML file containing questions")
    p.add_argument("output_pdf", help="Path where the generated PDF will be written")
    p.add_argument("--title", default="", help="Test title")
    p.add_argument("--author", default="", help="Author name")
    p.add_argument("--class-name", dest="class_name", default="", help="Class name")
    p.add_argument("--form-id", dest="form_id", default="", help="Form identifier (e.g. A, B)")
    p.add_argument("--duration", default="", help="Duration string (e.g. '30 min')")
    p.add_argument("--images-dir", dest="images_dir", default=None, help="Directory containing images (default: images/ next to the YAML file)")
    args = p.parse_args(argv)

    out = generate_test(
        args.input_yaml,
        args.output_pdf,
        title=args.title,
        author=args.author,
        class_name=args.class_name,
        form_id=args.form_id,
        duration=args.duration,
        images_dir=args.images_dir,
    )
    print(out)


if __name__ == "__main__":
    main()
