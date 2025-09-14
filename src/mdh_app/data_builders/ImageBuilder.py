from __future__ import annotations


import logging
from os.path import exists
from typing import List, Optional, Tuple, TYPE_CHECKING


import numpy as np
import SimpleITK as sitk


from mdh_app.managers.shared_state_manager import should_exit
from mdh_app.utils.dicom_utils import read_dcm_file
from mdh_app.utils.sitk_utils import merge_imagereader_metadata


if TYPE_CHECKING:
    import numpy.typing as npt
    from pydicom import Dataset
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


def _read_and_validate_files(
    file_paths: List[str],
    expected_SIUID: Optional[str] = None,
) -> Optional[List[str]]:
    """Read and validate DICOM files for geometric consistency."""
    if not isinstance(file_paths, list) or not all(isinstance(f, str) for f in file_paths):
        logger.error(f"File paths must be a list of strings. Received: {type(file_paths)}")
        return None

    if expected_SIUID is not None and not isinstance(expected_SIUID, str):
        logger.error(
            f"Expected SeriesInstanceUID must be a string or None. "
            f"Received: {type(expected_SIUID)}"
        )
        return None

    valid_files_count = 0
    image_orientation_patient: Optional[List[float]] = None
    normal_vector: Optional[npt.NDArray[np.float32]] = None
    distances: List[Tuple[float, str]] = []

    for filepath in file_paths:
        if not exists(filepath):
            logger.warning(f"File does not exist, skipping: {filepath}")
            continue
        
        ds: Optional[Dataset] = read_dcm_file(filepath)
        if ds is None:
            logger.error(f"Failed to read DICOM file {filepath}, skipping this part of the image.")
            continue
        
        # Validate SeriesInstanceUID if expected
        if expected_SIUID:
            series_uid = ds.get("SeriesInstanceUID", "")
            if series_uid != expected_SIUID:
                logger.warning(
                    f"SeriesInstanceUID mismatch in {filepath}. "
                    f"Expected: {expected_SIUID}, Found: {series_uid}"
                )
                continue
        
        # Extract and validate Image Orientation Patient (0020,0037)
        image_orientation = ds.get("ImageOrientationPatient", None)
        if image_orientation is None:
            logger.warning(f"Missing ImageOrientationPatient in {filepath}")
            continue
        
        # Establish reference orientation from first valid file
        if image_orientation_patient is None:
            image_orientation_patient = image_orientation
            orientation_array = np.array(image_orientation, dtype=np.float32)
            # Calculate normal vector for slice ordering
            normal_vector = np.cross(orientation_array[0:3], orientation_array[3:6])
        elif image_orientation_patient != image_orientation:
            logger.error(
                f"Inconsistent ImageOrientationPatient in {filepath}. "
                "All images must have the same orientation."
            )
            return None
        
        # Extract and validate Image Position Patient (0020,0032)
        image_position = ds.get("ImagePositionPatient", None)
        if image_position is None:
            logger.warning(f"Missing ImagePositionPatient in {filepath}")
            continue
        
        # Calculate distance along normal vector for spatial ordering
        position_array = np.array(image_position, dtype=np.float32)
        distance = np.dot(normal_vector, position_array)
        distances.append((distance, filepath))
        valid_files_count += 1
    
    if image_orientation_patient is None:
        logger.error("No valid ImageOrientationPatient found in any file")
        return None
    
    if valid_files_count == 0:
        logger.error("No valid DICOM image files found after validation")
        return None
    
    logger.info(f"Validated {valid_files_count} DICOM image files for series construction")
    
    sorted_files = _sort_files(distances)
    
    return sorted_files


def _sort_files(distances: List[Tuple[float, str]]) -> List[str]:
    """Sort files by spatial position for 3D reconstruction."""
    distances.sort(key=lambda distance_file_pair: distance_file_pair[0])
    sorted_files = [filepath for _, filepath in distances]
    
    logger.debug(
        f"Sorted {len(sorted_files)} files by spatial position. "
        f"Distance range: {distances[0][0]:.2f} to {distances[-1][0]:.2f}"
    )
    return sorted_files


def construct_image(
    file_paths: List[str],
    ss_mgr: SharedStateManager,
    expected_SIUID: Optional[str] = None,
) -> Optional[sitk.Image]:
    """Construct 3D SimpleITK image from validated DICOM files."""
    if should_exit(ss_mgr, "Aborting image construction task due to shutdown request"):
        return None
    
    sorted_files = _read_and_validate_files(file_paths, expected_SIUID)
    if sorted_files is None:
        logger.error("File validation failed, cannot construct image")
        return None
    
    if should_exit(ss_mgr, "Aborting image construction task due to shutdown request"):
        return None
    
    # Configure SimpleITK image series reader
    reader = sitk.ImageSeriesReader()
    reader.MetaDataDictionaryArrayUpdateOn()  # Preserve DICOM metadata
    reader.LoadPrivateTagsOn()  # Include private DICOM tags
    reader.SetOutputPixelType(sitk.sitkFloat32)  # Standardize to float32
    reader.SetFileNames(sorted_files)
    
    # Execute image construction
    try:
        logger.info(f"Constructing 3D image from {len(sorted_files)} DICOM files")
        image = reader.Execute()
    except Exception as e:
        logger.error("ImageSeriesReader failed to construct image!", exc_info=True, stack_info=True)
        return None
    
    # Ensure consistent data type
    image = sitk.Cast(image, sitk.sitkFloat32)
    
    # Merge metadata from all slices into the final image
    try:
        image = merge_imagereader_metadata(reader, image)
    except Exception as e:
        logger.exception("Failed to merge metadata.", exc_info=True, stack_info=True)
        # Continue without merged metadata
    
    logger.info(
        f"Loaded IMAGE with SeriesInstanceUID '{expected_SIUID}' "
        f"with origin {image.GetOrigin()}, direction {image.GetDirection()}, "
        f"spacing {image.GetSpacing()}, size {image.GetSize()}."
    )
    return image

