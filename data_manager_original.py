from __future__ import annotations


import gc
import json
import weakref
import logging
from os.path import exists
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union, Optional


import cv2
import numpy as np
import SimpleITK as sitk
from scipy.ndimage import center_of_mass


from mdh_app.data_builders.ImageBuilder import ImageBuilder
from mdh_app.data_builders.RTStructBuilder import RTStructBuilder
from mdh_app.data_builders.RTPlanBuilder import RTPlanBuilder
from mdh_app.data_builders.RTDoseBuilder import RTDoseBuilder
from mdh_app.utils.general_utils import get_traceback, weakref_nested_structure
from mdh_app.utils.sitk_utils import (
    sitk_resample_to_reference, resample_sitk_data_with_params, sitk_to_array, 
    get_sitk_roi_display_color, get_orientation_labels
)


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


class DataManager:
    """Manages RT data loading and processing using SimpleITK."""

    def __init__(self, conf_mgr: ConfigManager, ss_mgr: SharedStateManager) -> None:
        """Initialize data manager with configuration and state managers."""
        self.conf_mgr = conf_mgr
        self.ss_mgr = ss_mgr
        self.initialize_data()
    
    def initialize_data(self) -> None:
        """Initialize data structures and cache."""
        self._patient_objectives_dict: Dict[str, Any] = {}
        self._sitk_images_params: Dict[str, Any] = {}
        self._loaded_data_dict: Dict[str, Dict[Any, Any]] = {
            "image": {},
            "rtstruct": {},
            "rtdose": {},
            "rtplan": {}
        }
        self.initialize_cache()

    def initialize_cache(self) -> None:
        """Initialize temporary data cache."""
        self._cached_numpy_data: Dict[Any, np.ndarray] = {}
        self._cached_rois_sitk: Dict[Any, weakref.ReferenceType] = {}
        self._cached_numpy_dose_sum: Optional[np.ndarray] = None
        self._cached_sitk_reference: Optional[sitk.Image] = None
        self._cached_texture_param_dict: Dict[str, Any] = {}

    def clear_data(self) -> None:
        """Clear all loaded data and trigger garbage collection."""
        self._patient_objectives_dict.clear()
        self._sitk_images_params.clear()
        for key in self._loaded_data_dict:
            self._loaded_data_dict[key].clear()
        self.clear_cache()
        gc.collect()

    def clear_cache(self) -> None:
        """Clear all cached temporary data."""
        self._cached_numpy_data.clear()
        self._cached_rois_sitk.clear()
        self._cached_numpy_dose_sum = None
        self._cached_sitk_reference = None
        self._cached_texture_param_dict.clear()
    
    def load_all_dicom_data(self, rt_links_data_dict: Dict[str, List[Any]], patient_id: str) -> None:
        """Load all DICOM data based on provided links."""
        for modality, tasks in rt_links_data_dict.items():
            for task in tasks:
                if self.ss_mgr.cleanup_event.is_set() or self.ss_mgr.shutdown_event.is_set():
                    return
                if modality == "IMAGE":
                    self.load_sitk_image(*task)
                elif modality == "RTSTRUCT":
                    self.load_sitk_rtstruct(*task)
                elif modality == "RTPLAN":
                    self.load_rtplan(*task)
                elif modality == "RTDOSE":
                    self.load_sitk_rtdose(*task)
                else:
                    logger.error(f"Unsupported modality '{modality}' encountered. Skipping load.")
        self.clear_cache()
        if not self.check_if_data_loaded("any"):
            logger.error("No data was loaded. Please try again.")
            return
        self.load_rtstruct_goals(patient_id)
        logger.info("Finished loading selected SITK data.")
    
    def load_sitk_image(self, modality: str, series_instance_uid: str, file_paths: List[str]) -> None:
        """Load IMAGE and update internal data dictionary."""
        if (
            modality in self._loaded_data_dict["image"] and
            series_instance_uid in self._loaded_data_dict["image"][modality]
        ):
            logger.error(f"Failed to load {modality} with SeriesInstanceUID '{series_instance_uid}' as it already exists.")
            return

        logger.info(f"Reading {modality} with SeriesInstanceUID '{series_instance_uid}' from files: [{file_paths[0]}, ...]")
        sitk_image = ImageBuilder(file_paths, self.ss_mgr, series_instance_uid).build_sitk_image()
        if sitk_image is None:
            return

        if modality not in self._loaded_data_dict["image"]:
            self._loaded_data_dict["image"][modality] = {}
        self._loaded_data_dict["image"][modality][series_instance_uid] = sitk_image
        self._sitk_images_params[series_instance_uid] = {
            "origin": sitk_image.GetOrigin(),
            "spacing": sitk_image.GetSpacing(),
            "direction": sitk_image.GetDirection(),
            "cols": sitk_image.GetSize()[0],
            "rows": sitk_image.GetSize()[1],
            "slices": sitk_image.GetSize()[2],
        }
        logger.info(
            f"Loaded {modality} with SeriesInstanceUID '{series_instance_uid}' "
            f"with origin {sitk_image.GetOrigin()}, direction {sitk_image.GetDirection()}, "
            f"spacing {sitk_image.GetSpacing()}, size {sitk_image.GetSize()}."
        )
    
    def load_sitk_rtstruct(self, modality: str, sop_instance_uid: str, file_path: str) -> None:
        """Load RTSTRUCT and update internal data dictionary."""
        if sop_instance_uid in self._loaded_data_dict["rtstruct"]:
            logger.error(f"Failed to load {modality} with SOPInstanceUID '{sop_instance_uid}' as it already exists.")
            return

        logger.info(f"Reading {modality} with SOPInstanceUID '{sop_instance_uid}' from file '{file_path}'.")
        rtstruct_info_dict = RTStructBuilder(file_path, self._sitk_images_params, self.ss_mgr, self.conf_mgr).build_rtstruct_info_dict()
        if not rtstruct_info_dict:
            logger.error(f"Unable to build info for RTSTRUCT with SOPInstanceUID '{sop_instance_uid}'.")
            return

        self._loaded_data_dict["rtstruct"][sop_instance_uid] = rtstruct_info_dict
        logger.info(f"Loaded {modality} with SOPInstanceUID '{sop_instance_uid}'.")
    
    def load_rtplan(self, modality: str, sop_instance_uid: str, file_path: str) -> None:
        """Load RTPLAN and update internal data dictionary."""
        if sop_instance_uid in self._loaded_data_dict["rtplan"]:
            logger.error(f"Failed to load RTPLAN with SOPInstanceUID '{sop_instance_uid}' as it already exists.")
            return

        logger.info(f"Reading {modality} with SOPInstanceUID '{sop_instance_uid}' from file '{file_path}'.")
        rt_plan_info_dict = RTPlanBuilder(file_path, self.ss_mgr, read_beam_cp_data=True).build_rtplan_info_dict()
        if not rt_plan_info_dict:
            return

        # rt_plan_info_dict keys: rt_plan_label, rt_plan_name, rt_plan_description, rt_plan_date, rt_plan_time, approval_status, 
        #       review_date, review_time, reviewer_name, target_prescription_dose_cgy, number_of_fractions_planned, 
        #       number_of_beams, patient_position, setup_technique, beam_dict
        self._loaded_data_dict["rtplan"][sop_instance_uid] = rt_plan_info_dict
        temp_dict = {
            k: v if k != "beam_dict" else f"Beam data for {len(v)} beams (data truncated for printing)"
            for k, v in rt_plan_info_dict.items()
        }
        logger.info(f"Loaded {modality} with SOPInstanceUID '{sop_instance_uid}'. RT Plan details: {temp_dict}")
    
    def load_sitk_rtdose(self, modality: str, sop_instance_uid: str, file_path: str) -> None:
        """Load RTDOSE and update internal data dictionary."""
        logger.info(f"Reading {modality} with SOPInstanceUID '{sop_instance_uid}' from file '{file_path}'.")
        rt_dose_info_dict = RTDoseBuilder(file_path, self.ss_mgr).build_rtdose_info_dict()
        if not rt_dose_info_dict:
            return

        dose_summation_type: str = rt_dose_info_dict["dose_summation_type"]
        if dose_summation_type.upper() not in ["PLAN", "BEAM"]:
            logger.error(
                f"Unsupported dose summation type '{dose_summation_type}' for {modality} with SOPInstanceUID '{sop_instance_uid}'."
            )
            return

        referenced_sop_instance_uid: str = rt_dose_info_dict["referenced_sop_instance_uid"]
        if referenced_sop_instance_uid not in self._loaded_data_dict["rtdose"]:
            self._loaded_data_dict["rtdose"][referenced_sop_instance_uid] = {
                "plan_dose": {},
                "beam_dose": {},
                "beams_composite": None,
            }
        curr_dict_ref = self._loaded_data_dict["rtdose"][referenced_sop_instance_uid]

        if dose_summation_type.upper() == "PLAN":
            if sop_instance_uid in curr_dict_ref["plan_dose"]:
                logger.error(
                    f"RTDOSE for PLAN with SOPInstanceUID '{sop_instance_uid}' under RTPLAN '{referenced_sop_instance_uid}' already exists."
                )
                return
            curr_dict_ref["plan_dose"][sop_instance_uid] = rt_dose_info_dict["sitk_dose"]

        elif dose_summation_type.upper() == "BEAM":
            if sop_instance_uid in curr_dict_ref["beam_dose"]:
                logger.error(
                    f"RTDOSE for BEAM with SOPInstanceUID '{sop_instance_uid}' under RTPLAN '{referenced_sop_instance_uid}' already exists."
                )
                return
            curr_dict_ref["beam_dose"][sop_instance_uid] = rt_dose_info_dict["sitk_dose"]
            if curr_dict_ref["beams_composite"] is None:
                curr_dict_ref["beams_composite"] = sitk_resample_to_reference(
                    rt_dose_info_dict["sitk_dose"],
                    rt_dose_info_dict["sitk_dose"],
                    interpolator=sitk.sitkLinear,
                    default_pixel_val_outside_image=0.0
                )
            else:
                sitk_rtdose = sitk_resample_to_reference(
                    rt_dose_info_dict["sitk_dose"],
                    curr_dict_ref["beams_composite"],
                    interpolator=sitk.sitkLinear,
                    default_pixel_val_outside_image=0.0
                )
                curr_dict_ref["beams_composite"] = sitk.Add(curr_dict_ref["beams_composite"], sitk_rtdose)
            for key in rt_dose_info_dict["sitk_dose"].GetMetaDataKeys():
                curr_dict_ref["beams_composite"].SetMetaData(key, rt_dose_info_dict["sitk_dose"].GetMetaData(key))
            curr_dict_ref["beams_composite"].SetMetaData("referenced_beam_number", "composite")

        logger.info(
            f"Loaded {dose_summation_type} {modality} with SOPInstanceUID '{sop_instance_uid}' "
            f"and referenced RTPLAN SOPInstanceUID '{referenced_sop_instance_uid}'."
        )
    
    def load_rtstruct_goals(self, patient_id: str) -> None:
        """Load and apply RTSTRUCT goals from JSON file."""
        if not self._loaded_data_dict["rtstruct"]:
            return

        if not patient_id:
            logger.error("No patient ID provided; cannot update RTSTRUCT with goals.")
            return

        objectives_fpath = self.conf_mgr.get_objectives_filepath()
        if not objectives_fpath or not objectives_fpath.endswith(".json") or not exists(objectives_fpath):
            logger.error(f"Objectives JSON file not found at location: {objectives_fpath}. Cannot update RTSTRUCT with goals.")
            return

        with open(objectives_fpath, 'rt') as file:
            patient_objectives = json.load(file).get(patient_id, {})
        if not patient_objectives:
            logger.error(f"No objectives found for patient ID '{patient_id}' in the JSON file.")
            return
        
        self._patient_objectives_dict.update(patient_objectives)
        
        # Find relevant objectives for the patient's RTSTRUCT & RTPLAN
        matched_objectives: Dict[str, Any] = {}
        for rt_struct_info_dict in self._loaded_data_dict["rtstruct"].values():
            if rt_struct_info_dict.get("StructureSetLabel"):
                logger.info(f"Checking objectives for RTSTRUCT with label: {rt_struct_info_dict['StructureSetLabel']} ...")
                structure_set_objectives = self._patient_objectives_dict.get("StructureSetId", {}).get(
                    rt_struct_info_dict["StructureSetLabel"], {}
                )
                if structure_set_objectives:
                    matched_objectives.update(structure_set_objectives)
        for rt_plan_info_dict in self._loaded_data_dict["rtplan"].values():
            if rt_plan_info_dict.get("rt_plan_label"):
                logger.info(f"Checking objectives for RTPLAN with label: {rt_plan_info_dict['rt_plan_label']} ...")
                plan_objectives = self._patient_objectives_dict.get("PlanId", {}).get(
                    rt_plan_info_dict["rt_plan_label"], {}
                )
                if plan_objectives:
                    matched_objectives.update(plan_objectives)
        if not matched_objectives:
            logger.error("No objectives found for the patient in the JSON file; cannot update RTSTRUCT with goals.")
            return
        
        # Add ROI goals as SITK metadata
        for sopiuid, rt_struct_info_dict in self._loaded_data_dict["rtstruct"].items():
            for roi_sitk in rt_struct_info_dict["list_roi_sitk"]:
                if roi_sitk is None:
                    continue
                original_roi_name = roi_sitk.GetMetaData("original_roi_name")
                current_struct_goals = json.loads(roi_sitk.GetMetaData("roi_goals"))
                found_struct_goals = matched_objectives.get(original_roi_name, {}).get("Goals")
                if not found_struct_goals:
                    for obj_struct, obj_dict in matched_objectives.items():
                        if obj_struct == original_roi_name or original_roi_name in obj_dict.get("ManualStructNames", []):
                            found_struct_goals = obj_dict.get("Goals")
                            break
                if not found_struct_goals:
                    continue
                current_struct_goals.update(found_struct_goals)
                roi_sitk.SetMetaData("roi_goals", json.dumps(current_struct_goals))
            
            # Log updated goals for the RTSTRUCT
            updated_goals = [
                (roi_sitk.GetMetaData("current_roi_name"), json.loads(roi_sitk.GetMetaData("roi_goals")))
                for roi_sitk in rt_struct_info_dict["list_roi_sitk"] if roi_sitk.GetMetaData("roi_goals")
            ]
            logger.info(f"Updated goals for RTSTRUCT (SOPInstanceUID: {sopiuid}): {updated_goals}")
    
    def check_if_data_loaded(self, modality_key: str = "any") -> bool:
        """Check whether data has been loaded for specified modality."""
        if modality_key == "any":
            return any(self._loaded_data_dict.values())
        if modality_key == "all":
            return all(self._loaded_data_dict.values())
        valid_keys = {"image", "rtstruct", "rtplan", "rtdose"}
        if modality_key not in valid_keys:
            logger.error(f"Unsupported modality key '{modality_key}'. Expected one of {valid_keys}.")
            return False
        return bool(self._loaded_data_dict.get(modality_key))
    
    def return_list_of_all_original_roi_names(self, match_criteria: Optional[str] = None) -> List[str]:
        """
        Retrieve a list of all original (unmodified) ROI names, optionally filtered by criteria.

        Args:
            match_criteria: Optional substring to filter ROI names.

        Returns:
            A list of matching ROI names.
        """
        if not (isinstance(match_criteria, str) or match_criteria is None):
            logger.error(f"Invalid match criteria provided: {match_criteria}. Expected a string or None.")
            return []
        # Find all original ROI names
        roi_names: List[str] = []
        for rt_struct_info_dict in self._loaded_data_dict["rtstruct"].values():
            for roi_sitk in rt_struct_info_dict["list_roi_sitk"]:
                if roi_sitk is None:
                    continue
                original_roi_name = roi_sitk.GetMetaData("original_roi_name")
                if not original_roi_name:
                    continue
                # Add the ROI name if there are no match criteria, or if the criteria is found in the ROI name
                if not match_criteria or match_criteria.lower() in original_roi_name.lower():
                    roi_names.append(original_roi_name)
        return roi_names
    
    def return_data_from_modality(self, modality_key: str) -> Optional[Any]:
        """
        Retrieve loaded data for a specified modality as a nested structure of weak references.

        Args:
            modality_key: One of 'image', 'rtstruct', 'rtplan', or 'rtdose'.

        Returns:
            A dictionary of weak references to the data, or None if the key is invalid.
        """
        valid_keys = {"image", "rtstruct", "rtplan", "rtdose"}
        if modality_key not in valid_keys:
            logger.error(f"Unsupported modality key '{modality_key}'. Expected one of: {valid_keys}.")
            return None
        return weakref_nested_structure(self._loaded_data_dict[modality_key])
    
    def return_sitk_reference_param(self, param: str) -> Optional[Any]:
        """
        Retrieve a specified parameter from the cached SimpleITK reference image.

        Args:
            param: Parameter to retrieve. Options: 'origin', 'spacing', 'direction', 'size',
                   'original_spacing', 'original_size', 'original_direction'.

        Returns:
            The parameter value or None if invalid or unavailable.
        """
        valid_params = {"origin", "spacing", "direction", "size", "original_spacing", "original_size", "original_direction"}
        if param not in valid_params:
            logger.error(f"Unsupported parameter '{param}'. Expected one of: {valid_params}.")
            return None
        if self._cached_sitk_reference is None:
            return None
        if param == "origin":
            return self._cached_sitk_reference.GetOrigin()
        if param == "spacing":
            return self._cached_sitk_reference.GetSpacing()
        if param == "direction":
            return self._cached_sitk_reference.GetDirection()
        if param == "size":
            return self._cached_sitk_reference.GetSize()
        if param == "original_spacing":
            return tuple(map(float, self._cached_sitk_reference.GetMetaData("original_spacing").strip('[]()').split(', ')))
        if param == "original_size":
            return tuple(map(int, self._cached_sitk_reference.GetMetaData("original_size").strip('[]()').split(', ')))
        if param == "original_direction":
            return tuple(map(float, self._cached_sitk_reference.GetMetaData("original_direction").strip('[]()').split(', ')))
        return None
    
    def remove_sitk_roi_from_rtstruct(self, keys: Union[List[Union[str, int]], Tuple[Union[str, int], ...], set]) -> None:
        """
        Remove an ROI from the specified RTSTRUCT.

        Args:
            keys: A sequence containing at least four keys in the order:
                  ['rtstruct', SOPInstanceUID, 'list_roi_sitk', index].
        """
        if not (isinstance(keys, (tuple, list, set)) and all(isinstance(key, (str, int)) for key in keys)):
            logger.error(f"Keys must be a sequence of strings or integers. Received: {keys}.")
            return
        if len(keys) < 4:
            logger.error(f"Keys must contain at least four elements. Received: {keys}.")
            return
        if keys[0] != "rtstruct":
            logger.error(f"First key must be 'rtstruct'; received: {keys[0]}.")
            return
        if keys[1] not in self._loaded_data_dict["rtstruct"]:
            logger.error(f"SOPInstanceUID '{keys[1]}' not found in RTSTRUCT data.")
            return
        if keys[2] != "list_roi_sitk" or keys[2] not in self._loaded_data_dict["rtstruct"][keys[1]]:
            logger.error(f"ROI list not found in RTSTRUCT for key: {keys[2]}.")
            return
        self._loaded_data_dict["rtstruct"][keys[1]][keys[2]][keys[3]] = None
        logger.info(f"ROI at index {keys[3]} removed from RTSTRUCT with SOPInstanceUID '{keys[1]}'.")
    
    def update_active_data(self, load_data: bool, display_data_keys: Union[List[Union[str, int]], Tuple[Union[str, int], ...], set]) -> None:
        """
        Update active display data based on the specified keys.

        Args:
            load_data: True to load data; False to remove.
            display_data_keys: Sequence of keys specifying the data to update.
        """
        if not isinstance(load_data, bool):
            logger.error(f"Load data flag must be boolean. Received: {load_data}.")
            return
        if not (isinstance(display_data_keys, (tuple, list, set)) and all(isinstance(key, (str, int)) for key in display_data_keys)):
            logger.error(f"Display data keys must be a sequence of strings or integers. Received: {display_data_keys}.")
            return
        if len(display_data_keys) < 2:
            logger.error(f"Display data keys must contain at least two elements. Received: {display_data_keys}.")
            return

        # Handle the case where all data of a specific type should be loaded or removed
        if display_data_keys[-1] == "all":
            # Get to the dictionary level where the data is stored
            current_dict = self._loaded_data_dict
            for key in display_data_keys[:-1]:
                current_dict = current_dict.setdefault(key, {})
            # Get the actual keys to load or remove. We enumerate in case the current dictionary is not actually a dictionary but a list (ex: ROIs)
            real_keys = (
                [display_data_keys[:-1] + (key,) if isinstance(current_dict, dict) else display_data_keys[:-1] + (i,)]
                for i, key in enumerate(current_dict)
            )
            for real_ddkey in [item for sublist in real_keys for item in sublist]:
                self.update_active_data(load_data, real_ddkey)
            return

        # Check if the data is already loaded
        if load_data and display_data_keys in self._cached_numpy_data:
            return

        # Clear cache
        if not load_data:
            self._cached_numpy_data.pop(display_data_keys, None)
            self._cached_rois_sitk.pop(display_data_keys, None)
        # Load data
        else:
            current_dict = self._loaded_data_dict
            for key in display_data_keys[:-1]:
                current_dict = current_dict.setdefault(key, {})
            final_key = display_data_keys[-1]
            sitk_data = current_dict[final_key]
            if sitk_data is not None:
                self._update_cached_sitk_reference(sitk_data)
                if display_data_keys[0] == "rtstruct":
                    self._cached_rois_sitk[display_data_keys] = weakref.ref(sitk_data)
                self._cached_numpy_data[display_data_keys] = self._get_np(sitk_data)
        self.update_cache(display_data_keys)
    
    def _update_cached_sitk_reference(self, sitk_data: sitk.Image) -> None:
        """
        Update the cached reference image using provided SITK data.

        Args:
            sitk_data: A SimpleITK image.
        """
        if self._cached_sitk_reference is None:
            original_voxel_spacing = sitk_data.GetSpacing()
            original_size = sitk_data.GetSize()
            original_direction = sitk_data.GetDirection()
            voxel_spacing = self._cached_texture_param_dict.get("voxel_spacing", sitk_data.GetSpacing())
            rotation = self._cached_texture_param_dict.get("rotation", None)
            flips = self._cached_texture_param_dict.get("flips", None)
            self._cached_sitk_reference = resample_sitk_data_with_params(
                sitk_data=sitk_data,
                set_spacing=voxel_spacing,
                set_rotation=rotation,
                set_flip=flips,
                interpolator=sitk.sitkLinear,
                numpy_output=False,
                numpy_output_dtype=None
            )
            self._cached_sitk_reference.SetMetaData("original_spacing", str(original_voxel_spacing))
            self._cached_sitk_reference.SetMetaData("original_size", str(original_size))
            self._cached_sitk_reference.SetMetaData("original_direction", str(original_direction))
    
    def _resample_sitk_to_cached_reference(self, sitk_data: sitk.Image) -> sitk.Image:
        """
        Resample SITK data to match the cached reference image.

        Args:
            sitk_data: A SimpleITK image.

        Returns:
            The resampled SimpleITK image.
        """
        if self._cached_sitk_reference is None:
            self._update_cached_sitk_reference(sitk_data)
        return sitk_resample_to_reference(
            sitk_data, 
            self._cached_sitk_reference, 
            interpolator=sitk.sitkLinear, 
            default_pixel_val_outside_image=0.0
        )
    
    def _get_np(self, sitk_data: sitk.Image) -> np.ndarray:
        """
        Convert a SimpleITK image to a NumPy array after resampling.

        Args:
            sitk_data: A SimpleITK image.

        Returns:
            The resulting NumPy array.
        """
        resampled = self._resample_sitk_to_cached_reference(sitk_data)
        return sitk_to_array(resampled)
    
    def update_cache(self, display_data_keys: Union[Tuple[Any, ...], List[Any]]) -> None:
        """
        Update the cache based on current active data. If no numpy data is cached, clear the cache.
        For RTDOSE data, compute the dose sum normalized by its maximum.

        Args:
            display_data_keys: Keys identifying the data to update.
        """
        if not self._cached_numpy_data:
            self.clear_cache()
            return

        if display_data_keys[0] == "rtdose":
            npy_dose_keys = [keys for keys in self._cached_numpy_data if keys[0] == "rtdose"]
            if npy_dose_keys:
                dose_sum = np.sum([self._cached_numpy_data[keys] for keys in npy_dose_keys], axis=0)
                self._cached_numpy_dose_sum = dose_sum / (np.max(dose_sum) + 1e-4)
            else:
                self._cached_numpy_dose_sum = None
    
    def return_texture_from_active_data(self, texture_params: Dict[str, Any]) -> np.ndarray:
        """
        Generate and return a flattened texture slice from the cached data based on the given parameters.

        Args:
            texture_params: Dictionary of parameters defining texture properties.

        Returns:
            A 1D NumPy array representing the resized texture slice.
        """
        if not texture_params or not isinstance(texture_params, dict):
            logger.error(f"Texture generation failed: texture parameter dictionary is missing or invalid: {texture_params}")
            return np.zeros(1, dtype=np.float32)

        image_length = texture_params.get("image_length")
        if not image_length or not isinstance(image_length, int):
            logger.error(f"Texture generation failed: 'image_length' is missing or not an integer in {texture_params}")
            return np.zeros(1, dtype=np.float32)

        texture_RGB_size = image_length * image_length * 3

        slicer = texture_params.get("slicer")
        if not slicer or not isinstance(slicer, tuple) or not all(isinstance(s, (slice, int)) for s in slicer):
            logger.error(f"Texture generation failed: 'slicer' is missing or invalid in {texture_params}")
            return np.zeros(texture_RGB_size, dtype=np.float32)

        view_type = texture_params.get("view_type")
        if not view_type or not isinstance(view_type, str) or view_type not in ["axial", "coronal", "sagittal"]:
            logger.error(f"Texture generation failed: 'view_type' is missing or invalid in {texture_params}")
            return np.zeros(texture_RGB_size, dtype=np.float32)
        
        try:
            # Rebuild cache if texture parameters have changed
            if self._check_for_texture_param_changes(texture_params, ignore_keys=["view_type", "slicer", "slices", "xyz_ranges"]):
                cached_keys = list(self._cached_numpy_data.keys())
                self.clear_cache()
                self._cached_texture_param_dict = texture_params
                for display_data_keys in cached_keys:
                    self.update_active_data(True, display_data_keys)

            # Determine base layer shape based on slicer dimensions and create base layer
            shape_RGB = tuple(s.stop - s.start for s in slicer if isinstance(s, slice)) + (3,)
            base_layer = np.zeros(shape_RGB, dtype=np.float32)

            # Blend images, masks, and doses if display alphas are provided
            alphas = texture_params.get("display_alphas")
            if alphas and len(alphas) == 3:
                self._blend_images_RGB(base_layer, slicer, texture_params["image_window_level"], texture_params["image_window_width"], alphas[0])
                self._blend_masks_RGB(base_layer, slicer, texture_params["contour_thickness"], alphas[1])
                self._blend_doses_RGB(base_layer, slicer, texture_params["dose_thresholds"], alphas[2])
            else:
                logger.error(f"Data textures could not be blended: 'display_alphas' are missing or invalid: {alphas}")
            
            # Add crosshairs to the base layer
            self._draw_slice_crosshairs(
                base_layer, 
                texture_params["show_crosshairs"], 
                view_type, 
                texture_params["slices"], 
                texture_params["xyz_ranges"]
            )
            
            # Adjust dimension order based on view type
            if view_type == "coronal":
                base_layer = np.swapaxes(base_layer, 0, 1)
            elif view_type == "sagittal":
                base_layer = np.fliplr(np.swapaxes(base_layer, 0, 1))
            
            # Normalize and clip to [0, 1]
            base_layer = np.clip(base_layer, 0, 255) / 255.0
            
            # Resize to the desired image dimensions
            base_layer = cv2.resize(base_layer, (image_length, image_length), interpolation=cv2.INTER_LINEAR)
            
            # Add orientation labels after resizing to avoid text distortion
            self._draw_orientation_labels(
                base_layer, 
                texture_params["show_orientation_labels"], 
                view_type, 
                texture_params["rotation"], 
                texture_params["flips"]
            )
            
            # Resize to the desired image dimensions and flatten to a 1D texture
            return base_layer.ravel()
        except Exception as e:
            logger.error(f"Failed to generate a texture." + get_traceback(e))
            return np.zeros(texture_RGB_size, dtype=np.float32)
        
    def _check_for_texture_param_changes(
        self, 
        texture_params: Dict[str, Any], 
        ignore_keys: Optional[List[str]] = None
    ) -> bool:
        """
        Determine if the provided texture parameters differ from the cached parameters.

        Args:
            texture_params: The current texture parameters.
            ignore_keys: List of parameter keys to ignore during comparison.

        Returns:
            True if differences are detected; otherwise, False.
        """
        if self._cached_texture_param_dict is None:
            return True
        
        for key, value in texture_params.items():
            if ignore_keys and key in ignore_keys:
                continue
            cached_value = self._cached_texture_param_dict.get(key)
            if isinstance(value, (list, tuple, set)):
                if any(v != cv for v, cv in zip(value, cached_value)):
                    return True
            elif value != cached_value:
                return True

        return False
       
    def _blend_layers(self, base_layer: np.ndarray, overlay: np.ndarray, alpha: float) -> None:
        """
        Blend an overlay onto the base layer using the specified alpha value.

        This function modifies the base_layer in place.

        Args:
            base_layer: The base image layer.
            overlay: The overlay image layer.
            alpha: The blending alpha value (0-100).
        """
        overlay_indices = overlay.any(axis=-1)
        alpha_ratio = alpha / 100.0
        base_layer[overlay_indices] = (
            base_layer[overlay_indices] * (1 - alpha_ratio) +
            overlay[overlay_indices].astype(np.float32) * alpha_ratio
        )
    
    def _blend_images_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        image_window_level: float,
        image_window_width: float,
        alpha: float
    ) -> None:
        """
        Blend active image slices into the base layer using specified window level, window width, and blending alpha.

        Args:
            base_layer: The base layer for image blending.
            slicer: A tuple defining the slicing of the image.
            image_window_level: The window level value.
            image_window_width: The window width value.
            alpha: The blending alpha (0-100).
        """
        numpy_images = self.find_active_npy_images()
        if not numpy_images:
            return

        if image_window_level is None or image_window_width is None or alpha is None:
            logger.error(f"Image blending failed: Missing parameters (level: {image_window_level}, width: {image_window_width}, alpha: {alpha}).")
            return

        lower_bound = image_window_level - (image_window_width / 2)
        upper_bound = image_window_level + (image_window_width / 2)

        image_list = []
        for numpy_image in numpy_images:
            image_slice = ((np.clip(numpy_image[slicer], lower_bound, upper_bound) - lower_bound) /
                        ((upper_bound - lower_bound) + 1e-4) * 255)
            image_list.append(np.stack((image_slice,) * 3, axis=-1))

        num_images = len(image_list)
        composite_image = np.sum([img.astype(np.float32) for img in image_list if img is not None], axis=0)
        composite_image /= num_images  # Average the images

        self._blend_layers(base_layer, composite_image, alpha)
    
    def _blend_masks_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        contour_thickness: int,
        alpha: float
    ) -> None:
        """
        Blend mask overlays into the base layer using specified contour thickness and blending alpha.

        Args:
            base_layer: The base image layer.
            slicer: A tuple defining the slice of the mask.
            contour_thickness: The thickness of the mask contour.
            alpha: The blending alpha (0-100).
        """
        if not self._cached_rois_sitk:
            return

        if not contour_thickness or not alpha:
            logger.error(f"Mask blending failed: 'contour_thickness' ({contour_thickness}) or 'alpha' ({alpha}) is missing or invalid.")
            return

        # If contour_thickness is 0, fill the contour (0 has no utility)
        if contour_thickness == 0:
            contour_thickness = -1

        composite_masks_RGB = np.zeros_like(base_layer, dtype=np.uint8)
        
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_keys = list(self._cached_rois_sitk.keys())
        for roi_keys in cached_keys:
            if roi_keys not in self._cached_rois_sitk:
                continue
            roi_sitk_ref = self._cached_rois_sitk[roi_keys]
            if roi_keys not in self._cached_numpy_data:
                continue
            roi_display_color = get_sitk_roi_display_color(roi_sitk_ref())
            contours, _ = cv2.findContours(
                image=self._cached_numpy_data[roi_keys][slicer].astype(np.uint8),
                mode=cv2.RETR_EXTERNAL,
                method=cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(
                image=composite_masks_RGB,
                contours=contours,
                contourIdx=-1,
                color=roi_display_color,
                thickness=contour_thickness
            )

        self._blend_layers(base_layer, composite_masks_RGB, alpha)
    
    def _dosewash_colormap(self, value_array: np.ndarray) -> np.ndarray:
        """
        Apply a DoseWash colormap to a normalized 2-D dose array.

        Args:
            value_array: A 2-D NumPy array with values normalized to [0, 1].

        Returns:
            A 2-D NumPy array of corresponding RGB values (each in [0, 1]).
        """
        if not isinstance(value_array, np.ndarray) or value_array.ndim != 2:
            raise ValueError(f"Expected a 2-D NumPy array; received type {type(value_array)} with shape {value_array.shape if isinstance(value_array, np.ndarray) else 'N/A'}.")
        if np.min(value_array) < 0 or np.max(value_array) > 1:
            raise ValueError(f"Values must be normalized to [0,1] (min: {np.min(value_array)}, max: {np.max(value_array)}).")

        # Define the colormap in BGR order and normalize to [0, 1]
        base_colors = np.array([
            [0, 0, 90],     # Deep Blue (0%)  
            [0, 15, 180],   # Blue (~10%)  
            [0, 60, 255],   # Bright Blue (~20%)  
            [0, 120, 255],  # Blue-Cyan (~30%)  
            [0, 200, 255],  # Cyan (~40%)  
            [0, 255, 200],  # Cyan-Green (~50%)  
            [50, 255, 100], # Greenish (~55%)  
            [120, 255, 0],  # Green (~60%)  
            [200, 255, 0],  # Yellow-Green (~70%)  
            [255, 255, 0],  # Yellow (~80%)  
            [255, 180, 0],  # Yellow-Orange (~85%)  
            [255, 120, 0],  # Orange (~90%)  
            [255, 50, 0],   # Deep Orange (~95%)  
            [255, 0, 0]     # Red (100%)  
        ])
        base_colors = np.clip(base_colors / 255, 0.0, 1.0)

        # Compute interpolated RGB values
        num_colors = len(base_colors)
        color_idx = value_array * (num_colors - 1)
        lower_idx = np.floor(color_idx).astype(int)
        upper_idx = np.ceil(color_idx).astype(int)
        blend_factor = color_idx - lower_idx

        # Ensure valid indices
        lower_idx = np.clip(lower_idx, 0, num_colors - 1)
        upper_idx = np.clip(upper_idx, 0, num_colors - 1)

        # Get interpolated RGB values
        rgb = (1 - blend_factor)[..., None] * base_colors[lower_idx] + blend_factor[..., None] * base_colors[upper_idx]
        return np.clip(rgb, 0.0, 1.0)
        
    def _blend_doses_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        dose_thresholds: Union[Tuple[float, float], List[float]],
        alpha: float
    ) -> None:
        """
        Blend dose overlays into the base layer using specified dose thresholds and blending alpha.

        Args:
            base_layer: The base image layer.
            slicer: A tuple defining the slice of the dose data.
            dose_thresholds: A tuple or list with lower and upper dose thresholds.
            alpha: The blending alpha (0-100).
        """
        if self._cached_numpy_dose_sum is None:
            return

        if (
            not dose_thresholds or 
            not isinstance(dose_thresholds, (tuple, list)) or
            len(dose_thresholds) != 2 or 
            not alpha
        ):
            logger.error(f"Dose blending failed: 'dose_thresholds' ({dose_thresholds}) or 'alpha' ({alpha}) is missing or invalid.")
            return

        min_threshold_p, max_threshold_p = dose_thresholds
        total_dose_slice = self._cached_numpy_dose_sum[slicer].squeeze()  # 2D slice, values in [0,1]
        cmap_data = self._dosewash_colormap(total_dose_slice)
        cmap_data[(total_dose_slice <= min_threshold_p / 100) | (total_dose_slice >= max_threshold_p / 100)] = 0
        cmap_data = cmap_data[..., :3] * 255

        self._blend_layers(base_layer, cmap_data, alpha)
    
    def _draw_slice_crosshairs(
        self,
        base_layer: np.ndarray,
        show_crosshairs: bool,
        view_type: str,
        slices: Union[Tuple[int, int, int], List[int]],
        xyz_ranges: Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]],
        crosshair_color: int = 150
    ) -> None:
        """
        Draw crosshairs on the base layer at specified slice locations.

        Args:
            base_layer: The image layer on which to draw crosshairs.
            show_crosshairs: Flag indicating whether to display crosshairs.
            view_type: The view type ('axial', 'coronal', or 'sagittal').
            slices: A tuple or list of three integer slice positions.
            xyz_ranges: A tuple of three (min, max) integer pairs defining the spatial ranges.
            crosshair_color: The intensity/color value to use for crosshairs.
        """
        if not show_crosshairs:
            return
        
        if not slices or not isinstance(slices, (list, tuple)) or len(slices) != 3 or not all(isinstance(s, int) for s in slices):
            logger.error(f"Crosshair drawing failed: 'slices' is missing or invalid: {slices}")
            return
        
        if not xyz_ranges or not isinstance(xyz_ranges, (list, tuple)) or len(xyz_ranges) != 3 or not all(
            isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(v, int) for v in r) for r in xyz_ranges
        ):
            logger.error(f"Crosshair drawing failed: 'xyz_ranges' is missing or invalid: {xyz_ranges}")
            return
        
        # Convert absolute slice positions to relative positions within the given ranges
        slices = [s - r[0] for s, r in zip(slices, xyz_ranges)]

        def get_thickness(dim_size: int) -> int:
            """Calculate dynamic thickness: 1 plus an increment for every 500 pixels."""
            return max(1, 1 + (dim_size // 500) * 2)

        if view_type == "axial":
            thickness_x = get_thickness(base_layer.shape[1])
            thickness_y = get_thickness(base_layer.shape[0])
            if 0 <= slices[0] < base_layer.shape[1]:  # Vertical
                base_layer[:, max(0, slices[0] - thickness_x // 2) : min(base_layer.shape[1], slices[0] + thickness_x // 2 + 1), :] = crosshair_color
            if 0 <= slices[1] < base_layer.shape[0]:  # Horizontal
                base_layer[max(0, slices[1] - thickness_y // 2) : min(base_layer.shape[0], slices[1] + thickness_y // 2 + 1), :, :] = crosshair_color
        elif view_type == "coronal":
            thickness_x = get_thickness(base_layer.shape[1])
            thickness_y = get_thickness(base_layer.shape[0])
            if 0 <= slices[2] < base_layer.shape[1]:  # Vertical
                base_layer[:, max(0, slices[2] - thickness_x // 2) : min(base_layer.shape[1], slices[2] + thickness_x // 2 + 1), :] = crosshair_color
            if 0 <= slices[0] < base_layer.shape[0]:  # Horizontal
                base_layer[max(0, slices[0] - thickness_y // 2) : min(base_layer.shape[0], slices[0] + thickness_y // 2 + 1), :, :] = crosshair_color
        elif view_type == "sagittal":
            thickness_x = get_thickness(base_layer.shape[1])
            thickness_y = get_thickness(base_layer.shape[0])
            if 0 <= slices[2] < base_layer.shape[1]:  # Vertical
                base_layer[:, max(0, slices[2] - thickness_x // 2) : min(base_layer.shape[1], slices[2] + thickness_x // 2 + 1), :] = crosshair_color
            if 0 <= slices[1] < base_layer.shape[0]:  # Horizontal
                base_layer[max(0, slices[1] - thickness_y // 2) : min(base_layer.shape[0], slices[1] + thickness_y // 2 + 1), :, :] = crosshair_color
        
    def _draw_orientation_labels(
        self,
        base_layer: np.ndarray,
        show_orientation_labels: bool,
        view_type: str,
        rotation: int,
        flips: List[bool]
    ) -> None:
        """
        Draw orientation labels (L/R, A/P, S/I) on the base image and blend them onto it.

        Args:
            base_layer: The image layer on which to draw labels.
            show_orientation_labels: Whether orientation labels should be drawn.
            view_type: One of 'axial', 'coronal', or 'sagittal'.
            rotation: The rotation angle in degrees.
            flips: A list of booleans indicating flip status for each axis.
        """
        if not show_orientation_labels:
            return

        # Do not draw orientation labels if the image is too small
        h, w = base_layer.shape[:2]
        if h < 50 or w < 50:
            return
        
        dicom_direction = self.return_sitk_reference_param("original_direction") or tuple(np.eye(3).flatten().tolist())
        rotation_angle = int(rotation) or 0
        flips = flips or [False, False, False]
        
        orientation_labels = get_orientation_labels(dicom_direction, rotation_angle, flips)
        if not orientation_labels:
            logger.error(f"Orientation labels are invalid; cannot draw labels.")
            return
        
        # Define label properties
        font = cv2.FONT_HERSHEY_COMPLEX
        font_scale = min(w, h) * 2e-3
        font_thickness = max(1, round(min(w, h) * 1e-3))
        
        text_RGBA = self.conf_mgr.get_orientation_label_color()
        text_RGB = [min(max(round(i), 0), 255) for i in text_RGBA[:3]]
        alpha = min(max(text_RGBA[3] / 2.55, 0), 100)  # Convert 0-255 to 0-100
        
        # Create an overlay for text
        overlay = np.zeros_like(base_layer, dtype=np.uint8)
        
        # Define a small buffer based on image size (1% of width/height)
        buffer_x = max(1, int(0.01 * w))  # At least 1 pixel
        buffer_y = max(1, int(0.01 * h))
        
        # Draw labels on the overlay
        keys_labels = {
            k.lower().strip():str(v).strip() 
            for k, v in orientation_labels.items() 
            if k.lower().strip().startswith(view_type.lower())
        }
        for key_position, label_text in keys_labels.items():
            if label_text:
                text_size = cv2.getTextSize(label_text, font, font_scale, font_thickness)[0]
                
                # Default center alignment
                text_x = round((w - text_size[0]) / 2)  # Center horizontally
                text_y = round((h + text_size[1]) / 2)  # Center vertically
                
                # Snap to the edges
                if key_position.endswith("left"):
                    text_x = buffer_x  # Fully left
                elif key_position.endswith("right"):
                    text_x = w - text_size[0] - buffer_x  # Fully right
                elif key_position.endswith("top"):
                    text_y = text_size[1] + buffer_y  # Fully top
                elif key_position.endswith("bottom"):
                    text_y = h - buffer_y  # Fully bottom
                
                cv2.putText(overlay, label_text, (text_x, text_y), font, font_scale, text_RGB, font_thickness, cv2.LINE_AA)
        
        self._blend_layers(base_layer, overlay, alpha)
    
    def find_active_npy_images(self) -> List[np.ndarray]:
        """
        Retrieve all active IMAGE NumPy arrays from the cache.

        Returns:
            A list of NumPy arrays for active IMAGE data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_img_keys = [keys for keys in self._cached_numpy_data.keys() if keys[0] == "image"]
        return [numpy_data for keys in cached_img_keys if (numpy_data := self._cached_numpy_data.get(keys)) is not None]
    
    def find_active_npy_rois(self) -> List[np.ndarray]:
        """
        Retrieve all active RTSTRUCT NumPy arrays from the cache.

        Returns:
            A list of NumPy arrays for active RTSTRUCT data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_rts_keys = [keys for keys in self._cached_numpy_data.keys() if keys[0] == "rtstruct"]
        return [numpy_data for keys in cached_rts_keys if (numpy_data := self._cached_numpy_data.get(keys)) is not None]
    
    def find_active_npy_doses(self) -> List[np.ndarray]:
        """
        Retrieve all active RTDOSE NumPy arrays from the cache.

        Returns:
            A list of NumPy arrays for active RTDOSE data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_rtd_keys = [keys for keys in self._cached_numpy_data.keys() if keys[0] == "rtdose"]
        return [numpy_data for keys in cached_rtd_keys if (numpy_data := self._cached_numpy_data.get(keys)) is not None]
    
    def return_roi_info_list_at_slice(
        self, 
        slicer: Union[slice, Tuple[Union[slice, int], ...]]
    ) -> List[Tuple[str, str, Tuple[int, int, int]]]:
        """
        Retrieve ROI information at the specified slice.

        Args:
            slicer: A slice or tuple of slices defining the current view.

        Returns:
            A list of tuples containing (ROI number, current ROI name, display color).
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_roi_keys = list(self._cached_rois_sitk.keys())
        return [
            (
                roi_sitk.GetMetaData("roi_number"),
                roi_sitk.GetMetaData("current_roi_name"),
                get_sitk_roi_display_color(roi_sitk)
            )
            for roi_keys in cached_roi_keys
            if (roi_sitk := self._cached_rois_sitk.get(roi_keys, lambda: None)()) 
            is not None and self.check_if_keys_exist(roi_keys, slicer)
        ]
    
    def return_image_value_list_at_slice(
        self, 
        slicer: Union[slice, Tuple[Union[slice, int], ...]]
    ) -> List[np.ndarray]:
        """
        Retrieve image slices from active IMAGE data for the specified view.

        Args:
            slicer: A slice or tuple of slices defining the current view.

        Returns:
            A list of image slices as NumPy arrays.
        """
        return [numpy_image[slicer] for numpy_image in self.find_active_npy_images()]
    
    def return_dose_value_list_at_slice(
        self, 
        slicer: Union[slice, Tuple[Union[slice, int], ...]]
    ) -> List[np.ndarray]:
        """
        Retrieve dose slices from active RTDOSE data for the specified view.

        Args:
            slicer: A slice or tuple of slices defining the current view.

        Returns:
            A list of dose slices as NumPy arrays.
        """
        return [numpy_dose[slicer] for numpy_dose in self.find_active_npy_doses()]
        
    def return_is_any_data_active(self) -> bool:
        """
        Determine if any active data exists in the cache.

        Returns:
            True if active data is present; otherwise, False.
        """
        return bool(self._cached_numpy_data)

    def count_active_data_items(self) -> int:
        """
        Count the total number of active data items in the cache.

        Returns:
            The number of active data items.
        """
        return len(self._cached_numpy_data)
    
    def check_if_keys_exist(
        self,
        keys: Union[Tuple[Union[str, int], ...], List[Union[str, int]]],
        slicer: Optional[Union[slice, Tuple[Union[slice, int], ...]]] = None
    ) -> bool:
        """
        Check if the specified keys exist in the cache and contain nonzero data.

        Args:
            keys: A tuple or list of keys identifying the cached data.
            slicer: Optional slice to inspect a portion of the data.

        Returns:
            True if data exists for the given keys; otherwise, False.
        """
        if slicer is not None:
            return keys in self._cached_numpy_data and np.any(self._cached_numpy_data[keys][slicer])
        if keys not in self._cached_numpy_data:
            self.update_active_data(True, keys)
        return keys in self._cached_numpy_data and np.any(self._cached_numpy_data[keys])

    def return_npy_center_of_mass(
        self, 
        keys: Union[Tuple[Union[str, int], ...], List[Union[str, int]]]
    ) -> Optional[Tuple[int, int, int]]:
        """
        Compute the center of mass of the cached NumPy array identified by the keys.

        Args:
            keys: A tuple or list of keys identifying the NumPy array.

        Returns:
            A tuple (x, y, z) representing the center of mass, or None if data is unavailable.
        """
        if not self.check_if_keys_exist(keys):
            return None

        yxz_com = [round(i) for i in center_of_mass(self._cached_numpy_data[keys])]
        return (yxz_com[1], yxz_com[0], yxz_com[2])
        
    def return_npy_extent_ranges(
        self, 
        keys: Union[Tuple[Union[str, int], ...], List[Union[str, int]]]
    ) -> Optional[Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]], Optional[Tuple[int, int]]]]:
        """
        Compute the extent ranges of nonzero values in the cached NumPy array.

        Args:
            keys: A tuple or list of keys identifying the NumPy array.

        Returns:
            A tuple of (x_range, y_range, z_range), where each range is a tuple (min, max) or None if not available.
        """
        if not self.check_if_keys_exist(keys):
            return None

        extent = np.nonzero(self._cached_numpy_data[keys])
        x_range = (np.min(extent[1]), np.max(extent[1])) if np.any(extent[1]) else None
        y_range = (np.min(extent[0]), np.max(extent[0])) if np.any(extent[0]) else None
        z_range = (np.min(extent[2]), np.max(extent[2])) if np.any(extent[2]) else None
        return (x_range, y_range, z_range)
