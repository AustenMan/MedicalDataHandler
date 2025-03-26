import logging
import numpy as np
import SimpleITK as sitk
from os.path import exists
from typing import List, Optional, Tuple

from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dicom_utils import read_dcm_file, get_dict_tag_values
from mdh_app.utils.general_utils import get_traceback
from mdh_app.utils.sitk_utils import merge_imagereader_metadata

logger = logging.getLogger(__name__)

class ImageBuilder:
    """
    Constructs an Image from a series of DICOM Image files.
    
    Attributes:
        file_paths (List[str]): List of file paths to the DICOM Image files.
        ss_mgr (SharedStateManager): Manager for shared resources.
        expected_SIUID (Optional[str]): Expected SeriesInstanceUID for validation.
        image_orientation_patient (Optional[List[float]]): Image orientation (patient) information.
        normal_vector (Optional[np.ndarray]): Normal vector to the plane defined by the image orientation.
        distances (List[Tuple[float, str]]): List of distances and corresponding file paths.
        sorted_files (List[str]): File paths sorted by their distances along the normal vector.
    """
    
    def __init__(self, file_paths: List[str], ss_mgr: SharedStateManager, expected_SIUID: Optional[str] = None) -> None:
        """
        Initialize the ImageBuilder with file paths and optional expected SeriesInstanceUID.
        
        Args:
            file_paths (List[str]): File paths to the DICOM Image files.
            ss_mgr (SharedStateManager): Manager for shared resources.
            expected_SIUID (Optional[str]): Expected SeriesInstanceUID for validation.
        """
        self.file_paths = file_paths
        self.ss_mgr = ss_mgr
        self.expected_SIUID = expected_SIUID
        self.image_orientation_patient: Optional[List[float]] = None
        self.normal_vector: Optional[np.ndarray] = None
        self.distances: List[Tuple[float, str]] = []
        self.sorted_files: List[str] = []
    
    def _should_exit(self) -> bool:
        """
        Checks if the task should be aborted due to cleanup or shutdown events.
        
        Returns:
            bool: True if an exit condition is met, False otherwise.
        """
        if (self.ss_mgr is not None and 
            (self.ss_mgr.cleanup_event.is_set() or 
             self.ss_mgr.shutdown_event.is_set())):
            logger.info("Aborting Image Builder task.")
            return True
        return False
    
    def _read_and_validate_files(self) -> bool:
        """
        Reads and validates the input DICOM files for Image construction.
        
        Returns:
            bool: True if the files are valid and consistent, False otherwise.
        """
        if not self.file_paths or not isinstance(self.file_paths, list) or not all(isinstance(f, str) for f in self.file_paths):
            logger.error(f"File paths must be provided as a list of strings. Received: {self.file_paths}.")
            return False
        
        if self.expected_SIUID is not None and (not self.expected_SIUID or not isinstance(self.expected_SIUID, str)):
            logger.error(f"Expected SeriesInstanceUID must be a string or None. Received: {self.expected_SIUID}.")
            return False
        
        for filepath in self.file_paths:
            if not exists(filepath):
                logger.warning(f"File {filepath} does not exist. Skipping.")
                continue
            
            ds = read_dcm_file(filepath, to_json_dict=True)
            
            # Validate SeriesInstanceUID
            read_SIUID = get_dict_tag_values(ds, "0020000E")
            if self.expected_SIUID and read_SIUID != self.expected_SIUID:
                logger.warning(f"SIUID mismatch in {filepath}. Expected: {self.expected_SIUID}, Found: {read_SIUID}. Skipping.")
                continue
            
            # Validate ImageOrientationPatient
            read_IOP = get_dict_tag_values(ds, "00200037")
            if read_IOP is None:
                logger.warning(f"Missing Image Orientation (Patient) in {filepath}. Skipping.")
                continue
            
            if self.image_orientation_patient is None:
                # First valid IOP found
                self.image_orientation_patient = read_IOP
                IOP = np.array(read_IOP, dtype=np.float32)
                self.normal_vector = np.cross(IOP[0:3], IOP[3:6])
            elif self.image_orientation_patient != read_IOP:
                logger.error(f"Inconsistent Image Orientation (Patient) in {filepath}.")
                return False
            
            # Validate ImagePositionPatient
            read_IPP = get_dict_tag_values(ds, "00200032")
            if read_IPP is None:
                logger.warning(f"Missing Image Position (Patient) in {filepath}. Skipping.")
                continue
            
            # Compute the distance along the normal vector for sorting in slice order
            IPP = np.array(read_IPP, dtype=np.float32)
            distance = np.dot(self.normal_vector, IPP)
            self.distances.append((distance, filepath))
        
        if self.image_orientation_patient is None:
            logger.error("No valid Image Orientation (Patient) found in the provided files.")
            return False
        
        if not self.distances:
            logger.error("No valid files found after validation.")
            return False
        
        return True
    
    def _sort_files(self) -> None:
        """
        Sorts the files based on their distances along the normal vector.
        """
        self.distances.sort(key=lambda x: x[0])
        self.sorted_files = [filepath for _, filepath in self.distances]
    
    def build_sitk_image(self) -> Optional[sitk.Image]:
        """
        Constructs a SimpleITK image from the sorted Image files.
        
        Returns:
            Optional[sitk.Image]: The constructed image if successful, otherwise None.
        """
        if self._should_exit() or not self._read_and_validate_files():
            return None
        
        self._sort_files()
        
        if self._should_exit():
            return None
        
        reader = sitk.ImageSeriesReader()
        reader.MetaDataDictionaryArrayUpdateOn()
        reader.LoadPrivateTagsOn()
        reader.SetOutputPixelType(sitk.sitkFloat32)
        reader.SetFileNames(self.sorted_files)
        
        # Read the image series. 
        try:
            image = reader.Execute()
        except Exception as e:
            logger.error(f"Failed to execute the ImageSeriesReader." + get_traceback(e))
            return None
        
        image = sitk.Cast(image, sitk.sitkFloat32)
        
        # Merge metadata across all slices.
        image = merge_imagereader_metadata(reader, image)
        return image

