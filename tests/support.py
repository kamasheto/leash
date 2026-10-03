"""Shared helpers for the test suite."""

import importlib.machinery
import importlib.util
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "cli"


def load_cli():
    # `cli` has no .py extension, so it can't be imported the normal way.
    loader = importlib.machinery.SourceFileLoader("leash_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader("leash_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
