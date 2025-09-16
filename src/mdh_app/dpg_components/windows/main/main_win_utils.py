from __future__ import annotations


import logging
from typing import TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import create_settings_window
from mdh_app.dpg_components.core.utils import get_tag, add_custom_button
from mdh_app.dpg_components.themes.button_themes import get_colored_button_theme, get_hidden_button_theme
from mdh_app.dpg_components.windows.logging.log_window import toggle_logger_display
from mdh_app.dpg_components.windows.data_table.data_table_win import toggle_data_window


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def _fill_mw_settings_table() -> None:
    """Populate the main window with settings buttons."""
    if dpg.get_item_children("mw_top_table", slot=1):
        return
    
    with dpg.table(
        parent="mw_top_table", 
        header_row=False, 
        freeze_rows=1,
        policy=dpg.mvTable_SizingStretchProp, 
        precise_widths=True,
        no_pad_innerX=True,
        no_pad_outerX=True,
        width=-1, 
        height=-1
    ):
        dpg.add_table_column(width_stretch=True)
        dpg.add_table_column(width_stretch=True)
        dpg.add_table_column(width_stretch=True)
        
        tag_row = dpg.generate_uuid()
        with dpg.table_row(tag=tag_row):
            add_custom_button(
                label="Settings", 
                parent_tag=tag_row,
                width=-1,
                height=-1,
                theme_tag=get_colored_button_theme((30, 100, 80)), 
                callback=lambda: create_settings_window(), 
                tooltip_text="Toggles the application settings window."
            )
            add_custom_button(
                label="Event Log", 
                parent_tag=tag_row, 
                width=-1,
                height=-1,
                theme_tag=get_colored_button_theme((85, 60, 130)), 
                callback=toggle_logger_display, 
                tooltip_text="Toggles the log window."
            )
            add_custom_button(
                label="Data Explorer", 
                parent_tag=tag_row, 
                width=-1,
                height=-1,
                theme_tag=get_colored_button_theme((60, 90, 150)), 
                callback=lambda: toggle_data_window(), 
                tooltip_text="Toggles the data window."
            )


def _fill_mw_log() -> None:
    """Populate the main window with the latest log message."""
    if dpg.get_item_children("mw_top_log", slot=1):
        return
    
    tag_latest_gui_response = get_tag("latest_gui_response")
    tag_latest_gui_response_tooltip_text = get_tag("latest_gui_response_tooltip_text")
    add_custom_button(
        tag=tag_latest_gui_response, 
        label="", 
        parent_tag="mw_top_log", 
        width=-2, 
        height=-4, 
        tooltip_tag=tag_latest_gui_response_tooltip_text, 
        theme_tag=get_hidden_button_theme()
    )


def _build_main_window_layout() -> str:
    """
    Return the main window layout as a string.

    NOTE:
        Ensure all rules are followed with \n and \t characters.
        The returned string ***must*** use TAB characters for indentation and newlines for line breaks.
        
        ***I do not recommend making changes.***
        Changes to the layout may have downstream impacts.

    Returns:
        A string representing the dashboard layout.
    """
    return (
        "LAYOUT dashboard left top\n"
        "\tCOL mw_overall None\n"
        "\t\tROW None\n"
        "\t\t\tCOL mw_top_table None center center\n"
        "\t\tROW None\n"
        "\t\t\tCOL mw_top_log None center center\n"
        "\t\tROW 0.88\n"
        "\t\t\tCOL mw_ctr None\n"
        "\t\t\t\tROW None\n"
        "\t\t\t\t\tCOL mw_ctr_topleft None center center\n"
        "\t\t\t\t\tCOL mw_ctr_topright None center center\n"
        "\t\t\t\tROW None\n"
        "\t\t\t\t\tCOL mw_ctr_bottomleft None center center\n"
        "\t\t\t\t\tCOL mw_ctr_bottomright None center center\n"
        "\t\t\tCOL mw_right 0.3 center top\n"
    )

