from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Dict, Any


import dearpygui.dearpygui as dpg
import SimpleITK as sitk


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
    
    # Retrieve RT Doses and RT Plans
    rtdoses_dict = data_mgr.get_modality_data("rtdose")
    rtplans_dict = data_mgr.get_modality_data("rtplan")
    
    # Update RT Doses with the number of fractions planned from the RT Plans
    for ref_rtp_sopiuid, rtdose_types_dict in rtdoses_dict.items():
        for rtdose_type, rtdose_value in rtdose_types_dict.items():
            fxns = str(int(rtplans_dict.get(ref_rtp_sopiuid, {}).get("number_of_fractions_planned", 0) or 0))
            if isinstance(rtdose_value, dict):
                for rtd_sopiuid, sitk_rtdose_ref in rtdose_value.items():
                    if sitk_rtdose_ref() is not None:
                        sitk_rtdose_ref().SetMetaData("number_of_fractions_planned", fxns)
            elif isinstance(rtdose_value, sitk.Image):
                rtdose_value.SetMetaData("number_of_fractions_planned", fxns)
    
    # Build mappings for matched and unmatched data
    images_dict = data_mgr.get_modality_data("image")
    rtd_rtp_matched_dict = {
        ref_rtp_sopiuid: (rtdoses_dict[ref_rtp_sopiuid], rtplans_dict[ref_rtp_sopiuid])
        for ref_rtp_sopiuid in rtdoses_dict if ref_rtp_sopiuid in rtplans_dict
    }
    rtdoses_unmatched_dict = {
        ref_rtp_sopiuid: rtdoses_dict[ref_rtp_sopiuid]
        for ref_rtp_sopiuid in rtdoses_dict if ref_rtp_sopiuid not in rtplans_dict
    }
    rtplans_unmatched_dict = {
        rtp_sopiuid: rtplans_dict[rtp_sopiuid]
        for rtp_sopiuid in rtplans_dict if rtp_sopiuid not in rtdoses_dict
    }
    rtstructs_dict = data_mgr.get_modality_data("rtstruct")
    
    add_images_to_menu(images_dict)
    _update_rmenu_matched_rtd_rtp(rtd_rtp_matched_dict)
    add_doses_to_menu(rtdoses_unmatched_dict)
    add_plans_to_menu(rtplans_unmatched_dict)
    add_structure_sets_to_menu(rtstructs_dict)
    
    # Show the save button after all data is loaded
    dpg.configure_item(tag_save_button, show=True)


def _update_rmenu_matched_rtd_rtp(rtd_rtp_matched_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with linked RT Dose and RT Plan data.

    Args:
        rtd_rtp_matched_dict: Dictionary of matched RT dose and RT plan data keyed by SOPInstanceUID.
    """
    if not rtd_rtp_matched_dict:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Doses & Plans (Linked)", default_open=True):
        for idx, (rtp_sopiuid, (rtd_dict, rtplan_dict)) in enumerate(rtd_rtp_matched_dict.items(), start=1):
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=f"Linked Group #{idx}", default_open=True):
                _add_rtp_button(modality_node, rtp_sopiuid, rtplan_dict)
                _add_rtd_buttons(modality_node, rtp_sopiuid, rtd_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])


def _update_rmenu_matched_rtd_rtp(rtd_rtp_matched_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with linked RT Dose and RT Plan data.

    Args:
        rtd_rtp_matched_dict: Dictionary of matched RT dose and RT plan data keyed by SOPInstanceUID.
    """
    if not rtd_rtp_matched_dict:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Doses & Plans (Linked)", default_open=True):
        for idx, (rtp_sopiuid, (rtd_dict, rtplan_dict)) in enumerate(rtd_rtp_matched_dict.items(), start=1):
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=f"Linked Group #{idx}", default_open=True):
                _add_rtp_button(modality_node, rtp_sopiuid, rtplan_dict)
                _add_rtd_buttons(modality_node, rtp_sopiuid, rtd_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])




