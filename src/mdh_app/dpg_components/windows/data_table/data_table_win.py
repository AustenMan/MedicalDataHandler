from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict, Tuple
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.database.db_utils import get_num_patients, get_patient_full
from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_separator
from mdh_app.dpg_components.themes.table_themes import get_table_cell_spacing_theme
from mdh_app.dpg_components.windows.data_table.data_table_utils import (
    _get_patient_dates, _load_selected_data, _confirm_removal_func,
    build_dicom_label, build_dicom_tooltip, 
)
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_win import create_popup_dicom_inspection
from mdh_app.dpg_components.windows.patient_object.pt_obj_window import create_window_ptobj_inspection
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete
from mdh_app.dpg_components.core.dpg_patient_graph import (
    CheckboxRegistry, build_patient_graph, add_file_checkbox, add_master_checkbox, 
    add_item_link_checkbox, k_file
)


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
            
            row_tag = dpg.generate_uuid()
            with dpg.table_row(tag=row_tag):
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by a specific patient name. Reload table to apply.")
                    dpg.add_text("Name: ")
                    dpg.add_input_text(
                        tag=tag_filter_name,
                        width=size_dict["button_width"],
                        default_value="",
                        on_enter=True,
                    )
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by a specific patient MRN. Reload table to apply.")
                    dpg.add_text("MRN: ")
                    dpg.add_input_text(
                        tag=tag_filter_mrn,
                        width=size_dict["button_width"],
                        default_value="",
                        on_enter=True,
                    )
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Filter by data that you have previously processed. Reload table to apply.")
                    dpg.add_text("Processed Type: ")
                    dpg.add_combo(
                        tag=tag_filter_processed,
                        items=["Any", "Processed", "Unprocessed"],
                        default_value="Any",
                        width=size_dict["button_width"],
                    )
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("Specify the page number for the data table. Reload table to apply.")
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
            
            row_tag = dpg.generate_uuid()
            with dpg.table_row(tag=row_tag):
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
                        label="Load or Reload Data Table",
                        callback=wrap_with_cleanup(_create_ptobj_table),
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
    
    logger.info("Updating the patient data table...")
    
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
    if filter_processed_value == "Processed":
        find_never_processed = False
    elif filter_processed_value == "Unprocessed":
        find_never_processed = True
    else:
        find_never_processed = None
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
    for label_idx, label in enumerate(column_labels):
        dpg.add_table_column(parent=tag_data_table, label=label, width_fixed=True)
    
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
                    callback=lambda s, a, u: ss_mgr.submit_action(partial(create_window_ptobj_inspection, s, a, u)),
                    user_data=patient_obj
                )
                dpg.add_button(
                    label="Remove",
                    height=size_dict["button_height"],
                    callback=_confirm_removal_func,
                    user_data=(pdata_row_tag, patient_obj)
                )
            dpg.add_text(default_value=patient_name)
            dpg.add_text(default_value=patient_id)
            dates_dict = _get_patient_dates(patient_obj)
            dpg.add_text(default_value=dates_dict["DateCreated"] if dates_dict["DateCreated"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastModified"] if dates_dict["DateLastModified"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastAccessed"] if dates_dict["DateLastAccessed"] is not None else "N/A")
            dpg.add_text(default_value=dates_dict["DateLastProcessed"] if dates_dict["DateLastProcessed"] is not None else "N/A")
    
    # Unfreeze interaction with the table after updating
    dpg.configure_item(tag_table_reload_button, enabled=True, label=original_reload_label)


def _display_patient_files_table(sender: Union[str, int], app_data: Any, user_data: "Patient") -> None:
    """
    Renders a table of a patient's DICOM files, grouped by type and relationship.
    """
    # Ensure relationships are loaded
    patient = get_patient_full(user_data.id)
    if not patient:
        logger.error("Patient not found / could not load.")
        return

    # Build graph and checkbox registry
    g = build_patient_graph(patient)
    reg = CheckboxRegistry()

    # Set up UI
    size_dict = get_user_data(td_key="size_dict")
    toggle_data_window(force_show=True, label=f"Data for Patient: {(patient.mrn, patient.name)}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table")

    # Table Setup
    dpg.add_table_column(parent=tag_data_table, label="Select", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Type", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="ID", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Group Data", width_fixed=True)

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
                callback=wrap_with_cleanup(_load_selected_data),
                user_data=(patient, g, reg),
            )
    
    # DICOM Viewing Callback
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_view_cb = lambda s, a, u: ss_mgr.submit_action(partial(create_popup_dicom_inspection, s, a, u))
    
    # Master Checkbox Dictionary
    master_dict = {'cbox': None, 'children': []}
    
    # RTDOSE Plan Rows
    for rtdose in g.doses_plan:
        self_path = rtdose["path"]
        rtd_ref_plans = rtdose.get("ref_plans", [])
        rtd_ref_structs = rtdose.get("ref_structs", [])
        rtd_ref_series = rtdose.get("ref_series", [])

        with dpg.table_row(parent=tag_data_table):
            dose_group_cbox = dpg.add_checkbox(label="RTD & Linked Items", callback=reg.on_change, user_data=master_dict)
            dose_group_dict = {'cbox': dose_group_cbox, 'children': []}
            master_dict['children'].append(dose_group_dict)
            
            dpg.add_text("RTDOSE (Plan)")
            dpg.add_text(default_value=rtdose["sopi"])
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"SOP Instance UID: {rtdose['sopi']}")
            
            label = f"References {len(rtd_ref_plans)} Plan(s), {len(rtd_ref_structs)} Struct(s)"
            with dpg.tree_node(label=label):
                dose_cbox = dpg.add_checkbox(label=build_dicom_label(rtdose, "RD"), callback=reg.on_change, user_data=master_dict)
                dose_dict = {'cbox': dose_cbox, 'children': []}
                dose_group_dict['children'].append(dose_dict)
                
                ### Maybe add images first, then structs, then plans? Then add links to all?
                
                for plan_sopi in rtd_ref_plans:
                    rtplan = g.plans_by_sopi.get(plan_sopi)
                    if rtplan:
                        rtplan_cbox = dpg.add_checkbox(label=build_dicom_label(rtplan, "RP"), callback=reg.on_change, user_data=dose_dict)
                        rtplan_dict = {'cbox': rtplan_cbox, 'children': []}
                        dose_dict['children'].append(rtplan_dict)
                        
                for rtstruct_sopi in rtplan.get("ref_structs", []):
                    rtstruct = g.structs_by_sopi.get(rtstruct_sopi)
                    if rtstruct:
                        rtstruct_cbox = dpg.add_checkbox(label=build_dicom_label(rtstruct, "RS"), callback=reg.on_change, user_data=rtplan_dict)
                        rtstruct_dict = {'cbox': rtstruct_cbox, 'children': []}
                        rtplan_dict['children'].append(rtstruct_dict)
                
                for img_suid in rtstruct.get("ref_series", []):
                    img_series = g.images_by_series.get(img_suid)
                    if img_series:
                        img_series_cbox = dpg.add_checkbox(
                            label=build_dicom_label(img_series, "IMG", img_suid), 
                            callback=reg.on_change, 
                            user_data=rtstruct_dict
                        )
                        img_series_dict = {'cbox': img_series_cbox, 'children': []}
                        rtstruct_dict['children'].append(img_series_dict)
                        reg.register_checkbox(img_series_cbox, k_file, g.collect_paths_for_series(img_suid))
                        
                        


                add_item_link_checkbox(build_dicom_label(rtdose, "RD"), build_dicom_tooltip(rtdose), "rd_plan", rtdose["sopi"], [self_path], reg, dcm_view_cb)
                for ps in ref_plans:
                    rp = g.plans_by_sopi.get(ps)
                    if rp:
                        add_item_link_checkbox(build_dicom_label(rp, "RP"), build_dicom_tooltip(rp), "rp", ps, [rp["path"]], reg, dcm_view_cb)
                for rs_sopi in ref_structs:
                    rs = g.structs_by_sopi.get(rs_sopi)
                    if rs:
                        add_item_link_checkbox(build_dicom_label(rs, "RS"), build_dicom_tooltip(rs), "rs", rs_sopi, [rs["path"]], reg, dcm_view_cb)
                        for suid in rs.get("ref_series", []):
                            ri = g.images_by_series.get(suid)
                            add_item_link_checkbox(
                                build_dicom_label(ri, "IMG", suid), build_dicom_tooltip(ri), "img", suid, g.collect_paths_for_series(suid), reg, dcm_view_cb
                            )
    
    # RTDOSE Beam Group Rows
    # --- RTDOSE Beam Group Rows ---
    for plan_sopi, doses in sorted(g.doses_beam_groups.items()):
        beam_paths = [d["path"] for d in doses]
        ref_plans, ref_structs, ref_series = set(), set(), set()
        for d in doses:
            ref_plans.update(d.get("ref_plans", []))
            ref_structs.update(d.get("ref_structs", []))
            ref_series.update(d.get("ref_series", []))

        rd_group_paths = list(beam_paths)
        for ps in ref_plans:
            rp = g.plans_by_sopi.get(ps)
            if rp:
                rd_group_paths.append(rp["path"])
        for rs_sopi in ref_structs:
            rs = g.structs_by_sopi.get(rs_sopi)
            if rs:
                rd_group_paths.append(rs["path"])
                for suid in rs.get("ref_series", []):
                    rd_group_paths.extend(g.collect_paths_for_series(suid))

        with dpg.table_row(parent=tag_data_table):
            add_master_checkbox("RTD & Linked Items", rd_group_paths, reg)
            dpg.add_text("RTDOSE (Beams)")
            dpg.add_text(default_value=plan_sopi)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"Ref. Plan SOP UID: {plan_sopi}")

            label = f"{len(doses)} Dose(s), {len(ref_plans)} Plan(s), {len(ref_structs)} Struct(s)"
            with dpg.tree_node(label=label):
                add_item_link_checkbox("RD (all beams)", "Inspect individual beam files", "rd_beams", plan_sopi, beam_paths, reg, dcm_view_cb)
                for d in doses:
                    with dpg.group(horizontal=True):
                        add_file_checkbox(d["path"], reg)
                        dpg.add_button(
                            label=build_dicom_label(d, "Beam: "),
                            user_data=d["path"],
                            callback=dcm_view_cb,
                        )
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(build_dicom_tooltip(d))
                for ps in sorted(ref_plans):
                    rp = g.plans_by_sopi.get(ps)
                    if rp:
                        add_item_link_checkbox(build_dicom_label(rp, "RP"), build_dicom_tooltip(rp), "rp", ps, [rp["path"]], reg, dcm_view_cb)
                for rs_sopi in sorted(ref_structs):
                    rs = g.structs_by_sopi.get(rs_sopi)
                    if rs:
                        add_item_link_checkbox(build_dicom_label(rs, "RS"), build_dicom_tooltip(rs), "rs", rs_sopi, [rs["path"]], reg, dcm_view_cb)
                        for suid in rs.get("ref_series", []):
                            ri = g.images_by_series.get(suid)
                            add_item_link_checkbox(
                                build_dicom_label(ri, "IMG", suid), build_dicom_tooltip(ri), "img", suid, g.collect_paths_for_series(suid), reg, dcm_view_cb
                            )
    
    # RTPLAN Rows
    for plan_sopi, p in sorted(g.plans_by_sopi.items()):
        self_path = p["path"]
        ref_series = p.get("ref_series", [])
        ref_structs = p.get("ref_structs", [])
        rp_group_paths = [self_path]
        for rs_sopi in ref_structs:
            rs = g.structs_by_sopi.get(rs_sopi)
            if rs:
                rp_group_paths.append(rs["path"])
                for suid in rs.get("ref_series", []):
                    rp_group_paths.extend(g.collect_paths_for_series(suid))

        with dpg.table_row(parent=tag_data_table):
            add_master_checkbox("RTP & Linked Items", rp_group_paths, reg)
            dpg.add_text("RTPLAN")
            dpg.add_text(default_value=plan_sopi)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"SOP Instance UID: {plan_sopi}")

            label = f"References {len(ref_structs)} Struct(s), {len(ref_series)} Image Group(s)"
            with dpg.tree_node(label=label):
                add_item_link_checkbox(build_dicom_label(p, "RP"), build_dicom_tooltip(p), "rp", plan_sopi, [self_path], reg, dcm_view_cb)
                for rs_sopi in ref_structs:
                    rs = g.structs_by_sopi.get(rs_sopi)
                    if rs:
                        add_item_link_checkbox(build_dicom_label(rs, "RS"), build_dicom_tooltip(rs), "rs", rs_sopi, [rs["path"]], reg, dcm_view_cb)
                        for suid in rs.get("ref_series", []):
                            ri = g.images_by_series.get(suid)
                            add_item_link_checkbox(
                                build_dicom_label(ri, "IMG", suid), build_dicom_tooltip(ri), "img", suid, g.collect_paths_for_series(suid), reg, dcm_view_cb
                            )
    
    # RTSTRUCT Rows
    for struct_sopi, s in sorted(g.structs_by_sopi.items()):
        self_path = s["path"]
        ref_series = s.get("ref_series", [])
        rs_group_paths = [self_path]
        for suid in ref_series:
            rs_group_paths.extend(g.collect_paths_for_series(suid))

        with dpg.table_row(parent=tag_data_table):
            master_dict = {'cbox': None, 'children': []}
            master_dict['cbox'] = dpg.add_checkbox(label="RTS & Linked Images", callback=reg.on_change, user_data=master_dict)
            dpg.add_text("RTSTRUCT")
            dpg.add_text(default_value=struct_sopi)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"SOP Instance UID: {struct_sopi}")

            with dpg.tree_node(label=f"References {len(ref_series)} Image Group(s)"):
                rs_cb = dpg.add_checkbox(label=build_dicom_label(s, "RS"), callback=reg.on_change, user_data=master_dict) # build_dicom_tooltip(s)
                master_dict['children'].append({'cbox': rs_cb, 'children': []})
                # add_item_link_checkbox(build_dicom_label(s, "RS"), build_dicom_tooltip(s), "rs", struct_sopi, [self_path], reg, dcm_view_cb)
                for suid in ref_series:
                    ri = g.images_by_series.get(suid)
                    add_item_link_checkbox(
                        build_dicom_label(ri, "IMG", suid), build_dicom_tooltip(ri), "img", suid, g.collect_paths_for_series(suid), reg, dcm_view_cb
                    )
    
    # Image Group Rows
    for series_uid, entry in sorted(g.images_by_series.items()):
        series_paths = g.collect_paths_for_series(series_uid)
        with dpg.table_row(parent=tag_data_table):
            master_cbox = dpg.add_checkbox(label="Image Group", callback=reg.on_change, user_data=([series_uid], master_dict))
            dpg.add_text("IMAGE")
            dpg.add_text(default_value=series_uid)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"SeriesInstanceUID: {series_uid}")

            with dpg.tree_node(label=f"References {len(series_paths)} Image file(s)"):
                img_cb = dpg.add_checkbox(label="IMG", callback=reg.on_change, user_data=([series_uid], master_dict))
                img_dict = {'cbox': img_cb, 'children': []}
                for sopi, path in entry["files"]:
                    with dpg.group(horizontal=True):
                        file_cb = dpg.add_checkbox(label=label, callback=reg.on_change, user_data=([sopi], master_dict))
                        img_dict['children'].append({'cbox': file_cb, 'children': []})
                        dpg.add_button(
                            label=f"{entry['modality']}: {sopi}",
                            user_data=path,
                            callback=dcm_view_cb,
                        )
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(f"Path: {path}")
                master_dict['children'].append(img_dict)
        
        master_dict = {'cbox': None, 'children': []}



