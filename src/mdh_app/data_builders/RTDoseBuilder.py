import logging
import SimpleITK as sitk
from os.path import exists
from typing import Any, Dict, Union

from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dicom_utils import read_dcm_file, get_dict_tag_values
from mdh_app.utils.sitk_utils import merge_imagereader_metadata

logger = logging.getLogger(__name__)

class RTDoseBuilder:
    """
    Constructs RT Dose information from a DICOM RT Dose file.
    
    Attributes:
        file_path (str): Path to the DICOM RT Dose file.
        ss_mgr (SharedStateManager): Manager for shared resources.
        rt_dose_info_dict (Dict[str, Any]): Extracted RT Dose information.
    """
    
    def __init__(self, file_path: str, ss_mgr: SharedStateManager) -> None:
        """
        Initialize RTDoseBuilder.
        
        Args:
            file_path (str): Path to the RT Dose file.
            ss_mgr (SharedStateManager): Manager for shared resources.
        """
        self.file_path: str = file_path
        self.ss_mgr = ss_mgr
        self.rt_dose_info_dict: Dict[str, Any] = {}
    
    def _should_exit(self) -> bool:
        """
        Checks if the task should be aborted due to cleanup or shutdown events.
        
        Returns:
            bool: True if an exit condition is met, False otherwise.
        """
        if self.ss_mgr and (
            self.ss_mgr.cleanup_event.is_set() or 
            self.ss_mgr.shutdown_event.is_set()
        ):
            logger.info("Aborting RT Dose Builder task.")
            return True
        return False
    
    def _validate_inputs(self) -> bool:
        """
        Validate the input file path.
        
        Returns:
            bool: True if the file path is valid, False otherwise.
        """
        if not isinstance(self.file_path, str):
            logger.error("Input validation failed: file path must be a string, got %s.", type(self.file_path).__name__)
            return False
        if not exists(self.file_path):
            logger.error("Input validation failed: file not found at %s.", self.file_path)
            return False
        return True
    
    def _read_and_extract_dose_info(self) -> bool:
        """
        Reads the DICOM file and extracts RT Dose information.
        
        Returns:
            bool: True if extraction succeeds, False otherwise.
        """
        ds_dict = read_dcm_file(self.file_path, to_json_dict=True)
        if not ds_dict:
            logger.error(f"Failed to read DICOM file: {self.file_path}.")
            return False
        
        # Extract and validate Dose Summation Type (One of: PLAN, MULTI_PLAN, PLAN_OVERVIEW, FRACTION, BEAM, BRACHY, FRACTION_SESSION, BEAM_SESSION, BRACHY_SESSION, CONTROL_POINT, RECORD)
        dose_summation_type = get_dict_tag_values(ds_dict, "3004000A")
        if not isinstance(dose_summation_type, str) or dose_summation_type.upper() not in ["PLAN", "BEAM"]:
            logger.error(f"Unsupported Dose Summation Type '{dose_summation_type}' in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["dose_summation_type"] = dose_summation_type
        
        # Extract and validate Dose Units (One of: GY, RELATIVE)
        dose_units = get_dict_tag_values(ds_dict, "30040002")
        if not isinstance(dose_units, str) or dose_units.upper() not in ["GY"]:
            logger.error(f"Unsupported Dose Units '{dose_units}' in file {self.file_path}. Only 'GY' is supported.")
            return False
        self.rt_dose_info_dict["dose_units"] = dose_units
        
        # Extract and validate Dose Type (One of: PHYSICAL, EFFECTIVE, ERROR)
        dose_type = get_dict_tag_values(ds_dict, "30040004")
        if not isinstance(dose_type, str) or dose_type.upper() not in ["PHYSICAL"]:
            logger.error(f"Unsupported Dose Type '{dose_type}' in file {self.file_path}. Only 'PHYSICAL' is supported.")
            return False
        self.rt_dose_info_dict["dose_type"] = dose_type
        
        # Extract and validate Dose Grid Scaling, which is a scaling factor to convert stored pixel values to dose units
        dose_grid_scaling = get_dict_tag_values(ds_dict, "3004000E")
        if not isinstance(dose_grid_scaling, (float, int)):
            logger.error(f"Invalid Dose Grid Scaling '{dose_grid_scaling}' in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["dose_grid_scaling"] = dose_grid_scaling
        
        # Extract Referenced SOP Instance UID and, if applicable, Beam Number.
        referenced_rt_plan_sequence = get_dict_tag_values(ds_dict, "300C0002") or []
        referenced_sop_instance_uid: Union[str, None] = None
        referenced_beam_number: Union[str, None] = None
        
        for plan_item in referenced_rt_plan_sequence:
            if self._should_exit():
                return False
            
            ref_sop_instance_uid = get_dict_tag_values(plan_item, "00081155")
            if ref_sop_instance_uid is not None:
                if referenced_sop_instance_uid is None:
                    referenced_sop_instance_uid = ref_sop_instance_uid
                elif referenced_sop_instance_uid != ref_sop_instance_uid:
                    logger.warning(f"Warning: Multiple Referenced SOP Instance UIDs in file {self.file_path}. Using the first.")
            
            if dose_summation_type.upper() == "BEAM":
                referenced_fraction_group_sequence = get_dict_tag_values(plan_item, "300C0020") or []
                for fraction_item in referenced_fraction_group_sequence:
                    beam_sequence = get_dict_tag_values(fraction_item, "300C0004") or []
                    for beam_item in beam_sequence:
                        beam_number = get_dict_tag_values(beam_item, "300C0006")
                        if beam_number is not None:
                            if referenced_beam_number is None:
                                referenced_beam_number = beam_number
                            elif referenced_beam_number != beam_number:
                                logger.warning(f"Warning: Multiple Referenced Beam Numbers in file {self.file_path}. Using the first.")
        
        if referenced_sop_instance_uid is None:
            logger.error(f"Referenced SOP Instance UID not found in file {self.file_path}.")
            return False
        self.rt_dose_info_dict["referenced_sop_instance_uid"] = referenced_sop_instance_uid
        
        if dose_summation_type.upper() == "BEAM" and referenced_beam_number is None:
            logger.error(f"Referenced Beam Number not found in file {self.file_path} for BEAM Dose Summation Type.")
            return False
        self.rt_dose_info_dict["referenced_beam_number"] = referenced_beam_number
        
        return True
    
    def _create_sitk_dose(self) -> None:
        """Creates a SimpleITK image for the RT Dose and attaches relevant metadata."""
        reader = sitk.ImageFileReader()
        reader.SetFileName(self.file_path)
        reader.ReadImageInformation()
        
        if self._should_exit():
            return
        
        sitk_dose = reader.Execute()
        scaling_factor = float(self.rt_dose_info_dict["dose_grid_scaling"])
        # Convert to float64 for scaling, then cast to float32.
        sitk_dose = sitk.Cast(sitk.Cast(sitk_dose, sitk.sitkFloat64) * scaling_factor, sitk.sitkFloat32)
        sitk_dose = merge_imagereader_metadata(reader, sitk_dose)
        
        # Set additional metadata.
        sitk_dose.SetMetaData("referenced_beam_number", str(self.rt_dose_info_dict["referenced_beam_number"]))
        sitk_dose.SetMetaData("number_of_fractions_planned", "0")
        sitk_dose.SetMetaData("number_of_fractions_rtdose", "0")
        
        self.rt_dose_info_dict["sitk_dose"] = sitk_dose
    
    def build_rtdose_info_dict(self) -> Dict[str, Any]:
        """
        Constructs and returns the RT Dose information dictionary.
        
        Returns:
            Dict[str, Any]: The RT Dose information if successful, or an empty dictionary otherwise.
        """
        if self._should_exit() or not self._validate_inputs():
            return {}
        if self._should_exit() or not self._read_and_extract_dose_info():
            return {}
        
        self._create_sitk_dose()
        return self.rt_dose_info_dict

