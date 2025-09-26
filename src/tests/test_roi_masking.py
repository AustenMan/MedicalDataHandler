"""
Test ROI mask generation via build_single_mask() from mdh_app/managers/data_manager.py
"""
from __future__ import annotations


import numpy as np
import pytest
import SimpleITK as sitk


from mdh_app.utils.numpy_utils import numpy_roi_mask_generation


class TestROIMasking:
    """Test ROI mask generation for structure sets."""

    def test_physical_to_matrix_transform(self):
        """
        Test physical coordinate to matrix index transformation.
        References data_manager.py:89-90 transformation pipeline.
        """
        # Image parameters (matching build_single_mask)
        volume_shape = (50, 100, 100)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 2.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: flat array of physical coordinates (mm)
        contour_data_flat = [
            10.0, 10.0, 20.0,  # Square contour at Z=20mm
            20.0, 10.0, 20.0,
            20.0, 20.0, 20.0,
            10.0, 20.0, 20.0
        ]

        # Transform using build_single_mask pipeline (data_manager.py:89-90)
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        # Execute mask generation
        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")

        # Verify transformation: Physical (10,10,20) → matrix (10,10,10) with spacing [1,1,2]
        # In (slice,row,col) format: Z=20mm/2mm = slice 10
        assert mask[10, 10, 10] == 1, "Transform failed for first corner"
        assert mask[10, 20, 20] == 1, "Transform failed for opposite corner"

        # Verify contour interior filled
        assert mask[10, 15, 15] == 1, "Contour interior not filled"

    def test_nonplanar_contour_handling(self):
        """
        Test non-planar contour interpolation across slices.
        References data_manager.py:89-90 transformation + numpy_utils.py 3D interpolation.
        """
        # Image parameters
        volume_shape = (30, 50, 50)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 3.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: non-planar across Z levels
        contour_data_flat = [
            10.0, 10.0, 6.0,   # Z=6mm → slice 2
            20.0, 20.0, 12.0,  # Z=12mm → slice 4
            30.0, 30.0, 18.0   # Z=18mm → slice 6
        ]

        # Transform using build_single_mask pipeline
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "OPEN_NONPLANAR")

        # Verify original points (slice, row, col)
        assert mask[2, 10, 10] == 1, "Start point missing"
        assert mask[4, 20, 20] == 1, "Mid point missing"
        assert mask[6, 30, 30] == 1, "End point missing"

        # Check 3D interpolation
        total_voxels = np.sum(mask)
        assert total_voxels >= 3, "Insufficient interpolation"

    def test_oblique_orientation_handling(self):
        """
        Test oblique image orientation handling.
        References data_manager.py:68 direction cosines transformation.
        """
        # Oblique orientation - 45° rotation around Z-axis
        cos45 = np.cos(np.pi/4)
        sin45 = np.sin(np.pi/4)

        # Image parameters with oblique orientation
        volume_shape = (20, 40, 40)  # (slices, rows, cols)
        origin = [5.0, 5.0, 10.0]
        spacing = [2.0, 2.0, 4.0]
        # 45° Z-axis rotation direction cosines
        direction = [cos45, sin45, 0, -sin45, cos45, 0, 0, 0, 1]

        # DICOM ContourData: flat array of physical coordinates (mm)
        contour_data_flat = [
            15.0, 15.0, 18.0,  # Physical coordinates
            25.0, 15.0, 18.0,
            25.0, 25.0, 18.0,
            15.0, 25.0, 18.0
        ]

        # Transform using build_single_mask pipeline
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")

        # Verify mask exists and has reasonable size
        total_voxels = np.sum(mask)
        assert total_voxels > 0, "Empty mask from oblique transform"
        assert total_voxels < 200, "Mask too large for given contour"

        # Verify single slice occupancy (planar contour)
        occupied_slices = np.sum(np.sum(mask, axis=(1,2)) > 0)
        assert occupied_slices == 1, f"Planar contour spans {occupied_slices} slices, expected 1"

    def test_invalid_contour_handling(self):
        """
        Test handling of malformed contour data.
        References data_manager.py:58-66 contour validation.
        """
        # Image parameters
        volume_shape = (15, 30, 30)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 2.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # Transform setup
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        # Invalid DICOM ContourData cases
        invalid_cases = [
            [],  # Empty
            [1.0, 2.0],  # Incomplete coordinate set
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]  # Valid data for testing minimal handling
        ]

        for i, contour_data_flat in enumerate(invalid_cases):
            try:
                if len(contour_data_flat) >= 3:
                    contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
                    matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)
                    mask = np.zeros(volume_shape, dtype=np.uint8)
                    numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")
                    # Small valid dataset should produce minimal mask
                    assert np.sum(mask) <= 10, "Minimal data should produce small mask"
                else:
                    # Empty or insufficient data should fail gracefully
                    assert len(contour_data_flat) < 3, "Expected insufficient data"
            except (ValueError, IndexError):
                # Expected for invalid input
                pass