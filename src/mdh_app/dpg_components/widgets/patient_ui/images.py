from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Union, List


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def add_images_to_menu() -> None:
    """ Update the right menu with image data. """
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    image_siuids: List[str] = data_mgr.get_image_series_uids()
    if not image_siuids:
        return
    
    tag_save_dict = get_user_data("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Images", default_open=True):
        for image_siuid in image_siuids:
            modality = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "Modality", "Image")
            series_description = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "SeriesDescription", "N/A")
            study_description = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "StudyDescription", "N/A")
            date = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "SeriesDate", "N/A")
            time = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "SeriesTime", "")
            approval_status = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "ApprovalStatus", "N/A")
            review_date = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "ReviewDate", "N/A")
            review_time = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "ReviewTime", "")
            reviewer_name = data_mgr.get_image_metadata_by_series_uid_and_key(image_siuid, "ReviewerName", "N/A")

            image_btn_label = series_description or study_description or modality
            image_btn_label = f"{modality} - {image_btn_label}" if image_btn_label else modality
            image_text = (
                f"Series Date and Time: {date} {time}\n"
                f"Approval Status: {approval_status}\n"
                f"Review Date and Time: {review_date} {review_time}\n"
                f"Reviewer Name: {reviewer_name}"
            )
            
            with dpg.group(horizontal=True):
                dpg.add_checkbox(default_value=False, callback=update_cbox_callback, user_data=("image", image_siuid))
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Display image", wrap=size_dict["tooltip_width"])
                
                tag_button = dpg.add_button(
                    label=image_btn_label,
                    width=size_dict["button_width"],
                    callback=_popup_inspect_image,
                    user_data=image_siuid
                )
                with dpg.tooltip(parent=tag_button):
                    dpg.add_text(image_text, tag=f"{tag_button}_tooltiptext", wrap=size_dict["tooltip_width"])
                dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
            
            tag_save_dict[("image", image_siuid)] = tag_button
        
        dpg.add_spacer(height=size_dict["spacer_height"])


def _popup_inspect_image(sender: Union[str, int], app_data: Any, user_data: str) -> None:
    """
    Open a popup window to display image metadata.

    Args:
        sender: The button tag triggering the popup.
        app_data: Additional data from the sender.
        user_data: Tuple containing (image SOPInstanceUID, SimpleITK image reference, tooltip tag).
    """
    tag_inspect = get_tag("inspect_data_popup")
    safe_delete(tag_inspect)
    
    button_label = dpg.get_item_label(sender)
    image_siuid = user_data
    
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    img_metadata = data_mgr.get_image_metadata_dict_by_series_uid(image_siuid) or {}
    sorted_keys = sorted(img_metadata.keys())
    
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params()
    text_width = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_width), 10)
    
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
            label="SITK Image Read-Only Metadata Fields",
            theme_tag=get_hidden_button_theme(),
            add_separator_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            for key in sorted_keys:
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
                            dpg.add_text(f"MetaData value: {img_metadata[key]}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(
                            default_value=str(img_metadata[key]),
                            width=size_dict["button_width"],
                            readonly=True
                        )
        dpg.add_spacer(height=size_dict["spacer_height"])
