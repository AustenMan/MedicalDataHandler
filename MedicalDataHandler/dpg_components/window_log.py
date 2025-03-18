import dearpygui.dearpygui as dpg
from utils.logger_utils import get_logger
from utils.dpg_utils import get_popup_params
from dpg_components.custom_utils import get_tag
from dpg_components.themes import get_hidden_button_theme

def toggle_logger_display(sender, app_data, user_data):
    """ Toggles the visibility of the logger window in Dear PyGUI. """
    # Get dimensions and position for the logger window
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.595, height_ratio=0.5)
    
    tag_logger_window = get_tag("log_window")
    
    # Create the logger window if it does not exist
    if not dpg.does_item_exist(tag_logger_window):
        logger_tags = []
        dpg.add_window(tag=tag_logger_window, label="Logger", width=popup_width, height=popup_height, pos=popup_pos, show=False, no_close=False, user_data=logger_tags)
        dpg.bind_item_theme(item=tag_logger_window, theme=get_hidden_button_theme())
        dpg.add_button(parent=tag_logger_window, label="LOG BELOW", width=-1)
    
    # Toggle the window's visibility
    is_shown = dpg.is_item_shown(tag_logger_window)
    dpg.configure_item(tag_logger_window, show=not is_shown)
    if not is_shown:
        dpg.configure_item(tag_logger_window, width=popup_width, height=popup_height, collapsed=False, pos=popup_pos)
        dpg.focus_item(tag_logger_window)

def refresh_logger_messages():
    """ Displays log messages from the logger in Dear PyGUI. """
    # Get the logger
    logger = get_logger()
    
    # Update the last GUI response item, if it exists
    tag_lgr_tooltip_text = get_tag("latest_gui_response_tooltip_text")
    if dpg.does_item_exist(tag_lgr_tooltip_text):
        tag_latest_gui_response = get_tag("latest_gui_response")
        latest_msg = logger.handlers[0].get_latest_message()
        content_width = dpg.get_viewport_width() * 0.95
        text_width = dpg.get_text_size("A")[0] * dpg.get_global_font_scale()
        allowed_chars = int((content_width // text_width) - 3)
        if allowed_chars < 1:
            allowed_chars = 100
        dpg.configure_item(tag_latest_gui_response, label=latest_msg[:allowed_chars] + "..." if len(latest_msg) > allowed_chars else latest_msg)
        dpg.configure_item(tag_lgr_tooltip_text, default_value=latest_msg if latest_msg else "No log message to display.")
    
    # Return early if no visible logger window
    tag_logger_window = get_tag("log_window")
    if not dpg.does_item_exist(tag_logger_window) or not dpg.is_item_shown(tag_logger_window):
        return
    
    # Retrieve log messages from the logger's handler
    messages = logger.handlers[0].get_messages()
    if not messages:
        return
    
    # Calculate the wrapping width based on the logger window's size
    content_width = dpg.get_item_rect_size(tag_logger_window)[0]
    wrap_width = content_width - 8 if content_width else 100
    
    # Add or update messages in the logger window
    tag_last_msg = None
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
                before=tag_last_msg if tag_last_msg is not None else 0
            )
        else:
            # Update the existing text item with the latest message
            dpg.configure_item(item=tag, default_value=message, wrap=wrap_width)
        
        # Update the last message tag
        tag_last_msg = tag
