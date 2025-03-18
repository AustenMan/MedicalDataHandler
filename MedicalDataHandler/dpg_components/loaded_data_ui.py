import re
import time
import dearpygui.dearpygui as dpg
import SimpleITK as sitk
from dpg_components.custom_utils import get_tag, get_user_data, add_custom_button
from dpg_components.texture_updates import request_texture_update
from dpg_components.themes import get_hidden_button_theme, get_colored_button_theme
from dpg_components.window_confirmation import create_confirmation_popup
from dpg_components.window_save_data import create_save_window
from utils.dpg_utils import safe_delete, get_popup_params
from utils.general_utils import find_disease_site, struct_name_priority_key, verify_roi_goals_format, find_reformatted_mask_name, regex_find_dose_and_fractions, get_traceback
from utils.sitk_utils import get_sitk_roi_display_color

def fill_right_col_ptdata(active_pt, active_frame_of_reference_uid):
    """ Creates the main right menu for displaying data modification options. """
    if active_pt is None:
        return
    active_pt.update_last_accessed()
    
    # Get necessary parameters
    data_manager = get_user_data(td_key="data_manager")
    size_dict = get_user_data(td_key="size_dict")
    tag_ptinfo_button = get_tag("ptinfo_button")
    tag_save_button = get_tag("save_button")
    
    # Patient Info Section
    dpg.add_button(tag=tag_ptinfo_button, parent="mw_right", label="Patient Info", width=size_dict["button_width"], height=size_dict["button_height"], user_data=(active_pt, active_frame_of_reference_uid))
    dpg.bind_item_theme(item=dpg.last_item(), theme=get_hidden_button_theme())
    patient_id, patient_name = active_pt.return_patient_info()
    with dpg.group(parent="mw_right", horizontal=True):
        dpg.add_text(default_value="ID/MRN:", bullet=True)
        dpg.add_input_text(default_value=patient_id, width=size_dict["button_width"], height=size_dict["button_height"], readonly=True, hint="Patient ID")
    with dpg.group(parent="mw_right", horizontal=True):
        dpg.add_text(default_value="Name:", bullet=True)
        dpg.add_input_text(default_value=patient_name, width=size_dict["button_width"], height=size_dict["button_height"], readonly=True, hint="Patient Name")
    add_custom_button(
        label="Save Data", tag=tag_save_button, parent_tag="mw_right", 
        callback=create_save_window, user_data={}, add_spacer_before=True, add_separator_after=True, visible=False)
    
    # Retrieve RT Doses and RT Plans
    rtdoses_dict = data_manager.return_data_from_modality("rtdose")
    rtplans_dict = data_manager.return_data_from_modality("rtplan")
    
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
    
    # Build a mapping from RT Plan SOP Instance UID to RT Dose SOP Instance UIDs
    rtimages_dict = data_manager.return_data_from_modality("rtimage")
    rtd_rtp_matched_dict = {ref_rtp_sopiuid: (rtdoses_dict[ref_rtp_sopiuid], rtplans_dict[ref_rtp_sopiuid]) for ref_rtp_sopiuid in rtdoses_dict if ref_rtp_sopiuid in rtplans_dict}
    rtdoses_unmatched_dict = {ref_rtp_sopiuid: rtdoses_dict[ref_rtp_sopiuid] for ref_rtp_sopiuid in rtdoses_dict if ref_rtp_sopiuid not in rtplans_dict}
    rtplans_unmatched_dict = {rtp_sopiuid: rtplans_dict[rtp_sopiuid] for rtp_sopiuid in rtplans_dict if rtp_sopiuid not in rtdoses_dict}
    rtstructs_dict = data_manager.return_data_from_modality("rtstruct")
    
    _update_rmenu_rti(rtimages_dict)
    _update_rmenu_matched_rtd_rtp(rtd_rtp_matched_dict)
    _update_rmenu_unmatched_rtd(rtdoses_unmatched_dict)
    _update_rmenu_unmatched_rtp(rtplans_unmatched_dict)
    _update_rmenu_rts(rtstructs_dict)
    
    # Show the save button after all data is loaded
    dpg.configure_item(tag_save_button, show=True)

### RT IMAGE FUNCTIONS ###

def _update_rmenu_rti(rtimages_dict):
    """
    Updates the right menu with RT image data.
    
    Args:
        rtimages_dict (dict): Dictionary containing RT image data grouped by modality and SeriesInstanceUID.
    """
    if not rtimages_dict:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Images", default_open=True):
        for rti_modality, siuid_to_sitk_dict in rtimages_dict.items():
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=rti_modality, default_open=True):
                for rti_m_idx, (rti_siuid, sitk_image_ref) in enumerate(siuid_to_sitk_dict.items(), start=1):
                    _add_rti_button(tag_modality_node, rti_modality, rti_m_idx, rti_siuid, sitk_image_ref)
        dpg.add_spacer(height=size_dict["spacer_height"])

def _add_rti_button(tag_modality_node, rti_modality, rti_m_idx, rti_siuid, sitk_image_ref):
    """
    Adds a button for an RT image to the right menu.
    
    Args:
        tag_modality_node (int): The parent tree node tag for the modality.
        rti_modality (str): The RT image modality.
        rti_m_idx (int): The index of the RT image in the series.
        rti_siuid (str): The SeriesInstanceUID of the RT image.
        sitk_image_ref (sitk.Image): A reference to the SimpleITK image object.
    """
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.group(parent=tag_modality_node, horizontal=True):
        display_data_keys = ("rtimage", rti_modality, rti_siuid)
        save_dict = dpg.get_item_user_data(tag_save_button)
        save_dict[display_data_keys] = sitk_image_ref
        
        dpg.add_checkbox(default_value=False, callback=_send_cbox_update, user_data=display_data_keys)
        with dpg.tooltip(parent=dpg.last_item()):
            dpg.add_text("Display image", wrap=size_dict["tooltip_width"])
        
        tag_button = dpg.generate_uuid()
        tag_tooltip = dpg.generate_uuid()
        dpg.add_button(tag=tag_button, label=f"{rti_modality} #{rti_m_idx}", width=size_dict["button_width"], callback=_popup_inspect_rtimage, user_data=(rti_siuid, sitk_image_ref, tag_tooltip))
        dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
        _update_rti_button_tooltip(tag_button)

def _update_rti_button_tooltip(tag_button):
    """
    Updates the tooltip for an RT image button with metadata.
    
    Args:
        tag_button (int): The tag of the button whose tooltip is to be updated.
    """
    rti_siuid, sitk_image_ref, tag_tooltip = dpg.get_item_user_data(tag_button)
    safe_delete(tag_tooltip)
    
    if sitk_image_ref() is None:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    keys_to_get = ["StudyDescription", "SeriesDescription", "SeriesDate", "StudyDate"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text("Modality: RT Image", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"Series Instance UID: {rti_siuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            if sitk_image_ref().HasMetaDataKey(key):
                value = sitk_image_ref().GetMetaData(key)
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])

def _popup_inspect_rtimage(sender, app_data, user_data):
    """
    Opens a popup window to display RTIMAGE metadata.
    
    Args:
        sender (int): The tag of the button that triggered this popup.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains RTIMAGE metadata, including SOPInstanceUID, SimpleITK image reference, and tooltip tag.
    """
    # Get necessary parameters
    tag_inspect_sitk = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    # Cleanup any existing popup
    safe_delete(tag_inspect_sitk)
    
    tag_button = sender
    rti_siuid, sitk_image_ref, tag_tooltip = user_data
    
    popup_width, popup_height, popup_pos = get_popup_params()
    input_width = popup_width // 2
    
    # Helper function to add input fields
    def add_input_field(field_label, default_value, readonly=False):
        """
        Adds an input field to display metadata.
        
        Args:
            field_label (str): The label for the metadata field.
            default_value (str): The value to display in the input field.
            readonly (bool): If True, the input field will be read-only.
        """
        # Determine the title to display
        if "_" in field_label:
            title = field_label.replace('_', ' ').title()
        else:
            title = field_label
        
        # Format the title to a fixed width
        title = f"{title[:38]}:".ljust(40)
        
        with dpg.group(horizontal=True):
            dpg.add_text(title)
            input_kwargs = {'default_value': default_value, 'width': input_width, 'readonly': readonly}
            dpg.add_input_text(**input_kwargs)
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text(f"MetaData key: {str(field_label)}\nMetaData value: {default_value}", wrap=size_dict["tooltip_width"])
        dpg.add_spacer(height=size_dict["spacer_height"])
    
    with dpg.window(
        tag=tag_inspect_sitk, label="RT Image Info",  width=popup_width, height=popup_height,  pos=popup_pos, no_open_over_existing_popup=False, 
        popup=True, modal=True, no_title_bar=False, no_close=False, on_close=safe_delete(tag_inspect_sitk)
        ):
        add_custom_button(label="SITK Image Read-Only Metadata Fields", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        
        if sitk_image_ref() is None:
            return
        
        # Get all metadata keys and values
        metadata_keys = sitk_image_ref().GetMetaDataKeys()
        metadata_dict = {key: sitk_image_ref().GetMetaData(key) for key in metadata_keys}
        
        sorted_keys = sorted(metadata_dict.keys())
        for key in sorted_keys:
            add_input_field(field_label=key, default_value=str(metadata_dict[key]), readonly=True)

### MATCHED RT DOSE AND RT PLAN FUNCTIONS ###

def _update_rmenu_matched_rtd_rtp(rtd_rtp_matched_dict):
    """
    Updates the right menu with linked RT dose and RT plan data.
    
    Args:
        rtd_rtp_matched_dict (dict): Dictionary of matched RT dose and RT plan data grouped by SOPInstanceUID.
    """
    if not rtd_rtp_matched_dict:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Doses & Plans (Linked)", default_open=True):
        for link_idx, (rtp_sopiuid, (rtdose_types_dict, rtplan_info_dict)) in enumerate(rtd_rtp_matched_dict.items(), start=1):
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=f"Linked Group #{link_idx}", default_open=True):
                _add_rtp_button(tag_modality_node, rtp_sopiuid, rtplan_info_dict)
                _add_all_rtd_buttons(tag_modality_node, rtp_sopiuid, rtdose_types_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])

### RT DOSE FUNCTIONS ###

def _update_rmenu_unmatched_rtd(rtdoses_unmatched_dict):
    """
    Updates the right menu with unmatched RT dose data.
    
    Args:
        rtdoses_unmatched_dict (dict): Dictionary of unmatched RT dose data grouped by SOPInstanceUID.
    """
    if not rtdoses_unmatched_dict:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Doses (Unlinked)", default_open=True):
        for rtd_idx, (rtd_sopiuid, rtdose_types_dict) in enumerate(rtdoses_unmatched_dict.items(), start=1):
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=f"Unlinked RTDs Group #{rtd_idx}", default_open=True):
                _add_all_rtd_buttons(tag_modality_node, rtd_sopiuid, rtdose_types_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])

def _add_all_rtd_buttons(tag_modality_node, rtp_sopiuid, rtdose_types_dict):
    """
    Adds buttons for all RT Dose types to the UI.
    
    Args:
        tag_modality_node (int): The parent tree node tag.
        rtp_sopiuid (str): SOP Instance UID of the RT Plan.
        rtdose_types_dict (dict): Dictionary of RT Dose types and their corresponding data.
    """
    for rtdose_type, value in rtdose_types_dict.items():
        if not value:
            continue
        
        if rtdose_type == "beam_dose":
            tag_rtd_beam_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_rtd_beam_node, parent=tag_modality_node, label="RTDs with Type: Beam", default_open=False):
                for rtd_sopiuid, sitk_dose_ref in value.items():
                    if sitk_dose_ref() is None:
                        continue
                    
                    display_data_keys = ("rtdose", rtp_sopiuid, rtdose_type, rtd_sopiuid)
                    beam_num = sitk_dose_ref().GetMetaData("referenced_beam_number")
                    _add_rtd_button(tag_rtd_beam_node, rtd_sopiuid, sitk_dose_ref, display_data_keys, f"Beam #{beam_num}")
        elif rtdose_type == "plan_dose":
            for rtd_idx, (rtd_sopiuid, sitk_dose_ref) in enumerate(value.items(), start=1):
                display_data_keys = ("rtdose", rtp_sopiuid, rtdose_type, rtd_sopiuid)
                _add_rtd_button(tag_modality_node, rtd_sopiuid, sitk_dose_ref, display_data_keys, f"Plan-based #{rtd_idx}")
        elif rtdose_type == "beams_composite":
            display_data_keys = ("rtdose", rtp_sopiuid, rtdose_type)
            sitk_dose_ref = value
            _add_rtd_button(tag_modality_node, None, sitk_dose_ref, display_data_keys, "Beams Composite")
        else:
            print(f"Error: Unknown RT Dose type: {rtdose_type}")

def _add_rtd_button(tag_parent, rtd_sopiuid, sitk_dose_ref, display_data_keys, button_label=""):
    """
    Adds a button for an RT Dose to the UI.
    
    Args:
        tag_parent (int): The parent tree node tag.
        rtd_sopiuid (str): SOP Instance UID of the RT Dose.
        sitk_dose_ref (SimpleITK.Image): Reference to the SimpleITK RT Dose image.
        display_data_keys (tuple): Keys for identifying displayed data.
        button_label (str, optional): Label for the button. Defaults to "".
    """
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    save_dict = dpg.get_item_user_data(tag_save_button)
    save_dict[display_data_keys] = sitk_dose_ref
    
    if button_label and isinstance(button_label, str):
        button_label = f"RTD {button_label}"
    else:
        button_label = "RTD"
    
    with dpg.group(parent=tag_parent, horizontal=True):
        dpg.add_checkbox(default_value=False, callback=_send_cbox_update, user_data=display_data_keys)
        with dpg.tooltip(parent=dpg.last_item()):
            dpg.add_text(f"Display {button_label}", wrap=size_dict["tooltip_width"])
        
        tag_button = dpg.generate_uuid()
        tag_tooltip = dpg.generate_uuid()
        dpg.add_button(tag=tag_button, label=button_label, width=size_dict["button_width"], callback=_popup_inspect_rtdose, user_data=(rtd_sopiuid, sitk_dose_ref, tag_tooltip))
        dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
        _update_rtd_button_tooltip(tag_button)

def _update_rtd_button_tooltip(tag_button):
    """
    Updates the tooltip for an RT Dose button.
    
    Args:
        tag_button (int): The tag of the button whose tooltip needs updating.
    """
    rtd_sopiuid, sitk_dose_ref, tag_tooltip = dpg.get_item_user_data(tag_button)
    safe_delete(tag_tooltip)
    
    sitk_dose = sitk_dose_ref()
    if sitk_dose is None:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    keys_to_get = ["number_of_fractions_planned", "number_of_fractions_rtdose"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text("Modality: RT Dose", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rtd_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            if sitk_dose.HasMetaDataKey(key):
                value = sitk_dose.GetMetaData(key)
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])

def _popup_inspect_rtdose(sender, app_data, user_data):
    """
    Opens a popup window to inspect and edit RT Dose metadata.
    
    Args:
        sender (int): The tag of the button that triggered this popup.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains SOP Instance UID, SimpleITK RT Dose reference, and tooltip tag.
    """
    tag_inspect_sitk = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect_sitk)
    
    tag_button = sender
    rtd_sopiuid, sitk_dose_ref, tag_tooltip = user_data
    
    popup_width, popup_height, popup_pos = get_popup_params()
    input_width = popup_width // 2
    
    # Helper function to add input fields
    def add_input_field(field_label, default_value, readonly=False, tooltip_texts=[], callback=None, user_data=None, custom_title=None, spacer_after=True):
        """
        Adds an input field to display or edit RT Dose metadata.
        
        Args:
            field_label (str): The label for the metadata field.
            default_value (any): The value to display or edit.
            readonly (bool): If True, the field will be read-only.
            tooltip_texts (list, optional): Tooltips to display.
            callback (function, optional): Function to call when the field value changes.
            user_data (tuple, optional): Data to pass to the callback.
            custom_title (str, optional): Custom title for the field.
            spacer_after (bool): If True, adds spacing after the field.
        """
        # Determine the title to display
        if custom_title:
            title = custom_title
        elif field_label:
            if "_" in field_label:
                title = field_label.replace('_', ' ').title()
                title = title.replace("Rt", "RT").replace("RTd", "RTD").replace("Cgy", "cGy")
            else:
                title = field_label
        else:
            title = "MISSING TITLE"
        
        # Format the title to a fixed width
        title = f"{title[:38]}:".ljust(40)
        
        with dpg.group(horizontal=True):
            dpg.add_text(title)
            input_kwargs = {'default_value': default_value, 'width': input_width, 'readonly': readonly, 'callback': callback, 'user_data': user_data}
            if isinstance(default_value, int):
                input_kwargs.update({'min_value': 0, 'max_value': 9999, 'min_clamped': True, 'max_clamped': True,})
                dpg.add_input_int(**input_kwargs)
            else:
                dpg.add_input_text(**input_kwargs)
            
            # Add tooltip to the last item added (the input widget)
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text(f"MetaData key: {str(field_label)}\nMetaData value: {default_value}", wrap=size_dict["tooltip_width"])
                for tooltip_text in tooltip_texts:
                    dpg.add_text(tooltip_text, wrap=size_dict["tooltip_width"])
        
        if spacer_after:
            dpg.add_spacer(height=size_dict["spacer_height"])
    
    # Define the callback function to update the sitk metadata
    def update_sitk_metadata(sender, app_data, user_data):
        """
        Updates the metadata for the SimpleITK RT Dose object.
        
        Args:
            sender (int): The tag of the sender.
            app_data (any): The new value for the metadata field.
            user_data (tuple): Contains the SimpleITK RT Dose reference and metadata key to update.
        """
        sitk_dose_ref, metadata_key = user_data  # The metadata key passed as user_data
        new_value = app_data     # The new value from the input field
        
        sitk_dose = sitk_dose_ref()
        if sitk_dose is None:
            return
        
        # Update the sitk dose's metadata
        sitk_dose.SetMetaData(metadata_key, str(new_value))
        _update_rtd_button_tooltip(tag_button)
        print(f"Updated dose metadata key {metadata_key} with value {new_value}")
    
    with dpg.window(
        tag=tag_inspect_sitk, label="RT Dose Info",  width=popup_width, height=popup_height, pos=popup_pos, no_open_over_existing_popup=False, 
        popup=True, modal=True, no_title_bar=False, no_close=False, on_close=safe_delete(tag_inspect_sitk)
        ):
        add_custom_button(label="SITK Dose Details", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        add_custom_button(label="Editable Fields (Used to scale the dose! Read the tooltips!)", theme_tag=get_hidden_button_theme(), add_spacer_after=True)
        if sitk_dose_ref() is None:
            return
        
        # Get all metadata keys and values
        metadata_keys = sitk_dose_ref().GetMetaDataKeys()
        metadata_dict = {key: sitk_dose_ref().GetMetaData(key) for key in metadata_keys}
        
        number_of_fractions_planned = int(metadata_dict.get("number_of_fractions_planned", 0) or 0)
        number_of_fractions_rtdose = int(metadata_dict.get("number_of_fractions_rtdose", 0) or 0)
        
        add_input_field(
            field_label="number_of_fractions_planned", default_value=number_of_fractions_planned, readonly=False, callback=update_sitk_metadata, user_data=(sitk_dose_ref, "number_of_fractions_planned"), 
            tooltip_texts=["This should be the number of fractions that you WANT the dose to represent."]
        )
        add_input_field(
            field_label="number_of_fractions_rtdose", default_value=number_of_fractions_rtdose, readonly=False, callback=update_sitk_metadata, user_data=(sitk_dose_ref, "number_of_fractions_rtdose"), spacer_after=False,
            tooltip_texts=["This should be the number of fractions that the dose CURRENTLY represents.", "The dose will be scaled to RTPLAN number of fractions: (Dose * (RTP/RTD)). If 0 fractions, no dose scaling occurs."]
        )
        
        add_custom_button(label="Read-Only Metadata Fields", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        
        sorted_keys = sorted(metadata_dict.keys())
        for key in sorted_keys:
            if key in ["number_of_fractions_planned", "number_of_fractions_rtdose"]:
                continue  # Skip the two editable fields
            add_input_field(field_label=key, default_value=str(metadata_dict[key]), readonly=True)

### RT PLAN FUNCTIONS ###

def _update_rmenu_unmatched_rtp(rtplans_unmatched_dict):
    """
    Updates the right menu with unmatched RT plan data.
    
    Args:
        rtplans_unmatched_dict (dict): Dictionary of unmatched RT plan data grouped by SOPInstanceUID.
    """
    if not rtplans_unmatched_dict:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.tree_node(parent="mw_right", label="Plans (Unlinked)", default_open=True):
        for rtp_idx, (rtp_sopiuid, rtplan_info_dict) in enumerate(rtplans_unmatched_dict.items(), start=1):
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=f"Unlinked RTPs Group #{rtp_idx}", default_open=True):
                _add_rtp_button(tag_modality_node, rtp_sopiuid, rtplan_info_dict)
        dpg.add_spacer(height=size_dict["spacer_height"])        

def _add_rtp_button(tag_modality_node, rtp_sopiuid, rtplan_info_dict):
    """
    Adds a button for an RT Plan to the UI.
    
    Args:
        tag_modality_node (int): The parent tree node tag.
        rtp_sopiuid (str): SOP Instance UID of the RT Plan.
        rtplan_info_dict (dict): Metadata dictionary for the RT Plan.
    """
    data_manager = get_user_data(td_key="data_manager")
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    RTPlanLabel = rtplan_info_dict.get("RTPlanLabel", "")
    RTPlanName = rtplan_info_dict.get("RTPlanName", "")
    
    # Try to find machine name
    treatment_machines = list(set([beam_dict["treatment_machine_name"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["treatment_machine_name"]]))
    if len(treatment_machines) > 1:
        print(f"Error: Multiple treatment machines found for RT Plan with label: {RTPlanLabel}. Using the first machine from this list: {treatment_machines}")
    treatment_machine = treatment_machines[0] if treatment_machines else None
    rtplan_info_dict["rt_plan_machine"] = treatment_machine
    
    # Get the original PTV names
    orig_ptv_names = data_manager.return_list_of_all_original_roi_names("ptv")
    
    # Try to find disease site
    plan_disease_site = rtplan_info_dict.get("rt_plan_disease_site", find_disease_site(RTPlanLabel, RTPlanName, orig_ptv_names))
    rtplan_info_dict["rt_plan_disease_site"] = plan_disease_site
    
    with dpg.group(parent=tag_modality_node, horizontal=True):
        display_data_keys = ("rtplan", rtp_sopiuid)
        save_dict = dpg.get_item_user_data(tag_save_button)
        save_dict[display_data_keys] = rtplan_info_dict
        
        tag_button = dpg.generate_uuid()
        tag_tooltip = dpg.generate_uuid()
        dpg.add_button(tag=tag_button, label="RTP", width=size_dict["button_width"], callback=popup_inspect_rtplan_dict, user_data=(rtp_sopiuid, rtplan_info_dict, tag_tooltip))
        dpg.bind_item_theme(item=tag_button, theme=get_colored_button_theme((90, 110, 70)))
        _update_rtp_button_tooltip(tag_button)

def _update_rtp_button_tooltip(tag_button):
    """
    Updates the tooltip for an RT Plan button.
    
    Args:
        tag_button (int): The tag of the button whose tooltip needs updating.
    """
    rtp_sopiuid, rtplan_info_dict, tag_tooltip = dpg.get_item_user_data(tag_button)
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_tooltip)
    keys_to_get = ["RTPlanLabel", "RTPlanName", "RTPlanDescription", "RTPlanDate", "ApprovalStatus", "target_prescription_dose_cgy", "number_of_fractions_planned", "patient_position", "setup_technique"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text("Modality: RT Plan", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rtp_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            if key in rtplan_info_dict:
                value = rtplan_info_dict.get(key, "")
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])

def popup_inspect_rtplan_dict(sender, app_data, user_data):
    """ 
    Opens a popup window to display and modify RT Plan attributes. 
    
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
    sender (int): The tag of the button that triggered this popup.
    app_data (any): Additional data from the sender.
    user_data (tuple): Contains SOP Instance UID, RT Plan metadata dictionary, and tooltip tag.
    """
    tag_inspect_sitk = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect_sitk)
    
    tag_button = sender
    rtp_sopiuid, rtplan_info_dict, tag_tooltip = user_data
    
    config_manager = get_user_data("config_manager")
    disease_site_list = config_manager.get_disease_site_list(ready_for_dpg=True)
    machine_list = config_manager.get_machine_names_list(ready_for_dpg=True)
    
    # Starts as a dict and becomes a string when overriden, so need to check for dict type
    ReviewerName = rtplan_info_dict.get("ReviewerName", {})
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
    radiation_types = list(set([beam_dict["radiation_type"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["radiation_type"]]))
    radiation_type_string = "MIXED" if len(radiation_types) > 1 else radiation_types[0] if radiation_types else None
    beam_numbers_with_wedge = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_wedges"]]
    beam_numbers_with_compensator = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_compensators"]]
    beam_numbers_with_bolus = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_boli"]]
    beam_numbers_with_block = [beam_dict["beam_number"] for beam_dict in rtplan_info_dict["beam_dict"].values() if beam_dict["number_of_blocks"]]
    unique_isocenters = list(set([tuple(cp_idx_dict.get("isocenter_position")) for beam_dict in rtplan_info_dict["beam_dict"].values() for cp_idx_dict in beam_dict["control_point_dict"].values() if cp_idx_dict.get("isocenter_position")]))
    num_unique_isocenters = len(unique_isocenters)
    
    popup_width, popup_height, popup_pos = get_popup_params()
    input_width = popup_width // 2
    
    # Create a mapping of field names to GUI item tags
    field_tags = {}
    tag_base = f"{tag_inspect_sitk}_"
    
    # Function to create input fields and store their tags
    def add_input_field(field_name, default_value, hint="", readonly=False, items=None, tooltip_texts=[], custom_title=None, callback=None, spacer_after=True):
        """
        Adds an input field to the GUI for RT Plan attributes.
        
        Args:
            field_name (str): The key for the field.
            default_value (any): The default value to display.
            hint (str): Hint text for input fields.
            readonly (bool): If True, the field will be read-only.
            items (list, optional): If provided, creates a combo box with these items.
            tooltip_texts (list, optional): Tooltips to display.
            custom_title (str, optional): Custom title for the field.
            callback (function, optional): Function to call when the field value changes.
            spacer_after (bool): If True, adds spacing after the field.
        """
        # Generate the field tag
        if field_name:
            field_tag = f"{tag_base}{field_name}"
            field_tags[field_name] = field_tag
        else:
            field_tag = dpg.generate_uuid()
        
        # Determine the title to display
        if custom_title:
            title = custom_title
        elif field_name:
            title = field_name.replace('_', ' ').title()
            title = title.replace("Rt", "RT").replace("Cgy", "cGy")
        else:
            title = "MISSING TITLE"
        
        # Format the title to a fixed width
        title = f"{title[:38]}:".ljust(40)
        
        with dpg.group(horizontal=True):
            dpg.add_text(title)
            
            # Common kwargs for input widgets
            input_kwargs = {'tag': field_tag, 'default_value': default_value, 'width': input_width, 'callback': callback, 'user_data': field_name}
            
            if items:
                dpg.add_combo(items=items, **input_kwargs)
            elif isinstance(default_value, int):
                input_kwargs.update({'min_value': 0, 'max_value': 9999, 'min_clamped': True, 'max_clamped': True, 'readonly': readonly})
                dpg.add_input_int(**input_kwargs)
            else:
                input_kwargs.update({'height': size_dict["button_height"] // 2, 'hint': hint, 'readonly': readonly})
                dpg.add_input_text(**input_kwargs)
            
            # Add tooltip to the last item added (the input widget)
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text(f"MetaData key: {str(field_name)}\nMetaData value: {default_value}", wrap=size_dict["tooltip_width"])
                for tooltip_text in tooltip_texts:
                    dpg.add_text(tooltip_text, wrap=size_dict["tooltip_width"])
        
        if spacer_after:
            dpg.add_spacer(height=size_dict["spacer_height"])
    
    # Callback function to update the rtplan_info_dict
    def update_rtplan_info_dict(sender, app_data, user_data):
        """
        Updates the RT Plan metadata dictionary.
        
        Args:
            sender (int): The tag of the sender.
            app_data (any): The new value for the field.
            user_data (str): The metadata field name to update.
        """
        field_name = user_data  # The field name passed as user_data
        new_value = app_data    # The new value from the input field
        
        rtplan_info_dict[field_name] = new_value
        _update_rtp_button_tooltip(tag_button)
        print(f"Updated rtplan_info_dict[{field_name}] = {new_value}")
    
    with dpg.window(
        tag=tag_inspect_sitk, label="RT Plan Info", width=popup_width, height=popup_height, pos=popup_pos, 
        no_open_over_existing_popup=False, popup=True, modal=True, no_title_bar=False, no_close=False, on_close=safe_delete(tag_inspect_sitk)
        ):
        add_custom_button(label="RT Plan Details", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        
        add_custom_button(label="Editable Fields", theme_tag=get_hidden_button_theme(), add_spacer_after=True)
        add_input_field("RTPlanLabel", RTPlanLabel, hint="Enter a label for the plan", custom_title="RT Plan Label", callback=update_rtplan_info_dict)
        add_input_field("rt_plan_disease_site", plan_disease_site, items=disease_site_list, custom_title="Disease Site", callback=update_rtplan_info_dict)
        add_input_field("rt_plan_machine", treatment_machine, items=machine_list, custom_title="Treatment Machine", callback=update_rtplan_info_dict)
        add_input_field("target_prescription_dose_cgy", target_rx_dose_cgy, callback=update_rtplan_info_dict)
        add_input_field("number_of_fractions_planned", number_of_fractions_planned, tooltip_texts=["On saving, the plan name will include this number of fractions."], callback=update_rtplan_info_dict, spacer_after=False)
        
        add_custom_button(label="Read-only Fields", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        add_input_field("RTPlanName", RTPlanName, hint="Missing a name for the plan", readonly=True, custom_title="RT Plan Name")
        add_input_field("RTPlanDescription", RTPlanDescription, hint="Missing a description for the plan", readonly=True, custom_title="RT Plan Description")
        add_input_field("rt_plan_radiation_type", radiation_type_string, hint="Missing radiation type for the plan", readonly=True)
        add_input_field("patient_position", patient_position, hint="Missing a patient position for the plan", readonly=True)
        add_input_field("setup_technique", setup_technique, hint="Missing a setup technique for the plan", readonly=True)
        add_input_field("RTPlanDate", RTPlanDate, hint="Missing a date for the plan", readonly=True, custom_title="RT Plan Date")
        add_input_field("ApprovalStatus", ApprovalStatus, hint="Missing an approval status for the plan", readonly=True, custom_title="Approval Status")
        add_input_field("ReviewerName", ReviewerName, hint="Missing a reviewer for the plan", readonly=True, custom_title="Reviewer Name", spacer_after=False)
        
        add_custom_button(label="Read-only Beam Info", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        add_input_field(None, total_num_beams, hint="Total number of beams in the plan", readonly=True, custom_title="Number Of Beams")
        add_input_field(None, num_treatment_beams, hint="Number of treatment beams in the plan", readonly=True, custom_title="Number Of Treatment Beams")
        add_input_field(None, num_unique_isocenters, hint="Number of unique isocenters in the plan", readonly=True, custom_title="Number Of Unique Isocenters")
        add_input_field(None, unique_isocenters, hint="Unique isocenter positions in the plan", readonly=True, custom_title="Unique Isocenter Positions")
        add_input_field(None, len(beam_numbers_with_wedge), hint="Number of beams with wedges", readonly=True, custom_title="Number Of Beams With Wedges")
        add_input_field(None, len(beam_numbers_with_compensator), hint="Number of beams with compensators", readonly=True, custom_title="Number Of Beams With Compensators")
        add_input_field(None, len(beam_numbers_with_bolus), hint="Number of beams with bolus", readonly=True, custom_title="Number Of Beams With Bolus")
        add_input_field(None, len(beam_numbers_with_block), hint="Number of beams with blocks", readonly=True, custom_title="Number Of Beams With Blocks")

### RT STRUCT FUNCTIONS ###

def _update_rmenu_rts(rtstructs_dict):
    """
    Updates the right menu with RT structure set data.
    
    Args:
        rtstructs_dict (dict): Dictionary of RT structure set data grouped by SOPInstanceUID.
    """
    if not rtstructs_dict:
        return
    
    size_dict = get_user_data(td_key="size_dict")
    
    # Create a list to store the ROI checkboxes
    roi_checkboxes = []
    with dpg.tree_node(parent="mw_right", label="Structure Sets", default_open=True):
        for rts_idx, (rts_sopiuid, rtstruct_info_dict) in enumerate(rtstructs_dict.items(), start=1):
            tag_modality_node = dpg.generate_uuid()
            with dpg.tree_node(tag=tag_modality_node, label=f"RTS #{rts_idx}", default_open=True):
                _add_rts_button(roi_checkboxes, tag_modality_node, rts_sopiuid, rtstruct_info_dict)
                
                # List of ROIs
                list_roi_idx_sitk_refs = [(roi_idx, roi_sitk_ref) for roi_idx, roi_sitk_ref in enumerate(rtstruct_info_dict.get("list_roi_sitk", [])) if roi_sitk_ref is not None and isinstance(roi_sitk_ref(), sitk.Image)]
                list_roi_idx_sitk_refs = sorted(list_roi_idx_sitk_refs, key=lambda x: struct_name_priority_key(x[1]().GetMetaData("current_roi_name")))
                _add_rts_roi_buttons(roi_checkboxes, tag_modality_node, rts_sopiuid, list_roi_idx_sitk_refs)
                dpg.add_spacer(height=size_dict["spacer_height"])

def _add_rts_button(roi_checkboxes, tag_modality_node, rts_sopiuid, rtstruct_info_dict):
    """
    Adds a button for an RT Structure Set to the UI.
    
    Args:
        roi_checkboxes (list): List of ROI checkboxes.
        tag_modality_node (int): The parent tree node tag.
        rts_sopiuid (str): SOP Instance UID of the RT Structure Set.
        rtstruct_info_dict (dict): Metadata dictionary for the RT Structure Set.
    """
    size_dict = get_user_data(td_key="size_dict")
    
    with dpg.group(parent=tag_modality_node, horizontal=True):
        # Button to toggle display of all ROIs. Ensure 'all' is the last key in the tuple 
        display_data_keys = ("rtstruct", rts_sopiuid, "list_roi_sitk", "all") 
        dpg.add_button(label="Toggle All ROIs", height=size_dict["button_height"], callback=_try_toggle_all_rois, user_data=(roi_checkboxes, display_data_keys))
        with dpg.tooltip(parent=dpg.last_item()):
            dpg.add_text(default_value="Toggles the display of all ROIs.", wrap=size_dict["tooltip_width"])
        
        # Add button for the RT Structure Set
        tag_rts_button = dpg.generate_uuid()
        tag_rts_tooltip = dpg.generate_uuid()
        dpg.add_button(tag=tag_rts_button, label="RTS", width=size_dict["button_width"], height=size_dict["button_height"], callback=_popup_inspect_structure_set_info, user_data=(rts_sopiuid, rtstruct_info_dict, tag_rts_tooltip))
        dpg.bind_item_theme(item=tag_rts_button, theme=get_colored_button_theme((90, 110, 70)))
        _update_rts_button_and_tooltip(tag_rts_button)

def _try_toggle_all_rois(sender, app_data, user_data):
    """
    Toggles the display of all ROIs in the RT Structure Set.
    
    Args:
        sender (int): The tag of the button that triggered this callback.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains the list of ROI checkboxes and the display data keys.
    """
    shared_state_manager = get_user_data("shared_state_manager")
    if shared_state_manager.cleanup_event.is_set() or shared_state_manager.is_action_in_queue():
        print(f"An action is already in progress. Please wait for it to complete before toggling all ROIs again.")
        return
    
    # Start the action
    shared_state_manager.add_action(lambda: _toggle_all_rois(sender, app_data, user_data))

def _toggle_all_rois(sender, app_data, user_data):
    """ Toggles the display of all ROIs in the RT Structure Set. Params passed from _try_toggle_all_rois. """
    shared_state_manager = get_user_data("shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        roi_checkboxes, display_data_keys = user_data
        valid_checkboxes = [roi_checkbox for roi_checkbox in roi_checkboxes if dpg.does_item_exist(roi_checkbox)]
        
        if not valid_checkboxes:
            shared_state_manager.action_event.clear()
            return
        
        should_load = not any(dpg.get_value(roi_checkbox) for roi_checkbox in valid_checkboxes)
        for valid_checkbox in valid_checkboxes:
            dpg.set_value(valid_checkbox, should_load)
        _send_cbox_update(None, should_load, display_data_keys)
    except Exception as e:
        print(f"Error in toggling all ROIs: {get_traceback(e)}")
    finally:
        shared_state_manager.action_event.clear()

def _update_rts_button_and_tooltip(tag_button):
    """
    Updates the tooltip and label for an RT Structure Set button.
    
    Args:
        tag_button (int): The tag of the button whose tooltip and label need updating.
    """
    rts_sopiuid, rtstruct_info_dict, tag_tooltip = dpg.get_item_user_data(tag_button)
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_tooltip)
    
    keys_to_get = ["StructureSetName", "StructureSetLabel", "StructureSetDate", "StructureSetTime", "ApprovalStatus", "ApprovalDate", "ApprovalTime", "ReviewerName"]
    with dpg.tooltip(tag=tag_tooltip, parent=tag_button):
        dpg.add_text("Modality: RT Struct", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rts_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            if key in rtstruct_info_dict:
                value = rtstruct_info_dict.get(key, "")
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])
    
    ss_label = rtstruct_info_dict.get("StructureSetLabel", "")
    if ss_label:
        dpg.set_item_label(tag_button, f"RTS: {ss_label}")
    else:
        dpg.set_item_label(tag_button, "RTS")

def _popup_inspect_structure_set_info(sender, app_data, user_data):
    """
    Opens a popup window to display and modify RT Structure Set attributes.
    
    rtstruct_info_dict has the following keys:
        StructureSetLabel, StructureSetName, StructureSetDate, StructureSetTime, SeriesInstanceUID, list_roi_sitk
    
    Args:
        sender (int): The tag of the button that triggered this popup.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains SOP Instance UID, RT Structure metadata dictionary, and tooltip tag.
    """
    tag_inspect_sitk = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_inspect_sitk)
    
    tag_button = sender
    rts_sopiuid, rtstruct_info_dict, tag_tooltip = user_data
    
    StructureSetLabel = rtstruct_info_dict.get("StructureSetLabel", "")
    StructureSetName = rtstruct_info_dict.get("StructureSetName", "")
    StructureSetDate = rtstruct_info_dict.get("StructureSetDate", "")
    StructureSetTime = rtstruct_info_dict.get("StructureSetTime", "")
    ReferencedSeriesInstanceUID = rtstruct_info_dict.get("ReferencedSeriesInstanceUID", "")
    
    popup_width, popup_height, popup_pos = get_popup_params()
    input_width = popup_width // 2
    
    # Helper function to add input fields
    def add_input_field(label, default_value, readonly=False, callback=None, user_data=None, spacer_after=True):
        """
        Adds an input field to display or edit RT Structure Set metadata.
        
        Args:
            label (str): The label for the metadata field.
            default_value (any): The value to display or edit.
            readonly (bool): If True, the field will be read-only.
            callback (function, optional): Function to call when the field value changes.
            user_data (any, optional): Data to pass to the callback.
            spacer_after (bool): If True, adds spacing after the field.
        """
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:".ljust(40))
            input_kwargs = {'default_value': default_value, 'width': input_width, 'callback': callback, 'user_data': user_data}
            if isinstance(default_value, int):
                dpg.add_input_int(readonly=readonly, **input_kwargs)
            else:
                dpg.add_input_text(readonly=readonly, **input_kwargs)
        
        if spacer_after:
            dpg.add_spacer(height=size_dict["spacer_height"])
    
    # Callback to update rtstruct_info_dict
    def update_rtstruct_info(sender, app_data, user_data):
        """
        Updates the RT Structure Set metadata dictionary.
        
        Args:
            sender (int): The tag of the sender.
            app_data (any): The new value for the metadata field.
            user_data (str): The metadata field name to update.
        """
        field_name = user_data
        rtstruct_info_dict[field_name] = app_data
        _update_rts_button_and_tooltip(tag_button)
        print(f"Updated rtstruct_info_dict[{field_name}] = {app_data}")
    
    with dpg.window(
        tag=tag_inspect_sitk, label="Structure Set Info", width=popup_width, height=popup_height, pos=popup_pos,
        no_open_over_existing_popup=False, popup=True, modal=True, no_title_bar=False, no_close=False,
        on_close=lambda: safe_delete(tag_inspect_sitk)
    ):
        add_custom_button(label="RT Struct Details", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        
        # add_custom_button(label="Editable Fields", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        # add_input_field(label="Structure Set Label", default_value=StructureSetLabel, callback=update_rtstruct_info, user_data="StructureSetLabel", spacer_after=False)
        
        add_custom_button(label="Read-Only Fields", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        add_input_field(label="Structure Set Label", default_value=StructureSetLabel, readonly=True)
        add_input_field(label="Structure Set Name", default_value=StructureSetName, readonly=True)
        add_input_field(label="Structure Set Date", default_value=StructureSetDate, readonly=True)
        add_input_field(label="Structure Set Time", default_value=StructureSetTime, readonly=True)
        add_input_field(label="Referenced Series Instance UID", default_value=ReferencedSeriesInstanceUID, readonly=True)

def _add_rts_roi_buttons(roi_checkboxes, tag_modality_node, rts_sopiuid, list_roi_idx_sitk_refs):
    """
    Adds buttons for all ROIs in an RT Structure Set.
    
    Args:
        roi_checkboxes (list): List of ROI checkboxes.
        tag_modality_node (int): The parent tree node tag.
        rts_sopiuid (str): SOP Instance UID of the RT Structure Set.
        list_roi_idx_sitk_refs (list): List of ROI index and SimpleITK references.
    """
    if not list_roi_idx_sitk_refs:
        return
    
    tag_save_button = get_tag("save_button")
    size_dict = get_user_data(td_key="size_dict")
    
    for (roi_idx, roi_sitk_ref) in list_roi_idx_sitk_refs:
        _update_new_roi_name(roi_sitk_ref)
        roi_display_color = get_sitk_roi_display_color(roi_sitk_ref())
        
        # Group for ROI interaction
        tag_group_roi = dpg.generate_uuid()
        with dpg.group(tag=tag_group_roi, parent=tag_modality_node, horizontal=True):
            # Checkbox to toggle ROI display
            display_data_keys = ("rtstruct", rts_sopiuid, "list_roi_sitk", roi_idx)
            save_dict = dpg.get_item_user_data(tag_save_button)
            save_dict[display_data_keys] = roi_sitk_ref
            
            dpg.add_checkbox(default_value=False, callback=_send_cbox_update, user_data=display_data_keys)
            tag_checkbox = dpg.last_item()
            roi_checkboxes.append(tag_checkbox)
            with dpg.tooltip(parent=tag_checkbox):
                dpg.add_text("Display ROI", wrap=size_dict["tooltip_width"])
            
            # Color picker to customize ROI color
            dpg.add_button(width=30, callback=_popup_roi_color_picker, user_data=roi_sitk_ref)
            tag_colorbutton = dpg.last_item()
            with dpg.tooltip(parent=tag_colorbutton):
                dpg.add_text(default_value="Customize ROI color", wrap=size_dict["tooltip_width"])
            dpg.bind_item_theme(item=tag_colorbutton, theme=get_colored_button_theme(roi_display_color))
            
            # Button to center views on ROI
            dpg.add_button(label="CTR", callback=_update_views_roi_center, user_data=tag_checkbox)
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text(default_value="Center views on ROI", wrap=size_dict["tooltip_width"])
            
            # Button to remove ROI entirely
            dpg.add_button(label="DEL", callback=_remove_roi, user_data=(display_data_keys, tag_group_roi, tag_checkbox))
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text(default_value="Removes the ROI entirely until you reload the data.", wrap=size_dict["tooltip_width"])
            
            # Button to inspect ROI
            tag_roi_button = dpg.generate_uuid()
            tag_roi_tooltip = dpg.generate_uuid()
            dpg.add_button(tag=tag_roi_button, label="ROI", width=size_dict["button_width"], callback=_popup_inspect_roi, user_data=(rts_sopiuid, roi_sitk_ref, tag_roi_tooltip))
            dpg.bind_item_theme(item=tag_roi_button, theme=get_colored_button_theme((90, 110, 70)))
            _update_rts_roi_button_and_tooltip(tag_roi_button)

def _update_rts_roi_button_and_tooltip(tag_roi_button):
    """
    Updates the tooltip and label for an ROI button in an RT Structure Set.
    
    Args:
        tag_roi_button (int): The tag of the button whose tooltip and label need updating.
    """
    rts_sopiuid, roi_sitk_ref, tag_roi_tooltip = dpg.get_item_user_data(tag_roi_button)
    size_dict = get_user_data(td_key="size_dict")
    
    safe_delete(tag_roi_tooltip)
    
    keys_to_get = ["roi_number", "original_roi_name", "current_roi_name", "rt_roi_interpreted_type", "roi_goals", "roi_physical_properties"]
    with dpg.tooltip(tag=tag_roi_tooltip, parent=tag_roi_button):
        dpg.add_text("Modality: RT Struct (ROI)", wrap=size_dict["tooltip_width"])
        dpg.add_text(f"SOP Instance UID: {rts_sopiuid}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            if roi_sitk_ref().HasMetaDataKey(key):
                value = roi_sitk_ref().GetMetaData(key)
                dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])
    
    roi_number = int(roi_sitk_ref().GetMetaData("roi_number"))
    roi_curr_name = roi_sitk_ref().GetMetaData("current_roi_name")
    dpg.set_item_label(tag_roi_button, f"ROI #{roi_number}: {roi_curr_name}")

### ROI FUNCTIONS ###

def _popup_inspect_roi(sender, app_data, user_data):
    """
    Opens a popup window to display and modify individual ROI attributes.
    
    Each SITK ROI has the following MetaData: 
        original_roi_name, current_roi_name, roi_number, roi_display_color, rt_roi_interpreted_type, 
        roi_physical_properties (list of dicts, each dict has keys: roi_physical_property, roi_physical_property_value), 
        material_id, roi_goals (dict), roi_rx_dose, roi_rx_fractions, roi_rx_site
    
    Note: roi_goals has keys (goal_type) and values (goal requirements)
    
    Args:
        sender (int): The tag of the button that triggered the popup.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains the RT Struct SOPInstanceUID, ROI SITK reference, and tooltip tag.
    """
    tag_inspect_sitk = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    config_manager = get_user_data("config_manager")
    
    safe_delete(tag_inspect_sitk)
    
    tag_roi_button = sender
    rts_sopiuid, roi_sitk_ref, tag_roi_tooltip = user_data
    
    # Helper function to get metadata with default values and casting
    def get_metadata(roi_sitk_ref, key, default=None, cast_func=None):
        """
        Retrieves metadata from the SITK ROI with optional default value and type casting.
        
        Args:
            roi_sitk_ref (SimpleITK.Image): Reference to the ROI image.
            key (str): The metadata key to retrieve.
            default (any): The default value if the key does not exist.
            cast_func (function, optional): A function to cast the value.
        
        Returns:
            The retrieved and optionally casted metadata value, or the default value.
        """
        roi_sitk = roi_sitk_ref()
        if roi_sitk is None:
            return default
        
        if roi_sitk.HasMetaDataKey(key):
            value = roi_sitk.GetMetaData(key)
            if cast_func:
                try:
                    value = cast_func(value)
                except ValueError:
                    value = default
        else:
            value = default
        return value
    
    # Retrieve ROI metadata
    roi_number = get_metadata(roi_sitk_ref, "roi_number", cast_func=int)
    original_roi_name = get_metadata(roi_sitk_ref, "original_roi_name", default="")
    current_roi_name = get_metadata(roi_sitk_ref, "current_roi_name", default="")
    rt_roi_interpreted_type = get_metadata(roi_sitk_ref, "rt_roi_interpreted_type", default="")
    roi_physical_properties = get_metadata(roi_sitk_ref, "roi_physical_properties", default=[])
    material_id = get_metadata(roi_sitk_ref, "material_id", default="")
    roi_goals = get_metadata(roi_sitk_ref, "roi_goals", default={})
    roi_rx_dose = get_metadata(roi_sitk_ref, "roi_rx_dose", default=0, cast_func=lambda x: int(float(x)))
    roi_rx_fractions = get_metadata(roi_sitk_ref, "roi_rx_fractions", default=0, cast_func=lambda x: int(float(x)))
    roi_rx_site = get_metadata(roi_sitk_ref, "roi_rx_site", default="")
    
    # Get necessary data from config_manager
    tg_263_oar_names_list = config_manager.get_tg_263_oar_names_list(ready_for_dpg=True)
    organ_name_matching_dict = config_manager.get_organ_name_matching_dict()
    disease_site_list = config_manager.get_disease_site_list(ready_for_dpg=True)
    
    # Get popup parameters
    popup_width, popup_height, popup_pos = get_popup_params()
    input_width = popup_width // 2
    
    # Create unique DPG tags for the input fields
    name_option_tag = dpg.generate_uuid()
    custom_name_group_tag = dpg.generate_uuid()
    custom_name_input_tag = dpg.generate_uuid()
    templated_name_group_tag = dpg.generate_uuid()
    templated_name_input_tag = dpg.generate_uuid()
    ptv_inputs_group_tag = dpg.generate_uuid()
    rx_dose_input_tag = dpg.generate_uuid()
    rx_fractions_input_tag = dpg.generate_uuid()
    rx_site_input_tag = dpg.generate_uuid()
    
    # Helper function to add input fields
    def add_input_field(label, default_value, readonly=False, items=None, callback=None, user_data=None, tag=None, spacer_after=True):
        """
        Adds an input field to the popup for displaying or editing metadata.
        
        Args:
            label (str): The label for the input field.
            default_value (any): The default value for the field.
            readonly (bool): Whether the field is read-only.
            items (list, optional): List of items for a combo box input.
            callback (function, optional): Callback function for input changes.
            user_data (any, optional): Data passed to the callback.
            tag (int, optional): Unique tag for the input field.
            spacer_after (bool): Whether to add a spacer after the field.
        """
        if not tag:
            tag = dpg.generate_uuid()
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:".ljust(40))
            input_kwargs = {'tag': tag, 'default_value': default_value, 'width': input_width, 'callback': callback, 'user_data': user_data}
            if items:
                dpg.add_combo(items=items, **input_kwargs)
            elif isinstance(default_value, int):
                dpg.add_input_int(readonly=readonly, **input_kwargs)
            elif isinstance(default_value, (tuple, list)) and all(isinstance(item, int) for item in default_value):
                dpg.add_input_intx(min_value=0, max_value=255, min_clamped=True, max_clamped=True, size=len(default_value), readonly=readonly, **input_kwargs)
            else:
                dpg.add_input_text(readonly=readonly, **input_kwargs)
        
        if spacer_after:
            dpg.add_spacer(height=size_dict["spacer_height"])
    
    # Callback to update SITK metadata
    def update_roi_metadata(sender, app_data, user_data):
        """
        Updates the metadata of the ROI based on user input.
        
        Args:
            sender (int): The tag of the input field.
            app_data (any): The new value entered by the user.
            user_data (tuple): Contains the SITK ROI reference and metadata key.
        """
        roi_sitk_ref, metadata_key = user_data
        roi_sitk = roi_sitk_ref()
        if roi_sitk is None:
            return
        
        roi_sitk.SetMetaData(metadata_key, str(app_data))
        _update_new_roi_name(roi_sitk_ref, tag_roi_button, tag_roi_tooltip, tag_inspect_sitk)
        _update_rts_roi_button_and_tooltip(tag_roi_button)
        print(f"Updated ROI metadata [{metadata_key}] = {app_data}")
    
    # Callback to update DPG & SITK for name selection change
    def on_name_option_change(sender, app_data, user_data):
        """
        Handles changes to the naming option for the ROI, toggling between templated and custom names.
        
        Args:
            sender (int): The tag of the combo box for naming options.
            app_data (str): The selected naming option.
            user_data (any): Additional data passed to the callback.
        """
        use_templated_roi_name = app_data == "Match by Templated ROI Name"
        
        if use_templated_roi_name:
            new_name = dpg.get_value(templated_name_input_tag)
        else:
            new_name = dpg.get_value(custom_name_input_tag)
        
        on_name_change(None, new_name, None)
        
        dpg.configure_item(custom_name_group_tag, show=not use_templated_roi_name)
        dpg.configure_item(templated_name_group_tag, show=use_templated_roi_name)
    
    # Callback to update SITK when name changes
    def on_name_change(sender, app_data, user_data):
        """
        Updates the ROI's current name and adjusts related metadata if necessary.
        
        Args:
            sender (int): The tag of the input field for the ROI name.
            app_data (str): The new name for the ROI.
            user_data (any): Additional data passed to the callback.
        """
        new_name = str(app_data)
        
        # Check if "ptv" is in the new name (case-insensitive) to show or hide the rx input fields
        is_ptv = "ptv" in new_name.lower()
        if dpg.does_item_exist(ptv_inputs_group_tag):
            dpg.configure_item(ptv_inputs_group_tag, show=is_ptv)
        
        update_roi_metadata(None, new_name, (roi_sitk_ref, "current_roi_name"))
    
    # Callback function to filter the templated ROI names based on user input
    def on_roi_template_filter(sender, app_data, user_data):
        """
        Filters the templated ROI name list based on user input.
        
        Args:
            sender (int): The tag of the input field for filtering.
            app_data (str): The filter text entered by the user.
            user_data (any): Additional data passed to the callback.
        """
        filter_text = app_data.lower()
        templated_name_items = config_manager.get_tg_263_oar_names_list(ready_for_dpg=True)
        filtered_items = [choice for choice in templated_name_items if filter_text in choice.lower()]
        dpg.configure_item(templated_name_input_tag, items=filtered_items)
    
    def verify_roi_goal_input(sender, app_data, user_data):
        """
        Verifies the ROI goal input format and updates metadata if valid.
        
        Args:
            sender (int): The tag of the input field for ROI goals.
            app_data (str): The ROI goal input as a string.
            user_data (tuple): Contains the SITK ROI reference, ROI button tag, and error message tag.
        """
        roi_sitk_ref, tag_roi_button, tag_goalerrortext = user_data
        roi_goals_string = app_data
        
        popup_width = dpg.get_item_width(get_tag("inspect_sitk_popup"))
        
        is_valid, error_list = verify_roi_goals_format(roi_goals_string)
        if is_valid:
            update_roi_metadata(None, roi_goals_string, (roi_sitk_ref, "roi_goals"))
            dpg.configure_item(tag_goalerrortext, color=(39, 174, 96), wrap=round(popup_width * 0.9))
            dpg.set_value(tag_goalerrortext, "ROI Goal Input is valid and saved!")
        else:
            dpg.configure_item(tag_goalerrortext, color=(192, 57, 43), wrap=round(popup_width * 0.9))
            dpg.set_value(tag_goalerrortext, f"ROI Goal Input is invalid and will not be saved! Error(s) below:\n{error_list}")
    
    with dpg.window(
        tag=tag_inspect_sitk, label=f"ROI Info", width=popup_width, height=popup_height, pos=popup_pos,
        no_open_over_existing_popup=False, popup=True, modal=True, no_title_bar=False, no_close=False,
        on_close=lambda: safe_delete(tag_inspect_sitk)
        ):
        add_custom_button(label="ROI Details", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        
        add_custom_button(label="Editable ROI Name", theme_tag=get_hidden_button_theme(), add_spacer_after=True)
        
        # Name option selection
        name_options = ["Match by Templated ROI Name", "Set Custom ROI Name"]
        if any(current_roi_name == x for x in tg_263_oar_names_list):
            default_option = "Match by Templated ROI Name"
            templated_roi_name = current_roi_name
        else:
            default_option = "Set Custom ROI Name"
            templated_roi_name = find_reformatted_mask_name(original_roi_name, rt_roi_interpreted_type, tg_263_oar_names_list, organ_name_matching_dict)
        
        add_input_field(tag=name_option_tag, label="Naming Option", default_value=default_option, items=name_options, callback=on_name_option_change, spacer_after=False)
        
        # Templated name input (combo box) with filter
        with dpg.group(tag=templated_name_group_tag, show=(default_option == "Match by Templated ROI Name")):
            add_input_field(tag=templated_name_input_tag, label="Templated Name", default_value=templated_roi_name, items=tg_263_oar_names_list, callback=on_name_change, spacer_after=False)
            add_input_field(label="Template Filter", default_value="", callback=on_roi_template_filter)
        
        # Custom name input
        with dpg.group(tag=custom_name_group_tag, show=(default_option == "Set Custom ROI Name")):
            add_input_field(tag=custom_name_input_tag, label="Custom Name", default_value=current_roi_name or "", callback=on_name_change)
        
        # PTV-specific input fields
        is_ptv = "ptv" in current_roi_name.lower() 
        with dpg.group(tag=ptv_inputs_group_tag, show=is_ptv):
            add_custom_button(label="Editable PTV Fields", theme_tag=get_hidden_button_theme(), add_spacer_after=True)
            add_input_field(tag=rx_dose_input_tag, label="Rx Dose (cGy)", default_value=roi_rx_dose, callback=update_roi_metadata, user_data=(roi_sitk_ref, "roi_rx_dose"), spacer_after=False)
            add_input_field(tag=rx_fractions_input_tag, label="Rx Fractions", default_value=roi_rx_fractions, callback=update_roi_metadata,user_data=(roi_sitk_ref, "roi_rx_fractions"), spacer_after=False)
            add_input_field(tag=rx_site_input_tag,label="Disease Site", default_value=roi_rx_site or disease_site_list[0], items=disease_site_list, callback=update_roi_metadata, user_data=(roi_sitk_ref, "roi_rx_site"), spacer_after=False)
        
        # Goals input field
        add_custom_button(label="Editable ROI Goals", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        tag_goalerrortext = dpg.generate_uuid()
        add_input_field(label="Goals", default_value=roi_goals, readonly=False, callback=verify_roi_goal_input, user_data=(roi_sitk_ref, tag_roi_button, tag_goalerrortext))
        dpg.add_text(tag=tag_goalerrortext, default_value="", color=(192, 57, 43), wrap=round(popup_width * 0.9))
        dpg.add_spacer(height=size_dict["spacer_height"])
        dpg.add_text(
            wrap=round(popup_width * 0.9), 
            default_value=(
                "- Edit ROI goals above. Expected format is a dictionary with keys and values."
                "\n\t- Keys:"
                "\n\t\t- Pattern should follow: {metric}_{metricvalue}_{metricunit}"
                "\n\t\t- Metric can be V, D, DC, CV, CI, MAX, MEAN, MIN, etc."
                "\n\t\t- MetricValue should be a number (can be integer or float)"
                "\n\t\t- MetricUnit can be cGy, Gy, %, cc"
                "\n\t- Values:"
                "\n\t\t- Pattern should be a LIST of strings, with each following: {comparison}_{compvalue}_{compunit}, or just {compvalue} for CI"
                "\n\t\t- Comparison can be >, >=, <, <=, ="
                "\n\t- Rules:"
                "\n\t\t- Key: CI metric must have a metricvalue in units of cGy, Values: CI compvalue units must be float or int."
                "\n\t\t- Key: CV metric must have a metricvalue in units of cGy, Values: CV compvalue units must be cc or %."
                "\n\t\t- Key: DC metric must have a metricvalue in units of cc or %, Values: DC compvalue units must be cGy or %."
                "\n\t\t- Key: D metric must have a metricvalue in units of cc or %, Values: D compvalue units must be cGy or %."
                "\n\t\t- Keys: MAX, MEAN, MIN metrics must have metricvalue in units of cGy or %."
                "\n\t\t- Key: V metric must have a metricvalue in units of cGy or %, Values: V compvalue units must be % or cc."
                '\n\t- Example: {"V_7000_cGy": [">_95.0_%"], "MAX": ["<_7420_cGy"]}'
            )
        )
        
        # Read-only fields
        add_custom_button(label="Read-Only Fields", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        add_input_field(label="Original Name", default_value=original_roi_name, readonly=True)
        add_input_field(label="ROI Number", default_value=roi_number, readonly=True)
        add_input_field(label="ROI Display Color", default_value=get_sitk_roi_display_color(roi_sitk_ref()), readonly=True)
        add_input_field(label="Interpreted Type", default_value=rt_roi_interpreted_type, readonly=True)
        add_input_field(label="Physical Properties", default_value=roi_physical_properties, readonly=True)
        add_input_field(label="Material ID", default_value=material_id, readonly=True)
    
def _remove_roi(sender, app_data, user_data):
    """
    Removes an ROI from the Data Manager after user confirmation.
    
    Args:
        sender (int): The tag of the button triggering the removal.
        app_data (any): Additional data from the sender.
        user_data (tuple): Contains keys for the ROI, the ROI group tag, and the checkbox tag.
    """
    keys, tag_group_roi, tag_checkbox = user_data
    
    def on_confirm():
        # Turn off the display if the checkbox is checked
        if dpg.get_value(tag_checkbox):
            dpg.set_value(tag_checkbox, False)
            checkbox_callback = dpg.get_item_callback(tag_checkbox)
            if checkbox_callback:
                checkbox_callback(tag_checkbox, False, keys)
        
        # Remove the ROI from the GUI
        safe_delete(tag_group_roi)
        
        # Remove the ROI from the Data Manager
        data_manager = get_user_data(td_key="data_manager")
        data_manager.remove_sitk_roi_from_rtstruct(keys)
        print(f"Removed ROI that had keys: {keys}")
    
    # Create the confirmation popup before performing the removal
    create_confirmation_popup(
        button_callback=on_confirm, button_theme=get_hidden_button_theme(),
        warning_string="Proceeding will remove this ROI from the current RTSTRUCT. It can only re-accessed by re-loading the data. Are you sure you want to continue?"
    )

def _update_new_roi_name(roi_sitk_ref, tag_roi_button=None, tag_roitooltiptext=None, tag_sitkwindow=None):
    """
    Updates the ROI's current name and related metadata.
    
    Args:
        roi_sitk_ref (SimpleITK.Image): Reference to the ROI image.
        tag_roi_button (int, optional): Tag of the button for the ROI.
        tag_roitooltiptext (int, optional): Tag of the tooltip for the ROI.
        tag_sitkwindow (int, optional): Tag of the popup window for the ROI.
    """
    roi_sitk = roi_sitk_ref()
    if roi_sitk is None:
        return
    
    def process_roi_name_update(roi_sitk, final_name):
        roi_sitk.SetMetaData("current_roi_name", final_name)
        if final_name.lower() == "external":
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "EXTERNAL")
        elif "ptv" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "PTV")
        elif "ctv" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "CTV")
        elif "gtv" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "GTV")
        elif "cavity" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "CAVITY")
        elif "bolus" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "BOLUS")
        elif "isocenter" in final_name.lower():
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "ISOCENTER")
        elif any([i in final_name.lower() for i in ["couch", "support", "data_table", "rail", "bridge", "mattress", "frame"]]):
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "SUPPORT")
        else:
            roi_sitk.SetMetaData("rt_roi_interpreted_type", "OAR")
        roi_number = int(roi_sitk.GetMetaData("roi_number"))
        new_text = f"ROI #{roi_number}: {final_name}"
        if tag_roi_button and dpg.does_item_exist(tag_roi_button):
            dpg.configure_item(tag_roi_button, label=new_text)
        if tag_sitkwindow and dpg.does_item_exist(tag_sitkwindow):
            dpg.configure_item(tag_sitkwindow, label=new_text)
        if tag_roitooltiptext and dpg.does_item_exist(tag_roitooltiptext):
            dpg.set_value(tag_roitooltiptext, f"\tCurrent Name: {final_name}")
    
    current_roi_name = roi_sitk.GetMetaData("current_roi_name")
    original_roi_name = roi_sitk.GetMetaData("original_roi_name")
    
    # Skip if the current_roi_name is the default value
    if current_roi_name == "SELECT_MASK_NAME":
        process_roi_name_update(roi_sitk, f"?UNIDENTIFIED?_{original_roi_name[:10]}...")
        return
    
    # Find an occurrence of templated "GTV", "CTV", "ITV" (case insensitive)
    if any([current_roi_name == i for i in ["ITV", "GTV", "CTV"]]):
        cleaned_string = re.sub(r'(GTV|CTV|ITV)', '', original_roi_name, flags=re.IGNORECASE).strip().replace(" ", "_").lstrip("_")
        if cleaned_string:
            current_roi_name += f"_{cleaned_string}"
        process_roi_name_update(roi_sitk, current_roi_name)
        return
    
    # Handle non-templated cases
    if current_roi_name != "PTV" and not current_roi_name.startswith("PTV_"):
        # If not PTV, set the metadata values to empty strings
        if "ptv" not in current_roi_name.lower():
            roi_sitk.SetMetaData("roi_rx_dose", "")
            roi_sitk.SetMetaData("roi_rx_fractions", "")
            roi_sitk.SetMetaData("roi_rx_site", "")
        process_roi_name_update(roi_sitk, current_roi_name)
        return
    
    # Handle templated PTV cases
    current_roi_name = "PTV"
    orig_dose_fx_dict = regex_find_dose_and_fractions(original_roi_name)
    
    roi_rx_site = roi_sitk.GetMetaData("roi_rx_site")
    roi_rx_dose = roi_sitk.GetMetaData("roi_rx_dose")
    roi_rx_fractions = roi_sitk.GetMetaData("roi_rx_fractions")
    
    if not roi_rx_site:
        config_manager = get_user_data("config_manager")
        disease_site_list_base = config_manager.get_disease_site_list(ready_for_dpg=True)[0]
        found_disease_site = find_disease_site(None, None, [current_roi_name, original_roi_name])
        
        if not found_disease_site or found_disease_site == disease_site_list_base:
            process_roi_name_update(roi_sitk, current_roi_name)
            return
        
        roi_rx_site = found_disease_site
        roi_sitk.SetMetaData("roi_rx_site", roi_rx_site)
    
    current_roi_name = f"{current_roi_name}_{roi_rx_site}"
    
    if not roi_rx_dose:
        if not any(char.isdigit() for char in original_roi_name) or not orig_dose_fx_dict.get("dose"):
            process_roi_name_update(roi_sitk, current_roi_name)
            return
        
        roi_rx_dose = str(int(orig_dose_fx_dict["dose"]))
        roi_sitk.SetMetaData("roi_rx_dose", roi_rx_dose)
    
    current_roi_name = f"{current_roi_name}_{roi_rx_dose}"
    
    if not roi_rx_fractions:
        if not any(char.isdigit() for char in original_roi_name) or not orig_dose_fx_dict.get("fractions"):
            process_roi_name_update(roi_sitk, current_roi_name)
            return
        
        roi_rx_fractions = str(int(orig_dose_fx_dict["fractions"]))
        roi_sitk.SetMetaData("roi_rx_fractions", roi_rx_fractions)
    
    current_roi_name = f"{current_roi_name}_{roi_rx_fractions}"
    process_roi_name_update(roi_sitk, current_roi_name)

def _popup_roi_color_picker(sender, app_data, user_data):
    """
    Opens a color picker popup to select a new color for an ROI.
    
    Args:
        sender (int): The tag of the button triggering the popup.
        app_data (any): Additional data from the sender.
        user_data (SimpleITK.Image): Reference to the ROI image.
    """
    tag_colorpicker = get_tag("color_picker_popup")
    safe_delete(tag_colorpicker)
    
    roi_sitk_ref = user_data
    roi_sitk = roi_sitk_ref()
    if roi_sitk is None:
        return
    
    roi_number = int(roi_sitk.GetMetaData("roi_number"))
    roi_name = roi_sitk.GetMetaData("current_roi_name")
    current_color = get_sitk_roi_display_color(roi_sitk)
    
    mouse_pos = dpg.get_mouse_pos(local=False)
    with dpg.window(tag=tag_colorpicker, label=f"Choose Color For ROI #{roi_number}: {roi_name}", popup=True, pos=mouse_pos, on_close=lambda: safe_delete(tag_colorpicker)):
        dpg.add_color_picker(default_value=current_color, callback=_update_roi_color, no_alpha=True, user_data=(sender, roi_sitk_ref), display_rgb=True)
        dpg.add_button(label="Close", callback=lambda: safe_delete(tag_colorpicker))

def _update_roi_color(sender, app_data, user_data):
    """
    Updates the color of an ROI based on the color picker selection.
    
    Args:
        sender (int): The tag of the color picker.
        app_data (list[float]): The selected color as a list of RGB values.
        user_data (tuple): Contains the color button tag and the SITK ROI reference.
    """
    new_color_floats = app_data[:3]
    tag_colorbutton, roi_sitk_ref = user_data
    
    roi_sitk = roi_sitk_ref()
    if roi_sitk is None:
        return
    
    new_color = [round(min(max(255 * color, 0), 255)) for color in new_color_floats]
    roi_sitk.SetMetaData("roi_display_color", str(new_color))
    dpg.bind_item_theme(item=tag_colorbutton, theme=get_colored_button_theme(new_color))
    
    request_texture_update(texture_action_type="update")

def _update_views_roi_center(sender, app_data, user_data):
    """
    Centers the displayed views on the center of the specified ROI.
    
    Args:
        sender (int): The tag of the sender triggering the update.
        app_data (any): Additional data from the sender.
        user_data (int): The checkbox tag corresponding to the ROI.
    """
    tag_checkbox = user_data
    keys = dpg.get_item_user_data(tag_checkbox)
    data_manager = get_user_data("data_manager")
    img_tags = get_tag("img_tags")
    
    any_data_active_before = data_manager.return_is_any_data_active()
    dpg.set_value(tag_checkbox, True)
    data_manager.update_active_data(True, keys)
    any_data_active_after = data_manager.return_is_any_data_active()
    
    if not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
        time.sleep(1/10) # Wait to ensure the callback has time to update state
    
    roi_center = data_manager.return_npy_center_of_mass(keys)
    roi_extents = data_manager.return_npy_extent_ranges(keys)
    
    if not roi_center or not roi_extents:
        print(f"ROI '{keys[-1]}' has no center of mass or extents to center views on. Found center: {roi_center}, extents: {roi_extents}")
        return
    
    # Modify the current view limits to display the ROI
    for i, dim_tag in enumerate([img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]):
        limit_config = dpg.get_item_configuration(dim_tag)
        
        # Get the current limits
        limit_min = limit_config["min_value"]
        limit_max = limit_config["max_value"]
        limit_size = limit_max - limit_min
        
        # Get the current ranges
        curr_min, curr_max = dpg.get_value(dim_tag)[:2]
        
        # Get the roi ranges
        roi_min_val = roi_extents[i][0]
        roi_max_val = roi_extents[i][1]
        
        # Get the desired window size
        zoom_out_factor = 1.05
        new_min_val = max(
            # Take the smallest of the three values: current min, roi min - 5% of limit size, limit max - 10% of limit size
            min(
                curr_min, 
                round(roi_min_val - (zoom_out_factor * limit_size / 2)), 
                round(limit_max - (limit_size * 0.10))
            ), 
            # Do not allow values below limit min
            limit_min
        )
        new_max_val = min(
            # Take the largest of the three values: current max, roi max + 5% of limit size, new min + 10% of limit size
            max(
                curr_max, 
                round(roi_max_val + (zoom_out_factor * limit_size / 2)), 
                round(new_min_val + (limit_size * 0.10))
            ), 
            # Do not allow values above limit max
            limit_max
        )
        
        new_range = [new_min_val, new_max_val]
        dpg.set_value(dim_tag, new_range)
    
    dpg.set_value(img_tags["viewed_slices"], roi_center)
    
    request_texture_update(texture_action_type="update")

def _send_cbox_update(sender, app_data, user_data):
    """
    Updates the display state of data based on the checkbox state.
        
        Identifier is either SeriesInstanceUID (image) or SOPInstanceUID (non-image)
        Key is the dictionary key to check for
        Value is the SITK Image
    
    Args:
        sender (int): The tag of the checkbox.
        app_data (bool): The state of the checkbox (True for checked, False for unchecked).
        user_data (tuple): Contains keys for identifying the data in the Data Manager.
    """
    load_data = app_data
    display_data_keys = user_data
    data_manager = get_user_data("data_manager")
    
    any_data_active_before = data_manager.return_is_any_data_active()
    data_manager.update_active_data(load_data, display_data_keys)
    any_data_active_after = data_manager.return_is_any_data_active()
    
    # Data is now cleared -> reset the texture
    if any_data_active_before and not any_data_active_after:
        request_texture_update(texture_action_type="reset")
    # Data is now shown -> initialize the texture
    elif not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
    # No change -> update the texture
    else:
        request_texture_update(texture_action_type="update")
    
    
    