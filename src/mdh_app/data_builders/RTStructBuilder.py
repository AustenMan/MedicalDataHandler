import logging
import numpy as np
import SimpleITK as sitk
from os.path import exists
from random import randint
from json import dumps
from typing import Any, Dict, List, Optional
from concurrent.futures import as_completed, Future

from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dicom_utils import read_dcm_file, get_dict_tag_values, safe_keyword_for_tag
from mdh_app.utils.general_utils import find_reformatted_mask_name, get_traceback
from mdh_app.utils.numpy_utils import numpy_roi_mask_generation
from mdh_app.utils.sitk_utils import sitk_transform_physical_point_to_index

logger = logging.getLogger(__name__)

def build_single_mask(
    roi_info_dict: Dict[str, Any],
    sitk_image_params: Dict[str, Any],
    tg_263_oar_names_list: List[str],
    organ_name_matching_dict: Dict[str, Any],
    unmatched_organ_name: str
) -> Optional[sitk.Image]:
    """
    Build a binary mask for a single ROI from contour data.

    Args:
        roi_info_dict: ROI information including contour data and metadata.
        sitk_image_params: SimpleITK image parameters (slices, rows, cols, origin, spacing, direction).
        tg_263_oar_names_list: List of TG-263 compliant organ-at-risk names.
        organ_name_matching_dict: Dictionary for organ name matching.
        unmatched_organ_name: Name to use for unmatched organs.

    Returns:
        A SimpleITK binary mask with ROI metadata or None if no valid contour data is found.
    """
    roi_name = roi_info_dict["roi_name"]
    roi_number = roi_info_dict["roi_number"]
    mask_np = np.zeros(
        (sitk_image_params["slices"], sitk_image_params["rows"], sitk_image_params["cols"]),
        dtype=bool
    )
    has_data = False
    
    for idx, contour in enumerate(roi_info_dict["contour_data"]):
        if not all([
            contour["contour_geometric_type"],
            contour["number_of_contour_points"],
            contour["contour_data"]
        ]):
            logger.warning(f"Incomplete contour data for ROI '{roi_name}', index '{idx}'. Data: {contour}")
            continue
        
        contour_points = np.array(contour["contour_data"], dtype=np.float64).reshape(-1, 3)
        matrix_points = np.array([
            sitk_transform_physical_point_to_index(
                point,
                sitk_image_params["origin"],
                sitk_image_params["spacing"],
                sitk_image_params["direction"]
            )
            for point in contour_points
        ])
        mask_np = numpy_roi_mask_generation(
            cols=sitk_image_params["cols"],
            rows=sitk_image_params["rows"],
            mask=mask_np,
            matrix_points=matrix_points,
            geometric_type=contour["contour_geometric_type"]
        )
        has_data = True
    
    if not has_data:
        logger.warning(f"No valid contour data for ROI '{roi_name}'.")
        return None

    mask_np = np.clip(mask_np % 2, 0, 1)
    mask_sitk = sitk.Cast(sitk.GetImageFromArray(mask_np.astype(np.uint8)), sitk.sitkUInt8)
    mask_sitk.SetSpacing(sitk_image_params["spacing"])
    mask_sitk.SetDirection(sitk_image_params["direction"])
    mask_sitk.SetOrigin(sitk_image_params["origin"])

    current_roi_name = find_reformatted_mask_name(
        str(roi_name),
        str(roi_info_dict["rt_roi_interpreted_type"]),
        tg_263_oar_names_list,
        organ_name_matching_dict,
        unmatched_organ_name
    )
    
    metadata = {
        'original_roi_name': str(roi_name),
        'current_roi_name': str(current_roi_name),
        'roi_number': str(roi_number),
        'roi_display_color': str(roi_info_dict["roi_display_color"]),
        'rt_roi_interpreted_type': str(roi_info_dict["rt_roi_interpreted_type"]),
        'roi_physical_properties': dumps(roi_info_dict["roi_physical_properties"]),
        'material_id': str(roi_info_dict["material_id"]),
        'roi_goals': dumps({}),
        'roi_rx_dose': '',
        'roi_rx_fractions': '',
        'roi_rx_site': '',
    }
    for key, value in metadata.items():
        mask_sitk.SetMetaData(key, value)

    return mask_sitk

class RTStructBuilder:
    """
    Construct RT Structure Set information from a DICOM file.

    Attributes:
        file_path (str): Path to the RT Structure Set DICOM file.
        sitk_image_params_dict (dict): Dictionary of SimpleITK image parameters.
        ss_mgr (SharedStateManager): Manager for shared task execution.
        conf_mgr (ConfigManager): Provides TG-263 organ names and organ matching dictionaries.
        rtstruct_info_dict (dict): High-level structure set information.
        roi_info_dicts (dict): ROI information including contour data and metadata.
    """
    
    def __init__(
        self,
        file_path: str,
        sitk_image_params_dict: Dict[str, Dict[str, Any]],
        ss_mgr: SharedStateManager,
        conf_mgr: ConfigManager
    ) -> None:
        """
        Initialize the RTStructBuilder.

        Args:
            file_path (str): Path to the RT Structure Set DICOM file.
            sitk_image_params_dict (dict): SimpleITK image parameters dictionary.
            ss_mgr (SharedStateManager): Shared task execution manager.
            conf_mgr (ConfigManager): Configuration manager for organ names and matching.
        """
        self.file_path = file_path
        self.sitk_image_params_dict = sitk_image_params_dict
        self.ss_mgr = ss_mgr
        self.conf_mgr = conf_mgr
        self.rtstruct_info_dict: Dict[str, Any] = {}
        self.roi_info_dicts: Dict[str, Any] = {}
    
    def _should_exit(self) -> bool:
        """
        Checks if the task should be aborted due to cleanup or shutdown events.
        
        Returns:
            bool: True if an exit condition is met, False otherwise.
        """
        if (self.ss_mgr is not None and 
            (self.ss_mgr.cleanup_event.is_set() or 
             self.ss_mgr.shutdown_event.is_set())):
            logger.info("Aborting RT Plan Builder task.")
            return True
        return False
    
    def _validate_inputs(self) -> bool:
        """
        Validate inputs for building the structure set.

        Returns:
            True if inputs are valid; otherwise, False.
        """
        if not isinstance(self.file_path, str):
            logger.error(f"File path must be a string, got {type(self.file_path)} with value '{self.file_path}'.")
            return False

        if not exists(self.file_path):
            logger.error(f"File '{self.file_path}' does not exist.")
            return False

        
        if not self.sitk_image_params_dict or not isinstance(self.sitk_image_params_dict, dict):
            logger.error(f"Image parameters must be provided as a non-empty dictionary. Received type: '{type(self.sitk_image_params_dict)}' with value: '{self.sitk_image_params_dict}'.")
            return False
        
        # Check that all keys are strings and all values are dicts with keys "slices", "rows", "cols", "origin", "spacing", "direction"
        for key, value in self.sitk_image_params_dict.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                logger.error(f"Image parameters must have string keys and dictionary values. Got key type {type(key)} and value type {type(value)}.")
                return False
            required_keys = {"slices", "rows", "cols", "origin", "spacing", "direction"}
            if not required_keys.issubset(value.keys()):
                logger.error(f"Image parameters dictionary must include keys: 'slices', 'rows', 'cols', 'origin', 'spacing', 'direction'. Found keys: {value.keys()}.")
                return False
        
        if not self.ss_mgr:
            logger.error("Shared state manager not provided.")
            return False
        
        return True
    
    def _read_and_validate_dataset(self) -> bool:
        """
        Read and validate the DICOM dataset.

        Returns:
            True if the dataset is valid; otherwise, False.
        """
        ds = read_dcm_file(self.file_path, to_json_dict=True)
        if not ds:
            logger.error(f"Could not read DICOM file '{self.file_path}'.")
            return False

        if self._should_exit():
            return False

        self._extract_structure_set_info(ds)
        if not self.rtstruct_info_dict.get("ReferencedSeriesInstanceUID"):
            logger.error(f"Referenced Series Instance UID not found in '{self.file_path}'.")
            return False

        if self.rtstruct_info_dict["ReferencedSeriesInstanceUID"] not in self.sitk_image_params_dict:
            logger.error(f"Referenced Series Instance UID '{self.rtstruct_info_dict['ReferencedSeriesInstanceUID']}' not found in image parameters.")
            return False

        self._extract_roi_info(ds)
        if not self.roi_info_dicts:
            logger.error(f"No ROI contour data found in '{self.file_path}'.")
            return False

        return True
    
    def _extract_structure_set_info(self, ds: Dict[str, Any]) -> None:
        """Extract high-level structure set information from the dataset."""
        desired_tags = ["30060002", "30060004", "30060008", "30060009"]
        self.rtstruct_info_dict = {
            safe_keyword_for_tag(tag): get_dict_tag_values(ds, tag) for tag in desired_tags
        }
        self._get_referenced_series_instance_uid(ds)
        self.rtstruct_info_dict["list_roi_sitk"] = []
    
    def _get_referenced_series_instance_uid(self, ds: Dict[str, Any]) -> None:
        """Extract the Referenced Series Instance UID from the dataset."""
        ref_frame_seq = get_dict_tag_values(ds, "30060010")
        ref_siuid: Optional[str] = None
        if ref_frame_seq:
            for frame_item in ref_frame_seq:
                study_seq = get_dict_tag_values(frame_item, "30060012")
                if not study_seq:
                    continue
                for study_item in study_seq:
                    series_seq = get_dict_tag_values(study_item, "30060014")
                    if not series_seq:
                        continue
                    for series_item in series_seq:
                        read_siuid = get_dict_tag_values(series_item, "0020000E")
                        if read_siuid:
                            if ref_siuid is None:
                                ref_siuid = read_siuid
                            elif ref_siuid != read_siuid:
                                logger.warning(f"Multiple series instance UIDs found; using {ref_siuid} and ignoring {read_siuid}.")
        self.rtstruct_info_dict["ReferencedSeriesInstanceUID"] = ref_siuid
    
    def _extract_roi_info(self, ds: Dict[str, Any]) -> None:
        """Extract ROI and contour data from the dataset."""
        structure_set_roi_seq = get_dict_tag_values(ds, "30060020")
        roi_contour_seq = get_dict_tag_values(ds, "30060039")
        rt_roi_obs_seq = get_dict_tag_values(ds, "30060080")
        roi_info_temp: Dict[Any, Any] = {}

        for roi_item in structure_set_roi_seq or []:
            if self._should_exit():
                return
            roi_number = get_dict_tag_values(roi_item, "30060022")
            roi_name = get_dict_tag_values(roi_item, "30060026")
            roi_info_temp[roi_number] = {
                "roi_number": roi_number,
                "roi_name": roi_name,
                "contour_data": [],
                "roi_display_color": [randint(0, 255) for _ in range(3)],
                "rt_roi_interpreted_type": None,
                "roi_physical_properties": [],
                "material_id": None,
            }
        
        for contour_item in roi_contour_seq or []:
            if self._should_exit():
                return
            referenced_roi_number = get_dict_tag_values(contour_item, "30060084")
            if referenced_roi_number not in roi_info_temp:
                continue
            contour_sequence = get_dict_tag_values(contour_item, "30060040")
            for cs_item in contour_sequence or []:
                contour_dict = {
                    "contour_geometric_type": get_dict_tag_values(cs_item, "30060042"),
                    "number_of_contour_points": get_dict_tag_values(cs_item, "30060046"),
                    "contour_data": get_dict_tag_values(cs_item, "30060050"),
                }
                if contour_dict["contour_data"]:
                    roi_info_temp[referenced_roi_number]["contour_data"].append(contour_dict)
            roi_disp_color = get_dict_tag_values(contour_item, "3006002A")
            if roi_disp_color and isinstance(roi_disp_color, list) and len(roi_disp_color) == 3:
                roi_info_temp[referenced_roi_number]["roi_display_color"] = [round(min(max(x, 0), 255)) for x in roi_disp_color]

        for obs_item in rt_roi_obs_seq or []:
            if self._should_exit():
                return
            referenced_roi_number = get_dict_tag_values(obs_item, "30060084")
            if referenced_roi_number not in roi_info_temp:
                continue
            roi_info_temp[referenced_roi_number]["rt_roi_interpreted_type"] = get_dict_tag_values(obs_item, "300600A4")
            roi_info_temp[referenced_roi_number]["material_id"] = get_dict_tag_values(obs_item, "300A00E1")
            roi_phys_props_seq = get_dict_tag_values(obs_item, "300600B0")
            for prop_item in roi_phys_props_seq or []:
                prop = {
                    "roi_physical_property": get_dict_tag_values(prop_item, "300600B2"),
                    "roi_physical_property_value": get_dict_tag_values(prop_item, "300600B4"),
                }
                roi_info_temp[referenced_roi_number]["roi_physical_properties"].append(prop)

        self.roi_info_dicts = {k: v for k, v in roi_info_temp.items() if v["contour_data"]}
    
    def _build_sitk_masks(self) -> bool:
        """
        Build binary masks for each ROI using the contour data.

        Returns:
            True if at least one mask is built successfully; otherwise, False.
        """
        series_uid = self.rtstruct_info_dict["ReferencedSeriesInstanceUID"]
        sitk_image_params = self.sitk_image_params_dict[series_uid]
        tg_263_names = self.conf_mgr.get_tg_263_names(ready_for_dpg=True)
        organ_match_dict = self.conf_mgr.get_organ_matching_dict()
        unmatched_organ_name = self.conf_mgr.get_unmatched_organ_name()

        self.ss_mgr.startup_executor(use_process_pool=True)
        if self._should_exit():
            return False

        futures: List[Future] = [
            future for roi_info_dict in self.roi_info_dicts.values() if (
                future := self.ss_mgr.submit_executor_action(
                    build_single_mask, roi_info_dict, sitk_image_params, tg_263_names, organ_match_dict, unmatched_organ_name
                )
            ) is not None
        ]
        
        masks: List[sitk.Image] = []
        for future in as_completed(futures):
            if self._should_exit():
                break
            try:
                result = future.result()
                if result is not None:
                    masks.append(result)
            except Exception as e:
                logger.error(f"Failed to build an ROI mask." + get_traceback(e))
            finally:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
        
        self.ss_mgr.shutdown_executor()
        if self._should_exit():
            return False

        self.rtstruct_info_dict["list_roi_sitk"].extend(masks)
        if not self.rtstruct_info_dict["list_roi_sitk"]:
            logger.error(f"No valid masks built from {self.file_path}.")
            return False
        return True
    
    def _get_unique_roi_name(self, roi_name: str) -> str:
        """
        Generate a unique ROI name by appending an index if needed.

        Args:
            roi_name: The proposed ROI name.

        Returns:
            A unique ROI name.
        """
        existing_names = [
            mask.GetMetaData('current_roi_name') for mask in self.rtstruct_info_dict["list_roi_sitk"]
        ]
        if roi_name not in existing_names:
            return roi_name
        
        idx = 1
        unique_name = f"{roi_name}_{idx}"
        while unique_name in existing_names:
            idx += 1
            unique_name = f"{roi_name}_{idx}"
        return unique_name
    
    def build_rtstruct_info_dict(self) -> Optional[Dict[str, Any]]:
        """
        Build the RT Structure Set dictionary from the DICOM dataset.

        Returns:
            The constructed dictionary if successful; otherwise, None.
        """
        if self._should_exit() or not self._validate_inputs():
            return None
        if self._should_exit() or not self._read_and_validate_dataset():
            return None
        if self._should_exit() or not self._build_sitk_masks():
            return None
        return self.rtstruct_info_dict

