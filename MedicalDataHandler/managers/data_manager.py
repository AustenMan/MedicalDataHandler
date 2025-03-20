import gc
import weakref
import os
import cv2
import json
import numpy as np
import SimpleITK as sitk
from scipy.ndimage import center_of_mass
from data_builders.RTImageBuilder import RTImageBuilder
from data_builders.RTStructBuilder import RTStructBuilder
from data_builders.RTPlanBuilder import RTPlanBuilder
from data_builders.RTDoseBuilder import RTDoseBuilder
from utils.general_utils import get_traceback
from utils.sitk_utils import sitk_resample_to_reference, resample_sitk_data_with_params, sitk_to_array, get_sitk_roi_display_color, get_orientation_labels

def weakref_nested_structure(structure):
    """
    Recursively replace objects in a nested structure with weak references where applicable.
    
    Args:
        structure (Any): The input structure (dict, list, tuple, or other objects).
    
    Returns:
        Any: The structure with objects replaced by weak references where possible.
    """
    if isinstance(structure, dict):
        # If it's a dictionary, apply weakref recursively to each value
        return {key: weakref_nested_structure(value) for key, value in structure.items()}
    
    elif isinstance(structure, list):
        # If it's a list, apply weakref recursively to each item
        return [weakref_nested_structure(item) for item in structure]
    
    elif isinstance(structure, tuple):
        # If it's a tuple, apply weakref recursively to each item (and return a tuple)
        return tuple(weakref_nested_structure(item) for item in structure)
    
    # Check if the object supports weak references
    elif hasattr(structure, '__weakref__'):
        # If it's an object that can be weak-referenced, create a weakref
        return weakref.ref(structure)
    
    # For other types (such as int, float, str), return the object itself
    return structure

class DataManager:
    """
    A manager for loading, organizing, and handling RT data (RTIMAGE, RTSTRUCT, RTPLAN, RTDOSE) using SimpleITK.
    
    Attributes:
        config_manager (ConfigManager): The configuration manager instance.
        shared_state_manager (Executor): Manager for shared task execution.
    """
    def __init__(self, config_manager, shared_state_manager):
        """
        Initialize the DataManager.
        
        Args:
            config_manager (ConfigManager): Instance of the configuration manager.
            shared_state_manager (Executor): Instance of the shared state manager.
        """
        self.config_manager = config_manager
        self.shared_state_manager = shared_state_manager
        self.initialize_data()
    
    def initialize_data(self):
        """
        Initialize data storage structures and clear the cache.
        """
        self._patient_objectives_dict = {}
        self._sitk_rtimages_params = {}
        self._loaded_data_dict = {"rtimage": {}, "rtstruct": {}, "rtdose": {}, "rtplan": {}}
        self.initialize_cache()
    
    def initialize_cache(self):
        """
        Initialize the cache for storing temporary data.
        """
        self._cached_numpy_data = {}
        self._cached_rois_sitk = {}
        self._cached_numpy_dose_sum = None
        self._cached_sitk_reference = None
        self._cached_texture_param_dict = {}
    
    def clear_data(self):
        """
        Clear all data and cache, and run garbage collection.
        """
        self._patient_objectives_dict.clear()
        self._sitk_rtimages_params.clear()
        for key in self._loaded_data_dict:
            self._loaded_data_dict[key].clear()
        self.clear_cache()
        gc.collect()
    
    def clear_cache(self):
        """
        Clear the cache of temporary data.
        """
        self._cached_numpy_data.clear()
        self._cached_rois_sitk.clear()
        self._cached_numpy_dose_sum = None
        self._cached_sitk_reference = None
        self._cached_texture_param_dict.clear()
    
    def load_all_dicom_data(self, rt_links_data_dict, patient_id):
        """
        Load all data from DICOMs (RTIMAGE, RTSTRUCT, RTPLAN, RTDOSE) based on provided links and update the data dictionary.
        
        Args:
            rt_links_data_dict (dict): Dictionary containing data links grouped by modality.
            patient_id (str): The ID of the patient.
        """
        for matched_modality, list_of_tasks in rt_links_data_dict.items():
            for task_tuple in list_of_tasks:
                # Check if need to exit
                if (self.shared_state_manager.cleanup_event.is_set() or self.shared_state_manager.shutdown_event.is_set()):
                    return
                if matched_modality == "RTIMAGE":
                    self.load_sitk_image(*task_tuple)
                elif matched_modality == "RTSTRUCT":
                    self.load_sitk_rtstruct(*task_tuple)
                elif matched_modality == "RTPLAN":
                    self.load_rtplan(*task_tuple)
                elif matched_modality == "RTDOSE":
                    self.load_sitk_rtdose(*task_tuple)
                else:
                    print(f"Error: Failed to load data for unknown modality '{matched_modality}'")
        
        self.clear_cache()
        
        if not self.check_if_data_loaded("any"):
            print(f"Error: No data was loaded. Please try again.")
            return
        
        self.load_rtstruct_goals(patient_id)
        
        print("Finished loading selected SITK data.")
    
    def load_sitk_image(self, modality, series_instance_uid, file_paths):
        """
        Load an RTIMAGE and update the data dictionary.
        
        Args:
            modality (str): The modality type (e.g., "RTIMAGE").
            series_instance_uid (str): The SeriesInstanceUID of the RTIMAGE.
            file_paths (list): List of file paths for the RTIMAGE.
        """
        if modality in self._loaded_data_dict["rtimage"] and series_instance_uid in self._loaded_data_dict["rtimage"][modality]:
            print(f"Error in loading {modality} with SeriesInstanceUID '{series_instance_uid}'. {modality} already exists.")
            return
        
        print(f"Reading {modality} with SeriesInstanceUID '{series_instance_uid}' from files: [{file_paths[0]}, ...]")
        
        sitk_rtimage = RTImageBuilder(file_paths, self.shared_state_manager, series_instance_uid).build_sitk_image()
        if sitk_rtimage is None:
            return
        
        if modality not in self._loaded_data_dict["rtimage"]:
            self._loaded_data_dict["rtimage"][modality] = {}
        
        self._loaded_data_dict["rtimage"][modality][series_instance_uid] = sitk_rtimage
        self._sitk_rtimages_params[series_instance_uid] = {"origin": sitk_rtimage.GetOrigin(), "spacing": sitk_rtimage.GetSpacing(), "direction": sitk_rtimage.GetDirection(), "cols": sitk_rtimage.GetSize()[0], "rows": sitk_rtimage.GetSize()[1], "slices": sitk_rtimage.GetSize()[2]}
        
        print(f"Loaded {modality} with SeriesInstanceUID '{series_instance_uid}' and origin: {sitk_rtimage.GetOrigin()}, direction: {sitk_rtimage.GetDirection()}, spacing: {sitk_rtimage.GetSpacing()}, size: {sitk_rtimage.GetSize()}.")
    
    def load_sitk_rtstruct(self, modality, sop_instance_uid, file_path):
        """
        Load an RTSTRUCT and update the data dictionary.
        
        Args:
            modality (str): The modality type (e.g., "RTSTRUCT").
            sop_instance_uid (str): The SOPInstanceUID of the RTSTRUCT.
            file_path (str): The file path for the RTSTRUCT.
        """
        if sop_instance_uid in self._loaded_data_dict["rtstruct"]:
            print(f"Error in loading {modality} with SOPInstanceUID '{sop_instance_uid}'. {modality} already exists.")
            return
        
        print(f"Reading {modality} with SOPInstanceUID '{sop_instance_uid}' from file '{file_path}'.")
        
        rtstruct_info_dict = RTStructBuilder(file_path, self._sitk_rtimages_params, self.shared_state_manager, self.config_manager).build_rtstruct_info_dict()
        if not rtstruct_info_dict:
            print(f"Error in loading SITK RTSTRUCT with SOPInstanceUID '{sop_instance_uid}'. RTSTRUCT info dict could not be built.")
            return
        
        self._loaded_data_dict["rtstruct"][sop_instance_uid] = rtstruct_info_dict
        
        print(f"Loaded {modality} with SOPInstanceUID '{sop_instance_uid}'.")
    
    def load_rtplan(self, modality, sop_instance_uid, file_path):
        """
        Load an RTPLAN and update the data dictionary.
        
        Args:
            modality (str): The modality type (e.g., "RTPLAN").
            sop_instance_uid (str): The SOPInstanceUID of the RTPLAN.
            file_path (str): The file path for the RTPLAN.
        """
        if sop_instance_uid in self._loaded_data_dict["rtplan"]:
            print(f"Error in loading RTPLAN with SOPInstanceUID: {sop_instance_uid}. RTPLAN already exists.")
            return
        
        print(f"Reading {modality} with SOPInstanceUID: {sop_instance_uid} from file: {file_path}.")
        
        rt_plan_info_dict = RTPlanBuilder(file_path, self.shared_state_manager, read_beam_cp_data=True).build_rtplan_info_dict()
        if not rt_plan_info_dict:
            return
        
        # Keys: rt_plan_label, rt_plan_name, rt_plan_description, rt_plan_date, rt_plan_time, approval_status, review_date, review_time, reviewer_name, target_prescription_dose_cgy, number_of_fractions_planned, number_of_beams, patient_position, setup_technique, beam_dict
        self._loaded_data_dict["rtplan"][sop_instance_uid] = rt_plan_info_dict 
        
        temp_dict = {k: v if k not in ["beam_dict"] else f"Beam data found for {len(v)} beams, but the data is truncated for printing" for k, v in rt_plan_info_dict.items()}
        print(f"Loaded {modality} with SOPInstanceUID: {sop_instance_uid}.\n\tRT Plan details: {temp_dict}")
    
    def load_sitk_rtdose(self, modality, sop_instance_uid, file_path):
        """
        Load an RTDOSE and update the data dictionary.
        
        Args:
            modality (str): The modality type (e.g., "RTDOSE").
            sop_instance_uid (str): The SOPInstanceUID of the RTDOSE.
            file_path (str): The file path for the RTDOSE.
        """
        print(f"Reading {modality} with SOPInstanceUID: {sop_instance_uid} from file: {file_path}.")
        
        rt_dose_info_dict = RTDoseBuilder(file_path, self.shared_state_manager).build_rtdose_info_dict()
        if not rt_dose_info_dict:
            return
        
        # Get RTDOSE SummationType
        dose_summation_type = rt_dose_info_dict["dose_summation_type"]
        if dose_summation_type.upper() not in ["PLAN", "BEAM"]:
            print(f"Error in loading {modality} with SOPInstanceUID: {sop_instance_uid}. Unsupported dose summation type: {dose_summation_type}.")
            return
        
        # Get RTPLAN SOPInstanceUID
        referenced_sop_instance_uid = rt_dose_info_dict["referenced_sop_instance_uid"] 
        
        # Add RTDOSE to the dictionary based on the RTPLAN SOPInstanceUID
        if referenced_sop_instance_uid not in self._loaded_data_dict["rtdose"]:
            self._loaded_data_dict["rtdose"][referenced_sop_instance_uid] = {"plan_dose": {}, "beam_dose": {}, "beams_composite": None}
        
        # Reference the current dictionary
        curr_dict_ref = self._loaded_data_dict["rtdose"][referenced_sop_instance_uid]
        
        # Handle an RTDOSE that represents a PLAN dose
        if dose_summation_type.upper() == "PLAN":
            if sop_instance_uid in curr_dict_ref["plan_dose"]:
                print(f"Error in loading plan {modality} with SOPInstanceUID: {sop_instance_uid}. {modality} for RTPLAN SOPInstanceUID: {referenced_sop_instance_uid} already exists.")
                return
            
            curr_dict_ref["plan_dose"][sop_instance_uid] = rt_dose_info_dict["sitk_dose"]
        
        # Handle an RTDOSE that represents a BEAM dose
        elif dose_summation_type.upper() == "BEAM":
            if sop_instance_uid in curr_dict_ref["beam_dose"]:
                print(f"Error in loading beam {modality} with SOPInstanceUID: {sop_instance_uid}. {modality} for RTPLAN SOPInstanceUID: {referenced_sop_instance_uid} already exists.")
                return
            
            curr_dict_ref["beam_dose"][sop_instance_uid] = rt_dose_info_dict["sitk_dose"]
            if curr_dict_ref["beams_composite"] is None:
                # Create a copy
                curr_dict_ref["beams_composite"] = sitk_resample_to_reference(rt_dose_info_dict["sitk_dose"], rt_dose_info_dict["sitk_dose"], interpolator=sitk.sitkLinear, default_pixel_val_outside_image=0.0)
            else:
                sitk_rtdose = sitk_resample_to_reference(rt_dose_info_dict["sitk_dose"], curr_dict_ref["beams_composite"], interpolator=sitk.sitkLinear, default_pixel_val_outside_image=0.0)
                curr_dict_ref["beams_composite"] = sitk.Add(curr_dict_ref["beams_composite"], sitk_rtdose)
            
            for key in rt_dose_info_dict["sitk_dose"].GetMetaDataKeys():
                curr_dict_ref["beams_composite"].SetMetaData(key, rt_dose_info_dict["sitk_dose"].GetMetaData(key))
            curr_dict_ref["beams_composite"].SetMetaData("referenced_beam_number", "composite")
        
        print(f"Loaded {dose_summation_type} {modality} with SOPInstanceUID: {sop_instance_uid} and referenced RTPLAN SOPInstanceUID: {referenced_sop_instance_uid}.")
    
    def load_rtstruct_goals(self, patient_id):
        """
        Load RTSTRUCT goals based on the patient objectives defined in the JSON file.
        
        Args:
            patient_id (str): The ID of the patient.
        """
        if not self._loaded_data_dict["rtstruct"]:
            return
        
        if not patient_id:
            print("No patient ID found. Cannot update SITK RTSTRUCT with goals.")
            return
        
        objectives_fpath = self.config_manager.get_objectives_filepath()
        
        if not objectives_fpath or not objectives_fpath.endswith(".json") or not os.path.exists(objectives_fpath):
            print(f"Objective JSON file not found at location: {objectives_fpath}. Cannot update SITK RTSTRUCT with goals.")
            return
        
        with open(objectives_fpath, 'rt') as file:
            patient_objectives = json.load(file).get(patient_id, {})
        if not patient_objectives:
            print(f"No objectives found for patient with ID '{patient_id}' in the JSON file.")
            return
        
        if patient_objectives:
            self._patient_objectives_dict.update(patient_objectives)
        
        # Find relevant objectives for the patient's RTSTRUCT
        matched_objectives = {}
        for rt_struct_info_dict in self._loaded_data_dict["rtstruct"].values():
            if "StructureSetLabel" in rt_struct_info_dict and rt_struct_info_dict["StructureSetLabel"]:
                print(f"Checking objectives for RTSTRUCT with label: {rt_struct_info_dict['StructureSetLabel']} ...")
                structure_set_objectives_dict = self._patient_objectives_dict.get("StructureSetId", {}).get(rt_struct_info_dict["StructureSetLabel"], {})
                if structure_set_objectives_dict:
                    matched_objectives.update(structure_set_objectives_dict)
        
        # Find relevant objectives for the patient's RTPLAN
        for rt_plan_info_dict in self._loaded_data_dict["rtplan"].values():
            if "rt_plan_label" in rt_plan_info_dict and rt_plan_info_dict["rt_plan_label"]:
                print(f"Checking objectives for RTPLAN with label: {rt_plan_info_dict['rt_plan_label']} ...")
                plan_objectives_dict = self._patient_objectives_dict.get("PlanId", {}).get(rt_plan_info_dict["rt_plan_label"], {})
                if plan_objectives_dict:
                    matched_objectives.update(plan_objectives_dict)
        
        if not matched_objectives:
            print("No objectives found for the patient in the JSON file. Cannot update SITK RTSTRUCT with goals.")
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
                    for objective_struct, objective_struct_dict in matched_objectives.items():
                        if objective_struct == original_roi_name or original_roi_name in objective_struct_dict["ManualStructNames"]:
                            found_struct_goals = objective_struct_dict.get("Goals")
                            break
                
                if not found_struct_goals:
                    continue
                
                current_struct_goals.update(found_struct_goals)
                
                roi_sitk.SetMetaData("roi_goals", json.dumps(current_struct_goals))
            
            print(f"Updated goals for RTSTRUCT (SOPInstanceUID: {sopiuid}): {[(roi_sitk.GetMetaData('current_roi_name'), json.loads(roi_sitk.GetMetaData('roi_goals'))) for roi_sitk in rt_struct_info_dict['list_roi_sitk'] if roi_sitk.GetMetaData('roi_goals')]}")
    
    def check_if_data_loaded(self, modality_key="any"):
        """
        Check if data is loaded for a specified modality.
        
        Args:
            modality_key (str): The modality to check ('rtimage', 'rtstruct', 'rtplan', 'rtdose', 'any', or 'all').
        
        Returns:
            bool: True if the data exists, False otherwise.
        """
        if modality_key == "any":
            return any(self._loaded_data_dict.values())
        
        if modality_key == "all":
            return all(self._loaded_data_dict.values())
        
        valid_keys = {"rtimage", "rtstruct", "rtplan", "rtdose"}
        if modality_key not in valid_keys:
            print(f"Error: Unsupported modality key '{modality_key}'. Must be one of {valid_keys}.")
            return False
        
        return bool(self._loaded_data_dict.get(modality_key))
    
    def return_list_of_all_original_roi_names(self, match_criteria=None):
        """
        Retrieve a list of all original (unmodified) ROI names.
        
        Args:
            match_criteria (str, optional): A string to filter ROI names. Defaults to None.
        
        Returns:
            list: List of ROI names matching the criteria.
        """
        if not isinstance(match_criteria, (str, type(None))):
            print(f"Error in returning list of all original ROI names. Unsupported match criteria: {match_criteria}. Must be a string or None.")
            return []
        
        # Find all original ROI names
        roi_names = []
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
    
    def return_data_from_modality(self, modality_key):
        """
        Retrieve loaded data for a given modality.
        
        Args:
            modality_key (str): The modality key, one of 'rtimage', 'rtstruct', 'rtplan', or 'rtdose'.
        
        Returns:
            dict or None: A dictionary of weak references to the requested modality's data, or None if invalid input.
        """
        valid_keys = {"rtimage", "rtstruct", "rtplan", "rtdose"}
        if modality_key not in valid_keys:
            print(f"Error: Unsupported modality key '{modality_key}'. Must be one of: {valid_keys}.")
            return None
        
        return weakref_nested_structure(self._loaded_data_dict[modality_key])
    
    def return_sitk_reference_param(self, param):
        """
        Retrieve a specific parameter from the cached SimpleITK reference parameters.
        
        Args:
            param (str): The parameter to retrieve. Options: 'origin', 'spacing', 'direction', 'size', 
                        'original_spacing', 'original_size', 'original_direction'.
        
        Returns:
            Any or None: The requested parameter's value, or None if invalid or unavailable.
        """
        valid_params = {"origin", "spacing", "direction", "size", "original_spacing", "original_size", "original_direction"}
        if param not in valid_params:
            print(f"Error: Unsupported parameter '{param}'. Must be one of: {valid_params}.")
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
    
    def remove_sitk_roi_from_rtstruct(self, keys):
        """
        Remove an ROI from the specified RTSTRUCT.
        
        Args:
            keys (list/tuple/set): A sequence containing at least four keys: ['rtstruct', SOPInstanceUID, 'list_roi_sitk', index].
        
        Returns:
            None
        """
        if not isinstance(keys, (tuple, list, set)) or not all(isinstance(key, (str, int)) for key in keys):
            print(f"Error in removing SITK ROI from RTSTRUCT. Keys must be a tuple, list, or set of strings or integers. Received: {keys}.")
            return
        
        if len(keys) < 4:
            print(f"Error in removing SITK ROI from RTSTRUCT. Keys must have at least four keys. Received: {keys}.")
            return
        
        if keys[0] != "rtstruct":
            print(f"Error in removing SITK ROI from RTSTRUCT. First key must be 'rtstruct'. Received: {keys[0]}.")
            return
        
        if keys[1] not in self._loaded_data_dict["rtstruct"]:
            print(f"Error in removing SITK ROI from RTSTRUCT. SOPInstanceUID not found in RTSTRUCT. Received: {keys[1]}.")
            return
        
        if keys[2] != "list_roi_sitk" or keys[2] not in self._loaded_data_dict["rtstruct"][keys[1]]:
            print(f"Error in removing SITK ROI from RTSTRUCT. List of ROIs not found in RTSTRUCT. Received: {keys[2]}.")
            return
        
        self._loaded_data_dict["rtstruct"][keys[1]][keys[2]][keys[3]] = None
        print(f"ROI at index {keys[3]} removed from RTSTRUCT with SOP Instance UID '{keys[1]}'.")
    
    def update_active_data(self, load_data, display_data_keys):
        """
        Update the active display data based on the specified display keys.
        
        Args:
            load_data (bool): Whether to load (True) or remove (False) the active data.
            display_data_keys (list/tuple/set): Keys specifying the data to update.
        """
        if not isinstance(load_data, bool):
            print(f"Error in handling active data. Load data must be a boolean. Received: {load_data}.")
            return
        
        if not isinstance(display_data_keys, (tuple, list, set)) or not all(isinstance(key, (str, int)) for key in display_data_keys):
            print(f"Error in handling active data. Display data keys must be a tuple, list, or set of strings or integers. Received: {display_data_keys}.")
            return
        
        if len(display_data_keys) < 2:
            print(f"Error in handling active data. Display data keys must have at least two keys. Received: {display_data_keys}.")
            return
        
        # Handle the case where all data of a specific type should be loaded or removed
        if display_data_keys[-1] == "all":
            # Get to the dictionary level where the data is stored
            current_dict = self._loaded_data_dict
            for key in display_data_keys[:-1]:
                current_dict = current_dict.setdefault(key, {})
            # Get the actual keys to load or remove. We enumerate in case the current dictionary is not actually a dictionary but a list (ex: ROIs)
            real_ddkeys = [display_data_keys[:-1] + (key,) if isinstance(current_dict, dict) else display_data_keys[:-1] + (i,) for i, key in enumerate(current_dict)]
            for real_ddkey in real_ddkeys:
                self.update_active_data(load_data, real_ddkey)
            return
        
        # Check if the data is already loaded
        if load_data and display_data_keys in self._cached_numpy_data:
            return
        
        if not load_data:
            # Clear the cached data
            if display_data_keys in self._cached_numpy_data:
                self._cached_numpy_data.pop(display_data_keys)
            if display_data_keys in self._cached_rois_sitk:
                self._cached_rois_sitk.pop(display_data_keys)
        else:
            # Find the SITK data, and load it into the cache
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
    
    def _update_cached_sitk_reference(self, sitk_data):
        """
        Update the cached SimpleITK to reference based on the provided SITK data.
        
        Args:
            sitk_data (SimpleITK.Image): The SITK data to use for updating the reference.
        """
        if self._cached_sitk_reference is None:
            original_voxel_spacing = sitk_data.GetSpacing()
            original_size = sitk_data.GetSize()
            original_direction = sitk_data.GetDirection()
            voxel_spacing = self._cached_texture_param_dict.get("voxel_spacing", sitk_data.GetSpacing())
            rotation = self._cached_texture_param_dict.get("rotation", None)
            flips = self._cached_texture_param_dict.get("flips", None)
            
            self._cached_sitk_reference = resample_sitk_data_with_params(
                sitk_data=sitk_data, set_spacing=voxel_spacing, set_rotation=rotation, 
                set_flip=flips, interpolator=sitk.sitkLinear, numpy_output=False, numpy_output_dtype=None
            )
            
            self._cached_sitk_reference.SetMetaData("original_spacing", str(original_voxel_spacing))
            self._cached_sitk_reference.SetMetaData("original_size", str(original_size))
            self._cached_sitk_reference.SetMetaData("original_direction", str(original_direction))
    
    def _resample_sitk_to_cached_reference(self, sitk_data):
        """
        Resample the provided SITK data to match the cached reference.
        
        Args:
            sitk_data (SimpleITK.Image): The SITK data to resample.
        
        Returns:
            SimpleITK.Image: The resampled image.
        """
        if self._cached_sitk_reference is None:
            self._update_cached_sitk_reference(sitk_data)
        return sitk_resample_to_reference(sitk_data, self._cached_sitk_reference, interpolator=sitk.sitkLinear, default_pixel_val_outside_image=0.0)
    
    def _get_np(self, sitk_data):
        """
        Convert SITK data to a NumPy array.
        
        Args:
            sitk_data (SimpleITK.Image): The SITK data to convert.
        
        Returns:
            np.ndarray: The resulting NumPy array.
        """
        return sitk_to_array(self._resample_sitk_to_cached_reference(sitk_data))
    
    def update_cache(self, display_data_keys):
        """
        Resets the cache if no data remains for display, or updates RTDOSE data cache by summing all dose arrays and normalizing.
        
        Args:
            display_data_keys (tuple/list): Keys to identify the data to update.
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
    
    def return_texture_from_active_data(self, texture_params):
        """
        Generate and return a texture slice from the cached data based on the given parameters.
        
        Args:
            texture_params (dict): Dictionary of parameters defining the texture properties.
        
        Returns:
            np.ndarray: A 1D array representing the resized texture slice.
        """
        if not texture_params or not isinstance(texture_params, dict):
            print(f"Error texture generation. Texture parameter dictionary is missing or invalid: {texture_params}.")
            return np.zeros(1, dtype=np.float32) # Empty texture
        
        image_length = texture_params.get("image_length")
        if not image_length or not isinstance(image_length, int):
            print(f"Error texture generation. Texture parameter dictionary is missing an integer for 'image_length': {texture_params}.")
            return np.zeros(1, dtype=np.float32)
        
        texture_RGB_size = image_length * image_length * 3
        
        slicer = texture_params["slicer"]
        if not slicer or not isinstance(slicer, tuple) or not all(isinstance(s, slice) or isinstance(s, int) for s in slicer):
            print(f"Error texture generation. Texture parameter dictionary is missing a tuple of slice(s)/int(s) for 'slicer': {texture_params}.")
            return np.zeros(texture_RGB_size, dtype=np.float32)
        
        view_type = texture_params.get("view_type")
        if not view_type or not isinstance(view_type, str) or view_type not in ["axial", "coronal", "sagittal"]:
            print(f"Error texture generation. Texture parameter dictionary is missing a valid string for 'view_type': {texture_params}.")
            return np.zeros(texture_RGB_size, dtype=np.float32)
        
        try:
            # Rebuild cache if texture parameters have changed
            if self._check_for_texture_param_changes(texture_params, ignore_keys=["view_type", "slicer", "slices", "xyz_ranges"]):
                cached_list_of_keys = list(self._cached_numpy_data.keys())
                self.clear_cache()
                self._cached_texture_param_dict = texture_params
                for display_data_keys in cached_list_of_keys:
                    self.update_active_data(True, display_data_keys)
            
            # Determine base layer shape, which is based on how much data is being included by the slicer
            shape_RGB = tuple(s.stop - s.start for s in slicer if isinstance(s, slice)) + (3,)
            base_layer = np.zeros(shape_RGB, dtype=np.float32)
            
            # Alphas for blending images, masks, and doses
            alphas = texture_params["display_alphas"]
            if alphas and len(alphas) == 3:
                self._blend_images_RGB(base_layer, slicer, texture_params["image_window_level"], texture_params["image_window_width"], alphas[0])
                self._blend_masks_RGB(base_layer, slicer, texture_params["contour_thickness"], alphas[1])
                self._blend_doses_RGB(base_layer, slicer, texture_params["dose_thresholds"], alphas[2])
            else:
                print(f"Error in blending data. Display alphas are missing or invalid: {alphas}.")
            
            # Add crosshairs
            self._draw_slice_crosshairs(base_layer, texture_params["show_crosshairs"], view_type, texture_params["slices"], texture_params["xyz_ranges"])
            
            # Adjust dimension order based on view type
            if view_type == "coronal":
                base_layer = np.swapaxes(base_layer, 0, 1)
            elif view_type == "sagittal":
                base_layer = np.fliplr(np.swapaxes(base_layer, 0, 1))
            
            # Normalize and clip to [0, 1]
            base_layer = np.clip(base_layer, 0, 255) / 255.0
            
            # Resize to the desired image dimensions
            base_layer = cv2.resize(base_layer, (image_length, image_length), interpolation=cv2.INTER_LINEAR)
            
            # Finally, add orientation labels (perform after resizing to avoid distortion of text)
            self._draw_orientation_labels(base_layer, texture_params["show_orientation_labels"], view_type, texture_params["rotation"], texture_params["flips"])
            
            # Resize to the desired image dimensions and flatten to a 1D texture
            return base_layer.ravel()
        except Exception as e:
            print(get_traceback(e))
            return np.zeros(texture_RGB_size, dtype=np.float32) # Empty RGB texture
        
    def _check_for_texture_param_changes(self, texture_params, ignore_keys=None):
        """
        Check if texture parameters have changed compared to the cached parameters.
        
        Args:
            texture_params (dict): Current texture parameters.
            ignore_keys (list, optional): List of keys to ignore when checking for changes. Defaults to None.
        
        Returns:
            bool: True if changes are detected, False otherwise.
        """
        if self._cached_texture_param_dict is None:
            return True
        
        for key, value in texture_params.items():
            if isinstance(ignore_keys, list) and key in ignore_keys:
                continue
            cached_value = self._cached_texture_param_dict.get(key)
            if isinstance(value, (list, tuple, set)):
                if any(v != cv for v, cv in zip(value, cached_value)):
                    return True
            elif value != cached_value:
                return True
        
        return False
       
    def _blend_layers(self, base_layer, overlay, alpha):
        """
        Blend an overlay onto a base layer using the given alpha value.
        
        Args:
            base_layer (np.ndarray): The base image layer.
            overlay (np.ndarray): The overlay image layer.
            alpha (float): Alpha value (0-100) for blending.
        
        Returns:
            np.ndarray: The blended layer.
        """
        overlay_indices = overlay.any(axis=-1)
        alpha_ratio = alpha / 100.0
        base_layer[overlay_indices] = (base_layer[overlay_indices] * (1 - alpha_ratio) + overlay[overlay_indices].astype(np.float32) * alpha_ratio)
    
    def _blend_images_RGB(self, base_layer, slicer, image_window_level, image_window_width, alpha):
        """
        Blend multiple images into the base layer using the given window level, window width, and alpha value.
        
        Args:
            base_layer (np.ndarray): The base layer to draw the images on.
            slicer (tuple): Slicer for the image.
            image_window_level (float): Window level for the image.
            image_window_width (float): Window width for the image.
            alpha (float): Alpha value for blending.
        """
        numpy_images = self.find_active_npy_images()
        
        if not numpy_images:
            return
        
        if image_window_level is None or image_window_width is None or alpha is None:
            print(f"Error in blending images. Image window level ({image_window_level}), window width ({image_window_width}), or alpha ({alpha}) is missing.")
            return
        
        lower_bound, upper_bound = image_window_level - (image_window_width / 2), image_window_level + (image_window_width / 2)
        
        image_list = []
        for numpy_image in numpy_images:
            image_slice = ((np.clip(numpy_image[slicer], lower_bound, upper_bound) - lower_bound) / ((upper_bound - lower_bound) + 1e-4) * 255)
            image_list.append(np.stack((image_slice,) * 3, axis=-1))
        
        num_images = len(image_list)
        composite_image = np.sum([image.astype(np.float32) for image in image_list if image is not None], axis=0)
        composite_image /= num_images  # Average the images
        
        self._blend_layers(base_layer, composite_image, alpha)
    
    def _blend_masks_RGB(self, base_layer, slicer, contour_thickness, alpha):
        """
        Blend multiple masks into the base layer using the given contour thickness and alpha value.
        
        Args:
            base_layer (np.ndarray): The base layer to draw the masks on.
            slicer (tuple): Slicer for the mask.
            contour_thickness (int): Thickness of the contour.
            alpha (float): Alpha value for blending.
            
        """
        if not self._cached_rois_sitk:
            return
        
        if not contour_thickness or not alpha:
            print(f"Error in blending masks. Contour thickness ({contour_thickness}) or alpha ({alpha}) is missing.")
            return
        
        # If contour_thickness is 0, then we want to fill the contour instead of showing no contour. 0 has no utility.
        if contour_thickness == 0:
            contour_thickness = -1
        
        composite_masks_RGB = np.zeros_like(base_layer, dtype=np.uint8)
        
        for roi_keys, roi_sitk_ref in self._cached_rois_sitk.items():
            if not roi_keys in self._cached_numpy_data:
                continue
            roi_display_color = get_sitk_roi_display_color(roi_sitk_ref())
            contours, _ = cv2.findContours(image=self._cached_numpy_data[roi_keys][slicer].astype(np.uint8), mode=cv2.RETR_EXTERNAL, method=cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(image=composite_masks_RGB, contours=contours, contourIdx=-1, color=roi_display_color, thickness=contour_thickness)
        
        self._blend_layers(base_layer, composite_masks_RGB, alpha)
    
    def _dosewash_colormap(self, value_array):
        """
        Colorize a dose array using a DoseWash colormap.

        Args:
            value_array (np.ndarray): Normalized input value(s) in range [0,1].

        Returns:
            np.ndarray: Corresponding RGB color(s).
        """
        if not isinstance(value_array, np.ndarray) or value_array.ndim != 2:
            raise ValueError(f"Input values must be a 2-D NumPy array. Received type: {type(value_array)} and shape: {value_array.shape if isinstance(np.ndarray) else 'Not an array'}.")
        if np.min(value_array) < 0 or np.max(value_array) > 1:
            raise ValueError(f"Input values must be normalized to [0,1]. Received min: {np.min(value_array)} and max: {np.max(value_array)}.")
        
        # Define the colormap in BGR order
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
        
        base_colors = np.clip(base_colors / 255, 0.0, 1.0)  # Ensure values range from [0,1]
        
        # Compute interpolated RGB values
        num_colors = len(base_colors)
        color_idx = value_array * (num_colors - 1)  # Scale to colormap indices
        lower_idx = np.floor(color_idx).astype(int)
        upper_idx = np.ceil(color_idx).astype(int)
        blend_factor = color_idx - lower_idx  # Interpolation factor

        # Ensure valid indices
        lower_idx = np.clip(lower_idx, 0, num_colors - 1)
        upper_idx = np.clip(upper_idx, 0, num_colors - 1)
        
        # Get interpolated colors
        rgb = (1 - blend_factor)[..., None] * base_colors[lower_idx] + blend_factor[..., None] * base_colors[upper_idx]
        
        return np.clip(rgb, 0.0, 1.0)  # Ensure RGB values remain in [0,1]
        
    def _blend_doses_RGB(self, base_layer, slicer, dose_thresholds, alpha):
        """
        Blend multiple doses into the base layer using the given dose thresholds and alpha value.
        
        Args:
            base_layer (np.ndarray): The base layer to draw the doses on.
            slicer (tuple): Slicer for the dose.
            dose_thresholds (tuple): Lower and upper dose thresholds.
            alpha (float): Alpha value for blending. 
        """
        if self._cached_numpy_dose_sum is None:
            return
        
        if not dose_thresholds or not isinstance(dose_thresholds, (tuple, list)) or len(dose_thresholds) != 2 or not alpha:
            print(f"Error in blending doses. Dose thresholds ({dose_thresholds}) or alpha ({alpha}) is missing or invalid.")
            return
        
        min_threshold_p, max_threshold_p = dose_thresholds
        
        total_dose_slice = self._cached_numpy_dose_sum[slicer].squeeze() # 2D slice, range [0,1]
        cmap_data = self._dosewash_colormap(total_dose_slice)
        cmap_data[(total_dose_slice <= min_threshold_p / 100) | (total_dose_slice >= max_threshold_p / 100)] = 0
        cmap_data = cmap_data[..., :3] * 255
        
        self._blend_layers(base_layer, cmap_data, alpha)
    
    def _draw_slice_crosshairs(self, base_layer, show_crosshairs, view_type, slices, xyz_ranges, crosshair_color=150):
        """
        Draws crosshairs on the base layer at the specified slice locations.

        Args:
            base_layer (np.ndarray): The base layer where crosshairs should be drawn.
            show_crosshairs (bool): Whether to show crosshairs.
            view_type (str): The view type ('axial', 'coronal', or 'sagittal').
            slices (tuple): The slice locations for the crosshairs.
            xyz_ranges (tuple): The XYZ ranges for the crosshairs.
            crosshair_color (int): The color for the crosshairs.
        """
        if not show_crosshairs:
            return
        
        if not slices or not isinstance(slices, (list, tuple)) or len(slices) != 3 or not all(isinstance(s, int) for s in slices):
            print(f"Error in drawing crosshairs. Slices are missing or invalid: {slices}.")
            return
        
        if not xyz_ranges or not isinstance(xyz_ranges, (list, tuple)) or len(xyz_ranges) != 3 or not all(isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(v, int) for v in r) for r in xyz_ranges):
            print(f"Error in drawing crosshairs. XYZ ranges are missing or invalid: {xyz_ranges}.")
            return
        
        # Adjust absolute slice locations to relative locations based on xyz_ranges
        slices = [s - r[0] for s, r in zip(slices, xyz_ranges)]

        def get_thickness(dim_size):
            """Calculate thickness dynamically: 1 + 2 for every 500 pixels."""
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
        
    def _draw_orientation_labels(self, base_layer, show_orientation_labels, view_type, rotation, flips):
        """
        Draws orientation labels (L/R, A/P, S/I) on a texture.
        
        Args:
            base_layer (np.ndarray): The base layer where orientation labels should be drawn.
            show_orientation_labels (bool): Whether to show orientation labels.
            view_type (str): The view type ('axial', 'coronal', or 'sagittal').
            rotation (int): The rotation angle.
            flips (list): List of booleans indicating flips along the axes.
        
        Returns:
            Tuple[np.ndarray, float]: A tuple containing the overlay and alpha value.
        """
        if not show_orientation_labels:
            return
        
        # Do not draw orientation labels if the image is too small or the option is disabled
        h, w = base_layer.shape[:2]
        if h < 50 or w < 50:
            return
        
        dicom_direction = self.return_sitk_reference_param("original_direction") or tuple(np.eye(3).flatten().tolist())
        rotation_angle = int(rotation) or 0
        flips = flips or [False, False, False]
        
        orientation_labels = get_orientation_labels(dicom_direction, rotation_angle, flips)
        if not orientation_labels:
            print("Failed to draw orientation labels because the orientation labels are invalid.")
            return
        
        # Define label properties
        font = cv2.FONT_HERSHEY_COMPLEX
        font_scale = min(w, h) * 2e-3
        font_thickness = max(1, round(min(w, h) * 1e-3))
        
        text_RGBA = self.config_manager.get_orientation_label_color()
        text_RGB = [min(max(round(i), 0), 255) for i in text_RGBA[:3]]
        alpha = min(max(text_RGBA[3] / 2.55, 0), 100)  # Convert 0-255 to 0-100
        
        # Create an overlay for text
        overlay = np.zeros_like(base_layer, dtype=np.uint8)
        
        # Define a small buffer based on image size (1% of width/height)
        buffer_x = max(1, int(0.01 * w))  # At least 1 pixel
        buffer_y = max(1, int(0.01 * h))
        
        # Draw labels on the overlay
        keys_labels = {k.lower().strip():str(v).strip() for k, v in orientation_labels.items() if k.lower().strip().startswith(view_type.lower())}
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
    
    def find_active_npy_images(self):
        """
        Find all active (displayed) RTIMAGE NumPy arrays.
        
        Returns:
            list: A list of NumPy arrays for active RTIMAGE data.
        """
        return [numpy_data for keys, numpy_data in self._cached_numpy_data.items() if keys[0] == "rtimage"]
    
    def find_active_npy_rois(self):
        """
        Find all active (displayed) RTSTRUCT NumPy arrays.
        
        Returns:
            list: A list of NumPy arrays for active RTSTRUCT data.
        """
        return [numpy_data for keys, numpy_data in self._cached_numpy_data.items() if keys[0] == "rtstruct"]
    
    def find_active_npy_doses(self):
        """
        Find all active (displayed) RTDOSE NumPy arrays.
        
        Returns:
            list: A list of NumPy arrays for active RTDOSE data.
        """
        return [numpy_data for keys, numpy_data in self._cached_numpy_data.items() if keys[0] == "rtdose"]
    
    def return_roi_info_list_at_slice(self, slicer):
        """
        Retrieve ROI information at the specified slice.
        
        Args:
            slicer (slice): Slice object in consideration of the current view.
        
        Returns:
            list: A list of tuples containing ROI number, name, and color.
        """
        return [
            (
                roi_sitk_ref().GetMetaData("roi_number"), 
                roi_sitk_ref().GetMetaData("current_roi_name"), 
                get_sitk_roi_display_color(roi_sitk_ref())
            ) 
            for roi_keys, roi_sitk_ref in self._cached_rois_sitk.items() 
            if roi_sitk_ref() is not None and self.check_if_keys_exist(roi_keys, slicer)
       ]
    
    def return_image_value_list_at_slice(self, slicer):
        """
        Retrieve image values at the specified slice.
        
        Args:
            slicer (slice): Slice object in consideration of the current view.
        
        Returns:
            list: A list of image slices.
        """
        return [numpy_image[slicer] for numpy_image in self.find_active_npy_images()]
    
    def return_dose_value_list_at_slice(self, slicer):
        """
        Retrieve dose values at the specified slice.
        
        Args:
            slicer (slice): Slice object in consideration of the current view.
        
        Returns:
            list: A list of dose slices.
        """
        return [numpy_dose[slicer] for numpy_dose in self.find_active_npy_doses()]
    
    def return_is_any_data_active(self):
        """
        Check if any data is currently displayed/active.
        
        Returns:
            bool: True if there is displayed/active data, False otherwise.
        """
        return bool(self._cached_numpy_data)
    
    def count_active_data_items(self):
        """ 
        Return the total number of active data items across all keys.
        """
        return len(self._cached_numpy_data)
    
    def check_if_keys_exist(self, keys, slicer=None):
        """ 
        Return whether the specified data is active and exists. 
        
        Args:
            keys (tuple): Keys identifying the data in the cache.
            slicer (slice, optional): Slice object in consideration of the current view. Defaults to None.
        
        Returns:
            bool: True if the data exists, False otherwise.
        """
        if slicer is not None:
            return keys in self._cached_numpy_data and np.any(self._cached_numpy_data[keys][slicer])
        if keys and not keys in self._cached_numpy_data:
            self.update_active_data(True, keys)
        return keys and keys in self._cached_numpy_data and np.any(self._cached_numpy_data[keys])
    
    def return_npy_center_of_mass(self, keys):
        """
        Compute the center of mass for a NumPy array.
        
        Args:
            keys (tuple): Keys identifying the data in the cache.
        
        Returns:
            tuple: The center of mass in XYZ order, or None if no data exists.
        """
        if not self.check_if_keys_exist(keys):
            return None
        
        yxz_com = [round(i) for i in center_of_mass(self._cached_numpy_data[keys])]
        return (yxz_com[1], yxz_com[0], yxz_com[2])
        
    def return_npy_extent_ranges(self, keys):
        """
        Compute the extent ranges of non-zero values in a NumPy array.
        
        Args:
            keys (tuple): Keys identifying the data in the cache.
        
        Returns:
            tuple: Ranges for X, Y, and Z dimensions, or None if no data exists.
        """
        if not self.check_if_keys_exist(keys):
            return None
        
        extent = np.nonzero(self._cached_numpy_data[keys])
        y_range = (np.min(extent[0]), np.max(extent[0])) if np.any(extent[0]) else None
        x_range = (np.min(extent[1]), np.max(extent[1])) if np.any(extent[1]) else None
        z_range = (np.min(extent[2]), np.max(extent[2])) if np.any(extent[2]) else None
        return (x_range, y_range, z_range)
    
