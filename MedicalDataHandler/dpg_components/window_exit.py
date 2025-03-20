import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag
from utils.dpg_utils import safe_delete, get_popup_params

def create_exit_popup():
    """Creates the exit confirmation popup."""
    tag_exit_window = get_tag("exit_window")
    
    safe_delete(tag_exit_window)

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
            dpg.add_button(
                label="RETURN TO PROGRAM", 
                callback=lambda: safe_delete(tag_exit_window),
                width=button_WH[0], 
                height=button_WH[1], 
                pos=(button_X, current_Y)
                )
            
            current_Y += round(2 * button_WH[1])
            
            dpg.add_button(
                label="EXIT PROGRAM", 
                callback=dpg.stop_dearpygui, 
                width=button_WH[0], 
                height=button_WH[1], 
                pos=(button_X, current_Y)
                )
