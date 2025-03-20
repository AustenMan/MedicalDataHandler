import dearpygui.dearpygui as dpg
from dpg_components.cleanup import cleanup_wrapper
from dpg_components.custom_utils import get_tag, get_user_data, add_custom_button
from dpg_components.themes import get_pbar_theme
from utils.dpg_utils import get_popup_params, safe_delete
from utils.general_utils import get_traceback

def create_dicom_action_window(sender, app_data, user_data):
    """ Creates a popup for searching and processing DICOM files within a specified directory. """
    # Get necessary params
    tag_action_window = get_tag("action_window")
    tag_pbar = get_tag("pbar")
    size_dict = get_user_data(td_key="size_dict")
    dicom_manager = get_user_data(td_key="dicom_manager")
    popup_width, popup_height, popup_pos = get_popup_params(height_ratio=0.3)
    
    # If already exists, toggle visibility and return
    if dpg.does_item_exist(tag_action_window):
        is_shown = dpg.is_item_shown(tag_action_window)
        dpg.configure_item(tag_action_window, show=not is_shown)
        if not is_shown:
            dpg.configure_item(tag_action_window, width=popup_width, height=popup_height, collapsed=False, pos=popup_pos)
            dpg.focus_item(tag_action_window)
        return
    
    # Create the window
    dpg.add_window(
        tag=tag_action_window, 
        label="DICOM Actions", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        no_title_bar=False, 
        no_collapse=True, 
        on_close=lambda: safe_delete(tag_action_window)
    )
    
    # Add the progress bar
    dpg.add_progress_bar(
        tag=tag_pbar, 
        parent=tag_action_window, 
        width=size_dict["button_width"], 
        height=size_dict["button_height"],
        default_value=0, 
        overlay="Ready to find or link DICOM files. Choose an action below...",
    )
    dpg.bind_item_theme(dpg.last_item(), get_pbar_theme())
    
    # Add buttons
    add_custom_button(
        label="Choose a DICOM directory", 
        parent_tag=tag_action_window, 
        callback=_get_directory, 
        add_spacer_before=True, 
        add_spacer_after=True
    )
    add_custom_button(
        label="Start Linking DICOM Files", 
        parent_tag=tag_action_window, 
        callback=_start_action, 
        user_data=dicom_manager.start_linking_all_dicoms,
        add_spacer_before=True, 
        add_spacer_after=True
    )

def _get_directory(sender, app_data, user_data):
    """ Gets the directory path from the user. """
    # Check if an action is already in progress
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    config_manager = get_user_data(td_key="config_manager")
    dicom_manager = get_user_data(td_key="dicom_manager")
    popup_width, popup_height, popup_pos = get_popup_params(height_ratio=0.5)
    tag_fd = dpg.generate_uuid()
    
    def _on_directory_selected(sender, app_data, user_data):
        """Callback that passes the selected directory."""
        selected_dir = app_data  # `app_data` contains the selected directory
        _start_action(sender, app_data, user_data=selected_dir)  # Pass directory
    
    # App data: keys are "file_path_name", "file_name", "current_path", "current_filter", "min_size", "max_size", "selections"
    dpg.add_file_dialog(
        tag=tag_fd,
        label="Choose a directory containing DICOM files",
        directory_selector=True,
        default_path=config_manager.get_project_parent_dir(),
        modal=True,
        callback=lambda s, a, u: _start_action(s, a, lambda: dicom_manager.start_processing_dicom_directory(a.get("file_path_name"))),  
        cancel_callback=lambda: safe_delete(tag_fd),
        width=popup_width,
        height=popup_height,
    )

def _start_action(sender, app_data, user_data):
    """ Initiates the user-specified action. """
    # Check if an action is already in progress
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    print(f"sender: {sender}, app_data: {app_data}, user_data: {user_data}")
    action_to_take = user_data
    
    def action_to_take_wrapper():
        shared_state_manager.action_event.set()
        try:
            action_to_take()
        except Exception as e:
            print(get_traceback(e))
        finally:
            shared_state_manager.action_event.clear()
    
    def threaded_action_to_take():
        shared_state_manager.add_action(action_to_take_wrapper)
        
    cleanup_wrapper(action=threaded_action_to_take)

