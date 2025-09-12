from __future__ import annotations


import logging
import random
from typing import TYPE_CHECKING, Tuple, Any, Union, List
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.dpg_components.themes.button_themes import get_colored_button_theme
from mdh_app.dpg_components.widgets.patient_ui.rois import (
    _popup_roi_color_picker, _update_views_roi_center,
    _remove_roi, _popup_inspect_roi, update_roi_tooltip,
)
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_win import create_popup_dicom_inspection


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)



def add_structure_sets_to_menu() -> None:
    """ Update the right menu with RT Structure Set data. """
    data_mgr: DataManager = get_user_data("data_manager")
    rts_sopiuids: List[str] = data_mgr.get_rtstruct_uids()
    if not rts_sopiuids:
        return

    ss_mgr: SharedStateManager = get_user_data("shared_state_manager")
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Structure Sets", default_open=True):
        for rts_sopiuid in rts_sopiuids:
            modality = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "Modality", "RT Structure Set")
            ss_label = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "StructureSetLabel", "N/A")
            ss_name = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "StructureSetName", "N/A")
            ss_description = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "SeriesDescription", "N/A")
            date = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "StructureSetDate", "N/A")
            time = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "StructureSetTime", "")
            approval_status = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "ApprovalStatus", "N/A")
            review_date = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "ReviewDate", "N/A")
            review_time = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "ReviewTime", "")
            reviewer_name = data_mgr.get_rtstruct_ds_value_by_uid(rts_sopiuid, "ReviewerName", "N/A")
            roi_numbers: List[int] = data_mgr.get_rtstruct_roi_numbers_by_uid(rts_sopiuid, sort_by_name=True)
            
            any_label = ss_label if ss_label else (ss_name if ss_name else ss_description)
            final_label = f"{modality} - {any_label}" if any_label else modality
            
            tag_modality_node = dpg.generate_uuid()
            roi_cbox_tags = [dpg.generate_uuid() for _ in roi_numbers]
            with dpg.tree_node(tag=tag_modality_node, label=final_label, default_open=True):
                with dpg.group(horizontal=True):
                    # Button to toggle display of all ROIs
                    dpg.add_button(
                        label="Toggle All ROIs",
                        height=size_dict["button_height"],
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(toggle_all_rois, s, a, u)),
                        user_data=(roi_cbox_tags, rts_sopiuid)
                    )
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(f"Toggle display for all ROIs", wrap=size_dict["tooltip_width"])
                    
                    # Button to inspect the RT Structure Set details
                    tag_button = dpg.add_button(
                        label=final_label,
                        width=size_dict["button_width"],
                        height=size_dict["button_height"],
                        callback=create_popup_dicom_inspection,
                        user_data=rts_sopiuid
                    )
                    with dpg.tooltip(parent=tag_button):
                        dpg.add_text(
                            (
                                f"Label: {ss_label}\n" +
                                f"Name: {ss_name}\n" +
                                f"Description: {ss_description}\n" +
                                f"Date and Time: {date} {time}\n" +
                                f"Approval Status: {approval_status}\n" +
                                f"Review Date and Time: {review_date} {review_time}\n" +
                                f"Reviewer Name: {reviewer_name}"
                            ),
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))

                for roi_number, roi_cbox_tag in zip(roi_numbers, roi_cbox_tags):
                    _add_roi_button(tag_modality_node, roi_cbox_tag, rts_sopiuid, roi_number)

            dpg.add_spacer(height=size_dict["spacer_height"])


def toggle_all_rois(sender: Union[str, int], app_data: Any, user_data: Tuple[List[Any], str]) -> None:
    """
    Toggle display for all ROIs in the RT Structure Set.

    Args:
        sender: The triggering button tag.
        app_data: Additional event data.
        user_data: Tuple of (list of ROI checkbox tags, struct SOPInstanceUID).
    """
    roi_checkboxes, struct_uid = user_data
    valid_checkboxes = [chk for chk in roi_checkboxes if dpg.does_item_exist(chk)]
    if not valid_checkboxes:
        return

    should_load = not any(dpg.get_value(chk) for chk in valid_checkboxes)
    for chk in valid_checkboxes:
        dpg.set_value(chk, should_load)
    
    # Use DataManager's bulk operation
    data_mgr: DataManager = get_user_data("data_manager")
    data_mgr.load_all_roi_data_for_struct(struct_uid, should_load)
    ##### TO DO #####


def _add_roi_button(
    tag_parent_node: Union[str, int],
    roi_cbox_tag: Union[str, int],
    rts_sopiuid: str,
    roi_number: int,
) -> None:
    """ Add buttons for an ROI in an RT Structure Set. """
    data_mgr: DataManager = get_user_data("data_manager")
    size_dict = get_user_data(td_key="size_dict")
    clr_btn_width = round(dpg.get_text_size("CLR")[0] * 1.1)

    tag_group_roi = dpg.generate_uuid()
    with dpg.group(tag=tag_group_roi, parent=tag_parent_node, horizontal=True):
        # Checkbox to toggle ROI display
        dpg.add_checkbox(tag=roi_cbox_tag, default_value=False, callback=update_cbox_callback, user_data=("roi", rts_sopiuid, roi_number))
        with dpg.tooltip(parent=roi_cbox_tag):
            dpg.add_text("Display ROI", wrap=size_dict["tooltip_width"])
        
        # Color picker to customize ROI color
        tag_colorbutton = dpg.add_button(width=clr_btn_width, callback=_popup_roi_color_picker, user_data=(rts_sopiuid, roi_number))
        with dpg.tooltip(parent=tag_colorbutton):
            dpg.add_text(default_value="Customize ROI color", wrap=size_dict["tooltip_width"])
        roi_display_color = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIDisplayColor", [random.randint(0, 255) for _ in range(3)])
        dpg.bind_item_theme(item=tag_colorbutton, theme=get_colored_button_theme(roi_display_color))

        # Button to center views on ROI
        tag_ctrbutton = dpg.add_button(label="CTR", callback=_update_views_roi_center, user_data=(roi_cbox_tag, rts_sopiuid, roi_number))
        with dpg.tooltip(parent=tag_ctrbutton):
            dpg.add_text(default_value="Center views on ROI", wrap=size_dict["tooltip_width"])

        # Button to remove ROI from GUI
        tag_delbutton = dpg.add_button(label="DEL", callback=_remove_roi, user_data=(tag_group_roi, roi_cbox_tag))
        with dpg.tooltip(parent=tag_delbutton):
            dpg.add_text(default_value="Removes the ROI from display until data is reloaded.", wrap=size_dict["tooltip_width"])
        
        # Button to inspect ROI
        tag_roi_tooltip = dpg.generate_uuid()
        tag_roi_button = dpg.add_button(
            label="-MISSING-", 
            width=size_dict["button_width"], 
            callback=_popup_inspect_roi, 
            user_data=(rts_sopiuid, roi_number, tag_roi_tooltip)
        )
        dpg.bind_item_theme(item=tag_roi_button, theme=get_colored_button_theme((90, 110, 70)))
        update_roi_tooltip(tag_roi_button) # Set initial tooltip



