from __future__ import annotations


import logging
from os.path import exists
from typing import Any, Dict, Optional, TYPE_CHECKING


import SimpleITK as sitk


from mdh_app.utils.dicom_utils import get_dict_tag_values, read_dcm_file
from mdh_app.utils.sitk_utils import merge_imagereader_metadata


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


# Supported DICOM RT Dose parameters
SUPPORTED_DOSE_SUMMATION_TYPES = {"PLAN", "BEAM"}
SUPPORTED_DOSE_UNITS = {"GY"}
SUPPORTED_DOSE_TYPES = {"PHYSICAL"}


class RTDoseBuilder:
    """Builds 3D RT Dose from DICOM RT Dose files."""
    
    def __init__(self, file_path: str, ss_mgr: SharedStateManager) -> None:
        if not file_path:
            raise ValueError("File path cannot be empty")
            
        self.file_path = file_path
        self.ss_mgr = ss_mgr
        self.rt_dose_info_dict: Dict[str, Any] = {}
    
    def _should_exit(self) -> bool:
        """Check if build process should terminate."""
        if self.ss_mgr and (
            self.ss_mgr.cleanup_event.is_set() or 
            self.ss_mgr.shutdown_event.is_set()
        ):
            logger.info("Aborting RTDoseBuilder task due to shutdown request")
            return True
        return False
    
    def _validate_inputs(self) -> bool:
        """Validate input file path and accessibility."""
        if not isinstance(self.file_path, str):
            logger.error(
                f"File path must be a string, received: {type(self.file_path).__name__}"
            )
            return False
            
        if not exists(self.file_path):
            logger.error(f"DICOM RT Dose file not found: {self.file_path}")
            return False
            
        return True
    
    def _extract_dose_summation_type(self, ds_dict: Dict[str, Any]) -> Optional[str]:
        """Extract and validate dose summation type."""
        dose_summation_type = get_dict_tag_values(ds_dict, "3004000A")  # DoseSummationType
        
        if not isinstance(dose_summation_type, str):
            logger.error(f"Invalid DoseSummationType: {dose_summation_type}")
            return None
            
        if dose_summation_type.upper() not in SUPPORTED_DOSE_SUMMATION_TYPES:
            logger.error(
                f"Unsupported DoseSummationType '{dose_summation_type}'. "
                f"Supported types: {', '.join(SUPPORTED_DOSE_SUMMATION_TYPES)}"
            )
            return None
            
        return dose_summation_type
    
    def _extract_dose_units(self, ds_dict: Dict[str, Any]) -> Optional[str]:
        """Extract and validate dose units."""
        dose_units = get_dict_tag_values(ds_dict, "30040002")  # DoseUnits
        
        if not isinstance(dose_units, str):
            logger.error(f"Invalid DoseUnits: {dose_units}")
            return None
            
        if dose_units.upper() not in SUPPORTED_DOSE_UNITS:
            logger.error(
                f"Unsupported DoseUnits '{dose_units}'. "
                f"Supported units: {', '.join(SUPPORTED_DOSE_UNITS)}"
            )
            return None
            
        return dose_units
    
    def _extract_dose_type(self, ds_dict: Dict[str, Any]) -> Optional[str]:
        """Extract and validate dose type."""
        dose_type = get_dict_tag_values(ds_dict, "30040004")  # DoseType
        
        if not isinstance(dose_type, str):
            logger.error(f"Invalid DoseType: {dose_type}")
            return None
            
        if dose_type.upper() not in SUPPORTED_DOSE_TYPES:
            logger.error(
                f"Unsupported DoseType '{dose_type}'. "
                f"Supported types: {', '.join(SUPPORTED_DOSE_TYPES)}"
            )
            return None
            
        return dose_type
    
    def _extract_dose_grid_scaling(self, ds_dict: Dict[str, Any]) -> Optional[float]:
        """Extract and validate dose grid scaling factor."""
        dose_grid_scaling = get_dict_tag_values(ds_dict, "3004000E")  # DoseGridScaling
        
        if not isinstance(dose_grid_scaling, (float, int)):
            logger.error(f"Invalid DoseGridScaling: {dose_grid_scaling}")
            return None
            
        scaling_value = float(dose_grid_scaling)
        if scaling_value <= 0:
            logger.error(f"DoseGridScaling must be positive: {scaling_value}")
            return None
            
        return scaling_value
    
    def _extract_referenced_plan_info(
        self, 
        ds_dict: Dict[str, Any], 
        dose_summation_type: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract referenced RT plan information."""
        referenced_rt_plan_seq = get_dict_tag_values(ds_dict, "300C0002") or []  # ReferencedRTPlanSequence
        referenced_sop_instance_uid: Optional[str] = None
        referenced_beam_number: Optional[str] = None
        
        for plan_item in referenced_rt_plan_seq:
            if self._should_exit():
                return None, None
            
            # Extract Referenced SOP Instance UID
            ref_sop_uid = get_dict_tag_values(plan_item, "00081155")  # ReferencedSOPInstanceUID
            if ref_sop_uid and not referenced_sop_instance_uid:
                referenced_sop_instance_uid = ref_sop_uid
            elif ref_sop_uid and referenced_sop_instance_uid != ref_sop_uid:
                logger.warning(
                    f"Multiple Referenced SOP Instance UIDs found, using first: "
                    f"{referenced_sop_instance_uid}"
                )
            
            # Extract beam number for BEAM dose summation type
            if dose_summation_type.upper() == "BEAM":
                beam_number = self._extract_beam_number_from_plan(plan_item)
                if beam_number and not referenced_beam_number:
                    referenced_beam_number = beam_number
                elif beam_number and referenced_beam_number != beam_number:
                    logger.warning(
                        f"Multiple Referenced Beam Numbers found, using first: "
                        f"{referenced_beam_number}"
                    )
        
        return referenced_sop_instance_uid, referenced_beam_number
    
    def _extract_beam_number_from_plan(self, plan_item: Dict[str, Any]) -> Optional[str]:
        """Extract beam number from referenced plan item."""
        referenced_fraction_seq = get_dict_tag_values(plan_item, "300C0020") or []  # ReferencedFractionGroupSequence
        
        for fraction_item in referenced_fraction_seq:
            beam_seq = get_dict_tag_values(fraction_item, "300C0004") or []  # ReferencedBeamSequence
            
            for beam_item in beam_seq:
                beam_number = get_dict_tag_values(beam_item, "300C0006")  # ReferencedBeamNumber
                if beam_number:
                    return str(beam_number)
        
        return None
    
    def _read_and_extract_dose_info(self) -> bool:
        """Read DICOM file and extract RT Dose information."""
        try:
            ds_dict = read_dcm_file(self.file_path, to_json_dict=True)
        except Exception as e:
            logger.error(f"Failed to read DICOM RT Dose file {self.file_path}: {e}")
            return False
            
        if not ds_dict:
            logger.error(f"Empty DICOM dataset from file: {self.file_path}")
            return False
        
        # Extract and validate dose summation type
        dose_summation_type = self._extract_dose_summation_type(ds_dict)
        if not dose_summation_type:
            return False
        self.rt_dose_info_dict["dose_summation_type"] = dose_summation_type
        
        # Extract and validate dose units
        dose_units = self._extract_dose_units(ds_dict)
        if not dose_units:
            return False
        self.rt_dose_info_dict["dose_units"] = dose_units
        
        # Extract and validate dose type
        dose_type = self._extract_dose_type(ds_dict)
        if not dose_type:
            return False
        self.rt_dose_info_dict["dose_type"] = dose_type
        
        # Extract and validate dose grid scaling
        dose_grid_scaling = self._extract_dose_grid_scaling(ds_dict)
        if dose_grid_scaling is None:
            return False
        self.rt_dose_info_dict["dose_grid_scaling"] = dose_grid_scaling
        
        # Extract referenced plan information
        ref_sop_uid, ref_beam_number = self._extract_referenced_plan_info(
            ds_dict, dose_summation_type
        )
        
        if not ref_sop_uid:
            logger.error(f"Referenced SOP Instance UID not found in: {self.file_path}")
            return False
        self.rt_dose_info_dict["referenced_sop_instance_uid"] = ref_sop_uid
        
        if dose_summation_type.upper() == "BEAM" and not ref_beam_number:
            logger.error(
                f"Referenced Beam Number required for BEAM dose type in: {self.file_path}"
            )
            return False
        self.rt_dose_info_dict["referenced_beam_number"] = ref_beam_number
        
        logger.info(
            f"Extracted RT Dose info: {dose_summation_type} type, "
            f"scaling factor: {dose_grid_scaling}"
        )
        return True
    
    def _create_sitk_dose(self) -> Optional[sitk.Image]:
        """Create SimpleITK image from RT Dose file."""
        try:
            reader = sitk.ImageFileReader()
            reader.SetFileName(self.file_path)
            reader.ReadImageInformation()
            
            if self._should_exit():
                return None
            
            # Read the raw dose image
            sitk_dose = reader.Execute()
            
            # Apply dose grid scaling to convert stored values to dose units
            scaling_factor = float(self.rt_dose_info_dict["dose_grid_scaling"])
            logger.debug(f"Applying dose scaling factor: {scaling_factor}")
            
            # Scale dose values: convert to float64 for precision, then back to float32
            sitk_dose = sitk.Cast(sitk_dose, sitk.sitkFloat64)
            sitk_dose = sitk.Multiply(sitk_dose, scaling_factor)
            sitk_dose = sitk.Cast(sitk_dose, sitk.sitkFloat32)
            
            # Merge DICOM metadata into the image
            sitk_dose = merge_imagereader_metadata(reader, sitk_dose)
            
            # Add RT-specific metadata
            beam_number = self.rt_dose_info_dict.get("referenced_beam_number", "")
            sitk_dose.SetMetaData("referenced_beam_number", str(beam_number))
            sitk_dose.SetMetaData("number_of_fractions_planned", "0")
            sitk_dose.SetMetaData("number_of_fractions_rtdose", "0")
            
            logger.info(
                f"Created RT Dose image: {sitk_dose.GetSize()} voxels, "
                f"spacing: {sitk_dose.GetSpacing()}"
            )
            
            return sitk_dose
            
        except Exception as e:
            logger.error(f"Failed to create SimpleITK dose image: {e}")
            return None
    
    def build_rtdose_info_dict(self) -> Dict[str, Any]:
        """Build RT Dose information dictionary with SimpleITK image."""
        # Check for early termination
        if self._should_exit():
            return {}
            
        # Validate input file
        if not self._validate_inputs():
            logger.error("Input validation failed for RT Dose processing")
            return {}
        
        # Extract dose information from DICOM
        if self._should_exit() or not self._read_and_extract_dose_info():
            logger.error("Failed to extract RT Dose information")
            return {}
        
        # Create SimpleITK dose image
        sitk_dose = self._create_sitk_dose()
        if sitk_dose is None:
            logger.error("Failed to create SimpleITK dose image")
            return {}
            
        self.rt_dose_info_dict["sitk_dose"] = sitk_dose
        
        logger.info("Successfully built RT Dose information dictionary")
        return self.rt_dose_info_dict
    
    def get_dose_info_summary(self) -> Dict[str, Any]:
        """Get summary of extracted dose information."""
        if not self.rt_dose_info_dict:
            return {}
            
        summary = {
            "dose_summation_type": self.rt_dose_info_dict.get("dose_summation_type"),
            "dose_units": self.rt_dose_info_dict.get("dose_units"),
            "dose_type": self.rt_dose_info_dict.get("dose_type"),
            "dose_grid_scaling": self.rt_dose_info_dict.get("dose_grid_scaling"),
            "referenced_sop_instance_uid": self.rt_dose_info_dict.get("referenced_sop_instance_uid"),
        }
        
        if "sitk_dose" in self.rt_dose_info_dict:
            dose_image = self.rt_dose_info_dict["sitk_dose"]
            summary.update({
                "image_size": dose_image.GetSize(),
                "image_spacing": dose_image.GetSpacing(),
                "image_origin": dose_image.GetOrigin(),
            })
            
        return summary
