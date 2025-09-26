"""
Test ROI contour filling via numpy_roi_mask_generation() from mdh_app/utils/numpy_utils.py
"""
from __future__ import annotations


import numpy as np
import pytest


from mdh_app.utils.numpy_utils import numpy_roi_mask_generation


class TestContourFilling:
    """Test ROI contour filling operations."""

    def test_planar_polygon_filling(self):
        """
        Test polygon filling for planar contours.
        References numpy_utils.py:44-57 cv2.fillPoly() implementation.
        """
        # Image parameters (as in build_single_mask)
        volume_shape = (30, 60, 60)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 1.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: flat array of physical coordinates (mm) in X,Y,Z order
        contour_data_flat = [
            20.0, 20.0, 15.0,  # Point 1
            40.0, 20.0, 15.0,  # Point 2
            40.0, 40.0, 15.0,  # Point 3
            20.0, 40.0, 15.0   # Point 4
        ]

        # Transform physical coords to matrix indices (data_manager.py:89-90)
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        # Execute polygon filling
        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")

        # Verify polygon interior is filled
        assert mask[15, 30, 30] == 1, "Center not filled"  # [slice, row, col]
        assert mask[15, 25, 25] == 1, "Interior missing"
        assert mask[15, 35, 35] == 1, "Interior missing"

        # Verify boundary vertices
        assert mask[15, 20, 20] == 1, "Corner vertex missing"
        assert mask[15, 40, 40] == 1, "Corner vertex missing"

        # Verify exterior exclusion
        assert mask[15, 15, 15] == 0, "Exterior filled incorrectly"
        assert mask[15, 45, 45] == 0, "Exterior filled incorrectly"

        # Verify Z-plane isolation
        assert np.sum(mask[10, :, :]) == 0, "Adjacent slice filled"
        assert np.sum(mask[20, :, :]) == 0, "Adjacent slice filled"

    def test_non_planar_3d_interpolation(self):
        """
        Test 3D line interpolation between non-coplanar points.
        References numpy_utils.py:69-82 np.linspace() 3D interpolation.
        """
        # Image parameters
        volume_shape = (40, 50, 50)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 1.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: non-planar points across Z levels (in X,Y,Z order)
        contour_data_flat = [
            10.0, 10.0, 5.0,   # Point 1 at Z=5mm
            15.0, 20.0, 15.0,  # Point 2 at Z=15mm
            25.0, 30.0, 25.0   # Point 3 at Z=25mm
        ]

        # Transform using build_single_mask pipeline
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        # Execute 3D interpolation
        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "OPEN_NONPLANAR")

        # Verify original points (slice, row, col indexing)
        assert mask[5, 10, 10] == 1, "Start missing"
        assert mask[15, 20, 15] == 1, "Mid missing"
        assert mask[25, 30, 25] == 1, "End missing"

        # Verify 3D path continuity
        total_voxels = np.sum(mask)
        assert total_voxels >= 20, "Path too sparse"
        assert total_voxels <= 100, "Path too dense"

        # Verify Z-span coverage
        z_indices = np.where(np.sum(mask, axis=(1,2)) > 0)[0]
        z_min, z_max = z_indices[0], z_indices[-1]
        assert z_min <= 5, "Missing start Z level"
        assert z_max >= 25, "Missing end Z level"

    def test_concave_contour_handling(self):
        """
        Test concave contour handling.
        References numpy_utils.py:44-57 cv2.fillPoly() for anatomical shapes.
        """
        # Image parameters
        volume_shape = (20, 80, 80)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 1.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: C-shaped contour (concave anatomy) in X,Y,Z order
        contour_data_flat = [
            20.0, 20.0, 10.0,  # Start of C-shape
            60.0, 20.0, 10.0,  # Top right
            60.0, 30.0, 10.0,  # Inner top
            30.0, 30.0, 10.0,  # Inner left
            30.0, 50.0, 10.0,  # Inner right
            60.0, 50.0, 10.0,  # Inner bottom
            60.0, 60.0, 10.0,  # Bottom right
            20.0, 60.0, 10.0,  # Bottom left
            20.0, 20.0, 10.0   # Close contour
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

        # Verify outer regions are filled (slice, row, col indexing)
        assert mask[10, 25, 25] == 1, "Outer region not filled"
        assert mask[10, 25, 55] == 1, "Outer region not filled"
        assert mask[10, 55, 25] == 1, "Outer region not filled"

        # Verify concave interior (C-shape opening) is NOT filled
        assert mask[10, 40, 45] == 0, "Concave interior incorrectly filled"

        # Verify boundary points are marked
        assert mask[10, 20, 20] == 1, "Boundary not marked"
        assert mask[10, 60, 60] == 1, "Boundary not marked"

    def test_edge_case_bounds_validation(self):
        """
        Test edge cases and bounds validation.
        References numpy_utils.py:30-42 bounds checking.
        """
        # Image parameters
        volume_shape = (15, 30, 30)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 1.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # Transform setup
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        # DICOM edge cases
        edge_cases = [
            # Single point (degenerate contour)
            [15.0, 15.0, 7.0],
            # Linear contour (2 points)
            [5.0, 5.0, 7.0, 25.0, 25.0, 7.0],
            # Boundary contour
            [0.0, 0.0, 0.0, 29.0, 0.0, 0.0, 29.0, 29.0, 0.0, 0.0, 29.0, 0.0],
            # Out-of-bounds points
            [-5.0, -5.0, 7.0, 35.0, 35.0, 7.0]
        ]

        for i, contour_data_flat in enumerate(edge_cases):
            try:
                contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
                matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)
                mask = np.zeros(volume_shape, dtype=np.uint8)
                numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")

                # Verify mask has valid shape
                assert mask.shape == volume_shape, f"Edge case {i}: incorrect mask shape"

                # Verify mask contains only valid values
                assert np.all((mask == 0) | (mask == 1)), f"Edge case {i}: invalid mask values"

                # Verify reasonable mask size
                total_voxels = np.sum(mask)
                assert total_voxels <= np.prod(volume_shape), f"Edge case {i}: mask exceeds volume"

            except Exception as e:
                pytest.fail(f"Edge case {i} caused unexpected error: {e}")

    def test_large_volume_performance(self):
        """
        Test performance with large volumes.
        References numpy_utils.py:20-88 algorithm efficiency.
        """
        # Large volume typical of high-resolution imaging
        volume_shape = (200, 512, 512)  # (slices, rows, cols)
        origin = [0.0, 0.0, 0.0]
        spacing = [1.0, 1.0, 1.0]
        direction = [1, 0, 0, 0, 1, 0, 0, 0, 1]

        # DICOM ContourData: simple square for performance test
        contour_data_flat = [
            100.0, 100.0, 100.0,  # Square corners
            200.0, 100.0, 100.0,
            200.0, 200.0, 100.0,
            100.0, 200.0, 100.0
        ]

        # Transform using build_single_mask pipeline
        origin_array = np.array(origin, dtype=np.float32)
        spacing_array = np.array(spacing, dtype=np.float32)
        direction_array = np.array(direction, dtype=np.float32).reshape(3, 3)
        A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T

        contour_points_3d = np.array(contour_data_flat, dtype=np.float32).reshape(-1, 3)
        matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)

        # Monitor memory usage and execution time
        import time
        start_time = time.time()

        mask = np.zeros(volume_shape, dtype=np.uint8)
        numpy_roi_mask_generation(mask, matrix_points, "CLOSED_PLANAR")

        execution_time = time.time() - start_time

        # Verify reasonable execution time
        assert execution_time < 3.0, f"Large volume processing too slow: {execution_time:.2f}s"

        # Verify correct mask properties
        assert mask.shape == volume_shape, "Large volume mask has incorrect shape"
        assert mask.dtype == np.uint8, "Large volume mask should use efficient uint8 dtype"

        # Verify contour was processed correctly
        filled_voxels = np.sum(mask)
        assert 10000 <= filled_voxels <= 20000, f"Large volume contour size unreasonable: {filled_voxels}"