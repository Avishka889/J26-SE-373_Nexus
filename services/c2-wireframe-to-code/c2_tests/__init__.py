"""Test package, so shared fixtures import relatively.

Named c2_tests, not tests: the orchestrator's test package already owns
the module name "tests.conftest", and two packages with one name is an
ImportPathMismatchError when the whole suite runs.
"""
