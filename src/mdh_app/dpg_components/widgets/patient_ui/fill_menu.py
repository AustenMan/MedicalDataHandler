from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Dict, Any, List


import dearpygui.dearpygui as dpg


from mdh_app.database.db_utils import update_patient_accessed_at
from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme
from mdh_app.dpg_components.windows.save_data.save_data_win import create_save_window
from mdh_app.dpg_components.widgets.patient_ui.images import add_images_to_menu
from mdh_app.dpg_components.widgets.patient_ui.doses import add_doses_to_menu, _add_rtd_buttons
from mdh_app.dpg_components.widgets.patient_ui.plans import add_plans_to_menu, _add_rtp_button
from mdh_app.dpg_components.widgets.patient_ui.structure_sets import add_structure_sets_to_menu


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.database.models import Patient


logger = logging.getLogger(__name__)


def fill_right_col_ptdata(active_pt: Patient) -> None:
    """
    Populate the right column of the UI with patient data modification options.

    Args:
        active_pt: The active patient object.
    """
    if active_pt is None:
        return
    
    update_patient_accessed_at(active_pt)
    
    # Get necessary parameters
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    size_dict = get_user_data(td_key="size_dict")
    tag_ptinfo_button = get_tag("ptinfo_button")
    tag_save_button = get_tag("save_button")
    
    # Patient Info Section
    ptinfo_label = "Patient Info"
    btn_width = round(dpg.get_text_size(str(ptinfo_label))[0] * 1.5)
    btn_height = 0 if ptinfo_label else size_dict["button_height"]
    dpg.add_button(
        tag=tag_ptinfo_button,
        parent="mw_right",
        label="Patient Info",
        width=btn_width,
        height=btn_height,
        user_data=active_pt,
    )
    dpg.bind_item_theme(tag_ptinfo_button, get_hidden_button_theme())
    patient_mrn, patient_name = active_pt.mrn, active_pt.name
    with dpg.group(parent="mw_right", horizontal=True):
        dpg.add_text(default_value="ID/MRN:", bullet=True)
        btn_height = 0 if patient_mrn else size_dict["button_height"]
        dpg.add_input_text(
            default_value=patient_mrn,
            width=size_dict["button_width"],
            height=btn_height,
            readonly=True,
            hint="Patient ID"
        )
    with dpg.group(parent="mw_right", horizontal=True):
        dpg.add_text(default_value="Name:", bullet=True)
        btn_height = 0 if patient_name else size_dict["button_height"]
        dpg.add_input_text(
            default_value=patient_name,
            width=size_dict["button_width"],
            height=btn_height,
            readonly=True,
            hint="Patient Name"
        )
    add_custom_button(
        label="Save Data",
        tag=tag_save_button,
        parent_tag="mw_right",
        callback=create_save_window,
        user_data={},
        add_spacer_before=True,
        add_separator_after=True,
        visible=False
    )
    
    # Retrieve data mappings
    rtp_rtd_mappings: Dict[str, Any] = data_mgr.get_rtp_rtd_mappings()
    rtp_rtd_mapped: Dict[str, List[str]] = rtp_rtd_mappings.get("plan_to_doses", {})
    rtdoses_unmapped: List[str] = rtp_rtd_mappings.get("unmapped_doses", [])
    rtplans_unmapped: List[str] = rtp_rtd_mappings.get("unmapped_plans", [])

    add_images_to_menu()
    _update_rmenu_matched_rtd_rtp(rtp_rtd_mapped)
    add_doses_to_menu(rtdoses_unmapped)
    add_plans_to_menu(rtplans_unmapped)
    add_structure_sets_to_menu()
    
    # Show the save button after all data is loaded
    dpg.configure_item(tag_save_button, show=True)


def _update_rmenu_matched_rtd_rtp(rtp_rtd_mapped: Dict[str, List[str]]) -> None:
    """
    Update the right menu with linked RT Dose and RT Plan data.

    Args:
        rtp_rtd_mapped: Dictionary of RT Plan SOPInstanceUIDs mapped to lists of RT Dose SOPInstanceUIDs.
    """
    if not rtp_rtd_mapped:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Doses & Plans (Linked)", default_open=True):
        for idx, (rtp_sopiuid, rtd_sopiuids) in enumerate(rtp_rtd_mapped.items(), start=1):
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=f"Linked Group #{idx}", default_open=True):
                _add_rtp_button(modality_node, rtp_sopiuid)
                _add_rtd_buttons(modality_node, rtp_sopiuid, rtd_sopiuids)
        dpg.add_spacer(height=size_dict["spacer_height"])





