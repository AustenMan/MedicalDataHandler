from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes.progress_themes import get_pbar_theme
from mdh_app.dpg_components.windows.dicom_search.dcm_search_utils import _get_directory
from mdh_app.utils.dpg_utils import get_popup_params


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def create_dicom_action_window(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Create a window for DICOM actions in the GUI.
    The window includes a progress bar a button to choose a directory containing DICOM files.
    
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
        overlay="Ready to find DICOM files. Choose an action below...",
    )
    dpg.bind_item_theme(dpg.last_item(), get_pbar_theme())
    
    # Add buttons
    add_custom_button(
        label="Choose a DICOM directory", 
        parent_tag=tag_action_window, 
        callback=wrap_with_cleanup(_get_directory), 
        add_spacer_before=True, 
        add_spacer_after=True
    )
