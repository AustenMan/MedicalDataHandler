from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, List


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def add_doses_to_menu(rtdoses_sopiuids: List[str]) -> None:
    """ Update the right menu with dose data. """
    if not rtdoses_sopiuids:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Doses (Unlinked)", default_open=True):
        for rtd_sopiuid in rtdoses_sopiuids:
            _add_rtd_button("mw_right", rtd_sopiuid)
        dpg.add_spacer(height=size_dict["spacer_height"])


def _add_rtd_button(parent: Union[str, int], rtd_sopiuid: str) -> None:
    """ Add a button for an RT Dose under the given parent. """
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    tag_save_dict = get_user_data("save_button")
    size_dict = get_user_data(td_key="size_dict")

    modality = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "Modality", "RT Dose")
    dose_units = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "DoseUnits", "")
    dose_type = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "DoseType", "")
    dose_comment = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "DoseComment", "")
    dose_summation_type = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "DoseSummationType", "")
    date = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ContentDate", "N/A")
    time = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ContentTime", "")
    ref_rtp_sopiuid = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReferencedRTPlanSOPInstanceUID", "")
    ref_beam_number = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReferencedRTPlanBeamNumber", "")
    num_fxns_planned = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractionsPlanned", "0")
    num_fxns = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractions", "0")
    approval_status = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ApprovalStatus", "N/A")
    review_date = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReviewDate", "N/A")
    review_time = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReviewTime", "")
    reviewer_name = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReviewerName", "N/A")
    
    rtplan_label = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanLabel", "") if ref_rtp_sopiuid else ""
    rtplan_name = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanName", "") if ref_rtp_sopiuid else ""
    rtplan_description = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanDescription", "") if ref_rtp_sopiuid else ""
    rtplan_descriptor = rtplan_label or rtplan_name or rtplan_description
    
    rtd_btn_label = f"{dose_summation_type.title()} #{ref_beam_number} Dose" if (dose_summation_type and ref_beam_number) else (f"{dose_summation_type.title()} Dose" if dose_summation_type else "RT Dose")
    rtd_btn_label += f" for RT Plan '{rtplan_descriptor}'" if rtplan_descriptor else ""
    rtd_text = (
        f"Modality: {modality}\n"
        f"Dose Units: {dose_units}\n"
        f"Dose Type: {dose_type}\n"
        f"Dose Comment: {dose_comment}\n"
        f"Dose Summation Type: {dose_summation_type}\n"
        f"Referenced RT Plan Label/Name/Description: '{rtplan_label}'/'{rtplan_name}'/'{rtplan_description}'\n"
        f"Referenced RT Plan Beam Number: {ref_beam_number if ref_beam_number else 'N/A'}\n"
        f"Number of Fractions Planned (as intended by RT Plan): {num_fxns_planned}\n"
        f"Number of Fractions (as shown in the Dose): {num_fxns if num_fxns != "0" else "N/A"}\n"
        f"Content Date and Time: {date} {time}\n"
        f"Approval Status: {approval_status}\n"
        f"Review Date and Time: {review_date} {review_time}\n"
        f"Reviewer Name: {reviewer_name}\n"
    )
    
    with dpg.group(horizontal=True):
        dpg.add_checkbox(default_value=False, callback=update_cbox_callback, user_data=("dose", rtd_sopiuid))
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Display dose", wrap=size_dict["tooltip_width"])
        
        tag_button = dpg.add_button(
            label=rtd_btn_label,
            width=size_dict["button_width"],
            callback=_popup_inspect_rtdose,
            user_data=rtd_sopiuid,
        )
        with dpg.tooltip(parent=tag_button):
            dpg.add_text(rtd_text, tag=f"{tag_button}_tooltiptext", wrap=size_dict["tooltip_width"])
        dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
    
    tag_save_dict[("rtdose", rtd_sopiuid)] = tag_button


def _update_rtd_metadata_and_button_tooltip(sender: Union[str, int], app_data: Any, user_data: Tuple[str, Union[str, int], str, Any]) -> None:
    """ Update the tooltip for an RT Dose button with current metadata. """
    new_val = app_data
    rtd_sopiuid, tag_tooltiptext, meta_key = user_data
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    
    # Update the metadata
    data_mgr.set_rtdose_metadata_by_uid_and_key(rtd_sopiuid, meta_key, new_val)
    logger.info(f"Updated metadata {meta_key} with value {new_val}.")
    
    # If the tooltip text item doesn't exist, return
    if not dpg.does_item_exist(tag_tooltiptext):
        return
    
    # If the key is not one we care about for updating tooltip, return
    if meta_key not in ["NumberOfFractionsPlanned", "NumberOfFractions"]:
        return
    
    # Get new metadata values
    num_fxns_planned = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractionsPlanned", "0")
    num_fxns = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractions", "0")

    # Replace only those lines in the tooltip text
    current_text = dpg.get_value(tag_tooltiptext)
    updated_lines = []
    for line in current_text.splitlines():
        if line.startswith("Number of Fractions Planned"):
            updated_lines.append(f"Number of Fractions Planned (as intended by RT Plan): {num_fxns_planned}")
        elif line.startswith("Number of Fractions (as shown in the Dose)"):
            updated_lines.append(f"Number of Fractions (as shown in the Dose): {num_fxns if num_fxns != '0' else 'N/A'}")
        else:
            updated_lines.append(line)
    dpg.set_value(tag_tooltiptext, "\n".join(updated_lines))


def _popup_inspect_rtdose(sender: Union[str, int], app_data: Any, user_data: Tuple[str, Union[str, int]]) -> None:
    """
    Open a popup window for RT Dose metadata inspection and editing.

    Args:
        sender: The tag of the button that triggered the popup.
        app_data: Additional event data.
        user_data: Tuple containing (RT Dose SOPInstanceUID, tooltip tag).
    """
    tag_inspect = get_tag("inspect_data_popup")
    safe_delete(tag_inspect)
    
    button_label = dpg.get_item_label(sender)
    tag_tooltiptext = f"{sender}_tooltiptext"
    rtd_sopiuid = user_data
    
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    dose_metadata = data_mgr.get_rtdose_metadata_dict_by_uid(rtd_sopiuid) or {}
    sorted_keys = sorted(dose_metadata.keys())
    
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params()
    text_W = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_W), 10)
    
    with dpg.window(
        tag=tag_inspect,
        label=f"Inspecting '{button_label}' Metadata",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_open_over_existing_popup=False,
    ):
        add_custom_button(
            label="SITK Dose Details",
            theme_tag=get_hidden_button_theme(),
            add_separator_after=True
        )
        add_custom_button(
            label="Editable Fields (Used to scale the dose! Read the tooltips!)",
            theme_tag=get_hidden_button_theme(),
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            for key, key_description in [
                (
                    "NumberOfFractionsPlanned", 
                    "Number of Fractions Planned (as intended by RT Plan). In other words, how many fractions the plan *should* represent. e.g., you may want the plan&dose to be 30 fractions, so you input 30 here."),
                (
                    "NumberOfFractions",
                    "Number of Fractions (as shown in the Dose). In other words, how many fractions the dose currently represents. e.g., the dose may represent 1 fraction, so you input 1 here, and the software will perform a correction to match the Number of Fractions Planned."
                )
            ]:
                if key not in sorted_keys:
                    logger.warning(f"Expected metadata key '{key}' not found in RT Dose metadata.")
                    continue
                
                sorted_keys.remove(key)
                title = key
                if len(title) > char_fit:
                    title = f"{title[:char_fit-3]}..."
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData key: {key}", wrap=size_dict["tooltip_width"])
                        dpg.add_text(title)
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(key_description, wrap=size_dict["tooltip_width"])
                        value = int(dose_metadata.get(key, 0) or 0)
                        dpg.add_input_int(
                            default_value=value,
                            width=size_dict["button_width"],
                            callback=_update_rtd_metadata_and_button_tooltip,
                            user_data=(rtd_sopiuid, tag_tooltiptext, key),
                            min_value=0, max_value=9999,
                            min_clamped=True, max_clamped=True
                        )
        
        # Add read-only fields for the remaining metadata
        add_custom_button(
            label="Read-Only Metadata Fields",
            theme_tag=get_hidden_button_theme(),
            add_separator_before=True,
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            for key in sorted_keys:
                title = str(key)
                if len(title) > char_fit:
                    title = f"{title[:char_fit-3]}..."
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData key: {key}", wrap=size_dict["tooltip_width"])
                        dpg.add_text(title)
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData value: {dose_metadata[key]}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(
                            default_value=str(dose_metadata[key]),
                            width=size_dict["button_width"],
                            readonly=True
                        )
        
        dpg.add_spacer(height=size_dict["spacer_height"])
