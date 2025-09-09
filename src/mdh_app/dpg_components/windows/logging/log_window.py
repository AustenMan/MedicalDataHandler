from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme
from mdh_app.utils.dpg_utils import get_popup_params


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def toggle_logger_display(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Toggle the visibility of the log window in the Dear PyGUI interface.

    If the log window does not exist, it is created with a bound hidden-button theme and
    a default "LOG BELOW" button. When toggled to show, the window is configured with updated
    dimensions and focused.

    Args:
        sender: The tag of the UI element that triggered the action.
        app_data: Additional event data (unused).
        user_data: Custom user data (unused).
    """
    # Get dimensions and position for the log window
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.595, height_ratio=0.5)
    
    tag_logger_window = get_tag("log_window")
    
    # Create the log window if it does not exist
    if not dpg.does_item_exist(tag_logger_window):
        logger_tags = []
        dpg.add_window(
            tag=tag_logger_window, 
            label="Log", 
            width=popup_width, 
            height=popup_height, 
            pos=popup_pos, 
            show=False, 
            user_data=logger_tags,
            
        )
        dpg.bind_item_theme(item=tag_logger_window, theme=get_hidden_button_theme())
        dpg.add_button(parent=tag_logger_window, label="LOG BELOW", width=-1)
    
    # Toggle the window's visibility
    is_shown = dpg.is_item_shown(tag_logger_window)
    dpg.configure_item(tag_logger_window, show=not is_shown)
    if not is_shown:
        dpg.configure_item(tag_logger_window, width=popup_width, height=popup_height, collapsed=False, pos=popup_pos)
        dpg.focus_item(tag_logger_window)

