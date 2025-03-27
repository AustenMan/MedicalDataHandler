import logging
import dearpygui.dearpygui as dpg
from time import sleep
from functools import partial
from typing import Callable, Optional, Any, Union

from mdh_app.dpg_components.custom_utils import get_tag, get_user_data
from mdh_app.dpg_components.texture_updates import request_texture_update
from mdh_app.dpg_components.window_settings import create_settings_window
from mdh_app.dpg_components.themes import get_hidden_button_theme
from mdh_app.dpg_components.window_confirmation import create_confirmation_popup
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.managers.data_manager import DataManager
from mdh_app.managers.dicom_manager import DicomManager
from mdh_app.utils.dpg_utils import safe_delete
from mdh_app.utils.general_utils import get_traceback

logger = logging.getLogger(__name__)

def cleanup_wrapper(action: Optional[Callable[[Any, Any, Any], None]] = None) -> Callable:
    """
    Returns a DPG-compatible callback that wraps the given action with cleanup logic.

    Args:
        action: A callable accepting (sender, app_data, user_data), to be run after cleanup.

    Returns:
        A function to use as a DPG callback.
    """
    def wrapped(sender, app_data, user_data):
        ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
        data_mgr: DataManager = get_user_data(td_key="data_manager")

        if ss_mgr.cleanup_event.is_set():
            logger.warning("Cleanup already in progress.")
            return
        
        # If no data is loaded and no action is active, simply submit the action.
        if action is not None and not data_mgr.check_if_data_loaded("any") and not ss_mgr.is_action_in_progress():
            ss_mgr.submit_action(partial(action, sender, app_data, user_data))
            return

        def _execute_action() -> None:
            try:
                ss_mgr.cleanup_event.set()
                while ss_mgr.is_action_in_progress():
                    sleep(0.1)
                with ss_mgr.thread_lock:
                    if data_mgr.check_if_data_loaded("any"):
                        data_mgr.clear_data()
                        _reset_gui_layout()
                        logger.info("Cleanup complete.")
                ss_mgr.cleanup_event.clear()
                if action is not None:
                    ss_mgr.submit_action(partial(action, sender, app_data, user_data))
                safe_delete(get_tag("confirmation_popup"))
            except Exception as e:
                logger.error(f"Failed to perform cleanup." + get_traceback(e))

        create_confirmation_popup(
            button_callback=partial(ss_mgr.start_cleanup, _execute_action),
            button_theme=get_hidden_button_theme(),
            no_close=True,
            confirmation_text="An action is in progress. Cancel it and clear data?",
            warning_string="Cancelling will clear loaded data and stop ongoing tasks."
        )

    return wrapped

def _reset_gui_layout() -> None:
    """
    Reset the GUI layout to its default state by deleting specific windows and popups,
    clearing layout container children, resetting texture values, and reinitializing settings.
    """
    # Delete windows/popups that relate to loaded patient data
    tags_to_delete = [
        get_tag("settings_window"), 
        get_tag("color_picker_popup"), 
        get_tag("inspect_ptobj_window"),
        get_tag("inspect_dicom_popup"),
        get_tag("inspect_sitk_popup"),
        get_tag("save_sitk_window")
    ]
    safe_delete(tags_to_delete)
    
    # Delete children of these (keep the parents so we don't break the layout structure)
    layout_tags = ["mw_ctr_topleft", "mw_ctr_topright", "mw_ctr_bottomleft", "mw_ctr_bottomright", "mw_right"]
    safe_delete(layout_tags, children_only=True)
    
    # Get texture tags
    tag_ax_texture = get_tag("axial_dict")["texture"]
    tag_cor_texture = get_tag("coronal_dict")["texture"]
    tag_sag_texture = get_tag("sagittal_dict")["texture"]
    
    # Get texture values
    axial_val = dpg.get_value(tag_ax_texture)
    coronal_val = dpg.get_value(tag_cor_texture)
    sagittal_val = dpg.get_value(tag_sag_texture)
    
    # Reset texture values
    if axial_val is not None:
        axial_val[:] = 0
    if coronal_val is not None:
        coronal_val[:] = 0
    if sagittal_val is not None:
        sagittal_val[:] = 0
    
    create_settings_window(refresh=True)
    request_texture_update(texture_action_type="reset")

def _confirm_remove_all_func(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Remove all patient data objects after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    
    def delete_all_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_all_patient_data_objects()
        safe_delete(tag_data_window)
    
    def submit_remove_all_func(sender, app_data, user_data) -> None:
        clean_wrap = cleanup_wrapper(delete_all_func)
        clean_wrap(sender, app_data, user_data)
    
    create_confirmation_popup(
        button_callback=submit_remove_all_func,
        confirmation_text="Removing all data from the program",
        warning_string=(
            f"Are you sure you want to remove ALL patient data from the program?\n"
            "This action is irreversible. You would need to re-import the data to access it again.\n"
            "Remove ALL patient data?"
        ),
        second_confirm=True
    )