from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict, Tuple, Optional, Set, List


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.widgets.patient_ui.fill_menu import fill_right_col_ptdata
from mdh_app.dpg_components.windows.confirmation.confirm_window import create_confirmation_popup
from mdh_app.utils.dpg_utils import safe_delete
from mdh_app.dpg_components.core.dpg_patient_graph import k_file


if TYPE_CHECKING:
    from mdh_app.database.models import Patient
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.managers.dicom_manager import DicomManager
    from mdh_app.dpg_components.core.dpg_patient_graph import PatientGraph, CheckboxRegistry


logger = logging.getLogger(__name__)


def _get_patient_dates(patient: Patient) -> Dict[str, Optional[str]]:
    # Helper to return date fields as iso or "N/A"
    def dt_fmt(dt):
        return dt.isoformat() if dt else "N/A"
    return {
        "DateCreated": dt_fmt(patient.created_at),
        "DateLastModified": dt_fmt(patient.modified_at) if hasattr(patient, 'modified_at') else "N/A",
        "DateLastAccessed": dt_fmt(patient.accessed_at) if hasattr(patient, 'accessed_at') else "N/A",
        "DateLastProcessed": dt_fmt(patient.processed_at) if hasattr(patient, 'processed_at') else "N/A",
    }
    

def _confirm_removal_func(sender: Union[str, int], app_data: Any, user_data: Tuple[Union[str, int], Patient]) -> None:
    """Remove a patient data object after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    
    pd_row_tag: Union[str, int] = user_data[0]
    patient_obj: Patient = user_data[1]
    pt_key = (patient_obj.mrn, patient_obj.name)
    mrn, name = pt_key
    
    def delete_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_patient_from_db(mrn, name)
        safe_delete(pd_row_tag)
        all_patient_data: Dict[Tuple[str, str], Patient] = dpg.get_item_user_data(tag_data_window)
        if all_patient_data and pt_key in all_patient_data:
            all_patient_data.pop(pt_key, None)
            dpg.set_item_user_data(tag_data_window, all_patient_data)
    
    def submit_removal_func(sender, app_data, user_data) -> None:
        clean_wrap = wrap_with_cleanup(delete_func)
        clean_wrap(sender, app_data, user_data)
    
    create_confirmation_popup(
        button_callback=submit_removal_func,
        confirmation_text=f"Removing patient: MRN {mrn}, Name {name}",
        warning_string=(
            f"Are you sure you want to remove the patient:\n"
            f"MRN: {mrn}\nName: {name}\n"
            "This action is irreversible. You would need to re-import the data to access it again.\n"
            "Remove this patient?"
        )
    )


def build_dicom_label(d: dict, prefix: str = "RT MODALITY", override_core_search: str = "") -> str:
    """
    Build a compact label for display.
    Precedence: label > name > description > date > time > sopi.
    """
    core = override_core_search or (
        d.get("label")
        or d.get("name")
        or d.get("description")
        or d.get("date")
        or d.get("time")
        or d.get("sopi")
    )
    return f"{prefix} {core}"


def build_dicom_tooltip(d: dict) -> str:
    """Build a tooltip string from a DICOM metadata dict."""
    fields = [
        ("SOP Instance UID", d.get("sopi", "")),
        ("Label", d.get("label", "")),
        ("Name", d.get("name", "")),
        ("Description", d.get("description", "")),
        ("Date", d.get("date", "")),
        ("Time", d.get("time", "")),
        ("Modality", d.get("modality", "")),
    ]
    return "\n".join(f"{k}={v}" for k, v in fields if v)



def _load_selected_data(
    sender: Union[str, int],
    app_data: Any,
    user_data: Tuple[Patient, PatientGraph, CheckboxRegistry]
) -> None:
    """Load selected patient data into the application based on user input."""
    patient, g, reg = user_data
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    logger.info("Starting to load selected data. Please wait...")
    
    # Gather selected file paths
    selected_files: Set[str] = set()
    for path in reg.file_to_masters.keys():
        # Find any checkbox that represents this file.
        item_key = k_file(path)
        cbs = reg.item_to_cbs.get(item_key)
        if cbs and any(bool(dpg.get_value(cb)) for cb in cbs):
            selected_files.add(path)
    
    if not selected_files:
        logger.info("No files selected for loading.")
        return
    
    # Build rt_links_data_dict from graph + selected files
    rt_links_data_dict: Dict[str, List[Any]] = {
        "IMAGE":   [],  # (modality, series_instance_uid, [file_paths])
        "RTSTRUCT": [], # (modality, sop_instance_uid, struct_path, [ref_series_uids])
        "RTPLAN":  [],  # (modality, sop_instance_uid, plan_path, [ref_struct_sopi])
        "RTDOSE":  [],  # (modality, sopi, dose_path, dose_type, [ref_plans], [ref_structs], [ref_doses])
    }
    
    # IMAGES: include any series that has ≥1 selected file; include only selected files in the list
    for series_uid, entry in g.images_by_series.items():
        series_paths = [p for _s, p in entry["files"]]
        chosen = [p for p in series_paths if p in selected_files]
        if chosen:
            rt_links_data_dict["IMAGE"].append((entry["modality"], series_uid, chosen))
    
    # RTSTRUCT
    for struct_sopi, s in g.structs_by_sopi.items():
        if s["path"] in selected_files:
            rt_links_data_dict["RTSTRUCT"].append((s["modality"], struct_sopi, s["path"]))#, list(s["ref_series"])))
    
    # RTPLAN
    for plan_sopi, p in g.plans_by_sopi.items():
        if p["path"] in selected_files:
            rt_links_data_dict["RTPLAN"].append((p["modality"], plan_sopi, p["path"]))#, list(p["ref_structs"])))

    # RTDOSE beam groups - add individual doses if their file is selected
    for plan_sopi, doses in g.doses_beam_groups.items():
        for d in doses:
            if d["path"] in selected_files:
                rt_links_data_dict["RTDOSE"].append((
                    d["modality"], d["sopi"], d["path"], #d["dose_type"],
                    #list(d["ref_plans"]), list(d["ref_structs"]), list(d["ref_doses"])
                ))

    # RTDOSE plan items
    for d in g.doses_plan:
        if d["path"] in selected_files:
            rt_links_data_dict["RTDOSE"].append((
                d["modality"], d["sopi"], d["path"], #d["dose_type"],
                #list(d["ref_plans"]), list(d["ref_structs"]), list(d["ref_doses"])
            ))

    # Send to DataManager
    data_mgr.load_all_dicom_data(rt_links_data_dict, patient.mrn)
    
    fill_right_col_ptdata(patient)
    request_texture_update(texture_action_type="initialize")


