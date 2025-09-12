from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, Dict


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params
from mdh_app.utils.general_utils import find_disease_site
from mdh_app.managers.data_manager import PlanHandle


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def add_plans_to_menu(rtplans_unmatched_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with unmatched RT Plan data.

    Args:
        rtplans_unmatched_dict: Mapping of RT Plan SOP Instance UIDs to plan metadata.
    """
    if not rtplans_unmatched_dict:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Plans (Unlinked)", default_open=True):
        for idx, (rtp_sopiuid, rtplan_info_dict) in enumerate(rtplans_unmatched_dict.items(), start=1):
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=f"Unlinked RTPs Group #{idx}", default_open=True):
                _add_rtp_button(modality_node, rtp_sopiuid, rtplan_info_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])


def _add_rtp_button(tag_modality_node: Union[str, int], rtp_sopiuid: str) -> None:
    """
    Add an RT Plan button to the UI.

    Args:
        tag_modality_node: The parent tree node tag.
        rtp_sopiuid: The RT Plan SOP Instance UID.
        rtplan_info_dict: Metadata for the RT Plan.
    """
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    RTPlanLabel = rtplan_info_dict.get("RTPlanLabel", "")
    RTPlanName = rtplan_info_dict.get("RTPlanName", "")
    
    # Determine treatment machine from the beam dictionary.
    treatment_machines = list(set([m_name for beam_dict in rtplan_info_dict["beam_dict"].values() if (m_name := beam_dict.get("treatment_machine_name"))]))
    if len(treatment_machines) > 1:
        logger.info(f"Multiple treatment machines found for RT Plan '{RTPlanLabel}'. Using first: {treatment_machines}")
    treatment_machine = treatment_machines[0] if treatment_machines else None
    rtplan_info_dict["rt_plan_machine"] = treatment_machine
    
    # Get the original PTV names
    orig_ptv_names = data_mgr.get_orig_roi_names("ptv")
    
    # Try to find disease site
    plan_disease_site = rtplan_info_dict.get("rt_plan_disease_site", find_disease_site(RTPlanLabel, RTPlanName, orig_ptv_names))
    rtplan_info_dict["rt_plan_disease_site"] = plan_disease_site
    
    with dpg.group(parent=tag_modality_node, horizontal=True):
        plan_handle = PlanHandle(plan_uid=rtp_sopiuid)
        save_dict = dpg.get_item_user_data(tag_save_button)
        save_dict[plan_handle] = rtplan_info_dict

        tag_tooltip = dpg.generate_uuid()
        tag_button = dpg.add_button(
            label="RTP",
            width=size_dict["button_width"],
            callback=_popup_inspect_rtplan_dict,
            user_data=(rtp_sopiuid, rtplan_info_dict, tag_tooltip)
        )
        dpg.bind_item_theme(tag_button, get_colored_button_theme((90, 110, 70)))
        _update_rtp_button_tooltip(tag_button)


def _update_rtp_button_tooltip(tag_button: Union[str, int]) -> None:
    """
    Update the tooltip for an RT Plan button using current metadata.

    Args:
        tag_button: The tag of the RT Plan button.
    """
    rtp_sopiuid, rtplan_info_dict, tag_tooltip = dpg.get_item_user_data(tag_button)
    size_dict = get_user_data(td_key="size_dict")
    safe_delete(tag_tooltip)
    keys_to_show = [
        "RTPlanLabel", "RTPlanName", "RTPlanDescription", "RTPlanDate",
        "ApprovalStatus", "target_prescription_dose_cgy", "number_of_fractions_planned",
        "patient_position", "setup_technique"
    ]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text("Modality: RT Plan", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rtp_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_show:
            if key in rtplan_info_dict:
                value = rtplan_info_dict.get(key, "")
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])


def _popup_inspect_rtplan_dict(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """
    Open a popup to display and modify RT Plan attributes.

    rtplan_info_dict has the following keys:
        RTPlanLabel, RTPlanName, RTPlanDescription, RTPlanDate, RTPlanTime, ApprovalStatus, ReviewDate, ReviewTime,
        ReviewerName, target_prescription_dose_cgy, number_of_fractions_planned, number_of_beams, number_of_treatment_beams, patient_position, setup_technique, 
        beam_dict
    
    beam_dict has keys (beam_number), and values (dict). Each of those dicts has the following keys:
        beam_number, treatment_delivery_type, beam_dose, beam_meterset, manufacturers_model_name, device_serial_number, 
        treatment_machine_name, primary_dosimeter_unit, source_axis_distance, beam_name, beam_description, beam_type, 
        radiation_type, number_of_wedges, number_of_compensators, total_compensator_tray_factor, number_of_boli, number_of_blocks,
        total_block_tray_factor, final_cumulative_meterset_weight, number_of_control_points, referenced_patient_setup_number, 
        primary_fluence_mode, primary_fluence_mode_id, rt_beam_limiting_device_dict, wedge_dict, compensator_dict, block_dict,
        applicator_dict, control_point_dict, referenced_dose_SOPClassUID_list, referenced_dose_SOPInstanceUID_list, bolus_dict
    
    Args:
        sender: The tag of the button that triggered the popup.
        app_data: Additional event data.
        user_data: Tuple containing (RT Plan SOPInstanceUID, RT Plan metadata, tooltip tag).
    """
    tag_inspect = get_tag("inspect_data_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect)
    
    tag_button = sender
    rtp_sopiuid, rtplan_info_dict, tag_tooltip = user_data
    
    conf_mgr: ConfigManager = get_user_data("config_manager")
    disease_site_list = conf_mgr.get_disease_sites(ready_for_dpg=True)
    machine_list = conf_mgr.get_machine_names(ready_for_dpg=True)
    
    # Starts as a dict and becomes a string when overriden, so need to check for dict type
    ReviewerName: Union[str, Dict[str, Any]] = rtplan_info_dict.get("ReviewerName", "")
    if isinstance(ReviewerName, dict):
        ReviewerName = ReviewerName.get("Alphabetic", "")
    
    # Get general plan info
    RTPlanLabel = rtplan_info_dict.get("RTPlanLabel", "")
    RTPlanName = rtplan_info_dict.get("RTPlanName", "")
    RTPlanDescription = rtplan_info_dict.get("RTPlanDescription", "")
    RTPlanDate = rtplan_info_dict.get("RTPlanDate", "")
    ApprovalStatus = rtplan_info_dict.get("ApprovalStatus", "")
    target_rx_dose_cgy = rtplan_info_dict.get("target_prescription_dose_cgy", 0) or 0
    number_of_fractions_planned = rtplan_info_dict.get("number_of_fractions_planned", 0) or 0
    patient_position = rtplan_info_dict.get("patient_position", "")
    setup_technique = rtplan_info_dict.get("setup_technique", "")
    plan_disease_site = rtplan_info_dict.get("rt_plan_disease_site")
    treatment_machine = rtplan_info_dict.get("rt_plan_machine")
    
    # Get beam information
    total_num_beams = rtplan_info_dict.get("number_of_beams", 0)
    num_treatment_beams = len(rtplan_info_dict.get("beam_dict", {}))
    radiation_types = list(set([rtype for beam_dict in rtplan_info_dict["beam_dict"].values() if (rtype := beam_dict.get("radiation_type"))]))
    radiation_type_string = "MIXED" if len(radiation_types) > 1 else radiation_types[0] if radiation_types else None
    beam_numbers_with_wedge = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_wedges"]]
    beam_numbers_with_compensator = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_compensators"]]
    beam_numbers_with_bolus = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_boli"]]
    beam_numbers_with_block = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_blocks"]]
    unique_isocenters = list(set(
        tuple(iso_pos) for beam_dict in rtplan_info_dict["beam_dict"].values()
        for cp_dict in beam_dict["control_point_dict"].values() 
        if (iso_pos := cp_dict.get("isocenter_position"))
    ))
    num_unique_isocenters = len(unique_isocenters)
    
    popup_width, popup_height, popup_pos = get_popup_params()
    tag_base = f"{tag_inspect}_"
    
    # Callback function to update the rtplan_info_dict
    def update_rtplan_info_dict(sender: Union[str, int], app_data: Any, user_data: str) -> None:
        """
        Update a metadata field in the RT Plan dictionary.

        Args:
            sender: The tag of the event sender.
            app_data: The new value.
            user_data: The key in the RT Plan metadata to update.
        """
        field_name = user_data  # The field name passed as user_data
        new_value = app_data    # The new value from the input field
        rtplan_info_dict[field_name] = new_value
        _update_rtp_button_tooltip(tag_button)
        logger.info(f"Updated rtplan_info_dict[{field_name}] = {app_data}")
    
    with dpg.window(
        tag=tag_inspect,
        label="RT Plan Info",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_open_over_existing_popup=False
    ):
        add_custom_button(
            label="RT Plan Details",
            theme_tag=get_hidden_button_theme(),
            add_separator_after=True
        )
        add_custom_button(
            label="Editable Fields",
            theme_tag=get_hidden_button_theme(),
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            with dpg.table_row():
                dpg.add_text("RT Plan Label:")
                dpg.add_input_text(
                    tag=f"{tag_base}RTPlanLabel",
                    width=size_dict["button_width"],
                    default_value=RTPlanLabel,
                    hint="Enter a label for the plan",
                    callback=update_rtplan_info_dict,
                    user_data="RTPlanLabel"
                )
            with dpg.table_row():
                dpg.add_text("Disease Site:")
                dpg.add_combo(
                    tag=f"{tag_base}rt_plan_disease_site",
                    width=size_dict["button_width"],
                    default_value=plan_disease_site,
                    items=disease_site_list,
                    callback=update_rtplan_info_dict,
                    user_data="rt_plan_disease_site"
                )
            with dpg.table_row():
                dpg.add_text("Treatment Machine:")
                dpg.add_combo(
                    tag=f"{tag_base}rt_plan_machine",
                    width=size_dict["button_width"],
                    default_value=treatment_machine,
                    items=machine_list,
                    callback=update_rtplan_info_dict,
                    user_data="rt_plan_machine"
                )
            with dpg.table_row():
                dpg.add_text("Target Prescription Dose (cGy):")
                dpg.add_input_int(
                    tag=f"{tag_base}target_prescription_dose_cgy",
                    width=size_dict["button_width"],
                    default_value=target_rx_dose_cgy,
                    callback=update_rtplan_info_dict,
                    user_data="target_prescription_dose_cgy",
                    min_value=0,
                    max_value=9999,
                    min_clamped=True,
                    max_clamped=True
                )
            with dpg.table_row():
                dpg.add_text("Number Of Fractions Planned:")
                tag_plan_fxn_input = dpg.add_input_int(
                    tag=f"{tag_base}number_of_fractions_planned",
                    width=size_dict["button_width"],
                    default_value=number_of_fractions_planned,
                    callback=update_rtplan_info_dict,
                    user_data="number_of_fractions_planned",
                    min_value=0,
                    max_value=9999,
                    min_clamped=True,
                    max_clamped=True
                )
                with dpg.tooltip(parent=tag_plan_fxn_input):
                    dpg.add_text(f"Plan name will include this fraction count.", wrap=size_dict["tooltip_width"])
        
        add_custom_button(
            label="Read-only Fields",
            theme_tag=get_hidden_button_theme(),
            add_separator_before=True,
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            with dpg.table_row():
                dpg.add_text("RT Plan Name:")
                dpg.add_input_text(
                    tag=f"{tag_base}RTPlanName",
                    width=size_dict["button_width"],
                    default_value=RTPlanName,
                    hint="Plan name missing",
                    readonly=True,
                    user_data="RTPlanName"
                )
            with dpg.table_row():
                dpg.add_text("RT Plan Description:")
                dpg.add_input_text(
                    tag=f"{tag_base}RTPlanDescription",
                    width=size_dict["button_width"],
                    default_value=RTPlanDescription,
                    hint="Plan description missing",
                    readonly=True,
                    user_data="RTPlanDescription"
                )
            with dpg.table_row():
                dpg.add_text("Patient Position:")
                dpg.add_input_text(
                    tag=f"{tag_base}patient_position",
                    width=size_dict["button_width"],
                    default_value=patient_position,
                    hint="Patient position missing",
                    readonly=True,
                    user_data="patient_position"
                )
            with dpg.table_row():
                dpg.add_text("Setup Technique:")
                dpg.add_input_text(
                    tag=f"{tag_base}setup_technique",
                    width=size_dict["button_width"],
                    default_value=setup_technique,
                    hint="Setup technique missing",
                    readonly=True,
                    user_data="setup_technique"
                )
            with dpg.table_row():
                dpg.add_text("RT Plan Date:")
                dpg.add_input_text(
                    tag=f"{tag_base}RTPlanDate",
                    width=size_dict["button_width"],
                    default_value=RTPlanDate,
                    hint="Plan date missing",
                    readonly=True,
                    user_data="RTPlanDate"
                )
            with dpg.table_row():
                dpg.add_text("Approval Status:")
                dpg.add_input_text(
                    tag=f"{tag_base}ApprovalStatus",
                    width=size_dict["button_width"],
                    default_value=ApprovalStatus,
                    hint="Approval status missing",
                    readonly=True,
                    user_data="ApprovalStatus"
                )
            with dpg.table_row():
                dpg.add_text("Reviewer Name:")
                dpg.add_input_text(
                    tag=f"{tag_base}ReviewerName",
                    width=size_dict["button_width"],
                    default_value=ReviewerName,
                    hint="Reviewer missing",
                    readonly=True,
                    user_data="ReviewerName"
                )
        
        add_custom_button(
            label="Read-only Beam Info",
            theme_tag=get_hidden_button_theme(),
            add_separator_before=True,
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            with dpg.table_row():
                dpg.add_text("Radiation Type(s):")
                dpg.add_input_text(
                    tag=f"{tag_base}radiation_type",
                    width=size_dict["button_width"],
                    default_value=radiation_type_string,
                    hint="Radiation type information",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Number of Beams:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_beams",
                    width=size_dict["button_width"],
                    default_value=total_num_beams,
                    hint="Total beams in plan",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Number of Treatment Beams:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_treatment_beams",
                    width=size_dict["button_width"],
                    default_value=num_treatment_beams,
                    hint="Treatment beams count",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Number of Unique Isocenters:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_unique_isocenters",
                    width=size_dict["button_width"],
                    default_value=num_unique_isocenters,
                    hint="Unique isocenter count",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Unique Isocenter Positions:")
                dpg.add_input_text(
                    tag=f"{tag_base}unique_isocenters",
                    width=size_dict["button_width"],
                    default_value=unique_isocenters,
                    hint="Unique isocenter positions",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Beams with Wedges:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_beams_with_wedge",
                    width=size_dict["button_width"],
                    default_value=len(beam_numbers_with_wedge),
                    hint="Beams with wedges count",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Beams with Compensators:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_beams_with_compensator",
                    width=size_dict["button_width"],
                    default_value=len(beam_numbers_with_compensator),
                    hint="Beams with compensators count",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Beams with Bolus:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_beams_with_bolus",
                    width=size_dict["button_width"],
                    default_value=len(beam_numbers_with_bolus),
                    hint="Beams with bolus count",
                    readonly=True
                )
            with dpg.table_row():
                dpg.add_text("Beams with Blocks:")
                dpg.add_input_text(
                    tag=f"{tag_base}number_of_beams_with_block",
                    width=size_dict["button_width"],
                    default_value=len(beam_numbers_with_block),
                    hint="Beams with blocks count",
                    readonly=True
                )
