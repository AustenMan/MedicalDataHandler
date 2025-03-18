import dearpygui.dearpygui as dpg
from dpg_components.cleanup import cleanup_wrapper
from dpg_components.custom_utils import get_tag, get_user_data, add_custom_button
from dpg_components.loaded_data_ui import fill_right_col_ptdata
from dpg_components.texture_updates import request_texture_update
from dpg_components.themes import get_table_cell_spacing_theme
from dpg_components.window_ptobj_insp import try_inspect_patient_object
from utils.dpg_utils import get_popup_params, safe_delete
from utils.general_utils import get_traceback

def toggle_data_window(force_show=False, label=""):
    """
    Toggles the visibility of the data window, creating or configuring it as needed.
    
    Args:
        force_show (bool): If True, forces the table to be shown.
        label (str): The label for the data window.
    """
    # Get necessary parameters
    tag_data_window = get_tag("data_display_window")
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.90, height_ratio=0.5)
    
    # Create the data window if it doesn't exist
    if not dpg.does_item_exist(tag_data_window):
        # Create the data window and bind the theme
        dpg.add_window(
            tag=tag_data_window, 
            label=label or "Data Window", 
            width=popup_width, 
            height=popup_height, 
            pos=popup_pos, 
            show=True, 
            no_close=False, 
            on_close=lambda: dpg.hide_item(tag_data_window), 
            user_data={}
        )
        dpg.bind_item_theme(tag_data_window, get_table_cell_spacing_theme(6, 6))
        
        # Add a button to load or reload the data table
        add_custom_button(
            label="Load or Reload Data Table", 
            parent_tag=tag_data_window, 
            user_data=True,
            callback=_try_load_patient_table, 
            tooltip_text="Loads/reloads the data table with patient data.",
            add_separator_after=True
        )
    # Otherwise, configure the existing window
    else:
        set_visible = force_show or not dpg.is_item_shown(tag_data_window)
        prev_label = dpg.get_item_label(tag_data_window)
        dpg.configure_item(
            tag_data_window, 
            label=label or prev_label, 
            width=popup_width, 
            height=popup_height, 
            collapsed=not set_visible, show=set_visible
        )
        if set_visible:
            dpg.focus_item(tag_data_window)

def _create_new_data_table():
    """ Creates a new data table from scratch. """
    # Delete the old data table
    old_tag_data_table = get_tag("data_table")
    safe_delete(old_tag_data_table)
    
    # Create a new UUID for the table so that it resizes properly
    tag_data_table = dpg.generate_uuid()
    
    # Update the tag dictionary
    tag_dict = dpg.get_item_user_data("tag_dict")
    tag_dict["data_table"] = tag_data_table
    
    # Create the new data table
    tag_data_window = get_tag("data_display_window")
    size_dict = get_user_data(td_key="size_dict")
    dpg.add_table(
        tag=tag_data_table, 
        parent=tag_data_window,
        resizable=True, 
        reorderable=True, 
        hideable=False, 
        sortable=False, 
        scrollX=True, 
        scrollY=True, 
        row_background=True, 
        header_row=True, 
        freeze_rows=1, 
        borders_innerH=True, 
        borders_innerV=True, 
        borders_outerH=True, 
        borders_outerV=True, 
        policy=dpg.mvTable_SizingFixedFit, 
        context_menu_in_body=True, 
        delay_search=False, 
        pad_outerX=True,
        width=size_dict["table_w"], 
        height=size_dict["table_h"]
    )

def _try_load_patient_table(sender, app_data, user_data):
    """
    Displays a popup table with a list of patients and their associated metadata.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (bool): Whether to refresh the data table.
    """
    # Check if an action is already in progress
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    # Start the action
    def action_to_take():
        _create_ptobj_table(sender, app_data, user_data)
    
    def threaded_action_to_take():
        shared_state_manager.add_action(action_to_take)
    
    cleanup_wrapper(action=threaded_action_to_take)

def _create_ptobj_table(sender, app_data, user_data):
    """ Displays a popup table with a list of patients and their associated metadata. Params passed from _try_load_patient_table. """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        # Set the sender button to a waiting state
        sender_prev_label = dpg.get_item_label(sender)
        dpg.configure_item(sender, enabled=False, label="Please wait...")
        
        # Get necessary parameters
        refresh_data = user_data if user_data else False
        dicom_manager = get_user_data(td_key="dicom_manager")
        tag_data_window = get_tag("data_display_window")
        size_dict = get_user_data(td_key="size_dict")
        
        # Need to load patient data
        if refresh_data:
            # Load the patient data
            object_dict = dicom_manager.load_dicom_objects(return_object_dict=True)
            dpg.set_item_user_data(tag_data_window, object_dict)
        # Otherwise, get the existing data
        else:
            object_dict = dpg.get_item_user_data(tag_data_window)
        
        # Show the data window and create a new data table
        toggle_data_window(force_show=True, label="Patient Data")
        _create_new_data_table()
        tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
        
        column_labels = [None, "Patient ID", "Patient Name", "Date Created", "Date Last Modified", "Date Last Accessed", "Date Last Processed"]
        for label_idx, label in enumerate(column_labels):
            dpg.add_table_column(parent=tag_data_table, label=label, width_fixed=True)
        
        for (patient_id, patient_name), patient_class in object_dict.items():
            with dpg.table_row(parent=tag_data_table):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Select", height=size_dict["button_height"], callback=_create_frameofref_table, user_data=patient_class)
                    dpg.add_button(label="Inspect", height=size_dict["button_height"], callback=try_inspect_patient_object, user_data=patient_class)
                dpg.add_text(default_value=patient_id)
                dpg.add_text(default_value=patient_name)
                dates_dict = object_dict[(patient_id, patient_name)].return_dates_dict()
                dpg.add_text(default_value=dates_dict["DateCreated"] if dates_dict["DateCreated"] is not None else "N/A")
                dpg.add_text(default_value=dates_dict["DateLastModified"] if dates_dict["DateLastModified"] is not None else "N/A")
                dpg.add_text(default_value=dates_dict["DateLastAccessed"] if dates_dict["DateLastAccessed"] is not None else "N/A")
                dpg.add_text(default_value=dates_dict["DateLastProcessed"] if dates_dict["DateLastProcessed"] is not None else "N/A")
        
        # Reset the sender button to its previous label
        if dpg.does_item_exist(sender):
            dpg.configure_item(sender, enabled=True, label=sender_prev_label)
    except Exception as e:
        print(get_traceback(e))
    finally:
        shared_state_manager.action_event.clear()

def _create_frameofref_table(sender, app_data, user_data):
    """
    Displays a table of frame-of-reference UIDs for a selected patient, including data summaries.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (PatientData): The selected patient data object.
    """
    # Get necessary parameters
    selected_pt = user_data
    dicom_dict = selected_pt.return_dicom_dict()
    size_dict = get_user_data(td_key="size_dict")
    
    # Create the data window and table
    toggle_data_window(force_show=True, label=f"Data for Patient: {selected_pt.return_patient_info()}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
    
    # Get the data to display
    frame_of_reference_uids = list(dicom_dict.keys())
    if not frame_of_reference_uids:
        return # No data to display
    unique_modalities = list(set([modality for frame_of_reference in dicom_dict for modality in dicom_dict[frame_of_reference]]))
    
    # Fill the table with the data
    dpg.add_table_column(parent=tag_data_table, label="Frame of Reference UID", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Data Summary", width_stretch=True)
    with dpg.table_row(parent=tag_data_table):
        dpg.add_button(label="Go Back", height=size_dict["button_height"], callback=_create_ptobj_table)
    for frame_of_reference_uid in frame_of_reference_uids:
        with dpg.table_row(parent=tag_data_table):
            dpg.add_button(label=frame_of_reference_uid, height=size_dict["button_height"], callback=_create_modality_table, user_data=selected_pt)
            with dpg.group(horizontal=False):
                for modality in unique_modalities:
                    num_files = len(dicom_dict[frame_of_reference_uid][modality])
                    dpg.add_text(default_value=f"# {modality} Files: {num_files}")

def _create_modality_table(sender, app_data, user_data):
    """
    Displays a table of modalities associated with a specific frame-of-reference UID.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (PatientData): The selected patient data object.
    """
    # Get necessary parameters
    active_pt = user_data
    active_frame_of_reference_uid = dpg.get_item_label(sender)
    size_dict = get_user_data(td_key="size_dict")
    
    toggle_data_window(force_show=True, label=f"Data for Patient: {active_pt.return_patient_info()}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
    
    all_rti_data_dict, all_rt_links_dict = _get_modality_links(active_pt, active_frame_of_reference_uid)
    
    # Track checkboxes by File Path for synchronization
    checkbox_states = {}
    
    # Start building the table
    dpg.add_table_column(parent=tag_data_table, label="Toggle inclusion/exclusion of data", width_stretch=True)
    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            dpg.add_button(label="Go Back", width=150, height=size_dict["button_height"], callback=_modify_button_after_callback, user_data=active_pt)
            dpg.add_button(label="Load Selected Data", callback=_try_load_selected_data, width=150, height=size_dict["button_height"], user_data=(active_pt, active_frame_of_reference_uid, all_rti_data_dict, all_rt_links_dict, checkbox_states))
    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            dpg.add_checkbox(callback=_checkbox_toggle_all_callback, user_data=checkbox_states)
            dpg.add_text(default_value="Toggle All Data")
    
    # Add RT Items to the table
    items_added = set()
    for sop_instance_uid, rt_links_dict in all_rt_links_dict.items():
        if rt_links_dict["Modality"] is not None and not sop_instance_uid in items_added:
            with dpg.table_row(parent=tag_data_table):
                _add_rt_item_tree(checkbox_states, sop_instance_uid, rt_links_dict)
            items_added.add(sop_instance_uid)
    for siuid, rti_dict in all_rti_data_dict.items():
        if rti_dict["Modality"] is not None and not siuid in items_added:
            with dpg.table_row(parent=tag_data_table):
                _add_rt_item_tree(checkbox_states, siuid, rti_dict)
            items_added.add(siuid)
    
    # Modify the table inner width based on the longest file path
    longest_fpath = None
    for fpath in checkbox_states:
        if longest_fpath is None or len(fpath) > len(longest_fpath):
            longest_fpath = fpath
    if longest_fpath:
        req_table_width = round(dpg.get_text_size(longest_fpath)[0] * 1.5)
        dpg.configure_item(tag_data_table, inner_width=req_table_width)

def _checkbox_callback(sender, app_data, user_data):
    """
    Callback function for individual checkbox interactions.
    
    Sets the state of all checkboxes associated with a specific file path.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (bool): The new state of the checkbox.
        user_data (list[str]): A tuple of checkbox states and specific updated file paths.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    # Prevent race conditions
    with shared_state_manager.thread_lock:
        checkbox_states, fpaths = user_data
        current_state = dpg.get_value(sender)
        for fpath in fpaths:
            for checkbox_id in checkbox_states.get(fpath, []):
                dpg.set_value(checkbox_id, current_state)

def _checkbox_toggle_all_callback(sender, app_data, user_data):
    """
    Callback function for the "Select All" checkbox, propagating the state to all linked checkboxes.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (bool): The new state of the master checkbox.
        user_data (any): The checkbox states reference.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    # Prevent race conditions
    with shared_state_manager.thread_lock:
        current_state = dpg.get_value(sender)
        checkbox_states = user_data
        for fpath, checkbox_ids in checkbox_states.items():
            for checkbox_id in checkbox_ids:
                dpg.set_value(checkbox_id, current_state)

def _add_rt_item_tree(checkbox_states, curr_item_id, curr_item_dict, child=False, nested_fpaths=None, processed_child_items=None):
    """
    Recursively adds RT item data to the tree structure in the UI.
    
    Args:
        checkbox_states (dict): Dictionary of checkbox states for synchronization.
        curr_item_id (str): The current item ID being processed.
        curr_item_dict (dict): The dictionary containing the RT item data.
        child (bool): Indicates if the current item is a child node.
        nested_fpaths (list[str]): A list of file paths associated with the current node.
        processed_child_items (set[str]): A set of processed child items, to prevent duplicate entries.
    """
    if processed_child_items is None:
        processed_child_items = set()  # Initialize at the top level
    
    if "Filepath" in curr_item_dict:
        file_path = curr_item_dict["Filepath"]
        modality = curr_item_dict["Modality"]
        if modality is None:
            return
        linked_modalities = curr_item_dict.get("Linked_Modalities", [{}])
        
        if not child:
            nested_fpaths = [file_path]
            with dpg.group(horizontal=True):
                sop_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=(checkbox_states, nested_fpaths))
                with dpg.tree_node(label=f"{modality} Tree from SOPInstanceUID: {curr_item_id}"):
                    with dpg.group(horizontal=True):
                        file_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=[file_path])
                        dpg.add_text(f"{modality} File: {file_path}")
                    checkbox_states.setdefault(file_path, []).extend([sop_checkbox, file_checkbox])
                    for linked_modality in linked_modalities:
                        for linked_item_id, linked_item_dict in linked_modality.items():
                            if not linked_item_id in processed_child_items:
                                _add_rt_item_tree(checkbox_states, linked_item_id, linked_item_dict, child=True, nested_fpaths=nested_fpaths, processed_child_items=processed_child_items)
                                processed_child_items.add(linked_item_id)
        else:
            nested_fpaths.append(file_path)
            with dpg.group(horizontal=True):
                sop_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=(checkbox_states, [file_path]))
                dpg.add_text(default_value=f"Linked {modality} File: {file_path}")
            checkbox_states.setdefault(file_path, []).append(sop_checkbox)
            for linked_modality in linked_modalities:
                for linked_item_id, linked_item_dict in linked_modality.items():
                    if not linked_item_id in processed_child_items:
                        _add_rt_item_tree(checkbox_states, linked_item_id, linked_item_dict, child=True, nested_fpaths=nested_fpaths, processed_child_items=processed_child_items)
                        processed_child_items.add(linked_item_id)
    
    elif "Filepaths" in curr_item_dict:
        file_paths = curr_item_dict["Filepaths"]
        modality = curr_item_dict["Modality"]
        if modality is None:
            return
        
        if not child:
            nested_fpaths = file_paths
            with dpg.group(horizontal=True):
                siuid_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=(checkbox_states, nested_fpaths))
                with dpg.tree_node(label=f"{modality} Tree from SeriesInstanceUID: {curr_item_id}"):
                    for file_path in file_paths:
                        if not file_path in processed_child_items:
                            with dpg.group(horizontal=True):
                                file_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=(checkbox_states, [file_path]))
                                dpg.add_text(f"{modality} File: {file_path}")
                            checkbox_states.setdefault(file_path, []).extend([siuid_checkbox, file_checkbox])
                            processed_child_items.add(file_path)
        else:
            nested_fpaths.extend(file_paths)
            with dpg.group(horizontal=True):
                siuid_checkbox = dpg.add_checkbox(callback=_checkbox_callback, user_data=(checkbox_states, file_paths))
                dpg.add_text(default_value=f"Linked {modality} Files: [{file_paths[0]}, ...]")
            for file_path in file_paths:
                if not file_path in processed_child_items:
                    checkbox_states.setdefault(file_path, []).append(siuid_checkbox)
                    processed_child_items.add(file_path)

def _modify_button_after_callback(sender, app_data, user_data):
    """
    Callback function for the "Go Back" button, returning to the previous table.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (any): Custom user data passed to the callback.
    """
    dpg.configure_item(sender, enabled=False, label="Going Back...")
    _create_frameofref_table(sender, app_data, user_data)
    
def _get_modality_links(active_pt, active_frame_of_reference_uid):
    """
    Retrieves modality links for the active patient and frame of reference.
    
    Args:
        active_pt (PatientData): The active patient data object.
        active_frame_of_reference_uid (str): The active frame of reference UID.
    
    Returns:
        tuple[dict, dict]: A tuple containing:
            - rti_data: Dictionary of RT image data grouped by SeriesInstanceUID.
            - rt_links: Dictionary of RT modality links grouped by SOPInstanceUID.
    """
    rti_data = {}
    rt_links = {}
    
    FoR_dicom_dict = active_pt.return_dicom_dict().get(active_frame_of_reference_uid)
    if not FoR_dicom_dict:
        print(f"Error: No DICOM data found for FoR: {active_frame_of_reference_uid}")
        return rti_data, rt_links
    
    patient_id, patient_name = active_pt.return_patient_info()
    
    for SOPInstanceUIDs_dict in FoR_dicom_dict.values():
        for file_path in SOPInstanceUIDs_dict.values():
            fpath_refs_dict = active_pt.return_dicom_frefs_dict().get(file_path, {})
            
            fpath_pt_id = fpath_refs_dict.get("PatientID", None)
            fpath_patients_name = fpath_refs_dict.get("PatientsName", None)
            
            # Check if the PatientID and PatientName match the PatientID and PatientName of the Patient
            if patient_id != fpath_pt_id or patient_name != fpath_patients_name:
                print(f"File {file_path} has an Patient ID or Name mismatch: {patient_id} != {fpath_pt_id} or {patient_name} != {fpath_patients_name}")
                continue
            
            fpath_modality = fpath_refs_dict.get("Modality", None)
            if not fpath_modality:
                print(f"File {file_path} is missing its Modality in the filepath references dict")
                continue
            fpath_modality = fpath_modality.upper()
            
            fpath_dosesummationtype = fpath_refs_dict.get("DoseSummationType", None)
            if fpath_dosesummationtype:
                fpath_modality = f"{fpath_modality} {fpath_dosesummationtype}"
            
            fpath_SOPInstanceUID = fpath_refs_dict.get("SOPInstanceUID", None)
            if not fpath_SOPInstanceUID:
                print(f"File {file_path} is missing its SOPInstanceUID in the filepath references dict")
                continue
            
            fpath_FrameOfReferenceUID = fpath_refs_dict.get("FrameOfReferenceUID", None)
            if not fpath_FrameOfReferenceUID:
                print(f"File {file_path} is missing its FrameOfReferenceUID in the filepath references dict")
                continue
            if fpath_FrameOfReferenceUID != active_frame_of_reference_uid:
                print(f"File {file_path} has a FrameOfReferenceUID mismatch: {fpath_FrameOfReferenceUID} != {active_frame_of_reference_uid}")
                continue
            
            # Handle RT Images
            if fpath_modality in ["CT", "MR", "MRI", "PT", "PET"]:
                fpath_SIUID = fpath_refs_dict.get("SeriesInstanceUID", None)
                if not fpath_SIUID:
                    print(f"File {file_path} with modality {fpath_modality} is missing its SeriesInstanceUID in the filepath references dict")
                    continue
                
                if not fpath_SIUID in rti_data:
                    rti_data[fpath_SIUID] = {"Modality": fpath_modality, "Filepaths": []}
                elif rti_data[fpath_SIUID]["Modality"] is None:
                    rti_data[fpath_SIUID]["Modality"] = fpath_modality
                
                if fpath_modality != rti_data[fpath_SIUID]["Modality"]:
                    print(f"File {file_path} with modality {fpath_modality} has a mismatched modality in the SeriesInstanceUID: {fpath_SIUID}, which expected {rti_data[fpath_SIUID]['Modality']}")
                    continue
                
                if file_path in rti_data[fpath_SIUID]["Filepaths"]:
                    print(f"File {file_path} with modality {fpath_modality} is already in the SeriesInstanceUID: {fpath_SIUID}")
                    continue
                
                rti_data[fpath_SIUID]["Filepaths"].append(file_path)
                
                continue
            
            # Add non-image files to the RT Links dict
            if not fpath_SOPInstanceUID in rt_links:
                rt_links[fpath_SOPInstanceUID] = {"Filepath": file_path, "Modality": fpath_modality, "Linked_Modalities": []}
            elif rt_links[fpath_SOPInstanceUID]["Filepath"] is None and rt_links[fpath_SOPInstanceUID]["Modality"] is None:
                rt_links[fpath_SOPInstanceUID]["Filepath"] = file_path
                rt_links[fpath_SOPInstanceUID]["Modality"] = fpath_modality
            
            # NOTE TO : RTSTRUCT ReferencedSeriesInstanceUID -> CT/MR/etc SeriesInstanceUID ... RTPLAN ReferencedSOPInstanceUID -> RTSTRUCT SOPInstanceUID ... RTDOSE ReferencedSOPInstanceUID -> RTPLAN SOPInstanceUID
            fpath_ref_SIUIDs = fpath_refs_dict.get("ReferencedSeriesInstanceUID", [])
            for fpath_ref_SIUID in fpath_ref_SIUIDs:
                if not fpath_ref_SIUID in rti_data:
                    rti_data[fpath_ref_SIUID] = {"Modality": None, "Filepaths": []}
                rt_links[fpath_SOPInstanceUID]["Linked_Modalities"].append({fpath_ref_SIUID: rti_data[fpath_ref_SIUID]})
            
            fpath_ref_SOPIUIDs = fpath_refs_dict.get("ReferencedSOPInstanceUID", [])
            for fpath_ref_SOPIUID in fpath_ref_SOPIUIDs:
                if not fpath_ref_SOPIUID in rt_links:
                    rt_links[fpath_ref_SOPIUID] = {"Filepath": None, "Modality": None, "Linked_Modalities": []}
                rt_links[fpath_SOPInstanceUID]["Linked_Modalities"].append({fpath_ref_SOPIUID: rt_links[fpath_ref_SOPIUID]})
    
    return rti_data, rt_links

def _try_load_selected_data(sender, app_data, user_data):
    """
    Attempts to load selected data based on user input.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains active_pt, active_frame_of_reference_uid, all_rti_data_dict, all_rt_links_dict, checkbox_states.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    # Start the action
    def action_to_take():
        _load_selected_data(sender, app_data, user_data)
    
    def threaded_action_to_take():
        shared_state_manager.add_action(action_to_take)
    
    cleanup_wrapper(action=threaded_action_to_take)

def _load_selected_data(sender, app_data, user_data):
    """ Loads the selected data into the application. Params passed from _try_load_selected_data. """
    # Get necessary parameters
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        active_pt, active_frame_of_reference_uid, all_rti_data_dict, all_rt_links_dict, checkbox_states = user_data
        data_manager = get_user_data(td_key="data_manager")
        
        print(f"Starting to load selected data. Please wait...")
        
        rt_links_data_dict = {"RTIMAGE": [], "RTSTRUCT": [], "RTPLAN": [], "RTDOSE": []}
        
        for siuid, rti_dict in all_rti_data_dict.items():
            modality = rti_dict["Modality"]
            if not modality:
                print(f"Error for SIUID: {siuid}. Failed to load data for unknown modality: {modality}")
                continue
            
            checked_fpaths = [fpath for fpath in rti_dict["Filepaths"] if any(dpg.get_value(checkbox_id) for checkbox_id in checkbox_states.get(fpath, []))]
            if not checked_fpaths:
                continue
            
            rt_links_data_dict["RTIMAGE"].append((modality, siuid, checked_fpaths))
        
        for sop_instance_uid, rt_links_dict in all_rt_links_dict.items():
            modality = rt_links_dict["Modality"]
            
            if modality is None:
                continue
            
            file_path = rt_links_dict["Filepath"]
            
            if not any(dpg.get_value(checkbox_id) for checkbox_id in checkbox_states.get(file_path, [])):
                continue
            
            if modality.upper() in ["RS", "RTS", "RTSTR", "RTSTRUCT", "STRUCT"]:
                rt_links_data_dict["RTSTRUCT"].append((modality, sop_instance_uid, file_path))
            elif modality.upper() in ["RP", "RTP", "RTPLAN", "PLAN"]:
                rt_links_data_dict["RTPLAN"].append((modality, sop_instance_uid, file_path))
            elif modality.upper() in ["RD", "RTD", "RTDOSE", "DOSE", "RD BEAM", "RTD BEAM", "RTDOSE BEAM", "DOSE BEAM", "RD PLAN", "RTD PLAN", "RTDOSE PLAN", "DOSE PLAN"]:
                rt_links_data_dict["RTDOSE"].append((modality, sop_instance_uid, file_path))
            else:
                print(f"Error, failed to load data for unknown modality: {modality}")
        
        patient_id = active_pt.return_patient_id()
        data_manager.load_all_dicom_data(rt_links_data_dict, patient_id)
        
        fill_right_col_ptdata(active_pt, active_frame_of_reference_uid)
        request_texture_update(texture_action_type="initialize")
    except Exception as e:
        print(f"Error loading selected data: {get_traceback(e)}")
    finally:
        shared_state_manager.action_event.clear()
