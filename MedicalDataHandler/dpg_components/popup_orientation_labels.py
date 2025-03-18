import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data
from dpg_components.texture_updates import request_texture_update
from utils.dpg_utils import safe_delete

def create_orientation_label_color_picker(sender, app_data, user_data):
    """ Creates a popup color picker to choose the color for orientation labels. """
    tag_ol_window = get_tag("color_picker_popup")
    config_manager = get_user_data(td_key="config_manager")
    
    if dpg.does_item_exist(tag_ol_window):
        safe_delete(tag_ol_window, children_only=True)
        dpg.configure_item(tag_ol_window, label="Choose Orientation Label Color", popup=True, show=True)
    else:
        dpg.add_window(tag=tag_ol_window, label="Choose Orientation Label Color", popup=True)
    
    dpg.add_color_picker(
        parent=tag_ol_window, 
        default_value=config_manager.get_orientation_label_color(), 
        callback=_update_orientation_label_color, 
        alpha_bar=True, 
        no_alpha=False,
    )
    dpg.add_button(
        parent=tag_ol_window, 
        label="Close", 
        callback=lambda: safe_delete(tag_ol_window)
    )

def _update_orientation_label_color(sender, app_data, user_data):
    """
    Updates the orientation label color based on the selected value from the color picker.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (list): The selected color as a list of RGBA values.
        user_data (any): Custom user data passed to the callback.
    """
    new_color = tuple([round(min(max(255 * x, 0), 255)) for x in app_data])
    
    config_manager = get_user_data(td_key="config_manager")
    config_manager.update_setting("orientation_label_color", new_color)
    
    request_texture_update(texture_action_type="update")
