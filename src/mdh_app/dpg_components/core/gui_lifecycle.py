from __future__ import annotations


import logging
from time import sleep
from functools import partial
from typing import TYPE_CHECKING, Callable, Optional, Any, Union, Dict


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme
from mdh_app.dpg_components.windows.confirmation.confirm_window import create_confirmation_popup
from mdh_app.dpg_components.widgets.settings.data_settings import add_spacing_controls, add_rot_flip_controls
from mdh_app.dpg_components.widgets.settings.display_settings import add_data_view_controls, add_data_windowing_controls, add_overlay_controls
from mdh_app.dpg_components.widgets.settings.gui_settings import add_gui_controls, add_program_controls
from mdh_app.dpg_components.widgets.settings.interaction_settings import add_interaction_controls
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.shared_state_manager import SharedStateManager
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.managers.dicom_manager import DicomManager


logger = logging.getLogger(__name__)


def create_settings_window(refresh: bool = False) -> None:
    """
    Create and manage the Settings window with various configuration options.
    
    If refresh is True, the window is deleted and recreated.
    Otherwise, if the window exists, its visibility and dimensions are toggled.
    """
    # Get tag and check if the window should be refreshed
    tag_isw = get_tag("settings_window")
    
    # Get popup params
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # If refresh is requested, delete the window and make a new one
    if refresh:
        safe_delete(tag_isw)
    # Toggle the window, also keep its size/position updated
    elif dpg.does_item_exist(tag_isw):
        show_popup = not dpg.is_item_shown(tag_isw)
        if show_popup:
            dpg.configure_item(tag_isw, width=popup_width, height=popup_height, pos=popup_pos, show=show_popup)
        else:
            dpg.configure_item(tag_isw, show=show_popup)
        return
    
    # Get necessary parameters
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    size_dict: Dict[str, Any] = get_user_data(td_key="size_dict")
    default_display_dict: Dict[str, Any] = get_user_data(td_key="default_display_dict")
    
    # Create the window
    dpg.add_window(
        tag=tag_isw, 
        label="Settings", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos,
        no_open_over_existing_popup=False, 
        show=False, 
        on_close=lambda: dpg.configure_item(tag_isw, show=False)
    )
    
    # Fill the window
    add_gui_controls(tag_isw, size_dict, conf_mgr)
    add_overlay_controls(tag_isw, size_dict)
    add_interaction_controls(tag_isw, size_dict, conf_mgr)
    add_rot_flip_controls(tag_isw, size_dict, default_display_dict)
    add_data_view_controls(tag_isw, size_dict, default_display_dict)
    add_data_windowing_controls(tag_isw, size_dict, conf_mgr, default_display_dict)
    add_spacing_controls(tag_isw, size_dict, conf_mgr, default_display_dict)
    add_program_controls(tag_isw, size_dict, confirm_remove_all_data)


def wrap_with_cleanup(action: Optional[Callable[[Any, Any, Any], None]] = None) -> Callable:
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
        if action is not None and not data_mgr.is_any_data_loaded and not ss_mgr.is_action_in_progress():
            ss_mgr.submit_action(partial(action, sender, app_data, user_data))
            return

        def _execute_action() -> None:
            try:
                ss_mgr.cleanup_event.set()
                while ss_mgr.is_action_in_progress():
                    sleep(0.1)
                with ss_mgr.thread_lock:
                    if data_mgr.is_any_data_loaded:
                        data_mgr.clear_data()
                        _reset_gui_layout()
                        logger.info("Cleanup complete.")
                ss_mgr.cleanup_event.clear()
                if action is not None:
                    ss_mgr.submit_action(partial(action, sender, app_data, user_data))
                safe_delete(get_tag("confirmation_popup"))
            except Exception as e:
                logger.exception(f"Failed to perform cleanup!")

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
        get_tag("inspect_data_popup"),
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


def confirm_remove_all_data(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Remove all patient data objects after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    
    def delete_all_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_all_patient_data_objects()
        safe_delete(tag_data_window)
    
    def submit_remove_all_func(sender, app_data, user_data) -> None:
        clean_wrap = wrap_with_cleanup(delete_all_func)
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
