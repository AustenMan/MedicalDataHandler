import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data
from dpg_components.popup_dicom_insp import try_inspect_dicom_file
from utils.dpg_utils import safe_delete, get_popup_params, add_data_to_tree
from utils.general_utils import get_traceback

def try_inspect_patient_object(sender, app_data, user_data):
    """
    Displays detailed information about a selected patient object in a popup window.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (PatientData): The patient data object to inspect.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    # Start the action
    shared_state_manager.add_action(lambda: _create_window_ptobj_inspection(sender, app_data, user_data))

def _create_window_ptobj_inspection(sender, app_data, user_data):
    """  Create a popup window to inspect the patient object. Params passed from inspect_patient_object. """
    # Get necessary params
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        patient_class = user_data
        patient_info = patient_class.return_patient_info()
        tag_inspect_ptobj = get_tag("inspect_ptobj_window")
        popup_width, popup_height, popup_pos = get_popup_params()
        
        # Create a new window to inspect
        safe_delete(tag_inspect_ptobj)
        with dpg.window(
            tag=tag_inspect_ptobj, 
            label=f"Inspecting: {patient_info}", 
            width=popup_width, 
            height=popup_height, 
            pos=popup_pos, 
            no_open_over_existing_popup=False, 
            no_title_bar=False, 
            on_close=lambda: safe_delete(tag_inspect_ptobj),
            horizontal_scrollbar=True
            ):
            add_data_to_tree(
                data=patient_class, 
                parent=tag_inspect_ptobj, 
                text_wrap_width=round(0.95 * popup_width), 
                dcm_viewing_callback=try_inspect_dicom_file
            )
    except Exception as e:
        print(get_traceback(e))
    finally:
        shared_state_manager.action_event.clear()
