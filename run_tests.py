#!/usr/bin/env python3
"""
Test runner script for essential MedicalDataHandler tests.
Run from project root: python run_tests.py
"""
import sys
from pathlib import Path

# Add src to Python path for mdh_app imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Now run pytest on the tests
import pytest

if __name__ == "__main__":
    # Run tests with verbose output
    exit_code = pytest.main([
        "src/tests/",
        "-v",
        "--tb=short",
        "--color=yes"
    ])
    sys.exit(exit_code)