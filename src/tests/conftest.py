"""
Test fixtures.
"""
from __future__ import annotations


import pytest


@pytest.fixture
def sample_hu_values():
    """Sample HU values for specified tissues."""
    return {
        "air": -1000,
        "lung": -800,
        "fat": -100,
        "water": 0,
        "muscle": 50,
        "bone": 1000
    }


@pytest.fixture
def expected_red_values():
    """Sample RED values for specified tissues."""
    return {
        "air": 0.001,
        "lung": 0.193,
        "fat": 0.906,
        "water": 1.0,
        "muscle": 1.064,
        "bone": 1.59
    }