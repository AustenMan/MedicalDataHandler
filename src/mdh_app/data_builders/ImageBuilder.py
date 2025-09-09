from __future__ import annotations


import logging
from os.path import exists
from typing import List, Optional, Tuple, TYPE_CHECKING


import numpy as np
import SimpleITK as sitk


from mdh_app.utils.dicom_utils import get_dict_tag_values, read_dcm_file
from mdh_app.utils.general_utils import get_traceback
from mdh_app.utils.sitk_utils import merge_imagereader_metadata


if TYPE_CHECKING:
    import numpy.typing as npt
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


class ImageBuilder:
    """Builds 3D SimpleITK images from DICOM series with spatial ordering."""
    
    def __init__(
        self, 
        file_paths: List[str], 
        ss_mgr: SharedStateManager, 
        expected_SIUID: Optional[str] = None
    ) -> None:
        if not file_paths:
            raise ValueError("At least one file path must be provided")
            
        self.file_paths = file_paths
        self.ss_mgr = ss_mgr
        self.expected_SIUID = expected_SIUID
        
        # Internal state for image construction
        self._image_orientation_patient: Optional[List[float]] = None
        self._normal_vector: Optional[npt.NDArray[np.float32]] = None
        self._distances: List[Tuple[float, str]] = []
        self._sorted_files: List[str] = []
    
    def _should_exit(self) -> bool:
        """Check if build process should terminate."""
        if self.ss_mgr and (
            self.ss_mgr.cleanup_event.is_set() or 
            self.ss_mgr.shutdown_event.is_set()
        ):
            logger.info("Aborting ImageBuilder task due to shutdown request")
            return True
        return False
    
    def _read_and_validate_files(self) -> bool:
        """Read and validate DICOM files for geometric consistency."""
        if not isinstance(self.file_paths, list) or not all(
            isinstance(f, str) for f in self.file_paths
        ):
            logger.error(
                f"File paths must be a list of strings. Received: {type(self.file_paths)}"
            )
            return False
        
        if self.expected_SIUID is not None and not isinstance(self.expected_SIUID, str):
            logger.error(
                f"Expected SeriesInstanceUID must be a string or None. "
                f"Received: {type(self.expected_SIUID)}"
            )
            return False

        valid_files_count = 0
        
        for filepath in self.file_paths:
            if not exists(filepath):
                logger.warning(f"File does not exist, skipping: {filepath}")
                continue
            
            try:
                ds = read_dcm_file(filepath, to_json_dict=True)
            except Exception as e:
                logger.warning(f"Failed to read DICOM file {filepath}: {e}")
                continue
            
            # Validate SeriesInstanceUID if expected
            if self.expected_SIUID:
                series_uid = get_dict_tag_values(ds, "0020000E")  # SeriesInstanceUID
                if series_uid != self.expected_SIUID:
                    logger.warning(
                        f"SeriesInstanceUID mismatch in {filepath}. "
                        f"Expected: {self.expected_SIUID}, Found: {series_uid}"
                    )
                    continue
            
            # Extract and validate Image Orientation Patient (0020,0037)
            image_orientation = get_dict_tag_values(ds, "00200037")
            if image_orientation is None:
                logger.warning(f"Missing ImageOrientationPatient in {filepath}")
                continue
            
            # Establish reference orientation from first valid file
            if self._image_orientation_patient is None:
                self._image_orientation_patient = image_orientation
                orientation_array = np.array(image_orientation, dtype=np.float32)
                # Calculate normal vector for slice ordering
                self._normal_vector = np.cross(
                    orientation_array[0:3], 
                    orientation_array[3:6]
                )
            elif self._image_orientation_patient != image_orientation:
                logger.error(
                    f"Inconsistent ImageOrientationPatient in {filepath}. "
                    "All images must have the same orientation."
                )
                return False
            
            # Extract and validate Image Position Patient (0020,0032)
            image_position = get_dict_tag_values(ds, "00200032")
            if image_position is None:
                logger.warning(f"Missing ImagePositionPatient in {filepath}")
                continue
            
            # Calculate distance along normal vector for spatial ordering
            position_array = np.array(image_position, dtype=np.float32)
            distance = np.dot(self._normal_vector, position_array)
            self._distances.append((distance, filepath))
            valid_files_count += 1
        
        if self._image_orientation_patient is None:
            logger.error("No valid ImageOrientationPatient found in any file")
            return False
        
        if valid_files_count == 0:
            logger.error("No valid DICOM image files found after validation")
            return False
        
        logger.info(f"Validated {valid_files_count} DICOM image files for series construction")
        return True
    
    def _sort_files(self) -> None:
        """Sort files by spatial position for 3D reconstruction."""
        self._distances.sort(key=lambda distance_file_pair: distance_file_pair[0])
        self._sorted_files = [filepath for _, filepath in self._distances]
        
        logger.debug(
            f"Sorted {len(self._sorted_files)} files by spatial position. "
            f"Distance range: {self._distances[0][0]:.2f} to {self._distances[-1][0]:.2f}"
        )
    
    def build_sitk_image(self) -> Optional[sitk.Image]:
        """Construct 3D SimpleITK image from validated DICOM files."""
        # Check for early termination
        if self._should_exit():
            return None
            
        # Validate and process input files
        if not self._read_and_validate_files():
            logger.error("File validation failed, cannot construct image")
            return None
        
        # Sort files spatially
        self._sort_files()
        
        # Check for termination after processing
        if self._should_exit():
            return None
        
        # Configure SimpleITK image series reader
        reader = sitk.ImageSeriesReader()
        reader.MetaDataDictionaryArrayUpdateOn()  # Preserve DICOM metadata
        reader.LoadPrivateTagsOn()  # Include private DICOM tags
        reader.SetOutputPixelType(sitk.sitkFloat32)  # Standardize to float32
        reader.SetFileNames(self._sorted_files)
        
        # Execute image construction
        try:
            logger.info(f"Constructing 3D image from {len(self._sorted_files)} DICOM files")
            image = reader.Execute()
        except Exception as e:
            logger.error(
                f"ImageSeriesReader failed to construct image: {e}\n"
                f"Traceback: {get_traceback(e)}"
            )
            return None
        
        # Ensure consistent data type
        image = sitk.Cast(image, sitk.sitkFloat32)
        
        # Merge metadata from all slices into the final image
        try:
            image = merge_imagereader_metadata(reader, image)
        except Exception as e:
            logger.warning(f"Failed to merge metadata: {e}")
            # Continue without merged metadata as image is still valid
        
        logger.info(
            f"Successfully constructed image with dimensions: {image.GetSize()}, "
            f"spacing: {image.GetSpacing()}"
        )
        return image

    def get_file_count(self) -> int:
        """Get number of input DICOM files."""
        return len(self.file_paths)
    
    def get_sorted_files(self) -> List[str]:
        """Get spatially sorted file paths."""
        return self._sorted_files.copy()
    
    def get_image_orientation(self) -> Optional[List[float]]:
        """Get ImageOrientationPatient DICOM tag values."""
        return self._image_orientation_patient.copy() if self._image_orientation_patient else None
