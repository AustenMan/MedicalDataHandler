from __future__ import annotations


import logging
from typing import TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import create_settings_window
from mdh_app.dpg_components.core.layout_system import add_layout
from mdh_app.dpg_components.core.utils import get_tag
from mdh_app.dpg_components.windows.main.main_win_utils import _fill_mw_settings_table, _build_main_window_layout, _fill_mw_log


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def create_main_window() -> None:
    """
    Create and configure the main application window.

    This function initializes the main window if it does not exist, sets it as the primary
    window, applies a custom layout with tabs, and then fills in status and control panels.
    Finally, it creates the settings window.
    """
    tag_main_window = get_tag("main_window")
    
    # Create the main window if it does not exist
    if not dpg.does_item_exist(tag_main_window):
        dpg.add_window(
            tag=tag_main_window, 
            no_open_over_existing_popup=False,
            no_title_bar=True, 
            no_collapse=True, 
            no_resize=True, 
            horizontal_scrollbar=False, 
            no_scrollbar=True, 
            no_close=True, 
            no_move=True, 
            width=-1, 
            height=-1,
        )
        
        dpg.set_primary_window(tag_main_window, True)
        
        add_layout(
            layout=_build_main_window_layout(), 
            parent=tag_main_window, 
            border=True, 
            debug=False, 
            resizable=True
        )
        
        # Render several frames until the main window theme is available
        while not dpg.get_item_theme(tag_main_window):
            dpg.render_dearpygui_frame()
        
        # Set zero padding on the main window theme
        main_window_theme = dpg.get_item_theme(tag_main_window)
        with dpg.theme_component(dpg.mvAll, parent=main_window_theme):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
    
    _fill_mw_settings_table()
    _fill_mw_log()
    create_settings_window()

