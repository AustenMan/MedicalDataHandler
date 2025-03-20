import os
import json
import random
import numpy as np
import SimpleITK as sitk
from concurrent.futures import as_completed, Future
from utils.dicom_utils import read_dcm_file, get_tag_values, safe_keyword_for_tag
from utils.general_utils import find_reformatted_mask_name, get_traceback
from utils.numpy_utils import numpy_roi_mask_generation
from utils.sitk_utils import sitk_transform_physical_point_to_index

def build_single_mask(roi_info_dict, sitk_image_params, tg_263_oar_names_list, organ_name_matching_dict):
    """
    Builds a binary mask for a single ROI using contour data.
    
    Args:
        roi_info_dict (dict): Information about the ROI, including contour data and metadata.
        sitk_image_params (dict): SimpleITK image parameters (spacing, origin, direction).
        tg_263_oar_names_list (list): List of TG-263-compliant organ-at-risk names.
        organ_name_matching_dict (dict): Dictionary for organ name matching.
        shared_state_manager (SharedStateManager, optional): Used to check an event for signal continuation or exit. If clear, the monitor will exit. Defaults to None. 
    
    Returns:
        sitk.Image: A SimpleITK binary mask with metadata for the ROI, or None if unsuccessful.
    """
    roi_name = roi_info_dict["roi_name"]
    roi_number = roi_info_dict["roi_number"]
    
    mask_np = np.zeros((sitk_image_params["slices"], sitk_image_params["rows"], sitk_image_params["cols"]), dtype=bool)
    has_data = False
    
    for idx, contour in enumerate(roi_info_dict["contour_data"]):
        if not all([contour["contour_geometric_type"], contour["number_of_contour_points"], contour["contour_data"]]):
            print(f"Warning: Incomplete contour data for ROI '{roi_name}', contour index '{idx}'. Found: '{contour}'.")
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
        print(f"Warning: No valid contour data for this ROI named '{roi_name}'.")
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
        organ_name_matching_dict
    )
    
    # Set metadata
    metadata = {
        'original_roi_name': str(roi_name),
        'current_roi_name': str(current_roi_name),
        'roi_number': str(roi_number),
        'roi_display_color': str(roi_info_dict["roi_display_color"]),
        'rt_roi_interpreted_type': str(roi_info_dict["rt_roi_interpreted_type"]),
        'roi_physical_properties': json.dumps(roi_info_dict["roi_physical_properties"]),
        'material_id': str(roi_info_dict["material_id"]),
        'roi_goals': json.dumps({}),
        'roi_rx_dose': '',
        'roi_rx_fractions': '',
        'roi_rx_site': '',
    }
    
    for key, value in metadata.items():
        mask_sitk.SetMetaData(key, value)
    
    return mask_sitk

class RTStructBuilder:
    """
    A class for constructing RT Structure Set information from a DICOM file.
    
    Attributes:
        file_path (str): Path to the RT Structure Set DICOM file.
        sitk_image_params_dict (dict): Dictionary of SimpleITK image parameters.
        shared_state_manager (Executor): Manager for shared task execution.
        config_manager (ConfigManager): Configuration manager that provides TG-263 organ names and organ matching dictionaries.
        rtstruct_info_dict (dict): High-level information about the RT Structure Set.
        roi_info_dicts (dict): Information about ROIs, including contour data and metadata.
    """
    
    def __init__(self, file_path, sitk_image_params_dict, shared_state_manager, config_manager):
        """
        Initialize the RTStructBuilder.
        
        Args:
            file_path (str): Path to the RT Structure Set DICOM file.
            sitk_image_params_dict (dict): Dictionary of SimpleITK image parameters.
            shared_state_manager (Executor): Manager for shared task execution.
            config_manager (ConfigManager): Configuration manager that provides TG-263 organ names and organ matching dictionaries.
        """
        self.file_path = file_path
        self.sitk_image_params_dict = sitk_image_params_dict
        self.shared_state_manager = shared_state_manager
        self.config_manager = config_manager
        self.rtstruct_info_dict = {}
        self.roi_info_dicts = {}
    
    def _exit_task_status(self):
        should_exit = self.shared_state_manager is not None and (self.shared_state_manager.cleanup_event.is_set() or self.shared_state_manager.shutdown_event.is_set())
        if should_exit:
            print("Aborting RT Structure Set builder task.")
        return should_exit
    
    def _validate_inputs(self):
        """
        Validates the input parameters for the RT Structure Set builder.
        
        Returns:
            bool: True if inputs are valid, False otherwise.
        """
        if not isinstance(self.file_path, str):
            print(f"Error: File path must be a string. Received type: '{type(self.file_path)}' with value: '{self.file_path}'.")
            return False
        
        if not os.path.exists(self.file_path):
            print(f"Error: File '{self.file_path}' does not exist.")
            return False
        
        # Check that all keys are strings and all values are dicts with keys "slices", "rows", "cols", "origin", "spacing", "direction"
        if not isinstance(self.sitk_image_params_dict, dict):
            print(f"Error: Image parameters must be provided as a dictionary. Received type: '{type(self.sitk_image_params_dict)}' with value: '{self.sitk_image_params_dict}'.")
            return False
        
        if not self.sitk_image_params_dict:
            print(f"Error: Image parameters dictionary must not be empty.")
            return False
        
        for siuid_key, infodict_value in self.sitk_image_params_dict.items():
            if self._exit_task_status():
                return False
            
            if not isinstance(siuid_key, str) or not isinstance(infodict_value, dict):
                print(f"Error: Image parameters must be a dictionary with string keys and dictionary values. Received key type: '{type(siuid_key)}', value type: '{type(infodict_value)}'.")
                return False
            
            if not all(k in infodict_value for k in ["slices", "rows", "cols", "origin", "spacing", "direction"]):
                print(f"Error: Image parameters dictionary must have keys 'slices', 'rows', 'cols', 'origin', 'spacing', 'direction'.")
                return False
        
        if not self.shared_state_manager:
            print(f"Error: Shared state manager not provided.")
            return False
        
        return True
    
    def _read_and_validate_dataset(self):
        """
        Reads and validates the DICOM dataset.
        
        Returns:
            bool: True if dataset is valid, False otherwise.
        """
        ds = read_dcm_file(self.file_path, to_json_dict=True)
        if not ds:
            print(f"Error: Could not read DICOM file '{self.file_path}'.")
            return False
        
        if self._exit_task_status():
            return False
        
        # Extract structure set information
        self._extract_structure_set_info(ds)
        
        if not self.rtstruct_info_dict.get("ReferencedSeriesInstanceUID"):
            print(f"Error: Referenced Series Instance UID not found in '{self.file_path}'.")
            return False
        
        if self.rtstruct_info_dict["ReferencedSeriesInstanceUID"] not in self.sitk_image_params_dict:
            print(f"Error: Referenced Series Instance UID '{self.rtstruct_info_dict['ReferencedSeriesInstanceUID']}' not found in image parameters.")
            return False
        
        # Extract ROI information
        self._extract_roi_info(ds)
        
        if not self.roi_info_dicts:
            print(f"Error: No ROI contour data found in '{self.file_path}'.")
            return False
        
        return True
    
    def _extract_structure_set_info(self, ds):
        """
        Extracts high-level structure set information from the dataset.
        """
        desired_tags = ["30060002", "30060004", "30060008", "30060009"]
        self.rtstruct_info_dict = {
            safe_keyword_for_tag(tag): get_tag_values(ds, tag) for tag in desired_tags
        }
        self._get_referenced_series_instance_uid(ds)
        self.rtstruct_info_dict["list_roi_sitk"] = []
    
    def _get_referenced_series_instance_uid(self, ds):
        """
        Extracts the Referenced Series Instance UID from the dataset.
        """
        referenced_frame_of_reference_sequence = get_tag_values(ds, "30060010")
        if not referenced_frame_of_reference_sequence:
            return None
        
        ref_siuid = None
        for ref_frame_item in referenced_frame_of_reference_sequence:
            rt_referenced_study_sequence = get_tag_values(ref_frame_item, "30060012")
            if not rt_referenced_study_sequence:
                continue
            
            for rt_referenced_study_item in rt_referenced_study_sequence:
                rt_referenced_series_sequence = get_tag_values(rt_referenced_study_item, "30060014")
                if not rt_referenced_series_sequence:
                    continue
                
                for rt_referenced_series_item in rt_referenced_series_sequence:
                    read_ref_siuid = get_tag_values(rt_referenced_series_item, "0020000E")
                    if read_ref_siuid:
                        if ref_siuid is None:
                            ref_siuid = read_ref_siuid
                        elif ref_siuid != read_ref_siuid:
                            print(f"Warning: Multiple Referenced Series Instance UIDs found. Using {ref_siuid} but also found {read_ref_siuid}.")
        
        self.rtstruct_info_dict["ReferencedSeriesInstanceUID"] = ref_siuid
    
    def _extract_roi_info(self, ds):
        """
        Extracts information about ROIs, including contour data and metadata.
        """
        structure_set_roi_sequence = get_tag_values(ds, "30060020")
        roi_contour_sequence = get_tag_values(ds, "30060039")
        rt_roi_observations_sequence = get_tag_values(ds, "30060080")
        
        roi_info_temp = {}
        
        # Extract basic ROI info
        for roi_item in structure_set_roi_sequence or []:
            if self._exit_task_status():
                return
            
            roi_number = get_tag_values(roi_item, "30060022")
            roi_name = get_tag_values(roi_item, "30060026")
            roi_info_temp[roi_number] = {
                "roi_number": roi_number,
                "roi_name": roi_name,
                "contour_data": [],
                "roi_display_color": [random.randint(0, 255) for _ in range(3)],
                "rt_roi_interpreted_type": None,
                "roi_physical_properties": [],
                "material_id": None,
            }
        
        # Extract contour data
        for contour_item in roi_contour_sequence or []:
            if self._exit_task_status():
                return
            
            referenced_roi_number = get_tag_values(contour_item, "30060084")
            if referenced_roi_number not in roi_info_temp:
                continue
            
            contour_sequence = get_tag_values(contour_item, "30060040")
            for contour_seq_item in contour_sequence or []:
                item_contour_data_dict = {
                    "contour_geometric_type": get_tag_values(contour_seq_item, "30060042"),
                    "number_of_contour_points": get_tag_values(contour_seq_item, "30060046"),
                    "contour_data": get_tag_values(contour_seq_item, "30060050"),
                }
                if item_contour_data_dict["contour_data"]:
                    roi_info_temp[referenced_roi_number]["contour_data"].append(item_contour_data_dict)
            
            roi_display_color = get_tag_values(contour_item, "3006002A")
            if roi_display_color and isinstance(roi_display_color, list) and len(roi_display_color) == 3:
                roi_info_temp[referenced_roi_number]["roi_display_color"] = [round(min(max(x, 0), 255)) for x in roi_display_color]
        
        # Extract ROI observations
        for obs_item in rt_roi_observations_sequence or []:
            if self._exit_task_status():
                return
            
            referenced_roi_number = get_tag_values(obs_item, "30060084")
            if referenced_roi_number not in roi_info_temp:
                continue
            
            roi_info_temp[referenced_roi_number]["rt_roi_interpreted_type"] = get_tag_values(obs_item, "300600A4")
            roi_info_temp[referenced_roi_number]["material_id"] = get_tag_values(obs_item, "300A00E1")
            
            roi_physical_properties_sequence = get_tag_values(obs_item, "300600B0")
            for prop_item in roi_physical_properties_sequence or []:
                prop = {
                    "roi_physical_property": get_tag_values(prop_item, "300600B2"),
                    "roi_physical_property_value": get_tag_values(prop_item, "300600B4"),
                }
                roi_info_temp[referenced_roi_number]["roi_physical_properties"].append(prop)
        
        if self._exit_task_status():
            return
        
        # Filter to only keep ROIs with contour data
        self.roi_info_dicts = {k: v for k, v in roi_info_temp.items() if v["contour_data"]}
    
    def _build_sitk_masks(self):
        """
        Builds binary masks for each ROI.
        
        Returns:
            bool: True if masks are successfully built, False otherwise.
        """
        sitk_image_params = self.sitk_image_params_dict[self.rtstruct_info_dict["ReferencedSeriesInstanceUID"]]
        tg_263_oar_names_list = self.config_manager.get_tg_263_names(ready_for_dpg=True)
        organ_name_matching_dict = self.config_manager.get_organ_matching_dict()
        
        futures = []
        list_roi_sitk = []
        
        if self._exit_task_status():
            return False
        
        try:
            futures = [
                future for roi_info_dict in self.roi_info_dicts.values() if (
                    future := self.shared_state_manager.add_executor_action(
                        build_single_mask, roi_info_dict, sitk_image_params, tg_263_oar_names_list, organ_name_matching_dict
                    )
                ) is not None
            ]
            
            for future in as_completed(futures):
                try:
                    if self._exit_task_status():
                        break
                    result = future.result()
                    if result is not None:
                        list_roi_sitk.append(result)  # Retrieve mask from the future
                except Exception as e:
                    print(f"Error: Failed to process mask future: {get_traceback(e)}")
        except Exception as e:
            print(f"Error: Exception occurred while building masks: {get_traceback(e)}")
        finally:
            # Clean up any remaining futures
            for future in futures:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
        
        if self._exit_task_status():
            return False
        
        # Check if any masks were successfully built
        self.rtstruct_info_dict["list_roi_sitk"].extend(list_roi_sitk)
        if not self.rtstruct_info_dict["list_roi_sitk"]:
            print(f"Error: No valid masks built from {self.file_path}.")
            return False
        return True
    
    def _get_unique_roi_name(self, roi_name):
        """
        Generates a unique ROI name by appending an index if the name already exists. 
        """
        existing_names = [mask.GetMetaData('current_roi_name') for mask in self.rtstruct_info_dict["list_roi_sitk"]]
        if roi_name not in existing_names:
            return roi_name
        
        idx = 1
        unique_name = f"{roi_name}_{idx}"
        while unique_name in existing_names:
            idx += 1
            unique_name = f"{roi_name}_{idx}"
        
        return unique_name
    
    def build_rtstruct_info_dict(self):
        """
        Constructs the RT Structure Set information dictionary.
        
        Returns:
            dict: The constructed RT Structure Set dictionary, or None if the process fails.
        """
        if self._exit_task_status() or not self._validate_inputs():
            return None
        if self._exit_task_status() or not self._read_and_validate_dataset():
            return None
        if self._exit_task_status() or not self._build_sitk_masks():
            return None
        return self.rtstruct_info_dict

