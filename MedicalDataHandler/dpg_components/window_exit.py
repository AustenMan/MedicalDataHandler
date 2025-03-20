import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data
from utils.dpg_utils import safe_delete, get_popup_params

def exit_callback(sender, app_data, user_data):
    """Callback function for exiting the program."""
    # Get & remove the return button
    return_button = user_data
    safe_delete(return_button)
    
    # Disable the exit button and update its text
    dpg.disable_item(sender)
    dpg.configure_item(sender, label="SAFELY EXITING, PLEASE WAIT...")
    
    # Shutdown the shared state manager
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.shutdown_manager()
    
    # Stop the DPG context, which returns to the __init__.py cleanup function
    dpg.stop_dearpygui()

def create_exit_popup():
    """Creates the exit confirmation popup."""
    tag_exit_window = get_tag("exit_window")
    
    if dpg.does_item_exist(tag_exit_window):
        return

    popup_W, popup_H, popup_pos = get_popup_params()
    button_WH = round(popup_W * 0.3), round(popup_H * 0.1)
    button_X = (popup_W - button_WH[0]) // 2
    occupied_Y = round(3 * button_WH[1])
    current_Y = (popup_H - occupied_Y) // 2
    
    with dpg.window(
        tag=tag_exit_window, width=popup_W, height=popup_H, pos=popup_pos,
        autosize=False, no_resize=True, no_title_bar=True, no_move=True, no_collapse=True,
        no_close=True, no_background=False, modal=True, no_open_over_existing_popup=False,
        no_scroll_with_mouse=False, on_close=lambda: safe_delete(tag_exit_window), show=True
    ):
        with dpg.group(horizontal=False):
            return_button = dpg.add_button(
                label="RETURN TO PROGRAM", 
                callback=lambda: safe_delete(tag_exit_window),
                width=button_WH[0], 
                height=button_WH[1], 
                pos=(button_X, current_Y)
                )
            
            current_Y += round(2 * button_WH[1])
            
            dpg.add_button(
                label="EXIT PROGRAM", 
                callback=exit_callback, 
                user_data=return_button,
                width=button_WH[0], 
                height=button_WH[1], 
                pos=(button_X, current_Y)
                )
