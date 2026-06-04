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
    args = p.parse_args(argv)

    out = generate_test(args.input_yaml, args.output_pdf)
    print(out)


if __name__ == "__main__":
    main()
