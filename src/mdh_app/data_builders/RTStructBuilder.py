from __future__ import annotations


import logging
from os.path import exists
from typing import Any, Dict, Tuple, Optional, TYPE_CHECKING


from mdh_app.managers.shared_state_manager import should_exit
from mdh_app.utils.dicom_utils import read_dcm_file, get_first_ref_series_uid


if TYPE_CHECKING:
    from pydicom import Dataset
    from mdh_app.managers.shared_state_manager import SharedStateManager
    

logger = logging.getLogger(__name__)


def _validate_inputs(
    file_path: str,
    image_params: Dict[str, Any],
    ss_mgr: SharedStateManager,
    required_keys=("slices", "rows", "cols", "origin", "spacing", "direction"),
) -> bool:
    """Validation of all input parameters."""
    if not isinstance(file_path, str):
        logger.error(f"File path must be a string, got {type(file_path).__name__} with value '{file_path}'.")
        return False
    if not exists(file_path):
        logger.error(f"DICOM file does not exist: '{file_path}'")
        return False
    if not image_params or not isinstance(image_params, dict):
        logger.error(f"Image parameters must be a non-empty dict, got {type(image_params).__name__} with value '{image_params}'.")
        return False
    missing_keys = set(required_keys) - set(image_params.keys())
    if missing_keys:
        logger.error(f"Image parameters missing required keys: {missing_keys}")
        return False
    if not ss_mgr:
        logger.error("Shared state manager instance is required but missing.")
        return False
    return True


def _validate_structure_set_info(ds: Dataset) -> bool:
    """Validate essential structure set information (SOP UID, referenced series)."""
    try:
        if not ds.get("SOPInstanceUID", ""):
            logger.error("Missing SOP Instance UID in RT Structure Set, so it cannot be processed.")
            return False
        referenced_series_uid = get_first_ref_series_uid(ds)
        if not referenced_series_uid:
            logger.error("No Referenced Series Instance UID found in RT Structure Set, so it cannot be processed.")
            return False
    except Exception:
        logger.error("Error validating structure set information!", exc_info=True)
        return False

    return True


def _extract_roi_info(ds: Dataset, ss_mgr: SharedStateManager) -> Dict[int, Dict[str, Dataset]]:
    """ Searches for ROIs that contain essential components. """
    try:
        roi_datasets: Dict[int, Dict[str, Dataset]] = {}
        
        # Find each ROI's basic information
        for roi_ds in ds.get("StructureSetROISequence", []):
            if should_exit(ss_mgr, "Early termination requested during ROI info extraction."):
                return {}

            roi_number = roi_ds.get("ROINumber", None)
            if roi_number is not None:
                if roi_number not in roi_datasets:
                    roi_datasets[roi_number] = {"StructureSetROI": roi_ds}
                else:
                    logger.warning(f"Duplicate ROI found in Structure Set for ROI Number: {roi_number}")

        # Find each ROI's contour information
        for contour_ds in ds.get("ROIContourSequence", []):
            if should_exit(ss_mgr, "Early termination requested during ROI contour extraction."):
                return {}

            referenced_roi_number = contour_ds.get("ReferencedROINumber", None)
            if referenced_roi_number is not None:
                if referenced_roi_number in roi_datasets:
                    if "ROIContour" not in roi_datasets[referenced_roi_number]:
                        roi_datasets[referenced_roi_number]["ROIContour"] = contour_ds
                    else:
                        logger.warning(f"Duplicate ROI Contour found in ROI Contour Sequence for ROI Number: {referenced_roi_number}")
                else:
                    logger.warning(f"Found contour data for unknown ROI number: {referenced_roi_number}")

        # Find each ROI's observation information
        for obs_ds in ds.get("RTROIObservationsSequence", []):
            if should_exit(ss_mgr, "Early termination requested during ROI observation extraction."):
                return {}

            referenced_roi_number = obs_ds.get("ReferencedROINumber", None)
            if referenced_roi_number is not None:
                if referenced_roi_number in roi_datasets:
                    if "RTROIObservations" not in roi_datasets[referenced_roi_number]:
                        roi_datasets[referenced_roi_number]["RTROIObservations"] = obs_ds
                    else:
                        logger.warning(f"Duplicate RT ROI Observation found in RT ROI Observations Sequence for ROI Number: {referenced_roi_number}")
                else:
                    logger.warning(f"Found observation data for unknown ROI number: {referenced_roi_number}")

        # Filter to only include ROIs with all three components
        roi_datasets = {
            roi_number: components
            for roi_number, components in roi_datasets.items()
            if "ROIContour" in components and "RTROIObservations" in components and "StructureSetROI" in components
        }
        
        if not roi_datasets:
            logger.error("No valid ROI data was found in the structure set!")
        else:
            logger.info(f"Identified {len(roi_datasets)} valid ROIs in the structure set")
        
        return roi_datasets
    except Exception as e:
        logger.error(f"Error extracting ROI data from structure set!", exc_info=True)
        return {}


def extract_rtstruct_and_roi_datasets(
    file_path: str,
    image_params: Dict[str, Any],
    ss_mgr: SharedStateManager,
) -> Optional[Tuple[Dataset, Dict[int, Dict[str, Dataset]]]]:
    """
    Build ROI grouping from an RT Structure Set file.
    
    Returns:
        (ds, roi_datasets) if successful, else None.
    """
    logger.info(f"Starting RT Structure Set processing for file: '{file_path}'")
        
    # Validate inputs
    if should_exit(ss_mgr, "Processing terminated before structure set input validation."):
        return None
    if not _validate_inputs(file_path, image_params, ss_mgr):
        return None

    # Read DICOM dataset
    if should_exit(ss_mgr, "Processing terminated before structure set dataset reading."):
        return None
    ds: Optional[Dataset] = read_dcm_file(file_path)
    if ds is None:
        return None
    
    # Validate DICOM dataset
    if should_exit(ss_mgr, "Processing terminated before structure set dataset validation."):
        return None
    if not _validate_structure_set_info(ds):
        return None
    
    # Group ROI information
    if should_exit(ss_mgr, "Processing terminated before ROI information extraction."):
        return None
    roi_datasets: Dict[int, Dict[str, Dataset]] = _extract_roi_info(ds, ss_mgr)
    if not roi_datasets:
        return None
    
    logger.info(f"Completed RT Structure Set processing for file: '{file_path}'")
    return ds, roi_datasets

