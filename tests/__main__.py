"""Run the test suite verbosely:  python3 tests [unittest options]

Examples:
  python3 tests                   # everything (integration tests need nono)
  python3 tests -k integration    # only tests whose name matches
  python3 tests -k WithGit -f     # stop at the first failure
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

unittest.main(
    module=None,
    argv=[sys.argv[0], "discover", "-s", str(TESTS_DIR), "-v", *sys.argv[1:]],
)
