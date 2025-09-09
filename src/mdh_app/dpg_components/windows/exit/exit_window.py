from __future__ import annotations


import logging
from typing import TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag
from mdh_app.dpg_components.windows.exit.exit_utils import exit_callback
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


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
