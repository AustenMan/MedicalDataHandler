import os
import SimpleITK as sitk
from utils.dicom_utils import read_dcm_file, get_tag_values
from utils.sitk_utils import merge_imagereader_metadata

class RTDoseBuilder:
    """
    A class for constructing RT Dose information from a DICOM RT Dose file.
    
    Attributes:
        file_path (str): Path to the DICOM RT Dose file.
        shared_state_manager (class): Manager for shared resources.
        rt_dose_info_dict (dict): Stores extracted RT Dose information.
    """
    
    def __init__(self, file_path, shared_state_manager):
        """
        Initialize RTDoseBuilder with the file path to the DICOM RT Dose file.
        
        Args:
            file_path (str): Path to the RT Dose file.
            shared_state_manager (class): Manager for shared resources.
        """
        self.file_path = file_path
        self.shared_state_manager = shared_state_manager
        self.rt_dose_info_dict = {}
    
    def _exit_task_status(self):
        should_exit = self.shared_state_manager is not None and (self.shared_state_manager.cleanup_event.is_set() or self.shared_state_manager.shutdown_event.is_set())
        if should_exit:
            print("Aborting RT Dose Builder task.")
        return should_exit
    
    def _validate_inputs(self):
        """
        Validates the input file path.
        
        Returns:
            bool: True if inputs are valid, False otherwise.
        """
        if not isinstance(self.file_path, str):
            print(f"Input validation failed: The file path must be a string. Received: {type(self.file_path).__name__}.")
            return False
        if not os.path.exists(self.file_path):
            print(f"Input validation failed: File not found at path {self.file_path}.")
            return False
        return True
    
    def _read_and_extract_dose_info(self):
        """
        Reads the DICOM file and extracts RT Dose information.
        
        Returns:
            bool: True if the extraction is successful, False otherwise.
        """
        ds_dict = read_dcm_file(self.file_path, to_json_dict=True)
        if not ds_dict:
            print(f"Failed to read DICOM file: {self.file_path}.")
            return False
        
        # Extract and validate Dose Summation Type (One of: PLAN, MULTI_PLAN, PLAN_OVERVIEW, FRACTION, BEAM, BRACHY, FRACTION_SESSION, BEAM_SESSION, BRACHY_SESSION, CONTROL_POINT, RECORD)
        dose_summation_type = get_tag_values(ds_dict, "3004000A")
        if not isinstance(dose_summation_type, str) or dose_summation_type.upper() not in ["PLAN", "BEAM"]:
            print(f"Unsupported Dose Summation Type '{dose_summation_type}' in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["dose_summation_type"] = dose_summation_type
        
        # Extract and validate Dose Units (One of: GY, RELATIVE)
        dose_units = get_tag_values(ds_dict, "30040002")
        if not isinstance(dose_units, str) or dose_units.upper() not in ["GY"]:
            print(f"Unsupported Dose Units '{dose_units}' in file {self.file_path}. Only 'GY' is supported.")
            return False
        self.rt_dose_info_dict["dose_units"] = dose_units
        
        # Extract and validate Dose Type (One of: PHYSICAL, EFFECTIVE, ERROR)
        dose_type = get_tag_values(ds_dict, "30040004")
        if not isinstance(dose_type, str) or dose_type.upper() not in ["PHYSICAL"]:
            print(f"Unsupported Dose Type '{dose_type}' in file {self.file_path}. Only 'PHYSICAL' is supported.")
            return False
        self.rt_dose_info_dict["dose_type"] = dose_type
        
        # Extract and validate Dose Grid Scaling, which is a scaling factor to convert stored pixel values to dose units
        dose_grid_scaling = get_tag_values(ds_dict, "3004000E")
        if not isinstance(dose_grid_scaling, (float, int)):
            print(f"Invalid Dose Grid Scaling '{dose_grid_scaling}' in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["dose_grid_scaling"] = dose_grid_scaling
        
        # Extract Referenced SOP Instance UID and Beam Number (if applicable)
        referenced_rt_plan_sequence = get_tag_values(ds_dict, "300C0002") or []
        referenced_sop_instance_uid = None
        referenced_beam_number = None
        
        for plan_item in referenced_rt_plan_sequence:
            if self._exit_task_status():
                return False
            
            ref_sop_instance_uid = get_tag_values(plan_item, "00081155")
            if ref_sop_instance_uid is not None:
                if referenced_sop_instance_uid is None:
                    referenced_sop_instance_uid = ref_sop_instance_uid
                elif referenced_sop_instance_uid != ref_sop_instance_uid:
                    print(f"Warning: Multiple Referenced SOP Instance UIDs in file {self.file_path}. Using the first.")
            
            if self.rt_dose_info_dict["dose_summation_type"] == "BEAM":
                referenced_fraction_group_sequence = get_tag_values(plan_item, "300C0020") or []
                for fraction_item in referenced_fraction_group_sequence:
                    beam_sequence = get_tag_values(fraction_item, "300C0004") or []
                    for beam_item in beam_sequence:
                        beam_number = get_tag_values(beam_item, "300C0006")
                        if beam_number is not None:
                            if referenced_beam_number is None:
                                referenced_beam_number = beam_number
                            elif referenced_beam_number != beam_number:
                                print(f"Warning: Multiple Referenced Beam Numbers in file {self.file_path}. Using the first.")
        
        if referenced_sop_instance_uid is None:
            print(f"Referenced SOP Instance UID not found in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["referenced_sop_instance_uid"] = referenced_sop_instance_uid
        
        if self.rt_dose_info_dict["dose_summation_type"] == "BEAM" and referenced_beam_number is None:
            print(f"Referenced Beam Number not found in file {self.file_path} for BEAM Dose Summation Type.")
            return False
        self.rt_dose_info_dict["referenced_beam_number"] = referenced_beam_number
        
        return True
    
    def _create_sitk_dose(self):
        """
        Creates a SimpleITK image for the RT Dose.
        
        Returns:
            bool: True if the creation is successful, False otherwise.
        """
        reader = sitk.ImageFileReader()
        reader.SetFileName(self.file_path)
        reader.ReadImageInformation()
        
        if self._exit_task_status():
            return
        
        sitk_dose = reader.Execute()
        scaling_factor = float(self.rt_dose_info_dict["dose_grid_scaling"])
        sitk_dose = sitk.Cast(sitk.Cast(sitk_dose, sitk.sitkFloat64) * scaling_factor, sitk.sitkFloat32)
        sitk_dose = merge_imagereader_metadata(reader, sitk_dose)
        
        # Set additional metadata
        sitk_dose.SetMetaData("referenced_beam_number", str(self.rt_dose_info_dict["referenced_beam_number"]))
        sitk_dose.SetMetaData("number_of_fractions_planned", "0")
        sitk_dose.SetMetaData("number_of_fractions_rtdose", "0")
        
        self.rt_dose_info_dict["sitk_dose"] = sitk_dose
    
    def build_rtdose_info_dict(self):
        """
        Constructs the RT Dose information dictionary.
        
        Returns:
            dict: RT Dose information dictionary if successful, empty dictionary otherwise.
        """
        if self._exit_task_status() or not self._validate_inputs():
            return {}
        if self._exit_task_status() or not self._read_and_extract_dose_info():
            return {}
        
        self._create_sitk_dose()
        
        return self.rt_dose_info_dict

