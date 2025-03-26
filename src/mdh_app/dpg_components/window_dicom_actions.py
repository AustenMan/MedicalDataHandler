import logging
import dearpygui.dearpygui as dpg
from typing import Any, Union

from mdh_app.dpg_components.cleanup import cleanup_wrapper
from mdh_app.dpg_components.custom_utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes import get_pbar_theme
from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.dicom_manager import DicomManager
from mdh_app.utils.dpg_utils import get_popup_params

logger = logging.getLogger(__name__)

def create_dicom_action_window(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Create a popup window for searching and processing DICOM files in a specified directory.
    
    The window includes a progress bar and two buttons: one to choose a DICOM directory 
    and another to start linking DICOM files.
    
    Args:
        sender: The tag of the UI element triggering this action.
        app_data: Additional event data (unused).
        user_data: Custom user data (unused).
    """
    # Get necessary params
    tag_action_window = get_tag("action_window")
    tag_pbar = get_tag("pbar")
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params(height_ratio=0.3)
    
    # If already exists, toggle visibility and return
    if dpg.does_item_exist(tag_action_window):
        is_shown = dpg.is_item_shown(tag_action_window)
        dpg.configure_item(tag_action_window, show=not is_shown)
        if not is_shown:
            dpg.configure_item(tag_action_window, width=popup_width, height=popup_height, collapsed=False, pos=popup_pos)
            dpg.focus_item(tag_action_window)
        return
    
    # Create the window
    dpg.add_window(
        tag=tag_action_window, 
        label="DICOM Actions", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        no_title_bar=False, 
        no_collapse=True, 
        on_close=lambda: dpg.hide_item(tag_action_window)
    )
    
    # Add the progress bar
    dpg.add_progress_bar(
        tag=tag_pbar, 
        parent=tag_action_window, 
        width=size_dict["button_width"], 
        height=size_dict["button_height"],
        default_value=0, 
        overlay="Ready to find or link DICOM files. Choose an action below...",
    )
    dpg.bind_item_theme(dpg.last_item(), get_pbar_theme())
    
    # Add buttons
    add_custom_button(
        label="Choose a DICOM directory", 
        parent_tag=tag_action_window, 
        callback=cleanup_wrapper(_get_directory), 
        add_spacer_before=True, 
        add_spacer_after=True
    )
    add_custom_button(
        label="Start Linking DICOM Files", 
        parent_tag=tag_action_window, 
        callback=cleanup_wrapper(_start_link_dicoms),
        add_spacer_before=True, 
        add_spacer_after=True
    )

def _get_directory(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Open a file dialog to select a DICOM directory, then start processing the directory."""
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    popup_width, popup_height, popup_pos = get_popup_params(height_ratio=0.5)
    tag_fd = dpg.generate_uuid()
    
    dpg.add_file_dialog(
        tag=tag_fd,
        label="Choose a directory containing DICOM files",
        directory_selector=True,
        default_path=conf_mgr.get_project_dir(),
        modal=True,
        callback=cleanup_wrapper(_start_processing_directory),
        width=popup_width,
        height=popup_height,
    )

def _start_processing_directory(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Start processing the selected DICOM directory."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    dcm_mgr.process_dicom_directory(app_data.get("file_path_name"))

def _start_link_dicoms(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Start linking DICOM files in the selected directory."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    dcm_mgr.link_all_dicoms()
