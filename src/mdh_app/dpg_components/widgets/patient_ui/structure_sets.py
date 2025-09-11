from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, Dict, List
from functools import partial


import dearpygui.dearpygui as dpg
import SimpleITK as sitk


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.widgets.patient_ui.rois import (
    _update_new_roi_name, _popup_roi_color_picker, _update_views_roi_center,
    _remove_roi, _popup_inspect_roi, _update_rts_roi_button_and_tooltip,
)
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params
from mdh_app.utils.general_utils import struct_name_priority_key
from mdh_app.utils.sitk_utils import get_sitk_roi_display_color


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)



def add_structure_sets_to_menu(rtstructs_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with RT Structure Set data.

    Args:
        rtstructs_dict: Mapping of RT Structure Set SOP Instance UIDs to their metadata dictionaries.
    """
    if not rtstructs_dict:
        return

    size_dict = get_user_data(td_key="size_dict")
    roi_checkboxes: List[Any] = [] # # Create a list to store the ROI checkboxes
    with dpg.tree_node(parent="mw_right", label="Structure Sets", default_open=True):
        for rts_idx, (rts_sopiuid, rtstruct_info_dict) in enumerate(rtstructs_dict.items(), start=1):
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=f"RTS #{rts_idx}", default_open=True):
                _add_rts_button(roi_checkboxes, tag_modality_node, rts_sopiuid, rtstruct_info_dict)
                # List of ROIs: filter out None and ensure the object is a SimpleITK image
                roi_refs = [
                    (roi_idx, roi_sitk_ref) for roi_idx, roi_sitk_ref in enumerate(
                        rtstruct_info_dict.get("list_roi_sitk", [])
                    )
                    if roi_sitk_ref is not None and isinstance(roi_sitk_ref(), sitk.Image)
                ]
                # Sort ROIs based on their current name priority
                roi_refs = sorted(roi_refs, key=lambda x: struct_name_priority_key(x[1]().GetMetaData("current_roi_name")))
                _add_rts_roi_buttons(roi_checkboxes, tag_modality_node, rts_sopiuid, roi_refs)
                dpg.add_spacer(height=size_dict["spacer_height"])


def _add_rts_button(
    roi_checkboxes: List[Any],
    tag_modality_node: Union[str, int],
    rts_sopiuid: str,
    rtstruct_info_dict: Dict[str, Any]
) -> None:
    """
    Add an RT Structure Set button to the UI.

    Args:
        roi_checkboxes: List to store ROI checkbox tags.
        tag_modality_node: Parent tree node tag.
        rts_sopiuid: RT Structure Set SOP Instance UID.
        rtstruct_info_dict: Metadata for the RT Structure Set.
    """
    ss_mgr: SharedStateManager = get_user_data("shared_state_manager")
    size_dict = get_user_data(td_key="size_dict")
    with dpg.group(parent=tag_modality_node, horizontal=True):
        # Button to toggle display of all ROIs
        display_data_keys = ("rtstruct", rts_sopiuid, "list_roi_sitk", "all")
        tag_all_rois = dpg.add_button(
            label="Toggle All ROIs",
            height=size_dict["button_height"],
            callback=lambda s, a, u: ss_mgr.submit_action(partial(toggle_all_rois, s, a, u)),
            user_data=(roi_checkboxes, display_data_keys)
        )
        with dpg.tooltip(parent=tag_all_rois):
            dpg.add_text(f"Toggle display for all ROIs", wrap=size_dict["tooltip_width"])

        # Button to inspect the RT Structure Set details
        tag_rts_tooltip = dpg.generate_uuid()
        tag_rts_button = dpg.add_button(
            label="RTS",
            width=size_dict["button_width"],
            height=size_dict["button_height"],
            callback=_popup_inspect_structure_set_info,
            user_data=(rts_sopiuid, rtstruct_info_dict, tag_rts_tooltip)
        )
        dpg.bind_item_theme(tag_rts_button, get_colored_button_theme((90, 110, 70)))
        _update_rts_button_and_tooltip(tag_rts_button)


def toggle_all_rois(sender: Union[str, int], app_data: Any, user_data: Tuple[List[Any], Any]) -> None:
    """
    Toggle display for all ROIs in the RT Structure Set.

    Args:
        sender: The triggering button tag.
        app_data: Additional event data.
        user_data: Tuple of (list of ROI checkbox tags, display data keys).
    """
    roi_checkboxes, display_data_keys = user_data
    valid_checkboxes = [chk for chk in roi_checkboxes if dpg.does_item_exist(chk)]
    if not valid_checkboxes:
        return

    should_load = not any(dpg.get_value(chk) for chk in valid_checkboxes)
    for chk in valid_checkboxes:
        dpg.set_value(chk, should_load)
    update_cbox_callback(None, should_load, display_data_keys)


def _update_rts_button_and_tooltip(tag_button: Union[str, int]) -> None:
    """
    Update the tooltip and label for an RT Structure Set button.

    Args:
        tag_button: The button tag.
    """
    rts_sopiuid, rtstruct_info_dict, tag_tooltip = dpg.get_item_user_data(tag_button)
    size_dict = get_user_data(td_key="size_dict")
    safe_delete(tag_tooltip)
    keys_to_show = [
        "StructureSetName", "StructureSetLabel", "StructureSetDate", "StructureSetTime",
        "ApprovalStatus", "ApprovalDate", "ApprovalTime", "ReviewerName"
    ]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text(f"Modality: RT Struct", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rts_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_show:
            if key in rtstruct_info_dict:
                value = rtstruct_info_dict.get(key, "")
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])
    ss_label = rtstruct_info_dict.get("StructureSetLabel", "")
    new_label = f"RTS: {ss_label}" if ss_label else "RTS"
    dpg.set_item_label(tag_button, new_label)


def _popup_inspect_structure_set_info(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """
    Open a popup to display and allow modifications of RT Structure Set attributes.

    rtstruct_info_dict has the following keys:
        StructureSetLabel, StructureSetName, StructureSetDate, StructureSetTime, SeriesInstanceUID, list_roi_sitk
    
    Args:
        sender: The button tag that triggered the popup.
        app_data: Additional event data.
        user_data: Tuple containing (RT Structure Set SOP Instance UID, metadata dictionary, tooltip tag).
    """
    tag_inspect = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect)
    
    tag_button = sender
    rts_sopiuid, rtstruct_info_dict, tag_tooltip = user_data
    
    popup_width, popup_height, popup_pos = get_popup_params()
    text_width = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_width), 10)
    
    keys_to_show = ["StructureSetLabel", "StructureSetName", "StructureSetDate", "StructureSetTime", "ReferencedSeriesInstanceUID"]

    with dpg.window(
        tag=tag_inspect,
        label="Structure Set Info",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_open_over_existing_popup=False
    ):
        add_custom_button(
            label="RT Struct Details",
            theme_tag=get_hidden_button_theme(),
            add_separator_after=True
        )
        add_custom_button(
            label="Read-Only Fields",
            theme_tag=get_hidden_button_theme(),
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            for key in keys_to_show:
                value = str(rtstruct_info_dict.get(key, ""))
                title = str(key)
                if "_" in title:
                    title = title.replace('_', ' ').title()
                    title = title.replace("Rt", "RT").replace("RTd", "RTD").replace("Cgy", "cGy")
                # Format the title to a fixed width
                if len(title) > char_fit:
                    title = f"{title[:char_fit-3]}..."
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData key: {str(key)}", wrap=size_dict["tooltip_width"])
                        dpg.add_text(title)
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData value: {value}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(default_value=value, width=size_dict["button_width"], readonly=True)


def _add_rts_roi_buttons(
    roi_checkboxes: List[Any],
    tag_modality_node: Union[str, int],
    rts_sopiuid: str,
    list_roi_idx_sitk_refs: List[Tuple[Any, Any]]
) -> None:
    """
    Add buttons for all ROIs in an RT Structure Set.

    Args:
        roi_checkboxes: List to store ROI checkbox tags.
        tag_modality_node: Parent node tag.
        rts_sopiuid: RT Structure Set SOP Instance UID.
        list_roi_idx_sitk_refs: List of tuples (ROI index, SimpleITK ROI reference).
    """
    if not list_roi_idx_sitk_refs:
        return
    
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    clr_btn_width = round(dpg.get_text_size("CLR")[0] * 1.1)
    
    for (roi_idx, roi_sitk_ref) in list_roi_idx_sitk_refs:
        _update_new_roi_name(roi_sitk_ref)
        roi_display_color = get_sitk_roi_display_color(roi_sitk_ref())
        
        # Group for ROI interaction
        tag_group_roi = dpg.generate_uuid()
        with dpg.group(tag=tag_group_roi, parent=tag_modality_node, horizontal=True):
            # Checkbox to toggle ROI display
            display_data_keys = (rts_sopiuid, "list_roi_sitk", roi_idx)
            save_dict = dpg.get_item_user_data(tag_save_button)
            save_dict[display_data_keys] = roi_sitk_ref
            
            tag_checkbox = dpg.add_checkbox(default_value=False, callback=update_cbox_callback, user_data=display_data_keys)
            roi_checkboxes.append(tag_checkbox)
            with dpg.tooltip(parent=tag_checkbox):
                dpg.add_text("Display ROI", wrap=size_dict["tooltip_width"])
            
            # Color picker to customize ROI color
            tag_colorbutton = dpg.add_button(width=clr_btn_width, callback=_popup_roi_color_picker, user_data=roi_sitk_ref)
            with dpg.tooltip(parent=tag_colorbutton):
                dpg.add_text(default_value="Customize ROI color", wrap=size_dict["tooltip_width"])
            dpg.bind_item_theme(item=tag_colorbutton, theme=get_colored_button_theme(roi_display_color))
            
            # Button to center views on ROI
            tag_ctrbutton = dpg.add_button(label="CTR", callback=_update_views_roi_center, user_data=tag_checkbox)
            with dpg.tooltip(parent=tag_ctrbutton):
                dpg.add_text(default_value="Center views on ROI", wrap=size_dict["tooltip_width"])
            
            # Button to remove ROI entirely
            tag_delbutton = dpg.add_button(label="DEL", callback=_remove_roi, user_data=(display_data_keys, tag_group_roi, tag_checkbox))
            with dpg.tooltip(parent=tag_delbutton):
                dpg.add_text(default_value="Removes the ROI until data is reloaded.", wrap=size_dict["tooltip_width"])
            
            # Button to inspect ROI
            tag_roi_tooltip = dpg.generate_uuid()
            tag_roi_button = dpg.add_button(
                label="ROI", 
                width=size_dict["button_width"], 
                callback=_popup_inspect_roi, 
                user_data=(rts_sopiuid, roi_sitk_ref, tag_roi_tooltip)
            )
            dpg.bind_item_theme(item=tag_roi_button, theme=get_colored_button_theme((90, 110, 70)))
            _update_rts_roi_button_and_tooltip(tag_roi_button)



