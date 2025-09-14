from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, Dict, List


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_win import create_popup_dicom_inspection
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def add_plans_to_menu(rtplans_sopiuids: List[str]) -> None:
    """ Update the right menu with plan data. """
    if not rtplans_sopiuids:
        return
    
    size_dict = get_user_data(td_key="size_dict")

    with dpg.tree_node(parent="mw_right", label="RT Plans (Unlinked)", default_open=True):
        for rtp_sopiuid in rtplans_sopiuids:
            _add_rtp_button("mw_right", rtp_sopiuid)
        dpg.add_spacer(height=size_dict["spacer_height"])
            
def _add_rtp_button(parent: Union[str, int], rtp_sopiuid: str) -> None:
    """ Add a button for an RT Plan under the given parent. """
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    tag_save_dict = get_user_data("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    file_path = data_mgr.get_rtplan_filepath_by_uid(rtp_sopiuid)
    modality = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "Modality", "RT Plan")
    label = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanLabel", "")
    name = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanName", "")
    description = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanDescription", "")
    date = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanDate", "N/A")
    time = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanTime", "")
    num_fxns_planned = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "NumberOfFractionsPlanned", 1)
    approval_status = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "ApprovalStatus", "N/A")
    review_date = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "ReviewDate", "N/A")
    review_time = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "ReviewTime", "")
    reviewer_name = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "ReviewerName", "N/A")

    rtp_btn_descriptor = label or name or description or modality
    rtp_button_label = f"{modality} - {rtp_btn_descriptor}" if rtp_btn_descriptor else modality
    rtp_text = (
        f"RT Plan Label: {label}\n"
        f"RT Plan Name: {name}\n"
        f"RT Plan Description: {description}\n"
        f"RT Plan Date and Time: {date} {time}\n"
        f"Number of Fractions Planned: {num_fxns_planned}\n"
        f"Approval Status: {approval_status}\n"
        f"Review Date and Time: {review_date} {review_time}\n"
        f"Reviewer Name: {reviewer_name}\n"
    )
    rtp_btn_width = round(dpg.get_text_size(rtp_button_label)[0] * 1.1)
    
    beam_summaries: List[Dict[str, Any]] = data_mgr.get_rtplan_ds_beam_summary_by_uid(rtp_sopiuid)
    overall_beam_summary: Dict[str, Any] = data_mgr.get_rtplan_ds_overall_beam_summary_by_uid(rtp_sopiuid, beam_summaries)
    beam_summary_text = "Click to view beam information for this RT Plan." + (" Brief summary:\n" if overall_beam_summary else "")
    for key, value in overall_beam_summary.items():
        beam_summary_text += f"{key}: {value}\n"
    
    with dpg.group(parent=parent, horizontal=True):
        tag_rtp_button = dpg.add_button(
            label=rtp_button_label,
            width=rtp_btn_width,
            callback=create_popup_dicom_inspection,
            user_data=file_path,
        )
        with dpg.tooltip(parent=tag_rtp_button):
            dpg.add_text(f"Click to view RT Plan DICOM data. Brief summary:\n" + rtp_text, tag=f"{rtp_button_label}_tooltiptext", wrap=size_dict["tooltip_width"])
        dpg.bind_item_theme(item=tag_rtp_button, theme=get_colored_button_theme((90, 110, 70)))
        
        tag_beams_button = dpg.add_button(
            label="Beam Summary",
            width=size_dict["button_width"],
            callback=_popup_beam_summary,
            user_data=(rtp_sopiuid, rtp_text, beam_summaries)
        )
        with dpg.tooltip(tag_beams_button):
            dpg.add_text(beam_summary_text, wrap=size_dict["tooltip_width"])
        dpg.bind_item_theme(item=tag_beams_button, theme=get_colored_button_theme((70, 90, 110)))
    
    tag_save_dict[("rtplan", rtp_sopiuid)] = tag_rtp_button


def _popup_beam_summary(sender: Union[str, int], app_data: Any, user_data: Tuple[str, str, List[Dict[str, Any]]]) -> None:
    tag_inspect = get_tag("inspect_data_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect)
    
    button_label = dpg.get_item_label(sender)
    rtp_sopiuid, rtp_text, beam_summaries = user_data
    
    popup_width, popup_height, popup_pos = get_popup_params()
    text_width = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_width), 10)
    
    def _add_beam_summary_table(beam_summary: Dict[str, Any]) -> None:
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            for key, value in beam_summary.items():
                title = key
                if len(title) > char_fit:
                    title = f"{title[:char_fit-3]}..."
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData key: {key}", wrap=size_dict["tooltip_width"])
                        dpg.add_text(title)
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData value: {value}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(
                            default_value=str(value),
                            width=size_dict["button_width"],
                            readonly=True
                        )
        dpg.add_spacer(height=size_dict["spacer_height"])
    
    with dpg.window(
        tag=tag_inspect,
        label=f"Inspecting '{button_label}' Metadata",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_open_over_existing_popup=False
    ):
        add_custom_button(
            label="RT Plan General Info",
            theme_tag=get_hidden_button_theme(),
            add_separator_after=True
        )
        dpg.add_text(rtp_text, wrap=popup_width - 40)
        
        add_custom_button(
            label="RT Plan Beam Info",
            theme_tag=get_hidden_button_theme(),
            add_separator_before=True,
            add_separator_after=True
        )
        if not beam_summaries:
            dpg.add_text("No treatment beams were found in this plan.")
            return
        for beam_summary in beam_summaries:
            _add_beam_summary_table(beam_summary)
