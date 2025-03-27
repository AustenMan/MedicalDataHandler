import logging
import dearpygui.dearpygui as dpg
from functools import partial
from typing import Any, Dict, List, Tuple, Set, Union, Optional

from mdh_app.dpg_components.cleanup import cleanup_wrapper
from mdh_app.dpg_components.custom_utils import get_tag, get_user_data, add_custom_button, add_custom_separator
from mdh_app.dpg_components.loaded_data_ui import fill_right_col_ptdata
from mdh_app.dpg_components.texture_updates import request_texture_update
from mdh_app.dpg_components.themes import get_table_cell_spacing_theme
from mdh_app.dpg_components.window_confirmation import create_confirmation_popup
from mdh_app.dpg_components.window_ptobj_insp import create_window_ptobj_inspection
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.managers.data_manager import DataManager
from mdh_app.managers.dicom_manager import DicomManager
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete, modify_table_rows
from mdh_app.utils.patient_data_object import PatientData

logger = logging.getLogger(__name__)

def toggle_data_window(force_show: bool = False, label: str = "") -> None:
    """
    Toggle the visibility of the data window, creating or configuring it as needed.

    Args:
        force_show: If True, forces the window to be shown.
        label: The label to display on the data window.
    """
    tag_data_window = get_tag("data_display_window")
    tag_table_reload_button = get_tag("table_reload_button")
    tag_table_rows_input = get_tag("table_rows_input")
    tag_table_page_input = get_tag("table_page_input")
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.90, height_ratio=0.75)
    
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
            on_close=lambda: dpg.hide_item(tag_data_window), 
            user_data={}
        )
        dpg.bind_item_theme(tag_data_window, get_table_cell_spacing_theme(6, 6))
        
        # Add button table
        with dpg.table(parent=tag_data_window, header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.5)
            dpg.add_table_column(init_width_or_weight=0.5)
            
            row_tag = dpg.generate_uuid()
            with dpg.table_row(tag=row_tag):
                # Add a button to load or reload the data table
                add_custom_button(
                    tag=tag_table_reload_button,
                    label="Load or Reload Data Table", 
                    callback=cleanup_wrapper(_create_ptobj_table),
                    parent_tag=row_tag,
                    tooltip_text="Loads/reloads the data table with patient data.",
                )
                # Add a button to remove all data from the program
                add_custom_button(
                    label="Remove All Data", 
                    callback=_confirm_remove_all_func,
                    parent_tag=row_tag,
                    tooltip_text="Removes all patient data from the program.",
                )
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Specify the page number for the data table.")
                    dpg.add_text("Page Number: ")
                    dpg.add_input_int(
                        tag=tag_table_page_input,
                        width=size_dict["button_width"],
                        default_value=1,
                        min_value=1,
                        min_clamped=True,
                        max_value=1,
                        max_clamped=True,
                        on_enter=True,
                        step=1,
                        step_fast=5,
                        callback=cleanup_wrapper(_create_ptobj_table),
                    )
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=(
                                "Specify the number of patients to display per page.\n"
                                "Large values may experience performance issues."
                                )
                        )
                    dpg.add_text("Patients per Page: ")
                    dpg.add_input_int(
                        tag=tag_table_rows_input,
                        width=size_dict["button_width"],
                        default_value=50,
                        min_value=1,
                        min_clamped=True,
                        max_value=1,
                        max_clamped=True,
                        on_enter=True,
                        step=1,
                        step_fast=10,
                        callback=cleanup_wrapper(_create_ptobj_table),
                    )
        
        # Add a separator
        add_custom_separator(parent_tag=tag_data_window)
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

def _create_new_data_table() -> None:
    """Create a new data table from scratch, updating the tag dictionary."""
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

def _confirm_removal_func(sender: Union[str, int], app_data: Any, user_data: Tuple[Union[str, int], PatientData]) -> None:
    """Remove a patient data object after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    
    pd_row_tag: Union[str, int] = user_data[0]
    pd_class: PatientData = user_data[1]
    pt_id, pt_name = pd_class.return_patient_info()
    pt_key = (pt_id, pt_name)
    
    def delete_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_patient_data_object(pd_class)
        safe_delete(pd_row_tag)
        all_patient_data: Dict[Tuple[str, str], PatientData] = dpg.get_item_user_data(tag_data_window)
        if all_patient_data and pt_key in all_patient_data:
            all_patient_data.pop(pt_key, None)
            dpg.set_item_user_data(tag_data_window, all_patient_data)
    
    def submit_removal_func(sender, app_data, user_data) -> None:
        clean_wrap = cleanup_wrapper(delete_func)
        clean_wrap(sender, app_data, user_data)
    
    create_confirmation_popup(
        button_callback=submit_removal_func,
        confirmation_text=f"Removing data from program for patient with ID: {pt_id} and Name: {pt_name}",
        warning_string=(
            f"Are you sure you want to remove data from the program for the patient with:\n"
            f"ID: {pt_id} and Name: {pt_name}?\n"
            "This action is irreversible. You would need to re-import the data to access it again.\n"
            "Remove this data?"
        )
    )

def _confirm_remove_all_func(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Remove all patient data objects after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    tag_data_table = get_tag("data_table")
    
    def delete_all_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_all_patient_data_objects()
        modify_table_rows(table_tag=tag_data_table, delete=True)
        dpg.set_item_user_data(tag_data_window, {})
    
    def submit_remove_all_func(sender, app_data, user_data) -> None:
        clean_wrap = cleanup_wrapper(delete_all_func)
        clean_wrap(sender, app_data, user_data)
    
    create_confirmation_popup(
        button_callback=submit_remove_all_func,
        confirmation_text="Removing all data from the program",
        warning_string=(
            f"Are you sure you want to remove ALL patient data from the program?\n"
            "This action is irreversible. You would need to re-import the data to access it again.\n"
            "Remove ALL patient data?"
        ),
        second_confirm=True
    )

def _create_ptobj_table(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Display a popup table listing patients with their metadata.

    Args:
        sender: The tag of the triggering item.
        app_data: Additional event data.
        user_data: Additional user data.
    """
    # Freeze interaction with the table while updating
    tag_table_reload_button = get_tag("table_reload_button")
    tag_table_rows_input = get_tag("table_rows_input")
    tag_table_page_input = get_tag("table_page_input")
    freeze_tags = [tag_table_reload_button, tag_table_rows_input, tag_table_page_input]
    for tag in freeze_tags:
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=False)
    
    logger.info("Updating the patient data table...")
    
    # Get necessary parameters
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    size_dict = get_user_data(td_key="size_dict")
    
    # Find number of patients and number of rows to display
    num_pt_obj = dcm_mgr.get_num_patient_data_objects()
    num_table_rows = max(1, min(dpg.get_value(tag_table_rows_input), num_pt_obj))
    
    # Calculate number of pages and current page
    if num_pt_obj == 0:
        num_pages = 1
    else:
        num_pages = (num_pt_obj + num_table_rows - 1) // num_table_rows
    table_page = max(1, min(dpg.get_value(tag_table_page_input), num_pages))
    
    # Configure the limits on the table rows/indices inputs
    table_index = table_page - 1
    dpg.configure_item(tag_table_rows_input, max_value=num_pt_obj)
    dpg.set_value(tag_table_rows_input, num_table_rows)
    dpg.configure_item(tag_table_page_input, max_value=num_pages)
    dpg.set_value(tag_table_page_input, table_page)
    
    # Load relevant patient data
    subset_pt_data = dcm_mgr.load_patient_data_objects(subset_size=num_table_rows, subset_idx=table_index)
    dpg.set_item_user_data(tag_data_window, subset_pt_data)
    
    # Show the data window and create a new data table
    toggle_data_window(force_show=True, label="Patient Data")
    _create_new_data_table()
    tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
    
    column_labels = ["Actions", "Patient ID", "Patient Name", "Date Created", "Date Last Modified", "Date Last Accessed", "Date Last Processed"]
    for label_idx, label in enumerate(column_labels):
        dpg.add_table_column(parent=tag_data_table, label=label, width_fixed=True)
    
    for (patient_id, patient_name), patient_class in subset_pt_data.items():
        pdata_row_tag = dpg.generate_uuid()
        with dpg.table_row(tag=pdata_row_tag, parent=tag_data_table):
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Select", 
                    height=size_dict["button_height"], 
                    callback=_create_frameofref_table, 
                    user_data=patient_class
                )
                dpg.add_button(
                    label="Inspect", 
                    height=size_dict["button_height"], 
                    callback=lambda s, a, u: ss_mgr.submit_action(partial(create_window_ptobj_inspection, s, a, u)),
                    user_data=patient_class
                )
                dpg.add_button(
                    label="Remove",
                    height=size_dict["button_height"],
                    callback=_confirm_removal_func,
                    user_data=(pdata_row_tag, patient_class)
                )
            dpg.add_text(default_value=patient_id)
            dpg.add_text(default_value=patient_name)
            dates_dict = subset_pt_data[(patient_id, patient_name)].return_dates_dict()
            dpg.add_text(default_value=dates_dict["DateCreated"] if dates_dict["DateCreated"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastModified"] if dates_dict["DateLastModified"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastAccessed"] if dates_dict["DateLastAccessed"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastProcessed"] if dates_dict["DateLastProcessed"] is not None else "N/A")
    
    # Unfreeze interaction with the table after updating
    for tag in freeze_tags:
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=True)
    logger.info(f"Finished loading table page {table_page} with {num_table_rows} rows.")

def _create_frameofref_table(sender: Union[str, int], app_data: Any, user_data: PatientData) -> None:
    """
    Display a table of frame-of-reference UIDs for a selected patient, including summaries.

    Args:
        sender: The tag of the triggering item.
        app_data: Additional event data.
        user_data: The selected patient data object.
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
    unique_modalities = list({modality for modality_dict in dicom_dict.values() for modality in modality_dict})
    
    # Fill the table with the data
    dpg.add_table_column(parent=tag_data_table, label="Frame of Reference UID", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Data Summary", width_stretch=True)
    with dpg.table_row(parent=tag_data_table):
        dpg.add_button(
            label="Go Back", 
            height=size_dict["button_height"], 
            callback=_create_ptobj_table
        )
    for frame_of_reference_uid in frame_of_reference_uids:
        with dpg.table_row(parent=tag_data_table):
            dpg.add_button(
                label=frame_of_reference_uid, 
                height=size_dict["button_height"], 
                callback=_create_modality_table, 
                user_data=selected_pt
            )
            with dpg.group(horizontal=False):
                for modality in unique_modalities:
                    num_files = len(dicom_dict[frame_of_reference_uid][modality])
                    dpg.add_text(default_value=f"# {modality} Files: {num_files}")

def _create_modality_table(sender: Union[str, int], app_data: Any, user_data: PatientData) -> None:
    """
    Display a table of modalities associated with a specific frame-of-reference UID.

    Args:
        sender: The tag of the triggering item.
        app_data: Additional event data.
        user_data: The selected patient data object.
    """
    # Get necessary parameters
    active_pt = user_data
    active_frame_of_reference_uid = dpg.get_item_label(sender)
    
    toggle_data_window(force_show=True, label=f"Data for Patient: {active_pt.return_patient_info()}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
    
    all_image_data_dict, all_rt_links_dict = _get_modality_links(active_pt, active_frame_of_reference_uid)
    
    # Track checkboxes by File Path for synchronization
    checkbox_states: Dict[str, List[Any]] = {}
    
    # Start building the table
    dpg.add_table_column(parent=tag_data_table, label="Toggle inclusion/exclusion of data", width_stretch=True)
    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            gb_btn_label = "Go Back"
            gb_btn_width = round(dpg.get_text_size(gb_btn_label)[0] * 2)
            dpg.add_button(
                label=gb_btn_label, 
                width=gb_btn_width, 
                callback=_modify_button_after_callback, 
                user_data=active_pt
            )
            load_btn_label = "Load Selected Data"
            load_btn_width = round(dpg.get_text_size(load_btn_label)[0] * 2)
            dpg.add_button(
                label=load_btn_label, 
                callback=cleanup_wrapper(_load_selected_data), 
                width=load_btn_width, 
                user_data=(active_pt, active_frame_of_reference_uid, all_image_data_dict, all_rt_links_dict, checkbox_states)
            )
    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            dpg.add_checkbox(
                callback=_checkbox_toggle_all_callback, 
                user_data=checkbox_states
            )
            dpg.add_text(default_value="Toggle All Data")
    
    # Add RT Items to the table
    items_added = set()
    for sop_instance_uid, rt_links_dict in all_rt_links_dict.items():
        if rt_links_dict["Modality"] is not None and not sop_instance_uid in items_added:
            with dpg.table_row(parent=tag_data_table):
                _add_rt_item_tree(checkbox_states, sop_instance_uid, rt_links_dict)
            items_added.add(sop_instance_uid)
    for siuid, image_dict in all_image_data_dict.items():
        if image_dict["Modality"] is not None and not siuid in items_added:
            with dpg.table_row(parent=tag_data_table):
                _add_rt_item_tree(checkbox_states, siuid, image_dict)
            items_added.add(siuid)
    
    # Modify the table inner width based on the longest file path
    longest_fpath = None
    for fpath in checkbox_states:
        if longest_fpath is None or len(fpath) > len(longest_fpath):
            longest_fpath = fpath
    if longest_fpath:
        req_table_width = round(dpg.get_text_size(longest_fpath)[0] * 1.5)
        dpg.configure_item(tag_data_table, inner_width=req_table_width)

def _checkbox_callback(sender: Union[str, int], app_data: bool, user_data: Tuple[Dict[str, List[Any]], List[str]]) -> None:
    """
    Handle individual checkbox interactions by setting the state of all checkboxes for a given file path.

    Args:
        sender: The checkbox tag.
        app_data: The new state of the checkbox (True or False).
        user_data: A tuple containing (checkbox_states dict, list of file paths).
    """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    with ss_mgr.thread_lock:
        checkbox_states, fpaths = user_data
        current_state = dpg.get_value(sender)
        for fpath in fpaths:
            for checkbox_id in checkbox_states.get(fpath, []):
                dpg.set_value(checkbox_id, current_state)

def _checkbox_toggle_all_callback(sender: Union[str, int], app_data: bool, user_data: Dict[str, List[Any]]) -> None:
    """
    Propagate the "Select All" checkbox state to all linked checkboxes.

    Args:
        sender: The master checkbox tag.
        app_data: The new state (True or False).
        user_data: The dictionary of checkbox states.
    """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    with ss_mgr.thread_lock:
        current_state = dpg.get_value(sender)
        for fpath, checkbox_ids in user_data.items():
            for checkbox_id in checkbox_ids:
                dpg.set_value(checkbox_id, current_state)

def _add_rt_item_tree(
    checkbox_states: Dict[str, List[Any]],
    curr_item_id: str,
    curr_item_dict: Dict[str, Any],
    child: bool = False,
    nested_fpaths: Optional[List[str]] = None,
    processed_child_items: Optional[Set[str]] = None
) -> None:
    """
    Recursively add RT item data to the UI tree structure.

    Args:
        checkbox_states: Dictionary tracking checkbox IDs by file path.
        curr_item_id: The current item ID.
        curr_item_dict: Dictionary containing the RT item data.
        child: Whether the current item is a child node.
        nested_fpaths: List of file paths associated with the current node.
        processed_child_items: Set of already processed child item IDs.
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
                                _add_rt_item_tree(
                                    checkbox_states, 
                                    linked_item_id, 
                                    linked_item_dict, 
                                    child=True, 
                                    nested_fpaths=nested_fpaths, 
                                    processed_child_items=processed_child_items
                                )
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
                        _add_rt_item_tree(
                            checkbox_states, 
                            linked_item_id, 
                            linked_item_dict,
                            child=True, 
                            nested_fpaths=nested_fpaths, 
                            processed_child_items=processed_child_items
                        )
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

def _modify_button_after_callback(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Handle the "Go Back" button callback to return to the previous table.

    Args:
        sender: The tag of the button triggering the action.
        app_data: Additional event data.
        user_data: Custom user data.
    """
    dpg.configure_item(sender, enabled=False, label="Going Back...")
    _create_frameofref_table(sender, app_data, user_data)
    
def _get_modality_links(active_pt: PatientData, active_frame_of_reference_uid: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Retrieve modality links for the active patient and frame-of-reference UID.

    Args:
        active_pt: The active patient data object.
        active_frame_of_reference_uid: The active frame-of-reference UID.

    Returns:
        A tuple containing:
            - image_data: Dictionary of image data grouped by SeriesInstanceUID.
            - rt_links: Dictionary of RT modality links grouped by SOPInstanceUID.
    """
    image_data: Dict[str, Any] = {}
    rt_links: Dict[str, Any] = {}
    
    FoR_dicom_dict = active_pt.return_dicom_dict().get(active_frame_of_reference_uid)
    if not FoR_dicom_dict:
        logger.info(f"Missing DICOM data for FoR: {active_frame_of_reference_uid}")
        return image_data, rt_links
    
    patient_id, patient_name = active_pt.return_patient_info()
    
    for SOPInstanceUIDs_dict in FoR_dicom_dict.values():
        for file_path in SOPInstanceUIDs_dict.values():
            fpath_refs_dict = active_pt.return_dicom_frefs_dict().get(file_path, {})
            
            fpath_pt_id = fpath_refs_dict.get("PatientID", None)
            fpath_patients_name = fpath_refs_dict.get("PatientsName", None)
            
            # Check if the PatientID and PatientName match the PatientID and PatientName of the Patient
            if patient_id != fpath_pt_id or patient_name != fpath_patients_name:
                logger.info(f"File {file_path} has patient info mismatch: {patient_id} vs {fpath_pt_id}, {patient_name} vs {fpath_patients_name}")
                continue
            
            fpath_modality = fpath_refs_dict.get("Modality", None)
            if not fpath_modality:
                logger.info(f"File {file_path} is missing its Modality.")
                continue
            fpath_modality = fpath_modality.upper()
            
            fpath_dosesummationtype = fpath_refs_dict.get("DoseSummationType", None)
            if fpath_dosesummationtype:
                fpath_modality = f"{fpath_modality} {fpath_dosesummationtype}"
            
            fpath_SOPInstanceUID = fpath_refs_dict.get("SOPInstanceUID", None)
            if not fpath_SOPInstanceUID:
                logger.info(f"File {file_path} is missing its SOPInstanceUID.")
                continue
            
            fpath_FrameOfReferenceUID = fpath_refs_dict.get("FrameOfReferenceUID", None)
            if not fpath_FrameOfReferenceUID:
                logger.info(f"File {file_path} is missing its FrameOfReferenceUID.")
                continue
            if fpath_FrameOfReferenceUID != active_frame_of_reference_uid:
                logger.info(f"File {file_path} has a FrameOfReferenceUID mismatch: {fpath_FrameOfReferenceUID} != {active_frame_of_reference_uid}")
                continue
            
            # Handle Images
            if fpath_modality in ["CT", "MR", "MRI", "PT", "PET"]:
                fpath_SIUID = fpath_refs_dict.get("SeriesInstanceUID", None)
                if not fpath_SIUID:
                    logger.info(f"File {file_path} with modality {fpath_modality} is missing its SeriesInstanceUID.")
                    continue
                
                if fpath_SIUID not in image_data:
                    image_data[fpath_SIUID] = {"Modality": fpath_modality, "Filepaths": []}
                elif image_data[fpath_SIUID]["Modality"] is None:
                    image_data[fpath_SIUID]["Modality"] = fpath_modality
                
                if fpath_modality != image_data[fpath_SIUID]["Modality"]:
                    logger.info(f"File {file_path} modality mismatch for SeriesInstanceUID {fpath_SIUID}: {fpath_modality} vs {image_data[fpath_SIUID]['Modality']}")
                    continue
                
                if file_path in image_data[fpath_SIUID]["Filepaths"]:
                    logger.info(f"File {file_path} is already listed for SeriesInstanceUID {fpath_SIUID}")
                    continue
                
                image_data[fpath_SIUID]["Filepaths"].append(file_path)
                continue
            
            # Add non-image files to the RT Links dict
            if not fpath_SOPInstanceUID in rt_links:
                rt_links[fpath_SOPInstanceUID] = {"Filepath": file_path, "Modality": fpath_modality, "Linked_Modalities": []}
            elif rt_links[fpath_SOPInstanceUID]["Filepath"] is None and rt_links[fpath_SOPInstanceUID]["Modality"] is None:
                rt_links[fpath_SOPInstanceUID]["Filepath"] = file_path
                rt_links[fpath_SOPInstanceUID]["Modality"] = fpath_modality
            
            # NOTES on RT Links:
            # RTSTRUCT ReferencedSeriesInstanceUID -> CT/MR/etc SeriesInstanceUID ... 
            # RTPLAN ReferencedSOPInstanceUID -> RTSTRUCT SOPInstanceUID ... 
            # RTDOSE ReferencedSOPInstanceUID -> RTPLAN SOPInstanceUID
            fpath_ref_SIUIDs = fpath_refs_dict.get("ReferencedSeriesInstanceUID", [])
            for fpath_ref_SIUID in fpath_ref_SIUIDs:
                if not fpath_ref_SIUID in image_data:
                    image_data[fpath_ref_SIUID] = {"Modality": None, "Filepaths": []}
                rt_links[fpath_SOPInstanceUID]["Linked_Modalities"].append({fpath_ref_SIUID: image_data[fpath_ref_SIUID]})
            
            fpath_ref_SOPIUIDs = fpath_refs_dict.get("ReferencedSOPInstanceUID", [])
            for fpath_ref_SOPIUID in fpath_ref_SOPIUIDs:
                if not fpath_ref_SOPIUID in rt_links:
                    rt_links[fpath_ref_SOPIUID] = {"Filepath": None, "Modality": None, "Linked_Modalities": []}
                rt_links[fpath_SOPInstanceUID]["Linked_Modalities"].append({fpath_ref_SOPIUID: rt_links[fpath_ref_SOPIUID]})
    
    return image_data, rt_links

def _load_selected_data(
    sender: Union[str, int],
    app_data: Any,
    user_data: Tuple[PatientData, Any, Dict[str, Any], Dict[str, Any], Dict[str, List[Any]]]
) -> None:
    """
    Load selected patient data into the application based on user input.

    Args:
        sender: The tag of the triggering item.
        app_data: Additional event data.
        user_data: Tuple containing (active_pt, active_frame_of_reference_uid, all_image_data_dict, all_rt_links_dict, checkbox_states).
    """
    active_pt, active_frame_of_reference_uid, all_image_data_dict, all_rt_links_dict, checkbox_states = user_data
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    logger.info("Starting to load selected data. Please wait...")
    
    rt_links_data_dict: Dict[str, List[Any]] = {"IMAGE": [], "RTSTRUCT": [], "RTPLAN": [], "RTDOSE": []}
    
    for siuid, image_dict in all_image_data_dict.items():
        modality = image_dict.get("Modality")
        if not modality:
            logger.warning(f"Missing modality for SIUID: {siuid}. Data not loaded.")
            continue
        checked_fpaths = [
            fpath for fpath in image_dict.get("Filepaths", [])
            if any(dpg.get_value(checkbox_id) for checkbox_id in checkbox_states.get(fpath, []))
        ]
        if not checked_fpaths:
            continue
        rt_links_data_dict["IMAGE"].append((modality, siuid, checked_fpaths))
    
    for sop_instance_uid, rt_links_dict in all_rt_links_dict.items():
        modality = rt_links_dict.get("Modality")
        if modality is None:
            continue
        file_path = rt_links_dict.get("Filepath")
        if not any(dpg.get_value(checkbox_id) for checkbox_id in checkbox_states.get(file_path, [])):
            continue
        modality_upper = modality.upper()
        if modality_upper in ["RS", "RTS", "RTSTR", "RTSTRUCT", "STRUCT"]:
            rt_links_data_dict["RTSTRUCT"].append((modality, sop_instance_uid, file_path))
        elif modality_upper in ["RP", "RTP", "RTPLAN", "PLAN"]:
            rt_links_data_dict["RTPLAN"].append((modality, sop_instance_uid, file_path))
        elif modality_upper in ["RD", "RTD", "RTDOSE", "DOSE", "RD BEAM", "RTD BEAM", "RTDOSE BEAM", "DOSE BEAM", "RD PLAN", "RTD PLAN", "RTDOSE PLAN", "DOSE PLAN"]:
            rt_links_data_dict["RTDOSE"].append((modality, sop_instance_uid, file_path))
        else:
            logger.warning(f"Unknown modality: {modality}. Data not loaded.")
    
    patient_id = active_pt.return_patient_id()
    data_mgr.load_all_dicom_data(rt_links_data_dict, patient_id)
    
    fill_right_col_ptdata(active_pt, active_frame_of_reference_uid)
    request_texture_update(texture_action_type="initialize")
