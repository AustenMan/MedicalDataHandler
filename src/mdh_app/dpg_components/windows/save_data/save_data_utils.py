from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Union
from os.path import join
from json import dump, dumps, loads


import dearpygui.dearpygui as dpg
import SimpleITK as sitk


from mdh_app.database.db_utils import update_patient_processed_at
from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.utils.general_utils import validate_filename, atomic_save
from mdh_app.utils.numpy_utils import create_HU_to_RED_map
from mdh_app.utils.sitk_utils import sitk_to_array, array_to_sitk, sitk_resample_to_reference


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
        logger.error("No patient information found. Cannot save. Please load a patient before saving data.")
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
    
    logger.info("Starting save action...")
    
    save_data_dict = dpg.get_item_user_data(tag_save_window)
    
    patient_mrn, patient_name = active_pt.mrn, active_pt.name
    update_patient_processed_at(active_pt)
    
    # TODO: Save to a folder for Study?
    base_save_path = conf_mgr.get_nifti_data_save_dir([patient_mrn, patient_name])
    if base_save_path is None:
        logger.error(f"Failed to create save directory for {patient_mrn}, {patient_name}. Cancelling save.")
        return
    
    _process_image_saving(sender, save_data_dict, base_save_path)
    _process_roi_saving(sender, save_data_dict, base_save_path)
    _process_plan_saving(sender, save_data_dict, base_save_path)
    _process_dose_saving(sender, save_data_dict, base_save_path)
    
    if sender == save_data_dict["execute_bulk_save_tag"]:
        logger.info("Save action is complete.")
        if dpg.does_item_exist(tag_save_window):
            dpg.hide_item(tag_save_window)


def _process_image_saving(sender: Union[str, int], save_data_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save images according to user settings.

    This includes optional conversion of CT images from Hounsfield Units (HU) to Relative Electron Densities (RED),
    and resampling images based on custom parameters.
    
    Args:
        sender: The UI element tag that triggered the save.
        save_data_dict: Dictionary containing save settings and image data.
        base_save_path: Base directory path for saving images.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    
    convert_ct_hu_to_red = dpg.get_value(save_data_dict["main_checkboxes"]["convert_ct_hu_to_red"])
    override_image_with_roi_RED = dpg.get_value(save_data_dict["main_checkboxes"]["override_image_with_roi_RED"])
    roi_overrides = (
        [
            (roi_dict["data"], dpg.get_value(roi_dict["roi_phys_prop_tag"]))
            for roi_dict in save_data_dict["rois"]
            if dpg.get_value(roi_dict["roi_phys_prop_tag"]) >= 0.0
        ]
        if override_image_with_roi_RED else []
    )
    
    for image_dict in save_data_dict["images"]:
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
        
        save_path = join(base_save_path, validated_filename + ".nii")
        
        image_sitk_ref = image_dict["data"]
        image_sitk = image_sitk_ref()
        if image_sitk is None:
            logger.error(f"No SITK image found for {image_dict['modality']} image. Skipping save.")
            continue
        
        modality = image_dict["modality"]
        if modality.upper().strip() == "CT" and convert_ct_hu_to_red:
            data_array = sitk_to_array(image_sitk)
            data_array = create_HU_to_RED_map(
                hu_values=conf_mgr.get_ct_HU_map_vals(), 
                red_values=conf_mgr.get_ct_RED_map_vals()
            )(data_array) # Convert HU to RED
            
            if roi_overrides:
                for roi_sitk_ref, roi_red in roi_overrides:
                    if roi_sitk_ref() is None or roi_red < 0.0:
                        continue
                    roi_array = sitk_to_array(roi_sitk_ref(), bool)
                    data_array[roi_array] = roi_red
            
            new_image_sitk = array_to_sitk(data_array, image_sitk, copy_metadata=True)
        else:
            new_image_sitk = image_sitk
        
        if keep_custom_params:
            new_image_sitk = data_mgr._resample_sitk_to_cached_reference(new_image_sitk)
        
        try:
            sitk.WriteImage(new_image_sitk, save_path)
            logger.info(f"SITK Image saved to: {save_path}")
        except Exception as e:
            logger.exception(f"Failed to save SITK Image to: {save_path}.")


def _process_roi_saving(sender: Union[str, int], save_data_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save Regions of Interest (ROIs) based on user settings.

    ROIs with the same validated filename are merged (via summing their binary masks) and saved as one image.
    
    Args:
        sender: The UI element tag that triggered the save.
        save_data_dict: Dictionary containing save settings and ROI data.
        base_save_path: Base directory path for saving ROIs.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    # Initialize a dictionary to collect ROIs with the same filenames
    roi_files_dict: Dict[str, Any] = {}
    for roi_dict in save_data_dict["rois"]:
        if save_in_bulk and not dpg.get_value(roi_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != roi_dict["save_tag"]:
            continue
        
        roi_sitk_ref = roi_dict["data"]
        roi_sitk = roi_sitk_ref()
        if roi_sitk is None:
            continue
        
        if keep_custom_params:
            roi_sitk = data_mgr._resample_sitk_to_cached_reference(roi_sitk)
        
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
        save_path = join(base_save_path, validated_filename + ".nii")
        
        # Collect roi_sitk images for each validated filename
        if save_path not in roi_files_dict:
            roi_files_dict[save_path] = roi_sitk
        else:
            existing_roi_sitk = roi_files_dict[save_path]
            
            curr_roi_goals = loads(existing_roi_sitk.GetMetaData("roi_goals"))
            new_roi_goals = loads(data_sitk.GetMetaData("roi_goals"))
            new_roi_goals.update(curr_roi_goals)
            
            existing_roi_array = sitk_to_array(existing_roi_sitk, bool)
            roi_array = sitk_to_array(roi_sitk, bool)
            
            new_roi_array = existing_roi_array + roi_array
            new_roi_sitk = array_to_sitk(new_roi_array, existing_roi_sitk, copy_metadata=True)
            
            new_roi_sitk.SetMetaData("roi_goals", dumps(new_roi_goals))
            
            roi_files_dict[save_path] = new_roi_sitk
    
    # After collecting, combine and save the ROIs with the same filenames
    for save_path, data_sitk in roi_files_dict.items():
        try:
            sitk.WriteImage(data_sitk, save_path)
            logger.info(f"SITK ROI saved to: {save_path}")
        except Exception as e:
            logger.exception(f"Failed to write SITK ROI to {save_path}.")


def _process_plan_saving(sender: Union[str, int], save_data_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save RT Plan data based on user settings.
    
    Args:
        sender: The UI element tag triggering the save.
        save_data_dict: Dictionary containing save settings and RT Plan data.
        base_save_path: Base directory path for saving RT Plans.
    """
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    
    for plan_dict in save_data_dict["plans"]:
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
        save_path = join(base_save_path, validated_filename + ".json")
        
        rtplan_dict = plan_dict["data"]
        atomic_save(
            filepath=save_path, 
            write_func=lambda file: dump(rtplan_dict, file),
            success_message=f"RT Plan saved to: {save_path}",
            error_message=f"Failed to save RT Plan to {save_path}."
        )


def _process_dose_saving(sender: Union[str, int], save_data_dict: Dict[str, Any], base_save_path: str) -> None:
    """
    Process and save RT Dose data based on user settings.

    If multiple RT Dose items are selected for a dose sum, they are combined; otherwise, each dose is saved individually.
    
    Args:
        sender: The UI element tag triggering the save.
        save_data_dict: Dictionary containing save settings and RT Dose data.
        base_save_path: Base directory path for saving RT Doses.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    dosesum_name = dpg.get_value(save_data_dict["main_checkboxes"]["dosesum_name_tag"])
    
    dose_sum_list: List[Any] = [
        data_mgr._resample_sitk_to_cached_reference(dose_dict["data"]())
        if keep_custom_params else dose_dict["data"]()
        for dose_dict in save_data_dict["doses"]
        if dose_dict["data"]() is not None and dpg.get_value(dose_dict["dosesum_checkbox_tag"])
    ]
    
    if len(dose_sum_list) > 1 and (
        save_in_bulk or any(
            sender == dose_dict["save_tag"] and dpg.get_value(dose_dict["dosesum_checkbox_tag"])
            for dose_dict in save_data_dict["doses"]
        )
    ):
        save_filename = dosesum_name
        validated_filename = validate_filename(save_filename)
        if validated_filename:
            save_path = join(base_save_path, validated_filename + ".nii")
            
            dose_sum_array = sitk_to_array(dose_sum_list[0])
            for dose_sitk in dose_sum_list[1:]:
                dose_sum_array += sitk_to_array(sitk_resample_to_reference(dose_sitk, dose_sum_list[0]))
            dose_sum_sitk = array_to_sitk(dose_sum_array, dose_sum_list[0], copy_metadata=True)
            dose_sum_sitk.SetMetaData("DoseSummationType", "MULTI_PLAN")
            try:
                sitk.WriteImage(dose_sum_sitk, save_path)
            except Exception as e:
                logger.exception(f"Failed to write combined RT Dose to {save_path}.")
        else:
            logger.error(
                msg=(
                    f"No filename specified for RT Dose Sum. Received: {save_filename}, "
                    f"which was cleaned to: {validated_filename}. Skipping save."
                )
            )
    
    for dose_dict in save_data_dict["doses"]:
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
        save_path = join(base_save_path, validated_filename + ".nii")
        
        dose_sitk_ref: Callable[[], Any] = dose_dict["data"]
        dose_sitk = dose_sitk_ref()
        if dose_sitk is None:
            continue
        
        if keep_custom_params:
            dose_sitk = data_mgr._resample_sitk_to_cached_reference(dose_sitk)
        
        num_dose_fxns = dpg.get_value(dose_dict["num_dose_fxns_tag"])
        num_plan_fxns = dpg.get_value(dose_dict["num_plan_fxns_tag"])
        if num_dose_fxns and num_plan_fxns and num_dose_fxns > 0 and num_plan_fxns > 0 and num_dose_fxns != num_plan_fxns:
            scaling_ratio = num_plan_fxns / num_dose_fxns
            dose_array = sitk_to_array(dose_sitk) * scaling_ratio
            new_dose_sitk = array_to_sitk(dose_array, dose_sitk, copy_metadata=True)
        else:
            new_dose_sitk = dose_sitk
        
        try:
            sitk.WriteImage(new_dose_sitk, save_path)
            logger.info(f"SITK RT Dose saved to: {save_path}")
        except Exception as e:
            logger.exception(f"Failed to write SITK RT Dose to {save_path}.")

