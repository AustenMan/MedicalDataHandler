"""
Test HU-to-RED conversion via create_HU_to_RED_map() from mdh_app/utils/numpy_utils.py
"""
from __future__ import annotations


import numpy as np
import pytest


from mdh_app.utils.numpy_utils import create_HU_to_RED_map


class TestHUREDConversion:
    """Test HU-to-RED conversion for CT images."""

    def test_standard_tissue_conversion_accuracy(self, sample_hu_values, expected_red_values):
        """
        Test conversion accuracy for standard tissue types.
        References numpy_utils.py:91-97 interp1d linear interpolation.
        """
        hu_list = list(sample_hu_values.values())
        red_list = list(expected_red_values.values())

        # Create HU-to-RED mapping function
        hu_to_red_func = create_HU_to_RED_map(hu_list, red_list)

        # Test tissue values
        test_cases = [
            (sample_hu_values["air"], expected_red_values["air"], "Air"),
            (sample_hu_values["water"], expected_red_values["water"], "Water"),
            (sample_hu_values["bone"], expected_red_values["bone"], "Bone")
        ]

        for hu_value, expected_red, tissue in test_cases:
            result = hu_to_red_func(np.array([hu_value]))[0]

            # RT physics tolerance: ±2%
            tolerance = 0.02 * expected_red
            assert abs(result - expected_red) <= tolerance, \
                f"{tissue} failed: {result:.3f} vs expected {expected_red:.3f}"

    def test_fallback_to_default_calibration(self):
        """
        Test fallback behavior when invalid inputs trigger default calibration.
        References numpy_utils.py:78-89 backup values fallback.
        """
        # Invalid cases that trigger fallback
        invalid_cases = [
            ([], []),  # Empty lists
            (None, None),  # None values
            ([100], [1.0, 1.1]),  # Mismatched lengths
        ]

        for hu_vals, red_vals in invalid_cases:
            # Should use backup values from _get_backup_* functions
            hu_to_red_func = create_HU_to_RED_map(hu_vals, red_vals)

            # Test with backup calibration - water HU=0 should give RED~1.0
            water_red = hu_to_red_func(np.array([0]))[0]

            # From backup values: HU=0 maps to RED=1.0
            assert 0.99 <= water_red <= 1.01, \
                f"Fallback calibration incorrect: water RED = {water_red:.3f}"

    def test_extreme_value_extrapolation(self):
        """
        Test extrapolation for values outside calibration range.
        References numpy_utils.py:96 fill_value="extrapolate".
        """
        # Limited calibration range
        hu_vals = [-1000, 0, 1000]
        red_vals = [0.001, 1.0, 1.8]

        hu_to_red_func = create_HU_to_RED_map(hu_vals, red_vals)

        # Test extrapolation beyond range
        extreme_cases = [
            (-1500, "Below air HU"),  # Below calibration
            (3000, "Titanium implant HU"),  # Above calibration
        ]

        for extreme_hu, description in extreme_cases:
            result = hu_to_red_func(np.array([extreme_hu]))[0]

            # Linear extrapolation can give negative values - just check finite
            assert np.isfinite(result), \
                f"{description} extrapolation non-finite: {result}"

            # For practical RT use, extreme values should be bounded
            assert -1.0 <= result <= 15.0, \
                f"{description} extrapolation extreme: RED = {result:.3f}"

    def test_backup_calibration_values(self):
        """
        Test backup calibration values.
        References numpy_utils.py:100-149 backup value functions.
        """
        # Trigger backup by passing invalid inputs
        hu_to_red_func = create_HU_to_RED_map([], [])

        # Test key calibration points from backup tables
        test_points = [
            (-1000, 0.001),  # Air
            (-800, 0.193),   # Lung
            (0, 1.0),        # Water
            (1000, 1.59),    # Bone
        ]

        for hu_val, expected_red in test_points:
            result = hu_to_red_func(np.array([hu_val]))[0]

            # Should match backup calibration exactly
            assert abs(result - expected_red) < 0.001, \
                f"Backup calibration HU={hu_val}: got {result:.3f}, expected {expected_red:.3f}"
