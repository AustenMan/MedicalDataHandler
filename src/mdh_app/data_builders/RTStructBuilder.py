from __future__ import annotations


import logging
from concurrent.futures import Future, as_completed
from json import dumps
from os.path import exists
from random import randint
from typing import Any, Dict, List, Optional, TYPE_CHECKING


import numpy as np
import SimpleITK as sitk


from mdh_app.utils.dicom_utils import get_dict_tag_values, read_dcm_file, safe_keyword_for_tag
from mdh_app.utils.general_utils import find_reformatted_mask_name, get_traceback
from mdh_app.utils.numpy_utils import numpy_roi_mask_generation
from mdh_app.utils.sitk_utils import sitk_transform_physical_point_to_index


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.shared_state_manager import SharedStateManager
    

logger = logging.getLogger(__name__)


class RTSDicomTags:
    """DICOM tag constants for RT Structure Set processing."""
    
    # High-level structure set information
    STRUCTURE_SET_LABEL = "30060002"
    STRUCTURE_SET_NAME = "30060004"
    STRUCTURE_SET_DESCRIPTION = "30060006"
    STRUCTURE_SET_DATE = "30060008"
    STRUCTURE_SET_TIME = "30060009"
    
    # Reference frame and series information
    REFERENCED_FRAME_OF_REFERENCE_SEQUENCE = "30060010"
    RT_REFERENCED_STUDY_SEQUENCE = "30060012"
    RT_REFERENCED_SERIES_SEQUENCE = "30060014"
    SERIES_INSTANCE_UID = "0020000E"
    
    # ROI information
    STRUCTURE_SET_ROI_SEQUENCE = "30060020"
    ROI_NUMBER = "30060022"
    ROI_NAME = "30060026"
    ROI_DESCRIPTION = "30060028"
    ROI_VOLUME = "3006002C"
    ROI_DATETIME = "3006002D"
    ROI_CONTOUR_SEQUENCE = "30060039"
    ROI_DISPLAY_COLOR = "3006002A"
    REFERENCED_ROI_NUMBER = "30060084"
    
    # Contour information
    CONTOUR_SEQUENCE = "30060040"
    CONTOUR_GEOMETRIC_TYPE = "30060042"
    NUMBER_OF_CONTOUR_POINTS = "30060046"
    CONTOUR_NUMBER = "30060048"
    CONTOUR_DATA = "30060050"
    
    # ROI Observation information
    RT_ROI_OBSERVATIONS_SEQUENCE = "30060080"
    REFERENCED_ROI_NUMBER = "30060084"
    RT_ROI_INTERPRETED_TYPE = "300600A4"
    ROI_PHYSICAL_PROPERTIES_SEQUENCE = "300600B0"
    ROI_PHYSICAL_PROPERTY = "300600B2"
    ROI_PHYSICAL_PROPERTY_VALUE = "300600B4"
    MATERIAL_ID = "300A00E1"

class StructConstants:
    """Constants for RT Structure Set processing."""
    
    # Default RGB color range for ROI display colors
    RGB_COLOR_RANGE = (0, 255)
    
    # Required keys for SimpleITK image parameters validation
    REQUIRED_SITK_PARAMS = (
        "slices", "rows", "cols", "origin", "spacing", "direction"
    )


def _validate_contour_data(contour: Dict[str, Any]) -> bool:
    """Validate contour data completeness."""
    required_fields = [
        contour.get("contour_geometric_type"),
        contour.get("number_of_contour_points"),
        contour.get("contour_data")
    ]
    return all(field is not None and field != "" for field in required_fields)


def _validate_roi_display_color(color_data: Any) -> Optional[List[int]]:
    """Validate and normalize ROI display color data."""
    if not isinstance(color_data, list) or len(color_data) != 3:
        return None
    
    try:
        # Clamp each color component to valid RGB range
        normalized_color = [
            int(round(min(max(float(component), StructConstants.RGB_COLOR_RANGE[0]), StructConstants.RGB_COLOR_RANGE[1])))
            for component in color_data
        ]
        return normalized_color
    except (ValueError, TypeError):
        return None


def _generate_random_rgb_color() -> List[int]:
    """Generate random RGB color for ROI display."""
    return [randint(StructConstants.RGB_COLOR_RANGE[0], StructConstants.RGB_COLOR_RANGE[1]) for _ in range(3)]


def _create_roi_metadata(
    roi_info_dict: Dict[str, Any],
    current_roi_name: str
) -> Dict[str, str]:
    """Create standardized ROI metadata dictionary."""
    return {
        'original_roi_name': str(roi_info_dict.get("roi_name", "")),
        'current_roi_name': str(current_roi_name),
        'roi_number': str(roi_info_dict.get("roi_number", "")),
        'roi_display_color': str(roi_info_dict.get("roi_display_color", [])),
        'rt_roi_interpreted_type': str(roi_info_dict.get("rt_roi_interpreted_type", "")),
        'roi_physical_properties': dumps(roi_info_dict.get("roi_physical_properties", [])),
        'material_id': str(roi_info_dict.get("material_id", "")),
        'roi_goals': dumps({}),  # Reserved for future treatment goals
        'roi_rx_dose': '',       # Reserved for prescription dose
        'roi_rx_fractions': '',  # Reserved for prescription fractions
        'roi_rx_site': '',       # Reserved for treatment site
    }


def build_single_mask(
    roi_info_dict: Dict[str, Any],
    sitk_image_params: Dict[str, Any],
    tg_263_oar_names_list: List[str],
    organ_name_matching_dict: Dict[str, Any],
    unmatched_organ_name: str
) -> Optional[sitk.Image]:
    """Build binary mask from ROI contour data with TG-263 naming."""
    roi_name = roi_info_dict.get("roi_name", "Unknown_ROI")
    roi_number = roi_info_dict.get("roi_number", 0)
    
    # Initialize binary mask array with proper dimensions
    mask_shape = (
        sitk_image_params["slices"],
        sitk_image_params["rows"], 
        sitk_image_params["cols"]
    )
    mask_np = np.zeros(mask_shape, dtype=bool)
    has_valid_contour_data = False
    
    # Process each contour segment for this ROI
    contour_data_list = roi_info_dict.get("contour_data", [])
    for contour_idx, contour in enumerate(contour_data_list):
        # Validate contour data completeness
        if not _validate_contour_data(contour):
            logger.warning(
                f"Incomplete contour data for ROI '{roi_name}' (number: {roi_number}), "
                f"contour index {contour_idx}. Data: {contour}"
            )
            continue
        
        try:
            # Extract and reshape contour points from flat array to (N, 3) array
            contour_points_flat = contour["contour_data"]
            contour_points_3d = np.array(contour_points_flat, dtype=np.float64).reshape(-1, 3)
            
            # Transform physical coordinates to image matrix indices
            matrix_points = np.array([
                sitk_transform_physical_point_to_index(
                    point,
                    sitk_image_params["origin"],
                    sitk_image_params["spacing"],
                    sitk_image_params["direction"]
                )
                for point in contour_points_3d
            ])
            
            # Generate binary mask
            mask_np = numpy_roi_mask_generation(
                cols=sitk_image_params["cols"],
                rows=sitk_image_params["rows"],
                mask=mask_np,
                matrix_points=matrix_points,
                geometric_type=contour["contour_geometric_type"]
            )
            has_valid_contour_data = True
            
        except Exception as e:
            logger.error(
                f"Failed to process contour {contour_idx} for ROI '{roi_name}' "
                f"(number: {roi_number}): {str(e)}" + get_traceback(e)
            )
            continue
    
    # Check if any valid contour data was processed
    if not has_valid_contour_data:
        logger.warning(f"No valid contour data processed for ROI '{roi_name}' (number: {roi_number}).")
        return None
    
    # Ensure binary mask values are 0 or 1
    mask_np = np.clip(mask_np % 2, 0, 1)
    
    # Create SimpleITK image from numpy array
    mask_sitk = sitk.Cast(sitk.GetImageFromArray(mask_np.astype(np.uint8)), sitk.sitkUInt8)
    
    # Set spatial information
    mask_sitk.SetSpacing(sitk_image_params["spacing"])
    mask_sitk.SetDirection(sitk_image_params["direction"])
    mask_sitk.SetOrigin(sitk_image_params["origin"])

    # Determine standardized ROI name using TG-263
    current_roi_name = find_reformatted_mask_name(
        str(roi_name),
        str(roi_info_dict.get("rt_roi_interpreted_type", "")),
        tg_263_oar_names_list,
        organ_name_matching_dict,
        unmatched_organ_name
    )
    
    # Attach comprehensive metadata to the mask
    metadata = _create_roi_metadata(roi_info_dict, current_roi_name)
    for key, value in metadata.items():
        mask_sitk.SetMetaData(key, value)

    return mask_sitk


class RTStructBuilder:
    """Builds binary masks from DICOM RT Structure Sets."""

    def __init__(
        self,
        file_path: str,
        sitk_image_params_dict: Dict[str, Dict[str, Any]],
        ss_mgr: SharedStateManager,
        conf_mgr: ConfigManager
    ) -> None:
        """Initialize RT Structure Builder with required parameters."""
        self.file_path: str = file_path
        self.sitk_image_params_dict: Dict[str, Dict[str, Any]] = sitk_image_params_dict
        self.ss_mgr: SharedStateManager = ss_mgr
        self.conf_mgr: ConfigManager = conf_mgr
        
        # Initialize data containers
        self.rtstruct_info_dict: Dict[str, Any] = {}
        self.roi_info_dicts: Dict[str, Any] = {}

    def _should_exit(self) -> bool:
        """Check if task should terminate due to cleanup/shutdown events."""
        if (self.ss_mgr is not None and 
            (self.ss_mgr.cleanup_event.is_set() or 
             self.ss_mgr.shutdown_event.is_set())):
            logger.info("Aborting RT Structure Builder task due to cleanup/shutdown event.")
            return True
        return False

    def _validate_inputs(self) -> bool:
        """Validation of all input parameters."""
        # Validate file path
        if not isinstance(self.file_path, str):
            logger.error(
                f"File path must be a string, got {type(self.file_path).__name__} "
                f"with value '{self.file_path}'."
            )
            return False

        if not exists(self.file_path):
            logger.error(f"DICOM file does not exist: '{self.file_path}'")
            return False

        # Validate image parameters dictionary
        if not self.sitk_image_params_dict or not isinstance(self.sitk_image_params_dict, dict):
            logger.error(
                f"Image parameters must be provided as a non-empty dictionary. "
                f"Received type: '{type(self.sitk_image_params_dict).__name__}' "
                f"with value: '{self.sitk_image_params_dict}'"
            )
            return False
        
        # Validate structure of each image parameter entry
        for series_uid, params in self.sitk_image_params_dict.items():
            if not isinstance(series_uid, str):
                logger.error(
                    f"Series instance UID keys must be strings, "
                    f"got {type(series_uid).__name__} for key '{series_uid}'"
                )
                return False
                
            if not isinstance(params, dict):
                logger.error(
                    f"Image parameters must be dictionaries, "
                    f"got {type(params).__name__} for series '{series_uid}'"
                )
                return False
            
            # Check for all required SimpleITK parameter keys
            missing_keys = set(StructConstants.REQUIRED_SITK_PARAMS) - set(params.keys())
            if missing_keys:
                logger.error(
                    f"Image parameters for series '{series_uid}' missing required keys: "
                    f"{missing_keys}. Found keys: {set(params.keys())}"
                )
                return False
        
        # Validate shared state manager
        if not self.ss_mgr:
            logger.error("Shared state manager instance is required but was not provided.")
            return False
        
        # Validate configuration manager
        if not self.conf_mgr:
            logger.error("Configuration manager instance is required but was not provided.")
            return False
        
        return True

    def _read_and_validate_dataset(self) -> bool:
        """
        Read and validate the DICOM RT Structure Set dataset.
        
        Returns:
            bool: True if dataset is successfully read and validated, False otherwise

        Process Flow:
        1. Read DICOM file and convert to dictionary format
        2. Extract high-level structure set information
        3. Validate referenced series instance UID
        4. Extract all ROI and contour information
        5. Validate that processable ROI data exists
        """
        # Read DICOM file
        try:
            ds = read_dcm_file(self.file_path, to_json_dict=True)
            if not ds:
                logger.error(f"Could not read DICOM file: '{self.file_path}'")
                return False
        except Exception as e:
            logger.error(f"Error reading DICOM file '{self.file_path}': {str(e)}" + get_traceback(e))
            return False

        # Check for early termination
        if self._should_exit():
            logger.info("Early termination requested during dataset reading.")
            return False

        # Extract structure set information
        try:
            self._extract_structure_set_info(ds)
        except Exception as e:
            logger.error(f"Failed to extract structure set information: {str(e)}" + get_traceback(e))
            return False

        # Validate referenced series instance UID
        ref_series_uid = self.rtstruct_info_dict.get("ReferencedSeriesInstanceUID")
        if not ref_series_uid:
            logger.error(
                f"Referenced Series Instance UID not found in RT Structure Set file: '{self.file_path}'"
            )
            return False

        if ref_series_uid not in self.sitk_image_params_dict:
            logger.error(
                f"Referenced Series Instance UID '{ref_series_uid}' from RT Structure Set "
                f"not found in provided image parameters. Available series: "
                f"{list(self.sitk_image_params_dict.keys())}"
            )
            return False

        # Extract ROI information
        try:
            self._extract_roi_info(ds)
        except Exception as e:
            logger.error(f"Failed to extract ROI information: {str(e)}" + get_traceback(e))
            return False

        # Validate that we have processable ROI data
        if not self.roi_info_dicts:
            logger.error(f"No processable ROI contour data found in RT Structure Set: '{self.file_path}'")
            return False

        logger.info(
            f"Successfully loaded RT Structure Set with {len(self.roi_info_dicts)} ROIs "
            f"from file: '{self.file_path}'"
        )
        return True

    def _extract_structure_set_info(self, ds: Dict[str, Any]) -> None:
        """
        Parses the structure set metadata including labels, names,
        dates, and reference frame information.
        """
        # Extract basic structure set information using predefined tags
        basic_tags = [
            RTSDicomTags.STRUCTURE_SET_LABEL,
            RTSDicomTags.STRUCTURE_SET_NAME,
            RTSDicomTags.STRUCTURE_SET_DATE,
            RTSDicomTags.STRUCTURE_SET_TIME
        ]
        
        self.rtstruct_info_dict = {
            safe_keyword_for_tag(tag): get_dict_tag_values(ds, tag) 
            for tag in basic_tags
        }
        
        # Extract referenced series instance UID
        self._get_referenced_series_instance_uid(ds)
        
        # Initialize container for processed ROI masks
        self.rtstruct_info_dict["list_roi_sitk"] = []

    def _get_referenced_series_instance_uid(self, ds: Dict[str, Any]) -> None:
        """
        Extract the Referenced Series Instance UID from the structure set
        for spatial alignment with image data.
        """
        ref_frame_seq = get_dict_tag_values(ds, RTSDicomTags.REFERENCED_FRAME_OF_REFERENCE_SEQUENCE)
        referenced_series_uid: Optional[str] = None
        
        if ref_frame_seq:
            for frame_item in ref_frame_seq:
                # Navigate through RT Referenced Study Sequence
                study_seq = get_dict_tag_values(frame_item, RTSDicomTags.RT_REFERENCED_STUDY_SEQUENCE)
                if not study_seq:
                    continue
                    
                for study_item in study_seq:
                    # Navigate through RT Referenced Series Sequence
                    series_seq = get_dict_tag_values(study_item, RTSDicomTags.RT_REFERENCED_SERIES_SEQUENCE)
                    if not series_seq:
                        continue
                        
                    for series_item in series_seq:
                        # Extract Series Instance UID
                        series_uid = get_dict_tag_values(series_item, RTSDicomTags.SERIES_INSTANCE_UID)
                        if series_uid:
                            if referenced_series_uid is None:
                                referenced_series_uid = series_uid
                            elif referenced_series_uid != series_uid:
                                logger.warning(
                                    f"Multiple series instance UIDs found in structure set. "
                                    f"Using '{referenced_series_uid}' and ignoring '{series_uid}'"
                                )
        
        self.rtstruct_info_dict["ReferencedSeriesInstanceUID"] = referenced_series_uid

    def _extract_roi_info(self, ds: Dict[str, Any]) -> None:
        """
        Processes three main DICOM sequences:
        1. Structure Set ROI Sequence - Basic ROI information
        2. ROI Contour Sequence - Geometric contour data and display properties
        3. RT ROI Observations Sequence - ROI Type and identifiers
        """
        # Extract main DICOM sequences
        structure_set_roi_seq = get_dict_tag_values(ds, RTSDicomTags.STRUCTURE_SET_ROI_SEQUENCE)
        roi_contour_seq = get_dict_tag_values(ds, RTSDicomTags.ROI_CONTOUR_SEQUENCE)
        rt_roi_obs_seq = get_dict_tag_values(ds, RTSDicomTags.RT_ROI_OBSERVATIONS_SEQUENCE)

        roi_info_temp: Dict[Any, Any] = {}

        # Process Structure Set ROI Sequence - basic ROI information
        for roi_item in structure_set_roi_seq or []:
            if self._should_exit():
                return

            roi_number = get_dict_tag_values(roi_item, RTSDicomTags.ROI_NUMBER)
            roi_name = get_dict_tag_values(roi_item, RTSDicomTags.ROI_NAME)

            # Initialize ROI information structure
            roi_info_temp[roi_number] = {
                "roi_number": roi_number,
                "roi_name": roi_name,
                "contour_data": [],
                "roi_display_color": _generate_random_rgb_color(),  # Default random color
                "rt_roi_interpreted_type": None,
                "roi_physical_properties": [],
                "material_id": None,
            }

        # Process ROI Contour Sequence - geometric and display information
        for contour_item in roi_contour_seq or []:
            if self._should_exit():
                return

            referenced_roi_number = get_dict_tag_values(contour_item, RTSDicomTags.REFERENCED_ROI_NUMBER)
            if referenced_roi_number not in roi_info_temp:
                logger.warning(f"Found contour data for unknown ROI number: {referenced_roi_number}")
                continue
            
            # Process individual contour sequences
            contour_sequence = get_dict_tag_values(contour_item, RTSDicomTags.CONTOUR_SEQUENCE)
            for cs_item in contour_sequence or []:
                contour_dict = {
                    "contour_geometric_type": get_dict_tag_values(cs_item, RTSDicomTags.CONTOUR_GEOMETRIC_TYPE),
                    "number_of_contour_points": get_dict_tag_values(cs_item, RTSDicomTags.NUMBER_OF_CONTOUR_POINTS),
                    "contour_data": get_dict_tag_values(cs_item, RTSDicomTags.CONTOUR_DATA),
                }
                
                # Only add contours with valid data
                if contour_dict["contour_data"]:
                    roi_info_temp[referenced_roi_number]["contour_data"].append(contour_dict)
            
            # Process ROI display color
            roi_display_color = get_dict_tag_values(contour_item, RTSDicomTags.ROI_DISPLAY_COLOR)
            validated_color = _validate_roi_display_color(roi_display_color)
            if validated_color is not None:
                roi_info_temp[referenced_roi_number]["roi_display_color"] = validated_color

        # Process RT ROI Observations Sequence - type and identifiers
        for obs_item in rt_roi_obs_seq or []:
            if self._should_exit():
                return

            referenced_roi_number = get_dict_tag_values(obs_item, RTSDicomTags.REFERENCED_ROI_NUMBER)
            if referenced_roi_number not in roi_info_temp:
                logger.warning(f"Found observation data for unknown ROI number: {referenced_roi_number}")
                continue
            
            # Extract interpretation and material information
            roi_info_temp[referenced_roi_number]["rt_roi_interpreted_type"] = (
                get_dict_tag_values(obs_item, RTSDicomTags.RT_ROI_INTERPRETED_TYPE)
            )
            roi_info_temp[referenced_roi_number]["material_id"] = (
                get_dict_tag_values(obs_item, RTSDicomTags.MATERIAL_ID)
            )
            
            # Process physical properties sequence
            roi_phys_props_seq = get_dict_tag_values(obs_item, RTSDicomTags.ROI_PHYSICAL_PROPERTIES_SEQUENCE)
            for prop_item in roi_phys_props_seq or []:
                physical_property = {
                    "roi_physical_property": get_dict_tag_values(prop_item, RTSDicomTags.ROI_PHYSICAL_PROPERTY),
                    "roi_physical_property_value": get_dict_tag_values(prop_item, RTSDicomTags.ROI_PHYSICAL_PROPERTY_VALUE),
                }
                roi_info_temp[referenced_roi_number]["roi_physical_properties"].append(physical_property)

        # Filter to only include ROIs with actual contour data
        self.roi_info_dicts = {
            roi_number: roi_data 
            for roi_number, roi_data in roi_info_temp.items() 
            if roi_data["contour_data"]
        }
        
        logger.info(f"Extracted {len(self.roi_info_dicts)} ROIs with contour data from structure set")

    def _build_sitk_masks(self) -> bool:
        """
        Build binary SimpleITK masks for ROIs.
        Returns:
            bool: True if at least one mask is successfully built, False otherwise

        Process Flow:
        1. Retrieve image parameters and configuration data
        2. Start parallel executor with process pool
        3. Submit mask building tasks for each ROI
        4. Collect results
        5. Clean up executor resources
        6. Validate results and update structure set information
        """
        # Get required parameters for mask building
        series_uid = self.rtstruct_info_dict["ReferencedSeriesInstanceUID"]
        sitk_image_params = self.sitk_image_params_dict[series_uid]
        tg_263_names = self.conf_mgr.get_tg_263_names(ready_for_dpg=True)
        organ_match_dict = self.conf_mgr.get_organ_matching_dict()
        unmatched_organ_name = self.conf_mgr.get_unmatched_organ_name()

        generated_masks: List[sitk.Image] = []
        
        # Start parallel executor for CPU-intensive mask generation
        self.ss_mgr.startup_executor(use_process_pool=True)
        
        try:
            # Submit mask building tasks for each ROI
            submitted_futures = []
            for roi_info_dict in self.roi_info_dicts.values():
                if self._should_exit():
                    break
                    
                future = self.ss_mgr.submit_executor_action(
                    build_single_mask,
                    roi_info_dict,
                    sitk_image_params,
                    tg_263_names,
                    organ_match_dict,
                    unmatched_organ_name
                )
                
                if future is not None:
                    submitted_futures.append(future)
            
            logger.info(f"Submitted {len(submitted_futures)} mask building tasks for parallel processing")
            
            # Collect results as they complete
            for future in as_completed(submitted_futures):
                if self._should_exit():
                    logger.info("Early termination requested during mask building")
                    break
                
                try:
                    result = future.result()
                    if result is not None:
                        generated_masks.append(result)
                        roi_name = result.GetMetaData('current_roi_name')
                        logger.debug(f"Successfully built mask for ROI: '{roi_name}'")
                    else:
                        logger.debug("Mask building returned None result (likely no valid contour data)")
                        
                except Exception as e:
                    logger.error(f"Failed to build ROI mask: {str(e)}" + get_traceback(e))
                    
                finally:
                    # Clean up individual futures
                    if isinstance(future, Future) and not future.done():
                        future.cancel()
                        
        except Exception as e:
            logger.error(f"Error during parallel mask building: {str(e)}" + get_traceback(e))
            
        finally:
            # Always clean up the executor
            self.ss_mgr.shutdown_executor()
        
        # Check for early termination
        if self._should_exit():
            logger.info("Mask building process was terminated early")
            return False

        # Update structure set with generated masks
        self.rtstruct_info_dict["list_roi_sitk"].extend(generated_masks)
        
        # Validate results
        total_masks = len(self.rtstruct_info_dict["list_roi_sitk"])
        if total_masks == 0:
            logger.error(f"No valid masks were generated from RT Structure Set: '{self.file_path}'")
            return False
        
        logger.info(
            f"Successfully generated {total_masks} binary masks from "
            f"{len(self.roi_info_dicts)} ROIs in structure set"
        )
        return True

    def _ensure_unique_roi_names(self) -> None:
        """Resolve ROI naming conflicts and ensure unique names."""
        roi_masks = self.rtstruct_info_dict["list_roi_sitk"]
        name_counts: Dict[str, int] = {}
        
        # First pass: count occurrences of each name
        for mask in roi_masks:
            current_name = mask.GetMetaData('current_roi_name')
            name_counts[current_name] = name_counts.get(current_name, 0) + 1
        
        # Second pass: rename duplicates
        name_indices: Dict[str, int] = {}
        for mask in roi_masks:
            current_name = mask.GetMetaData('current_roi_name')
            
            # If name appears multiple times, append index
            if name_counts[current_name] > 1:
                name_indices[current_name] = name_indices.get(current_name, 0) + 1
                unique_name = f"{current_name}_{name_indices[current_name]}"
                mask.SetMetaData('current_roi_name', unique_name)
                logger.debug(f"Renamed duplicate ROI '{current_name}' to '{unique_name}'")

    def build_rtstruct_info_dict(self) -> Optional[Dict[str, Any]]:
        """
        Build the RT Structure Set information dictionary.
        
        Returns:
            Optional[Dict[str, Any]]: Structure set dictionary containing:
                - High-level structure set metadata
                - List of generated SimpleITK binary masks with metadata
                - All extracted DICOM information
                Returns None if processing fails at any stage

        Process Flow:
        1. Input validation (file existence, parameter validation)
        2. DICOM dataset reading and parsing
        3. ROI information extraction
        4. Parallel binary mask generation
        5. Name uniqueness enforcement
        6. Final validation and return

        Example Return Structure:
        ```python
        {
            "StructureSetLabel": "Primary Structure Set",
            "StructureSetName": "Thorax_Structures",
            "StructureSetDate": "20240101",
            "StructureSetTime": "120000",
            "ReferencedSeriesInstanceUID": "1.2.3.4.5...",
            "list_roi_sitk": [
                # List of SimpleITK.Image objects with metadata
                mask1, mask2, mask3, ...
            ]
        }
        ```
        """
        logger.info(f"Starting RT Structure Set processing for file: '{self.file_path}'")
        
        # Step 1: Validate inputs
        if self._should_exit():
            logger.info("Processing terminated before input validation")
            return None
            
        if not self._validate_inputs():
            logger.error("Input validation failed for RT Structure Set processing")
            return None

        # Step 2: Read and validate DICOM dataset
        if self._should_exit():
            logger.info("Processing terminated before dataset reading")
            return None
            
        if not self._read_and_validate_dataset():
            logger.error("DICOM dataset reading and validation failed")
            return None

        # Step 3: Build binary masks from contour data
        if self._should_exit():
            logger.info("Processing terminated before mask building")
            return None
            
        if not self._build_sitk_masks():
            logger.error("Binary mask generation failed")
            return None

        # Step 4: Ensure unique ROI names
        try:
            self._ensure_unique_roi_names()
        except Exception as e:
            logger.error(f"Failed to ensure unique ROI names: {str(e)}" + get_traceback(e))
            return None
        
        return self.rtstruct_info_dict
