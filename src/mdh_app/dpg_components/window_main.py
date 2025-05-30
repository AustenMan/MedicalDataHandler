import logging
import dearpygui.dearpygui as dpg

from mdh_app.dpg_components.custom_utils import get_tag, add_custom_button
from mdh_app.dpg_components.layout import add_layout
from mdh_app.dpg_components.themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.dpg_components.window_data import toggle_data_window
from mdh_app.dpg_components.window_dicom_actions import create_dicom_action_window
from mdh_app.dpg_components.window_settings import create_settings_window
from mdh_app.dpg_components.window_log import toggle_logger_display

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
                label="Log", 
                parent_tag=tag_row, 
                width=-1,
                height=-1,
                theme_tag=get_colored_button_theme((85, 60, 130)), 
                callback=toggle_logger_display, 
                tooltip_text="Toggles the log window."
            )
            add_custom_button(
                label="Add New Data", 
                parent_tag=tag_row, 
                width=-1,
                height=-1,
                theme_tag=get_colored_button_theme((180, 100, 45)), 
                callback=create_dicom_action_window, 
                tooltip_text="Start here to add data to the program.\n1) Find DICOM files in a directory\n2) Link the files\n3) Use 'View Data' and reload the table."
            )
            add_custom_button(
                label="Explore Data", 
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
        I do not recommend making changes. Changes to the layout may have downstream impacts.

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