from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Union


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.windows.orientation_labels.ori_labels_utilities import _update_orientation_label_color
from mdh_app.utils.dpg_utils import safe_delete


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def create_orientation_label_color_picker(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Create and display a popup color picker for orientation label color selection.
    
    Args:
        sender: The tag of the UI element triggering the color picker.
        app_data: Additional event data (unused).
        user_data: Custom user data (unused).
    """
    tag_ol_window = get_tag("color_picker_popup")
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    
    if dpg.does_item_exist(tag_ol_window):
        safe_delete(tag_ol_window, children_only=True)
        dpg.configure_item(tag_ol_window, label="Choose Orientation Label Color", popup=True, show=True)
    else:
        dpg.add_window(tag=tag_ol_window, label="Choose Orientation Label Color", popup=True)
    
    dpg.add_color_picker(
        parent=tag_ol_window, 
        default_value=conf_mgr.get_orientation_label_color(), 
        callback=_update_orientation_label_color, 
        alpha_bar=True, 
        no_alpha=False,
    )
    dpg.add_button(
        parent=tag_ol_window, 
        label="Close", 
        callback=lambda: safe_delete(tag_ol_window)
    )

