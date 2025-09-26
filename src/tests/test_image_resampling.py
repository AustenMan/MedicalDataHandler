"""
Test image resampling via resample_sitk_data_with_params() from mdh_app/utils/sitk_utils.py
"""
from __future__ import annotations


import numpy as np
import pytest
import SimpleITK as sitk


from mdh_app.utils.sitk_utils import resample_sitk_data_with_params


class TestImageResampling:
    """Test image resampling operations."""

    def test_rotation_transformation(self):
        """
        Test rotation with center-of-rotation calculations.
        References sitk_utils.py:90-96 transformation matrix and origin calculations.
        """
        # Create test image with known geometry
        original_image = sitk.Image([40, 40, 20], sitk.sitkFloat32)
        original_image.SetSpacing([2.0, 2.0, 4.0])
        original_image.SetOrigin([10.0, 20.0, 30.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Fill with marker to verify transformation
        array = sitk.GetArrayFromImage(original_image)
        array[10, 20, 20] = 100.0  # Marker at known position
        original_image = sitk.GetImageFromArray(array)
        original_image.SetSpacing([2.0, 2.0, 4.0])
        original_image.SetOrigin([10.0, 20.0, 30.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Apply 90-degree rotation around Z-axis
        resampled_image = resample_sitk_data_with_params(
            original_image,
            set_spacing=(2.0, 2.0, 4.0),
            set_rotation=90.0
        )

        # Verify Z dimension preserved during rotation
        assert resampled_image.GetSize()[2] == original_image.GetSize()[2], "Z dimension altered"

        # Verify center-of-rotation calculation
        original_center = original_image.TransformContinuousIndexToPhysicalPoint(
            (np.array(original_image.GetSize()) - 1) / 2.0
        )
        resampled_center = resampled_image.TransformContinuousIndexToPhysicalPoint(
            (np.array(resampled_image.GetSize()) - 1) / 2.0
        )

        center_diff = np.abs(np.array(original_center) - np.array(resampled_center))
        assert np.all(center_diff < 1.0), f"Center shifted: {center_diff}"

        # Track marker position through 90° rotation
        original_marker_phys = original_image.TransformIndexToPhysicalPoint((20, 20, 10))  # array[10, 20, 20]
        resampled_array = sitk.GetArrayFromImage(resampled_image)

        # Find marker in rotated image
        marker_indices = np.where(resampled_array > 90)
        if len(marker_indices[0]) > 0:
            marker_idx = (int(marker_indices[2][0]), int(marker_indices[1][0]), int(marker_indices[0][0]))
            rotated_marker_phys = resampled_image.TransformIndexToPhysicalPoint(marker_idx)

            # Distance from center should be preserved during rotation
            orig_dist = np.linalg.norm(np.array(original_marker_phys) - np.array(original_center))
            rot_dist = np.linalg.norm(np.array(rotated_marker_phys) - np.array(resampled_center))
            dist_diff = abs(orig_dist - rot_dist)
            assert dist_diff < 2.0, f"Rotation distance not preserved: {orig_dist:.2f} vs {rot_dist:.2f}mm"

    def test_spacing_transformation(self):
        """
        Test spacing changes preserve quantitative values.
        References sitk_utils.py:82-88 spacing and size calculations.
        """
        # Create image with known intensity profile
        original_image = sitk.Image([20, 20, 10], sitk.sitkFloat32)
        original_image.SetSpacing([2.0, 2.0, 5.0])
        original_image.SetOrigin([0.0, 0.0, 0.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Create step function for interpolation testing
        array = sitk.GetArrayFromImage(original_image)
        array[:, :10, :] = 1000.0  # Left half
        array[:, 10:, :] = 2000.0  # Right half
        original_image = sitk.GetImageFromArray(array)
        original_image.SetSpacing([2.0, 2.0, 5.0])
        original_image.SetOrigin([0.0, 0.0, 0.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Resample to higher resolution
        resampled_image = resample_sitk_data_with_params(
            original_image,
            set_spacing=(1.0, 1.0, 2.5)
        )

        resampled_array = sitk.GetArrayFromImage(resampled_image)

        # Verify intensity preservation in homogeneous regions
        left_region = resampled_array[:, :20]
        right_region = resampled_array[:, -20:]

        left_mean = np.mean(left_region[left_region > 500])
        right_mean = np.mean(right_region[right_region > 1500])

        assert 950 <= left_mean <= 1050, f"Left region: {left_mean}"
        assert 1950 <= right_mean <= 2050, f"Right region: {right_mean}"

    def test_coordinate_preservation(self):
        """
        Test spatial coordinate preservation.
        References sitk_utils.py:95-96 center calculation and origin transformation.
        """
        # Create image with known physical coordinates
        original_image = sitk.Image([16, 16, 8], sitk.sitkFloat32)
        original_image.SetSpacing([3.0, 3.0, 6.0])
        original_image.SetOrigin([12.0, 24.0, 36.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Place marker at known position
        array = sitk.GetArrayFromImage(original_image)
        array[4, 8, 8] = 500.0  # Known index position
        original_image = sitk.GetImageFromArray(array)
        original_image.SetSpacing([3.0, 3.0, 6.0])
        original_image.SetOrigin([12.0, 24.0, 36.0])
        original_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Calculate original physical coordinate
        original_physical_point = original_image.TransformIndexToPhysicalPoint((8, 8, 4))

        # Resample with different spacing
        resampled_image = resample_sitk_data_with_params(
            original_image,
            set_spacing=(1.5, 1.5, 3.0)
        )

        # Find marker in resampled image
        resampled_array = sitk.GetArrayFromImage(resampled_image)
        marker_indices = np.where(resampled_array > 400)

        if len(marker_indices[0]) > 0:
            # Get physical coordinate in resampled image
            marker_index = (int(marker_indices[2][0]), int(marker_indices[1][0]), int(marker_indices[0][0]))
            resampled_physical_point = resampled_image.TransformIndexToPhysicalPoint(marker_index)

            # Verify physical coordinates preserved
            coordinate_diff = np.abs(np.array(original_physical_point) - np.array(resampled_physical_point))
            assert np.all(coordinate_diff < 2.0), f"Coordinate shifted: {coordinate_diff}"

    def test_extreme_parameters(self):
        """
        Test robustness with extreme parameters.
        References sitk_utils.py:72-75 input validation.
        """
        # Create minimal test image
        test_image = sitk.Image([10, 10, 5], sitk.sitkFloat32)
        test_image.SetSpacing([1.0, 1.0, 2.0])
        test_image.SetOrigin([0.0, 0.0, 0.0])
        test_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Test extreme parameter cases
        extreme_cases = [
            {"set_spacing": (0.1, 0.1, 0.1)},  # Very high resolution
            {"set_spacing": (10.0, 10.0, 10.0)},  # Very low resolution
            {"set_spacing": (1.0, 1.0, 1.0), "set_rotation": 180.0},  # 180-degree rotation
            {"set_spacing": (1.0, 1.0, 1.0), "set_flip": (True, True, False)},  # X,Y flip
        ]

        for i, params in enumerate(extreme_cases):
            try:
                result = resample_sitk_data_with_params(test_image, **params)

                # Verify valid SimpleITK image
                assert isinstance(result, sitk.Image), f"Case {i}: invalid type"
                assert result.GetSize()[0] > 0, f"Case {i}: zero size"
                assert result.GetSize()[1] > 0, f"Case {i}: zero size"
                assert result.GetSize()[2] > 0, f"Case {i}: zero size"

                # Verify spacing validity
                result_spacing = result.GetSpacing()
                assert all(s > 0 for s in result_spacing), f"Case {i}: invalid spacing"

                # Verify no data corruption
                result_array = sitk.GetArrayFromImage(result)
                assert np.all(np.isfinite(result_array)), f"Case {i}: non-finite values"

            except Exception as e:
                pytest.fail(f"Case {i} error: {e}")

    def test_combined_transformations(self):
        """
        Test multiple parameters applied simultaneously.
        References sitk_utils.py:90-92 combined transformation matrix application.
        """
        # Create test image with asymmetric pattern
        test_image = sitk.Image([30, 40, 25], sitk.sitkFloat32)
        test_image.SetSpacing([1.5, 2.0, 3.0])
        test_image.SetOrigin([5.0, 10.0, 15.0])
        test_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Create distinguishable markers
        array = sitk.GetArrayFromImage(test_image)
        array[12, 15, 10] = 200.0  # Marker 1
        array[12, 25, 10] = 150.0  # Marker 2
        test_image = sitk.GetImageFromArray(array)
        test_image.SetSpacing([1.5, 2.0, 3.0])
        test_image.SetOrigin([5.0, 10.0, 15.0])
        test_image.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])

        # Apply combined transformation
        resampled_image = resample_sitk_data_with_params(
            test_image,
            set_spacing=(1.0, 1.0, 2.0),
            set_rotation=180.0,
            set_flip=(True, False, False)
        )

        # Verify final spacing
        final_spacing = resampled_image.GetSpacing()
        expected_spacing = (1.0, 1.0, 2.0)
        spacing_diff = np.abs(np.array(final_spacing) - np.array(expected_spacing))
        assert np.all(spacing_diff < 0.01), f"Spacing: {final_spacing} vs {expected_spacing}"

        # Verify data preservation and marker tracking
        resampled_array = sitk.GetArrayFromImage(resampled_image)
        assert np.max(resampled_array) > 100.0, "Data lost"
        assert np.all(np.isfinite(resampled_array)), "Non-finite values"

        # Track both marker positions through transformation
        original_marker1_phys = test_image.TransformIndexToPhysicalPoint((10, 15, 12))  # array[12, 15, 10]
        original_marker2_phys = test_image.TransformIndexToPhysicalPoint((10, 25, 12))  # array[12, 25, 10]

        # Get image centers
        orig_center = test_image.TransformContinuousIndexToPhysicalPoint(
            (np.array(test_image.GetSize()) - 1) / 2.0
        )
        trans_center = resampled_image.TransformContinuousIndexToPhysicalPoint(
            (np.array(resampled_image.GetSize()) - 1) / 2.0
        )

        # Find and validate marker 1 (value 200)
        marker1_indices = np.where(resampled_array > 180)
        if len(marker1_indices[0]) > 0:
            marker1_idx = (int(marker1_indices[2][0]), int(marker1_indices[1][0]), int(marker1_indices[0][0]))
            transformed_marker1_phys = resampled_image.TransformIndexToPhysicalPoint(marker1_idx)

            # Distance from center should be preserved
            orig_dist1 = np.linalg.norm(np.array(original_marker1_phys) - np.array(orig_center))
            trans_dist1 = np.linalg.norm(np.array(transformed_marker1_phys) - np.array(trans_center))
            dist_diff1 = abs(orig_dist1 - trans_dist1)
            assert dist_diff1 < 3.0, f"Marker 1 distance not preserved: {orig_dist1:.2f} vs {trans_dist1:.2f}mm"

        # Find and validate marker 2 (value 150)
        marker2_indices = np.where((resampled_array > 130) & (resampled_array < 180))
        if len(marker2_indices[0]) > 0:
            marker2_idx = (int(marker2_indices[2][0]), int(marker2_indices[1][0]), int(marker2_indices[0][0]))
            transformed_marker2_phys = resampled_image.TransformIndexToPhysicalPoint(marker2_idx)

            # Distance from center should be preserved
            orig_dist2 = np.linalg.norm(np.array(original_marker2_phys) - np.array(orig_center))
            trans_dist2 = np.linalg.norm(np.array(transformed_marker2_phys) - np.array(trans_center))
            dist_diff2 = abs(orig_dist2 - trans_dist2)
            assert dist_diff2 < 3.0, f"Marker 2 distance not preserved: {orig_dist2:.2f} vs {trans_dist2:.2f}mm"

            # Validate relative spacing between markers is preserved
            if len(marker1_indices[0]) > 0:
                orig_spacing = np.linalg.norm(np.array(original_marker1_phys) - np.array(original_marker2_phys))
                trans_spacing = np.linalg.norm(np.array(transformed_marker1_phys) - np.array(transformed_marker2_phys))
                spacing_diff = abs(orig_spacing - trans_spacing)
                assert spacing_diff < 4.0, f"Inter-marker spacing not preserved: {orig_spacing:.2f} vs {trans_spacing:.2f}mm"

    def test_non_orthogonal_planes(self):
        """
        Test compatibility with non-orthogonal CT planes (e.g., brachytherapy imaging).
        References sitk_utils.py:156-176 direction cosine transformation.
        """
        # Create image with non-orthogonal slice planes (tilted imaging)
        test_image = sitk.Image([30, 30, 15], sitk.sitkFloat32)
        test_image.SetSpacing([1.0, 1.0, 2.5])
        test_image.SetOrigin([0.0, 0.0, 0.0])

        # Non-orthogonal direction cosines (realistic oblique acquisition)
        angle = np.deg2rad(15)  # 15-degree oblique tilt
        cos_a, sin_a = np.cos(angle), np.sin(angle)

        # Create proper orthonormal direction matrix (oblique slices)
        direction = [
            cos_a, -sin_a, 0,    # X-axis rotated in XY plane
            sin_a,  cos_a, 0,    # Y-axis rotated in XY plane
            0,      0,     1     # Z-axis unchanged
        ]
        test_image.SetDirection(direction)

        # Add anatomical markers
        array = sitk.GetArrayFromImage(test_image)
        array[7, 15, 15] = 200.0   # Central marker
        array[3, 10, 10] = 150.0   # Edge marker
        test_image = sitk.GetImageFromArray(array)
        test_image.SetSpacing([1.0, 1.0, 2.5])
        test_image.SetOrigin([0.0, 0.0, 0.0])
        test_image.SetDirection(direction)

        # Test resampling with tilted planes
        try:
            resampled_image = resample_sitk_data_with_params(
                test_image,
                set_spacing=(0.5, 0.5, 1.25)
            )

            # Verify successful processing
            assert isinstance(resampled_image, sitk.Image), "Resampling failed"

            # Check data preservation
            resampled_array = sitk.GetArrayFromImage(resampled_image)
            assert np.all(np.isfinite(resampled_array)), "Non-finite values"
            assert np.max(resampled_array) > 100.0, "Marker data lost"

            # Verify spacing applied correctly
            result_spacing = resampled_image.GetSpacing()
            expected_spacing = (0.5, 0.5, 1.25)
            spacing_diff = np.abs(np.array(result_spacing) - np.array(expected_spacing))
            assert np.all(spacing_diff < 0.01), f"Spacing mismatch: {result_spacing}"

        except Exception as e:
            pytest.fail(f"Non-orthogonal plane handling failed: {e}")

        # Test rotations on non-orthogonal planes
        try:
            # Get original marker physical coordinates (correct index order: X,Y,Z)
            original_center_phys = test_image.TransformIndexToPhysicalPoint((15, 15, 7))  # Matches array[7, 15, 15]
            original_edge_phys = test_image.TransformIndexToPhysicalPoint((10, 10, 3))    # Matches array[3, 10, 10]

            rotated_image = resample_sitk_data_with_params(
                test_image,
                set_spacing=(1.0, 1.0, 2.5),
                set_rotation=90.0
            )

            # Verify rotation processing
            assert isinstance(rotated_image, sitk.Image), "Rotation failed"
            rotated_array = sitk.GetArrayFromImage(rotated_image)
            assert np.all(np.isfinite(rotated_array)), "Rotation created non-finite values"
            assert np.max(rotated_array) > 100.0, "Rotation lost marker data"

            # Find center marker in rotated image (value = 200)
            center_indices = np.where(rotated_array > 180)
            if len(center_indices[0]) > 0:
                # Convert from array indices (Z,Y,X) to image indices (X,Y,Z)
                center_idx = (int(center_indices[2][0]), int(center_indices[1][0]), int(center_indices[0][0]))
                rotated_center_phys = rotated_image.TransformIndexToPhysicalPoint(center_idx)

                # For 90° rotation around center, distance from center should be preserved
                orig_center = test_image.TransformContinuousIndexToPhysicalPoint(
                    (np.array(test_image.GetSize()) - 1) / 2.0
                )
                rot_center = rotated_image.TransformContinuousIndexToPhysicalPoint(
                    (np.array(rotated_image.GetSize()) - 1) / 2.0
                )

                # Distance from image center should be preserved
                orig_dist = np.linalg.norm(np.array(original_center_phys) - np.array(orig_center))
                rot_dist = np.linalg.norm(np.array(rotated_center_phys) - np.array(rot_center))
                dist_diff = abs(orig_dist - rot_dist)
                assert dist_diff < 2.0, f"Rotation distance not preserved: {orig_dist:.2f} vs {rot_dist:.2f}mm"

        except Exception as e:
            pytest.fail(f"Non-orthogonal plane rotation failed: {e}")

        # Test flips on non-orthogonal planes
        try:
            flipped_image = resample_sitk_data_with_params(
                test_image,
                set_spacing=(1.0, 1.0, 2.5),
                set_flip=(True, False, False)
            )

            # Verify flip processing
            assert isinstance(flipped_image, sitk.Image), "Flip failed"
            flipped_array = sitk.GetArrayFromImage(flipped_image)
            assert np.all(np.isfinite(flipped_array)), "Flip created non-finite values"
            assert np.max(flipped_array) > 100.0, "Flip lost marker data"

            # Verify image dimensions preserved
            orig_size = test_image.GetSize()
            flipped_size = flipped_image.GetSize()
            assert orig_size == flipped_size, f"Flip changed dimensions: {orig_size} vs {flipped_size}"

            # Verify center position preserved (flip is around center)
            orig_center = test_image.TransformContinuousIndexToPhysicalPoint(
                (np.array(test_image.GetSize()) - 1) / 2.0
            )
            flipped_center = flipped_image.TransformContinuousIndexToPhysicalPoint(
                (np.array(flipped_image.GetSize()) - 1) / 2.0
            )
            center_diff = np.linalg.norm(np.array(orig_center) - np.array(flipped_center))
            assert center_diff < 1.0, f"Flip moved image center: {center_diff:.2f}mm"

        except Exception as e:
            pytest.fail(f"Non-orthogonal plane flip failed: {e}")

        # Test combined operations on non-orthogonal planes
        try:
            combined_image = resample_sitk_data_with_params(
                test_image,
                set_spacing=(1.0, 1.0, 2.5),  # Keep same spacing to avoid interpolation loss
                set_rotation=45.0,
                set_flip=(False, True, False)
            )

            # Verify combined processing
            assert isinstance(combined_image, sitk.Image), "Combined operations failed"
            combined_array = sitk.GetArrayFromImage(combined_image)
            assert np.all(np.isfinite(combined_array)), "Combined ops created non-finite values"

            # Verify final spacing
            final_spacing = combined_image.GetSpacing()
            expected_final = (1.0, 1.0, 2.5)
            final_diff = np.abs(np.array(final_spacing) - np.array(expected_final))
            assert np.all(final_diff < 0.01), f"Combined spacing: {final_spacing}"

            # With rotation and flip, some data loss is expected due to interpolation
            # Check that some marker data survived (lower threshold)
            assert np.max(combined_array) > 50.0, f"All marker data lost: max = {np.max(combined_array):.2f}"

            # Verify image dimensions are reasonable
            orig_size = test_image.GetSize()
            combined_size = combined_image.GetSize()
            size_ratio = np.prod(combined_size) / np.prod(orig_size)
            assert 0.5 < size_ratio < 2.0, f"Size changed drastically: {orig_size} vs {combined_size}"

        except Exception as e:
            pytest.fail(f"Non-orthogonal combined operations failed: {e}")