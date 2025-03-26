import logging
import dearpygui.dearpygui as dpg
from typing import Any, List, Optional, Union

from mdh_app.utils.logger_utils import BufferHandler, get_root_logger
from mdh_app.utils.dpg_utils import get_popup_params
from mdh_app.dpg_components.custom_utils import get_tag
from mdh_app.dpg_components.themes import get_hidden_button_theme

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

def refresh_logger_messages() -> None:
    """
    Refresh the log window by updating its text items with the latest log messages (from the root logger).

    This function truncates the latest log message to fit the available space and updates a
    designated tooltip item. It then iterates over all log messages provided by the logger's
    primary handler and adds or updates text items in the log window accordingly.
    """
    # Get the root logger
    root_logger: logging.Logger = get_root_logger()
    
    # Get messages from the buffer handler
    buffer_handler: Optional[BufferHandler] = None
    if root_logger.handlers and any(isinstance(handler, BufferHandler) for handler in root_logger.handlers):
        buffer_handler = [handler for handler in root_logger.handlers if isinstance(handler, BufferHandler)][0]
    
    # Update the last GUI response item, if it exists
    tag_lgr_tooltip_text = get_tag("latest_gui_response_tooltip_text")
    if dpg.does_item_exist(tag_lgr_tooltip_text):
        tag_latest_gui_response = get_tag("latest_gui_response")
        latest_msg: Optional[str] = buffer_handler.get_latest_message() if buffer_handler else ""
        if latest_msg:
            # Get available space for the text
            content_width = dpg.get_viewport_client_width()
            # Calculate text width
            text_width = dpg.get_text_size(latest_msg)[0] * dpg.get_global_font_scale()
            # Calculate how many characters fit in the available space, minus 2 for padding
            allowed_chars = int(len(latest_msg) * (content_width / text_width)) - 2
            # Ensure at least 50 characters are displayed, in case of issues with the calculation
            allowed_chars = max(allowed_chars, 50)
            # Truncate if needed
            truncated_msg = latest_msg[:allowed_chars-3] + "..." if len(latest_msg) > allowed_chars else latest_msg
            dpg.configure_item(tag_latest_gui_response, label=truncated_msg)
        dpg.configure_item(tag_lgr_tooltip_text, default_value=latest_msg if latest_msg else "No log message to display.")
    
    # Return early if no visible log window
    tag_logger_window = get_tag("log_window")
    if not dpg.does_item_exist(tag_logger_window) or not dpg.is_item_shown(tag_logger_window):
        return
    
    # Calculate the wrapping width based on the log window's size
    content_width = dpg.get_item_rect_size(tag_logger_window)[0]
    wrap_width = content_width - 8 if content_width else 100
    
    # Add or update messages in the log window
    tag_last_msg: Optional[Union[str, int]] = None
    backup_messages = ["No log messages to display yet."]
    messages: List[str] = buffer_handler.get_messages() if buffer_handler else []
    if not messages:
        messages = backup_messages
    for message_idx, message in enumerate(messages, start=1):
        tag = f"logger_message_{message_idx}"
        
        if not dpg.does_item_exist(tag):
            # Create a new text item for the log message
            dpg.add_text(
                tag=tag, 
                parent=tag_logger_window, 
                default_value=message, 
                wrap=wrap_width, 
                bullet=True, 
                before=tag_last_msg if tag_last_msg is not None else 0,
            )
        else:
            # Update the existing text item with the latest message
            dpg.configure_item(item=tag, default_value=message, wrap=wrap_width)
        
        # Update the last message tag
        tag_last_msg = tag
