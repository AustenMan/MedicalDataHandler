import os
import numpy as np
import SimpleITK as sitk
from utils.dicom_utils import read_dcm_file, get_tag_values
from utils.sitk_utils import merge_imagereader_metadata

class RTImageBuilder:
    """
    A class for constructing an RT Image from a series of DICOM RT Image files.
    
    Attributes:
        file_paths (list of str): List of file paths to the DICOM RT Image files.
        shared_state_manager (class): Manager for shared resources.
        expected_SIUID (str, optional): Expected SeriesInstanceUID to validate against the files.
        image_orientation_patient (list of float): Image orientation (patient) information.
        normal_vector (numpy.ndarray): Normal vector to the plane defined by image orientation.
        distances (list of tuple): List of distances and corresponding file paths.
        sorted_files (list of str): File paths sorted by their distances along the normal vector.
    """
    
    def __init__(self, file_paths, shared_state_manager, expected_SIUID=None):
        """
        Initialize the RTImageBuilder with file paths and optional expected SeriesInstanceUID.
        
        Args:
            file_paths (list of str): File paths to the DICOM RT Image files.
            shared_state_manager (class): Manager for shared resources.
            expected_SIUID (str, optional): Expected SeriesInstanceUID for validation.
        """
        self.file_paths = file_paths
        self.shared_state_manager = shared_state_manager
        self.expected_SIUID = expected_SIUID
        self.image_orientation_patient = None
        self.normal_vector = None
        self.distances = []
        self.sorted_files = []
    
    def _exit_task_status(self):
        should_exit = self.shared_state_manager is not None and (self.shared_state_manager.cleanup_event.is_set() or self.shared_state_manager.shutdown_event.is_set())
        if should_exit:
            print("Aborting RT Image Builder task.")
        return should_exit
    
    def _read_and_validate_files(self):
        """
        Reads and validates the input DICOM files for RT Image construction.
        
        Returns:
            bool: True if the files are valid and consistent, False otherwise.
        """
        # Validate file_paths input
        if not self.file_paths or not isinstance(self.file_paths, list) or not all(isinstance(fpath, str) for fpath in self.file_paths):
            print(f"Error: File paths must be provided as a list of strings. Received: {self.file_paths}.")
            return False
        
        # Validate expected_SIUID
        if self.expected_SIUID is not None and (not self.expected_SIUID or not isinstance(self.expected_SIUID, str)):
            print(f"Error: Expected SeriesInstanceUID must be a string or None. Received: {self.expected_SIUID}.")
            return False
        
        for filepath in self.file_paths:
            if not os.path.exists(filepath):
                print(f"Warning: File {filepath} does not exist. Skipping.")
                continue
            
            ds = read_dcm_file(filepath, to_json_dict=True)
            
            # Validate SeriesInstanceUID
            read_SIUID = get_tag_values(ds, "0020000E")
            if self.expected_SIUID and read_SIUID != self.expected_SIUID:
                print(f"Warning: SIUID mismatch in {filepath}. Expected: {self.expected_SIUID}, Found: {read_SIUID}. Skipping.")
                continue
            
            # Validate ImageOrientationPatient
            read_IOP = get_tag_values(ds, "00200037")
            if read_IOP is None:
                print(f"Warning: Missing Image Orientation (Patient) in {filepath}. Skipping.")
                continue
            
            if self.image_orientation_patient is None:
                # First valid IOP found
                self.image_orientation_patient = read_IOP
                IOP = np.array(read_IOP, dtype=np.float32)
                self.normal_vector = np.cross(IOP[0:3], IOP[3:6])
            elif self.image_orientation_patient != read_IOP:
                print(f"Error: Inconsistent Image Orientation (Patient) in {filepath}.")
                return False
            
            # Validate ImagePositionPatient
            read_IPP = get_tag_values(ds, "00200032")
            if read_IPP is None:
                print(f"Warning: Missing Image Position (Patient) in {filepath}. Skipping.")
                continue
            
            # Compute the distance along the normal vector for sorting in slice order
            IPP = np.array(read_IPP, dtype=np.float32)
            distance = np.dot(self.normal_vector, IPP)
            self.distances.append((distance, filepath))
        
        if self.image_orientation_patient is None:
            print("Error: No valid Image Orientation (Patient) found in the provided files.")
            return False
        
        if not self.distances:
            print("Error: No valid files found after validation.")
            return False
        
        return True
    
    def _sort_files(self):
        """
        Sorts the files based on their distances along the normal vector.
        """
        self.distances.sort()
        self.sorted_files = [filepath for _, filepath in self.distances]
    
    def build_sitk_image(self):
        """
        Constructs a SimpleITK image from the sorted RT Image files.
        
        Returns:
            sitk.Image: The constructed image, or None if the process fails.
        """
        
        if self._exit_task_status() or not self._read_and_validate_files():
            return None
        
        self._sort_files()
        
        if self._exit_task_status():
            return None
        
        reader = sitk.ImageSeriesReader()
        reader.MetaDataDictionaryArrayUpdateOn()
        reader.LoadPrivateTagsOn()
        reader.SetOutputPixelType(sitk.sitkFloat32)
        reader.SetFileNames(self.sorted_files)
        
        # Read the image series and merge metadata across all slices
        image = sitk.Cast(reader.Execute(), sitk.sitkFloat32)
        image = merge_imagereader_metadata(reader, image)
        
        return image

