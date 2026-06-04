import test_generator


def test_version_present():
    assert hasattr(test_generator, "__version__")


def test_generate_test():
    assert test_generator.generate_test("foo") == "test_foo"
