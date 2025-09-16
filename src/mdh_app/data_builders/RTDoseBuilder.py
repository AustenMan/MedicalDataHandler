from __future__ import annotations


import logging
from typing import Optional, TYPE_CHECKING


import SimpleITK as sitk


from mdh_app.managers.shared_state_manager import should_exit
from mdh_app.utils.dicom_utils import read_dcm_file, get_first_ref_plan_sop_uid
from mdh_app.utils.sitk_utils import merge_imagereader_metadata


if TYPE_CHECKING:
    from pydicom import Dataset
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


# Supported DICOM RT Dose parameters
SUPPORTED_DOSE_SUMMATION_TYPES = {"PLAN", "BEAM"}
SUPPORTED_DOSE_UNITS = {"GY"}
SUPPORTED_DOSE_TYPES = {"PHYSICAL"}


def _validate_dose_dataset(ds: Dataset) -> bool:
    """Validate essential RT Dose dataset attributes."""
    try:
        dose_summation_type = ds.get("DoseSummationType", "").upper()
        if dose_summation_type not in SUPPORTED_DOSE_SUMMATION_TYPES:
            logger.error(
                f"Unsupported DoseSummationType '{dose_summation_type}'. "
                f"Supported types: {', '.join(SUPPORTED_DOSE_SUMMATION_TYPES)}"
            )
            return False
        
        dose_units = ds.get("DoseUnits", "").upper()
        if dose_units not in SUPPORTED_DOSE_UNITS:
            logger.error(
                f"Unsupported DoseUnits '{dose_units}'. "
                f"Supported units: {', '.join(SUPPORTED_DOSE_UNITS)}"
            )
            return False
        
        dose_type = ds.get("DoseType", "").upper()
        if dose_type not in SUPPORTED_DOSE_TYPES:
            logger.error(
                f"Unsupported DoseType '{dose_type}'. "
                f"Supported types: {', '.join(SUPPORTED_DOSE_TYPES)}"
            )
            return False

        dose_grid_scaling = ds.get("DoseGridScaling", None)
        if not isinstance(dose_grid_scaling, (float, int)) or dose_grid_scaling <= 0:
            logger.error(f"Invalid DoseGridScaling '{dose_grid_scaling}'")
            return False
        
        matched_ref_sop_uid = get_first_ref_plan_sop_uid(ds)
        if not matched_ref_sop_uid:
            logger.error("No valid Referenced RT Plan SOP Instance UID found in RT Dose dataset.")
            return False
        
    except Exception as e:
        logger.error("Error validating RT Dose dataset.", exc_info=True, stack_info=True)
        return False
    
    return True   


def construct_dose(file_path: str, ss_mgr: SharedStateManager) -> Optional[sitk.Image]:
    logger.info(f"Creating RT Dose from file: {file_path}")
    
    if should_exit(ss_mgr, "Cancelling RT Dose processing due to user request."):
        return None
    ds: Optional[Dataset] = read_dcm_file(file_path)
    if ds is None:
        return None
    
    if not _validate_dose_dataset(ds):
        return None
    if should_exit(ss_mgr, "Cancelling RT Dose processing due to user request."):
        return None
    
    try:
        reader = sitk.ImageFileReader()
        reader.SetFileName(file_path)
        reader.ReadImageInformation()
        reader.SetOutputPixelType(sitk.sitkFloat64)
        sitk_dose = reader.Execute()

        dose_grid_scaling = float(ds.DoseGridScaling)
        logger.debug(f"Applying dose grid scaling factor: {dose_grid_scaling}")
        sitk_dose = sitk.Multiply(sitk_dose, dose_grid_scaling)  # apply scaling in float64
        sitk_dose = sitk.Cast(sitk_dose, sitk.sitkFloat32)  # float32 generally adequate

        sitk_dose = merge_imagereader_metadata(reader, sitk_dose)

        matched_ref_sop_uid = get_first_ref_plan_sop_uid(ds)
        sitk_dose.SetMetaData("ReferencedRTPlanSOPInstanceUID", matched_ref_sop_uid)
        sitk_dose.SetMetaData("ReferencedRTPlanBeamNumber", "")
        sitk_dose.SetMetaData("NumberOfFractionsPlanned", "0")
        sitk_dose.SetMetaData("NumberOfFractions", "0")

        logger.info(f"Created RT Dose image: size={sitk_dose.GetSize()}, spacing={sitk_dose.GetSpacing()}")
        return sitk_dose
    except Exception as e:
        logger.error("Failed to create SimpleITK dose image.", exc_info=True, stack_info=True)
        return None

