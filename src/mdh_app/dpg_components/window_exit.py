import logging
import dearpygui.dearpygui as dpg
from typing import Any, Union

from mdh_app.dpg_components.custom_utils import get_tag, get_user_data
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params

logger = logging.getLogger(__name__)

def exit_callback(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Callback function to exit the program safely.

    This function disables the exit button, updates its label to indicate the exit process,
    shuts down the shared state manager, and stops the Dear PyGUI context.

    Args:
        sender: The tag of the exit button that triggered this callback.
        app_data: Additional event data (unused).
        user_data: The return button tag to be removed.
    """
    # Get & remove the return button
    return_button = user_data
    safe_delete(return_button)
    
    # Disable the exit button and update its text
    dpg.disable_item(sender)
    dpg.configure_item(sender, label="SAFELY EXITING, PLEASE WAIT...")
    
    # Shutdown the shared state manager
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    ss_mgr.shutdown_manager()
    
    # Stop the DPG context, which returns to the __init__.py cleanup function
    dpg.stop_dearpygui()

def create_exit_popup() -> None:
    """
    Create and display an exit confirmation popup.

    The popup window offers two options: "RETURN TO PROGRAM" to cancel exit, and
    "EXIT PROGRAM" to proceed with shutting down the application.
    """
    tag_exit_window = get_tag("exit_window")
    
    if dpg.does_item_exist(tag_exit_window):
        return

    popup_W, popup_H, popup_pos = get_popup_params()
    button_WH = round(popup_W * 0.3), round(popup_H * 0.1)
    button_X = (popup_W - button_WH[0]) // 2
    occupied_Y = round(3 * button_WH[1])
    current_Y = (popup_H - occupied_Y) // 2
    
    with dpg.window(
        tag=tag_exit_window, 
        width=popup_W, 
        height=popup_H, 
        pos=popup_pos,
        no_resize=True, 
        no_title_bar=True, 
        no_move=True, 
        no_collapse=True,
        no_close=True, 
        modal=True, 
        no_open_over_existing_popup=False,
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
