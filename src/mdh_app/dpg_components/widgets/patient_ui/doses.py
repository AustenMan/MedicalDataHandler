from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, Dict, Optional


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.widgets.patient_ui.pt_ui_utilities import update_cbox_callback
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def add_doses_to_menu(rtdoses_unmatched_dict: Dict[str, Any]) -> None:
    """
    Update the right menu with unlinked RT Dose data.

    Args:
        rtdoses_unmatched_dict: Dictionary of unmatched RT dose data keyed by SOPInstanceUID.
    """
    if not rtdoses_unmatched_dict:
        return
    size_dict = get_user_data(td_key="size_dict")
    with dpg.tree_node(parent="mw_right", label="Doses (Unlinked)", default_open=True):
        for idx, (sopiuid, rtd_dict) in enumerate(rtdoses_unmatched_dict.items(), start=1):
            modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=modality_node, label=f"Unlinked RTDs Group #{idx}", default_open=True):
                _add_rtd_buttons(modality_node, sopiuid, rtd_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])


def _add_rtd_buttons(tag_parent: Union[str, int], rtp_sopiuid: str, rtdose_types_dict: Dict[str, Any]) -> None:
    """
    Add buttons for each RT Dose type to the UI.

    Args:
        tag_parent: The parent tree node tag.
        rtp_sopiuid: RT Plan SOP Instance UID.
        rtdose_types_dict: Dictionary of RT Dose types and their data.
    """
    for rtdose_type, value in rtdose_types_dict.items():
        if not value:
            continue
        if rtdose_type == "beam_dose":
            beam_node = dpg.generate_uuid()
            with dpg.tree_node(tag=beam_node, parent=tag_parent, label="RTDs with Type: Beam", default_open=False):
                for rtd_sopiuid, sitk_dose_ref in value.items():
                    if sitk_dose_ref() is None:
                        continue
                    beam_num = sitk_dose_ref().GetMetaData("referenced_beam_number")
                    _add_rtd_button(beam_node, rtd_sopiuid, sitk_dose_ref, f"Beam #{beam_num}")
        elif rtdose_type == "plan_dose":
            for idx, (rtd_sopiuid, sitk_dose_ref) in enumerate(value.items(), start=1):
                _add_rtd_button(tag_parent, rtd_sopiuid, sitk_dose_ref, f"Plan-based #{idx}")
        elif rtdose_type == "beams_composite":
            _add_rtd_button(tag_parent, None, value, "Beams Composite")
        else:
            logger.error(f"Unknown RT Dose type: {rtdose_type}")


def _add_rtd_button(
    tag_parent: Union[str, int], 
    rtd_sopiuid: Optional[str], 
    sitk_dose_ref: Any,
    button_label: str = ""
) -> None:
    """
    Add a button for an RT Dose entry to the UI.

    Args:
        tag_parent: The parent node tag.
        rtd_sopiuid: RT Dose SOP Instance UID.
        sitk_dose_ref: Reference to the SimpleITK RT Dose image.
        button_label: Button label text.
    """
    size_dict = get_user_data(td_key="size_dict")

    button_label = f"RTD {button_label}" if button_label and isinstance(button_label, str) else "RTD"
    with dpg.group(parent=tag_parent, horizontal=True):
        tag_rtd_cbox = dpg.add_checkbox(default_value=False, callback=update_cbox_callback, user_data=sitk_dose_ref)
        with dpg.tooltip(parent=tag_rtd_cbox):
            dpg.add_text(f"Display {button_label}", wrap=size_dict["tooltip_width"])
        tag_button = dpg.add_button(
            label=button_label,
            width=size_dict["button_width"],
            callback=_popup_inspect_rtdose,
            user_data=(rtd_sopiuid, tag_rtd_cbox),
        )
        dpg.bind_item_theme(tag_button, get_colored_button_theme((90, 110, 70)))
        _update_rtd_button_tooltip(tag_button)


def _update_rtd_button_tooltip(tag_button: Union[str, int]) -> None:
    """
    Update the tooltip for an RT Dose button with current metadata.

    Args:
        tag_button: The tag of the button to update.
    """
    rtd_sopiuid, tag_rtd_cbox = dpg.get_item_user_data(tag_button)
    sitk_dose_ref = dpg.get_item_user_data(tag_rtd_cbox)
    tag_tooltip = f"{tag_button}_tooltip"
    
    safe_delete(tag_tooltip)
    sitk_dose = sitk_dose_ref()
    if sitk_dose is None:
        return
    size_dict = get_user_data(td_key="size_dict")
    keys_to_show = ["number_of_fractions_planned", "number_of_fractions_rtdose"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text(f"Modality: RT Dose", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rtd_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_show:
            if sitk_dose.HasMetaDataKey(key):
                value = sitk_dose.GetMetaData(key)
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])


def _popup_inspect_rtdose(sender: Union[str, int], app_data: Any, user_data: Tuple[str, Union[str, int]]) -> None:
    """
    Open a popup window for RT Dose metadata inspection and editing.

    Args:
        sender: The tag of the button that triggered the popup.
        app_data: Additional event data.
        user_data: Tuple containing (RT Dose SOPInstanceUID, SimpleITK RT Dose reference, tooltip tag).
    """
    tag_inspect = get_tag("inspect_sitk_popup")
    safe_delete(tag_inspect)
    
    tag_button = sender
    rtd_sopiuid, tag_rtd_checkbox = user_data
    sitk_dose_ref = dpg.get_item_user_data(tag_rtd_checkbox)
    size_dict = get_user_data(td_key="size_dict")
    
    popup_width, popup_height, popup_pos = get_popup_params()
    text_W = dpg.get_text_size("A")[0]
    char_fit = max(round((popup_width * 0.4) / text_W), 10)
    
    def update_sitk_metadata(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, str]) -> None:
        """
        Update a metadata field of the SimpleITK RT Dose object.

        Args:
            sender: The tag of the sender.
            app_data: The new value.
            user_data: Tuple with (SimpleITK RT Dose reference, metadata key).
        """
        sitk_dose_ref, meta_key = user_data
        new_val = app_data
        sitk_obj = sitk_dose_ref()
        if sitk_obj is None:
            return
        sitk_obj.SetMetaData(meta_key, str(new_val))
        _update_rtd_button_tooltip(tag_button)
        logger.info(f"Updated metadata {meta_key} with value {new_val}.")
    
    with dpg.window(
        tag=tag_inspect,
        label="RT Dose Info",
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
        if sitk_dose_ref() is None:
            return
        metadata_keys = sitk_dose_ref().GetMetaDataKeys()
        metadata = {key: sitk_dose_ref().GetMetaData(key) for key in metadata_keys}
        sorted_keys = sorted(metadata.keys())
        add_custom_button(
            label="Editable Fields (Used to scale the dose! Read the tooltips!)",
            theme_tag=get_hidden_button_theme(),
            add_spacer_after=True
        )
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            for key in ["number_of_fractions_planned", "number_of_fractions_rtdose"]:
                if key in sorted_keys:
                    sorted_keys.remove(key)
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
                                dpg.add_text(f"MetaData key: {key}", wrap=size_dict["tooltip_width"])
                            dpg.add_text(title)
                        with dpg.group(horizontal=True):
                            value = int(metadata.get(key, 0) or 0)
                            tag_fxn_in = dpg.add_input_int(
                                default_value=value,
                                width=size_dict["button_width"],
                                callback=update_sitk_metadata,
                                user_data=(sitk_dose_ref, key),
                                min_value=0, max_value=9999,
                                min_clamped=True, max_clamped=True
                            )
                            with dpg.tooltip(parent=tag_fxn_in):
                                info = ("Number of fractions desired (for scaling the dose)."
                                        if key == "number_of_fractions_planned"
                                        else "Number of fractions that the dose currently represents.")
                                dpg.add_text(info, wrap=size_dict["tooltip_width"])
        
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
                            dpg.add_text(f"MetaData value: {metadata[key]}", wrap=size_dict["tooltip_width"])
                        dpg.add_input_text(
                            default_value=str(metadata[key]), 
                            width=size_dict["button_width"], 
                            readonly=True
                        )
