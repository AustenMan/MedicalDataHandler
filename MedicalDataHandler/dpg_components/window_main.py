import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, add_custom_button
from dpg_components.layout import add_layout
from dpg_components.themes import get_hidden_button_theme, get_colored_button_theme
from dpg_components.window_data import toggle_data_window
from dpg_components.window_dicom_actions import create_dicom_action_window
from dpg_components.window_settings import create_settings_window
from dpg_components.window_log import toggle_logger_display

def create_main_window():
    """ Creates the main window. """
    tag_main_window = get_tag("main_window")
    
    # Create the main window if it does not exist
    if not dpg.does_item_exist(tag_main_window):
        dpg.add_window(
            tag=tag_main_window, no_open_over_existing_popup=False,
            no_title_bar=True, no_collapse=True, no_resize=True, horizontal_scrollbar=True, no_scrollbar=True, 
            no_close=True, no_move=True, width=-1, height=-1,
        )
        
        dpg.set_primary_window(tag_main_window, True)
        
        add_layout(layout=_build_main_window_layout(), parent=tag_main_window, border=True, debug=False, resizable=True)
        
        for _ in range(10):
            dpg.render_dearpygui_frame()
        
        # Set zero padding on the main window theme
        main_window_theme = dpg.get_item_theme(tag_main_window)
        with dpg.theme_component(dpg.mvAll, parent=main_window_theme):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
    
    _fill_top_row_gui_status()
    _fill_main_window_left_column()
    create_settings_window()

def _fill_top_row_gui_status():
    """ Fills the main window's top row. """
    tag_latest_gui_response = get_tag("latest_gui_response")
    if dpg.does_item_exist(tag_latest_gui_response):
        return
    
    tag_latest_gui_response_tooltip_text = get_tag("latest_gui_response_tooltip_text")
    add_custom_button(tag=tag_latest_gui_response, label="", parent_tag="mw_top", width=-1, height=-1, tooltip_tag=tag_latest_gui_response_tooltip_text, theme_tag=get_hidden_button_theme())

def _fill_main_window_left_column():
    """ Fills the main window's second row, left column. """
    if dpg.get_item_children("mw_left", slot=1):
        return
    
    add_custom_button(label="Settings", parent_tag="mw_left", theme_tag=get_colored_button_theme((30, 100, 80)), callback=lambda: create_settings_window(), add_spacer_before=True, add_separator_after=True, tooltip_text="Manage application settings.")
    add_custom_button(label="Log", parent_tag="mw_left", theme_tag=get_colored_button_theme((85, 60, 130)), callback=toggle_logger_display, add_separator_after=True, tooltip_text="Toggles the display of the log window.")
    add_custom_button(label="Add New Data", parent_tag="mw_left", theme_tag=get_colored_button_theme((180, 100, 45)), callback=create_dicom_action_window, add_separator_after=True, tooltip_text="Start here to add data to the program.\n1) Find DICOM files in a directory\n2) Link the files\n3) Use 'View Data' and reload the table.")
    add_custom_button(label="Explore Data", parent_tag="mw_left", theme_tag=get_colored_button_theme((60, 90, 150)), callback=lambda: toggle_data_window(), add_separator_after=True, tooltip_text="Toggles the display of the data window.")

def _build_main_window_layout():
    ### You ***must*** ensure the use of ***TABS*** in the returned string, not spaces! I do not recommend making any changes, as there WILL be many downstream impacts to consider. ###
    ### When editing layout, make sure to replace 4 consecutive spaces with a tab (	) to avoid errors ###
    return '''
LAYOUT dashboard left top
	COL mw_overall None
		ROW None
			COL mw_top None center center
		ROW 0.96
			COL mw_left 0.10 center top
			COL mw_ctr None
				ROW None
					COL mw_ctr_topleft None center center
					COL mw_ctr_topright None center center
				ROW None
					COL mw_ctr_bottomleft None center center
					COL mw_ctr_bottomright None center center
			COL mw_right 0.3 center top
'''
