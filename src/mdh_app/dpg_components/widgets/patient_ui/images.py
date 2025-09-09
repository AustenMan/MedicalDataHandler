from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, Dict


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def add_images_to_menu(images_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with image data.

    Args:
        images_dict: Dictionary of image data grouped by modality and SeriesInstanceUID.
    """
    if not images_dict:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Images", default_open=True):
        for image_modality, siuid_dict in images_dict.items():
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=image_modality, default_open=True):
                for idx, (siuid, sitk_image_ref) in enumerate(siuid_dict.items(), start=1):
                    _add_image_button(modality_node, image_modality, idx, siuid, sitk_image_ref)
        dpg.add_spacer(height=size_dict["spacer_height"])


def _add_image_button(
    tag_parent: Union[str, int],
    image_modality: str,
    index: int, 
    image_siuid: str,
    sitk_image_ref: Any
) -> None:
    """
    Add a button for an image to the right menu.

    Args:
        tag_parent: The parent tree node tag.
        image_modality: Image modality.
        index: Sequential index for display.
        image_siuid: SeriesInstanceUID for the image.
        sitk_image_ref: Reference to the SimpleITK image.
    """
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    save_dict = dpg.get_item_user_data(tag_save_button)
    display_keys = ("image", image_modality, image_siuid)
    save_dict[display_keys] = sitk_image_ref
    
    with dpg.group(parent=tag_parent, horizontal=True):
        tag_cbox_img = dpg.add_checkbox(default_value=False, callback=update_cbox_callback, user_data=display_keys)
        with dpg.tooltip(parent=tag_cbox_img):
            dpg.add_text("Display image", wrap=size_dict["tooltip_width"])
        
        tag_tooltip = dpg.generate_uuid()
        tag_button = dpg.add_button(
            label=f"{image_modality} #{index}", 
            width=size_dict["button_width"], 
            callback=_popup_inspect_image, 
            user_data=(image_siuid, sitk_image_ref, tag_tooltip)
        )
        dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
        _update_image_button_tooltip(tag_button)


def _update_image_button_tooltip(tag_button: Union[str, int]) -> None:
    """
    Update the tooltip for an image button using image metadata.

    Args:
        tag_button: The button tag to update.
    """
    image_siuid, sitk_image_ref, tag_tooltip = dpg.get_item_user_data(tag_button)
    safe_delete(tag_tooltip)
    if sitk_image_ref() is None:
        return
    size_dict = get_user_data(td_key="size_dict")
    keys_to_show = ["StudyDescription", "SeriesDescription", "SeriesDate", "StudyDate"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text(f"Modality: Image", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"Series Instance UID: {image_siuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_show:
            if sitk_image_ref().HasMetaDataKey(key):
                value = sitk_image_ref().GetMetaData(key)
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])


def _popup_inspect_image(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """
    Open a popup window to display image metadata.

    Args:
        sender: The button tag triggering the popup.
        app_data: Additional data from the sender.
        user_data: Tuple containing (image SOPInstanceUID, SimpleITK image reference, tooltip tag).
    """
    tag_inspect = get_tag("inspect_sitk_popup")
    safe_delete(tag_inspect)
    
    tag_button = sender
    image_siuid, sitk_image_ref, tag_tooltip = user_data
    size_dict = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params()
    text_width = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_width), 10)
    
    with dpg.window(
        tag=tag_inspect,
        label="Image Info",
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
        if sitk_image_ref() is None:
            return
        metadata_keys = sitk_image_ref().GetMetaDataKeys()
        metadata = {key: sitk_image_ref().GetMetaData(key) for key in metadata_keys}
        sorted_keys = sorted(metadata.keys())
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            for key in sorted_keys:
                title = str(key).replace('_', ' ').title()
                if len(title) > char_fit:
                    title = f"{title[:char_fit-3]}..."
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData key: {key}", wrap=size_dict["tooltip_width"])
                        dpg.add_text(title)
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item(), hide_on_activity=True):
                            dpg.add_text(f"MetaData value: {metadata[key]}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(
                            default_value=str(metadata[key]),
                            width=size_dict["button_width"],
                            readonly=True
                        )
