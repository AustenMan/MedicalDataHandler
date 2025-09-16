from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict, Tuple, Set
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.database.db_utils import get_num_patients, get_patient_full
from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_separator
from mdh_app.dpg_components.themes.table_themes import get_table_cell_spacing_theme
from mdh_app.dpg_components.windows.data_table.data_table_utils import (
    get_patient_dates, confirm_removal_callback, load_patient_data, build_dicom_structure,
)
from mdh_app.dpg_components.windows.dicom_search.dcm_search_win import create_dicom_action_window
from mdh_app.dpg_components.windows.patient_object.pt_obj_window import create_window_ptobj_inspection
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete


if TYPE_CHECKING:
    from mdh_app.database.models import Patient
    from mdh_app.managers.dicom_manager import DicomManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


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
    tag_filter_processed = get_tag("input_filter_processed")
    tag_filter_name = get_tag("input_filter_name")
    tag_filter_mrn = get_tag("input_filter_mrn")
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.9, height_ratio=0.9)
    
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
            horizontal_scrollbar=True,
            on_close=lambda: dpg.hide_item(tag_data_window), 
            user_data={}
        )
        dpg.bind_item_theme(tag_data_window, get_table_cell_spacing_theme(6, 6))
        
        # Add button table        
        with dpg.table(parent=tag_data_window, header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.5)
            dpg.add_table_column(init_width_or_weight=0.5)
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by a specific patient name. Reload table to apply.")
                    dpg.add_text("Name: ")
                    dpg.add_input_text(tag=tag_filter_name, width=size_dict["button_width"], default_value="", on_enter=True)
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by a specific patient MRN. Reload table to apply.")
                    dpg.add_text("MRN: ")
                    dpg.add_input_text(tag=tag_filter_mrn, width=size_dict["button_width"], default_value="", on_enter=True)
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by data that you have previously processed. Reload table to apply.")
                    dpg.add_text("Processed Type: ")
                    dpg.add_combo(tag=tag_filter_processed, items=["Any", "Processed", "Unprocessed"], default_value="Any", width=size_dict["button_width"])
                
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Specify the page number for the data table. Reload table to apply.")
                    dpg.add_text("Page: ")
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
                    )
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=(
                                "Specify the number of patients to display per page.\n"
                                "Large values may experience performance issues.\n"
                                "Reload table to apply."
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
                    )
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                            dpg.add_text(
                                default_value=(
                                    "Loads/reloads the data table with patient data."
                                )
                            )
                    dpg.add_button(
                        tag=tag_table_reload_button,
                        width=size_dict["button_width"],
                        label="Load Data Table",
                        callback=wrap_with_cleanup(_create_ptobj_table),
                    )
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                            dpg.add_text(
                                default_value=(
                                    "Add patient data to this local database by reading DICOM files from a directory."
                                )
                            )
                    dpg.add_button(
                        width=size_dict["button_width"],
                        label="Add New Data",
                        callback=create_dicom_action_window, 
                    )
                        
        
        add_custom_separator(parent_tag=tag_data_window)
    else:
        set_visible = force_show or not dpg.is_item_shown(tag_data_window)
        prev_label = dpg.get_item_label(tag_data_window)
        dpg.configure_item(tag_data_window, label=label or prev_label, width=popup_width, height=popup_height, collapsed=not set_visible, show=set_visible)
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
        inner_width=size_dict["table_w"] * 3,
        height=size_dict["table_h"]
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
    original_reload_label = dpg.get_item_label(tag_table_reload_button)
    dpg.configure_item(tag_table_reload_button, enabled=False, label="Loading...")
    
    # Get necessary parameters
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    tag_table_rows_input = get_tag("table_rows_input")
    tag_table_page_input = get_tag("table_page_input")
    tag_filter_processed = get_tag("input_filter_processed")
    tag_filter_name = get_tag("input_filter_name")
    tag_filter_mrn = get_tag("input_filter_mrn")
    size_dict = get_user_data(td_key="size_dict")
    
    # Find number of patients and number of rows to display
    num_pts = get_num_patients()
    num_table_rows = max(1, min(dpg.get_value(tag_table_rows_input), num_pts))

    # Calculate number of pages and current page
    if num_pts == 0:
        num_pages = 1
    else:
        num_pages = (num_pts + num_table_rows - 1) // num_table_rows
    table_page = max(1, min(dpg.get_value(tag_table_page_input), num_pages))
    
    # Configure the limits on the table rows/indices inputs
    table_index = table_page - 1
    dpg.configure_item(tag_table_rows_input, max_value=num_pts)
    dpg.set_value(tag_table_rows_input, num_table_rows)
    dpg.configure_item(tag_table_page_input, max_value=num_pages)
    dpg.set_value(tag_table_page_input, table_page)
    
    # Get filter values
    filter_processed_value = dpg.get_value(tag_filter_processed)
    find_never_processed = {"Processed": False, "Unprocessed": True}.get(filter_processed_value, None)
    mrn_search = dpg.get_value(tag_filter_mrn) or None
    name_search = dpg.get_value(tag_filter_name) or None
    
    # Load relevant patient data
    if sender == tag_table_reload_button:
        subset_pt_data: Dict[Tuple[str, str], Patient] = dcm_mgr.load_patient_data_from_db(
            subset_size=num_table_rows, 
            subset_idx=table_index,
            never_processed=find_never_processed,
            filter_mrns=mrn_search,
            filter_names=name_search)
        dpg.set_item_user_data(tag_data_window, subset_pt_data)
    else:
        subset_pt_data = dpg.get_item_user_data(tag_data_window)
    
    # Show the data window and create a new data table
    toggle_data_window(force_show=True, label="Patient Data")
    _create_new_data_table()
    tag_data_table = get_tag("data_table") # retrieve after creating the new table (UUID changes)
    
    column_labels = ["Actions", "Patient Name", "Patient ID", "Date Created", "Date Last Modified", "Date Last Accessed", "Date Last Processed"]
    for label in column_labels:
        dpg.add_table_column(parent=tag_data_table, label=label, width_fixed=True)
    
    pobj_insp_cb = lambda s, a, u: ss_mgr.submit_action(partial(create_window_ptobj_inspection, s, a, u))
    for (patient_id, patient_name), patient_obj in subset_pt_data.items():
        pdata_row_tag = dpg.generate_uuid()
        with dpg.table_row(tag=pdata_row_tag, parent=tag_data_table):
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Select", 
                    height=size_dict["button_height"], 
                    callback=_display_patient_files_table, 
                    user_data=patient_obj
                )
                dpg.add_button(
                    label="Inspect", 
                    height=size_dict["button_height"], 
                    callback=pobj_insp_cb,
                    user_data=patient_obj
                )
                dpg.add_button(
                    label="Remove",
                    height=size_dict["button_height"],
                    callback=confirm_removal_callback,
                    user_data=(pdata_row_tag, patient_obj)
                )
            dpg.add_text(default_value=patient_name)
            dpg.add_text(default_value=patient_id)
            dates_dict = get_patient_dates(patient_obj)
            dpg.add_text(default_value=dates_dict["DateCreated"] if dates_dict["DateCreated"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastModified"] if dates_dict["DateLastModified"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastAccessed"] if dates_dict["DateLastAccessed"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastProcessed"] if dates_dict["DateLastProcessed"] is not None else "N/A")
    
    # Unfreeze interaction with the table after updating
    dpg.configure_item(tag_table_reload_button, enabled=True, label=original_reload_label)


def _display_patient_files_table(sender: Union[str, int], app_data: Any, user_data: Patient) -> None:
    """ Renders a table of a patient's DICOM files, grouped by type and relationship. """
    # Ensure relationships are loaded
    patient = get_patient_full(user_data.id)
    if not patient:
        logger.error("Patient not found / could not load.")
        return

    # Set up UI
    size_dict = get_user_data(td_key="size_dict")
    toggle_data_window(force_show=True, label=f"Data for Patient: {(patient.mrn, patient.name)}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table")
    
    # Table Setup
    dpg.add_table_column(parent=tag_data_table, label="Selections", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Name(s)", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Label(s)", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Description(s)", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Date/Time(s)", width_fixed=True)

    # Track selected files for loading
    selected_files: Set[str] = set()
    loading_ud = (patient, selected_files)
    
    # Control Row
    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            back_label = "Go Back"
            dpg.add_button(
                label=back_label,
                width=round(dpg.get_text_size(back_label)[0] * 2),
                height=size_dict["button_height"],
                callback=_create_ptobj_table,
            )
            load_label = "Load Selected Data"
            dpg.add_button(
                label=load_label,
                width=round(dpg.get_text_size(load_label)[0] * 2),
                height=size_dict["button_height"],
                callback=wrap_with_cleanup(load_patient_data),
                user_data=loading_ud
            )
    
    # Build DICOM structure
    build_dicom_structure(*loading_ud)

