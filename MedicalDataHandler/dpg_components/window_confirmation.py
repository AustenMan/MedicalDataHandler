import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag
from utils.dpg_utils import safe_delete, get_popup_params

def create_confirmation_popup(button_callback, button_theme, no_close=False, confirmation_text="Proceeding, please wait...", warning_string="Confirm action: ", close_callback=None):
    """
    Create a confirmation popup with customizable options.
    
    Args:
        button_callback (Callable): The function to call when the confirmation button is clicked.
        button_theme (int, str, None): The theme to apply to the confirmation button.
        no_close (bool): If True, the popup window cannot be closed. Defaults to False.
        confirmation_text (str): The text to display when the confirmation button is clicked.
        warning_string (str): The warning message to display.
    
    Raises:
        ValueError: If any input parameters are invalid.
    """
    if not callable(button_callback):
        raise ValueError("Button callback must be a callable function.")
    if button_theme is not None and (not isinstance(button_theme, (int, str)) or not dpg.does_item_exist(button_theme)):
        raise ValueError("Button theme must be None, or a valid string or integer tag for an existing DearPyGui item.")
    
    tag_conf_popup = get_tag("confirmation_popup")
    safe_delete(tag_conf_popup)
    
    # Wrapper to handle the modification of the button after the callback is executed
    def modify_button_after_callback(sender, app_data, user_data):
        safe_delete(tag_conf_popup, children_only=True)
        dpg.add_button(parent=tag_conf_popup, label=confirmation_text, width=-1, height=button_height)
        dpg.bind_item_theme(item=dpg.last_item(), theme=button_theme)
        button_callback()
        safe_delete(tag_conf_popup)
    
    # Get popup dimensions and position
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.5, height_ratio=0.5)  # Assuming this is a helper function defined elsewhere
    button_height = round(popup_height // 10)
    
    def wrapped_close_callback(sender, app_data, user_data):
        if close_callback is not None:
            close_callback()
        safe_delete(tag_conf_popup)
    
    # Create the confirmation popup window
    with dpg.window(
        tag=tag_conf_popup, 
        label="User Confirmation Request", 
        width=popup_width, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        popup=True,
        modal=True, 
        no_title_bar=False, 
        no_close=no_close, 
        on_close=wrapped_close_callback
        ):
        
        # Add a button to confirm the action
        dpg.add_button(label=warning_string, width=-1, height=button_height)
        dpg.bind_item_theme(item=dpg.last_item(), theme=button_theme)
        
        # Add separator and spacer for spacing between buttons
        dpg.add_separator()
        dpg.add_spacer(height=button_height // 2)
        
        # Add the proceed button with a callback
        dpg.add_button(label="Proceed", width=-1, height=button_height, callback=modify_button_after_callback)
        dpg.add_spacer(height=button_height // 2)
        dpg.add_button(label="Go back", width=-1, height=button_height, callback=wrapped_close_callback)
