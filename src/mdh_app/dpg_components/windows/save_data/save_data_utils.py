from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, List, Union
from os import makedirs
from os.path import join, dirname

import dearpygui.dearpygui as dpg


from mdh_app.database.db_utils import update_patient_processed_at
from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.utils.general_utils import validate_filename, sanitize_path_component


if TYPE_CHECKING:
    from mdh_app.database.models import Patient
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def _execute_saving(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Execute the save operation for images, ROIs, RT Plans, and RT Doses either in bulk or individually.
    
    This function verifies patient information, prepares the save directory, and then calls
    specific processing functions for each data type.
    
    Args:
        sender: The UI element tag that triggered the save.
        app_data: Additional event data.
        user_data: Additional user data.
    """
    tag_save_window = get_tag("save_sitk_window")
    tag_ptinfo_button = get_tag("ptinfo_button")
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    
    if not dpg.does_item_exist(tag_ptinfo_button):
        logger.error("No patient data - load patient first")
        return
    
    active_pt: Patient = dpg.get_item_user_data(tag_ptinfo_button)
    if not isinstance(active_pt, Patient):
        logger.error(
            msg=(
                "Invalid patient information found. Cannot save. "
                f"Expected a Patient object, but received: {type(active_pt)}"
            )
        )
        return
    
    if not dpg.does_item_exist(tag_save_window):
        return
    
    logger.info("Saving data")
    
    save_selections_dict = dpg.get_item_user_data(tag_save_window)
    
    patient_mrn, patient_name = active_pt.mrn, active_pt.name
    update_patient_processed_at(active_pt)
    
    base_save_path = conf_mgr.get_dir_in_saved_data_dir([patient_mrn])
    if base_save_path is None:
        logger.error(f"Failed to create save directory for {patient_mrn}. Cancelling save.")
        return
    
    _process_image_saving(sender, save_selections_dict, base_save_path)
    _process_roi_saving(sender, save_selections_dict, base_save_path)
    _process_plan_saving(sender, save_selections_dict, base_save_path)
    _process_dose_saving(sender, save_selections_dict, base_save_path)
    
    if sender == save_selections_dict["execute_bulk_save_tag"]:
        logger.info("Save action is complete.")
        if dpg.does_item_exist(tag_save_window):
            dpg.hide_item(tag_save_window)


def _process_image_saving(sender: Union[str, int], save_selections_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save images according to user settings.

    This includes optional conversion of CT images from Hounsfield Units (HU) to Relative Electron Densities (RED),
    and resampling images based on custom parameters.
    
    Args:
        sender: The UI element tag that triggered the save.
        save_selections_dict: Dictionary containing save settings and image data.
        base_save_path: Base directory path for saving images.
    """
    keep_custom_params = dpg.get_value(save_selections_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_selections_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    convert_ct_hu_to_red = dpg.get_value(save_selections_dict["main_checkboxes"]["convert_ct_hu_to_red"])
    override_image_with_roi_RED = dpg.get_value(save_selections_dict["main_checkboxes"]["override_image_with_roi_RED"])
    roi_overrides = (
        [
            (roi_dict["data_key"], dpg.get_value(roi_dict["roi_phys_prop_tag"]))
            for roi_dict in save_selections_dict["rois"]
            if dpg.get_value(roi_dict["roi_phys_prop_tag"]) >= 0.0
        ]
        if override_image_with_roi_RED else []
    )
    
    for image_dict in save_selections_dict["images"]:
        if save_in_bulk and not dpg.get_value(image_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != image_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(image_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            logger.error(
                msg=(
                    f"No filename specified for {image_dict['modality']} image. "
                    f"Received: {save_filename}, which was cleaned to: {validated_filename}. "
                    "Skipping save."
                )
            )
            continue
        
        study_dir = sanitize_path_component(image_dict.get("study_instance_uid", "UNKNOWN"))
        modality = image_dict.get("modality", "IMAGE")
        series_instance_uid = image_dict.get("series_instance_uid") # never missing
        series_dir = sanitize_path_component(f"{modality.upper().strip()}.{series_instance_uid}")
        save_path = join(base_save_path, study_dir, series_dir, validated_filename + ".nrrd")
        makedirs(dirname(save_path), exist_ok=True)
        
        data_mgr.save_image(
            series_uid=series_instance_uid,
            roi_overrides=roi_overrides,
            output_path=save_path,
            convert_ct_hu_to_red=convert_ct_hu_to_red,
            use_cached_data=keep_custom_params
        )


def _process_roi_saving(sender: Union[str, int], save_selections_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save Regions of Interest (ROIs) based on user settings.

    ROIs with the same validated filename are merged and saved as one image.
    
    Args:
        sender: The UI element tag that triggered the save.
        save_selections_dict: Dictionary containing save settings and ROI data.
        base_save_path: Base directory path for saving ROIs.
    """
    keep_custom_params = dpg.get_value(save_selections_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_selections_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    # Initialize a dictionary to collect ROIs with the same filenames
    rois_to_save: Dict[str, List[int]] = {}
    for roi_dict in save_selections_dict["rois"]:
        if save_in_bulk and not dpg.get_value(roi_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != roi_dict["save_tag"]:
            continue
        
        # Build the filename for the ROI and the save path
        save_filename = dpg.get_value(roi_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            logger.error(
                msg=(
                    f"No filename specified for ROI. Received: {save_filename}, "
                    f"which was cleaned to: {validated_filename}. Skipping save."
                )
            )
            continue
        
        study_dir = sanitize_path_component(roi_dict.get("study_instance_uid", "UNKNOWN"))
        modality = roi_dict.get("modality", "RTSTRUCT")
        sop_instance_uid = roi_dict.get("sop_instance_uid") # never missing
        sop_dir = sanitize_path_component(f"{modality.upper().strip()}.{sop_instance_uid}")
        save_path = join(base_save_path, study_dir, sop_dir, validated_filename + ".nrrd")
        makedirs(dirname(save_path), exist_ok=True)
        
        rtp_sopiuid, roi_number = roi_dict["data_key"]
        rois_to_save.setdefault(save_path, []).append((rtp_sopiuid, roi_number))
    
    # After collecting, combine and save the ROIs with the same filenames
    for save_path, roi_keys in rois_to_save.items():
        data_mgr.save_roi(
            struct_uid=roi_keys[0][0],
            roi_numbers=[roi_key[1] for roi_key in roi_keys],
            output_path=save_path,
            use_cached_data=keep_custom_params
        )


def _process_plan_saving(sender: Union[str, int], save_selections_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save RT Plan data based on user settings.
    
    Args:
        sender: The UI element tag triggering the save.
        save_selections_dict: Dictionary containing save settings and RT Plan data.
        base_save_path: Base directory path for saving RT Plans.
    """
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    save_in_bulk = sender == save_selections_dict["execute_bulk_save_tag"]
    
    for plan_dict in save_selections_dict["plans"]:
        if save_in_bulk and not dpg.get_value(plan_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != plan_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(plan_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            logger.error(
                msg=(
                    f"No filename specified for RT Plan. Received: {save_filename}, "
                    f"which was cleaned to: {validated_filename}. Skipping save."
                )
            )
            continue
        
        study_dir = sanitize_path_component(plan_dict.get("study_instance_uid", "UNKNOWN"))
        modality = plan_dict.get("modality", "RTPLAN")
        sop_instance_uid = plan_dict.get("sop_instance_uid") # never missing
        sop_dir = sanitize_path_component(f"{modality.upper().strip()}.{sop_instance_uid}")
        save_path = join(base_save_path, study_dir, sop_dir, validated_filename + ".json")
        makedirs(dirname(save_path), exist_ok=True)
        
        data_mgr.save_plan(
            plan_uid=plan_dict["data_key"],
            output_path=save_path
        )


def _process_dose_saving(sender: Union[str, int], save_selections_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save RT Dose data based on user settings.

    If multiple RT Dose items are selected for a dose sum, they are combined; otherwise, each dose is saved individually.
    
    Args:
        sender: The UI element tag triggering the save.
        save_selections_dict: Dictionary containing save settings and RT Dose data.
        base_save_path: Base directory path for saving RT Doses.
    """
    keep_custom_params = dpg.get_value(save_selections_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_selections_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    # Handle dose sum if multiple selected
    dose_sum_list = [
        dose_dict["data_key"] 
        for dose_dict in save_selections_dict["doses"] 
        if dpg.get_value(dose_dict["dosesum_checkbox_tag"])
    ]
    
    if len(dose_sum_list) > 1:
        # Check if sum was triggered
        sum_triggered = save_in_bulk or any(
            sender == dose_dict["save_tag"] and dpg.get_value(dose_dict["dosesum_checkbox_tag"])
            for dose_dict in save_selections_dict["doses"]
        )
        
        # If sum is triggered, save the sum and skip individual saves
        if sum_triggered:
            dosesum_name = dpg.get_value(save_selections_dict["main_checkboxes"]["dosesum_name_tag"])
            validated_filename = validate_filename(dosesum_name)
            
            if not validated_filename:
                logger.error(f"Invalid dose sum filename: '{dosesum_name}'. Skipping sum.")
            else:
                # Get all unique paths to save the dose sum at
                paths = set()
                for dose_dict in save_selections_dict["doses"]:
                    if dose_dict["data_key"] in dose_sum_list:  # Only for summed doses
                        study_dir = sanitize_path_component(dose_dict.get("study_instance_uid", "UNKNOWN"))
                        modality = dose_dict.get("modality", "RTDOSE")
                        sop_instance_uid = dose_dict.get("sop_instance_uid")
                        sop_dir = sanitize_path_component(f"{modality.upper().strip()}.{sop_instance_uid}")
                        path = join(base_save_path, study_dir, sop_dir, validated_filename + ".nrrd")
                        makedirs(dirname(path), exist_ok=True)
                        paths.add(path)
                paths = list(paths)
                
                # Save the dose sum to all paths
                data_mgr.save_dose(
                    dose_uids=dose_sum_list,
                    output_paths=paths,
                    use_cached_data=keep_custom_params
                )
    
    for dose_dict in save_selections_dict["doses"]:
        if save_in_bulk and not dpg.get_value(dose_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != dose_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(dose_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        
        if not validated_filename:
            logger.error(
                msg=(
                    f"No filename specified for RT Dose. Received: {save_filename}, "
                    f"which was cleaned to: {validated_filename}. Skipping save."
                )
            )
            continue
        
        study_dir = sanitize_path_component(dose_dict.get("study_instance_uid", "UNKNOWN"))
        modality = dose_dict.get("modality", "RTDOSE")
        sop_instance_uid = dose_dict.get("sop_instance_uid") # never missing
        sop_dir = sanitize_path_component(f"{modality.upper().strip()}.{sop_instance_uid}")
        save_path = join(base_save_path, study_dir, sop_dir, validated_filename + ".nrrd")
        makedirs(dirname(save_path), exist_ok=True)
        
        data_mgr.save_dose(
            dose_uids=dose_dict["data_key"],
            output_paths=save_path,
            use_cached_data=keep_custom_params
        )



