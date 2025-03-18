import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data
from dpg_components.texture_updates import request_texture_update
from dpg_components.window_settings import create_settings_window
from dpg_components.themes import get_hidden_button_theme
from dpg_components.window_confirmation import create_confirmation_popup
from utils.dpg_utils import safe_delete
from utils.general_utils import get_traceback

def cleanup_wrapper(action=None):
    """ Wraps a function with cleanup actions to ensure data is cleared before execution of a new action. """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_cleanup_thread_alive():
        print("Cleanup is already running.")
        return
    
    # Set the cleanup event to stop any ongoing actions
    shared_state_manager.cleanup_event.set()
    
    # If no cleanup is required, call the provided function immediately and ensure the confirmation popup is not gone.
    data_manager = get_user_data(td_key="data_manager")
    if not data_manager.check_if_data_loaded("any") and not shared_state_manager.is_action_in_queue():
        if action is not None:
            try:
                action()
            except Exception as e:
                print(get_traceback(e))
        tag_confirm_popup = get_tag("confirmation_popup")
        safe_delete(tag_confirm_popup)
        shared_state_manager.cleanup_event.clear()
        return
    
    def cleanup_actions():
        try:
            # Clear any stored data
            data_manager.clear_data()
        
            # Reset the GUI layout
            _reset_gui_layout()
        
            # Call the original function
            if action is not None:
                action()
            
            # Close the popup after action
            tag_confirm_popup = get_tag("confirmation_popup")
            safe_delete(tag_confirm_popup)
        except Exception as e:
            print(get_traceback(e))
        finally:
            # Clear the cleanup event
            shared_state_manager.cleanup_event.clear()
    
    create_confirmation_popup(
            button_callback=lambda: shared_state_manager.start_cleanup_thread(cleanup_actions), close_callback=lambda: shared_state_manager.cleanup_event.clear(),
            button_theme=get_hidden_button_theme(), no_close=True, confirmation_text="Cancelling ongoing actions and clearing data, please wait...",
            warning_string="If you proceed, any loaded patient data will be cleared and any ongoing actions will be cancelled."
        )

def _reset_gui_layout():
    """ Resets the GUI layout to its default state. """
    # Delete windows/popups that relate to loaded patient data
    tags_to_delete = [
        get_tag("settings_window"), 
        get_tag("color_picker_popup"), 
        get_tag("inspect_ptobj_window"),
        get_tag("inspect_dicom_popup"),
        get_tag("inspect_sitk_popup"),
        get_tag("save_sitk_window")
    ]
    safe_delete(tags_to_delete)
    
    # Delete children of these (keep the parents so we don't break the layout structure)
    layout_tags = ["mw_ctr_topleft", "mw_ctr_topright", "mw_ctr_bottomleft", "mw_ctr_bottomright", "mw_right"]
    safe_delete(layout_tags, children_only=True)
    
    # Get texture tags
    tag_ax_texture = get_tag("axial_dict")["texture"]
    tag_cor_texture = get_tag("coronal_dict")["texture"]
    tag_sag_texture = get_tag("sagittal_dict")["texture"]
    
    # Get texture values
    axial_val = dpg.get_value(tag_ax_texture)
    coronal_val = dpg.get_value(tag_cor_texture)
    sagittal_val = dpg.get_value(tag_sag_texture)
    
    # Reset texture values
    if axial_val is not None:
        axial_val[:] = 0
    if coronal_val is not None:
        coronal_val[:] = 0
    if sagittal_val is not None:
        sagittal_val[:] = 0
    
    create_settings_window(refresh=True)
    request_texture_update(texture_action_type="reset")
