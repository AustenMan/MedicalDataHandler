from __future__ import annotations


import logging
import random
from typing import TYPE_CHECKING, Tuple, Any, Union, List
from time import sleep
from json import loads, dumps


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.dpg_components.windows.confirmation.confirm_window import create_confirmation_popup
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params
from mdh_app.utils.general_utils import find_disease_site, validate_roi_goals_format, regex_find_dose_and_fractions


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def update_roi_tooltip(tag_roi_button: Union[str, int]) -> None:
    """ Update the tooltip of an ROI button with its metadata. """
    if not dpg.does_item_exist(tag_roi_button):
        return
    
    size_dict = get_user_data(td_key="size_dict")
    data_mgr: DataManager = get_user_data("data_manager")
    rts_sopiuid, roi_number, tag_roi_tooltip = dpg.get_item_user_data(tag_roi_button)
    
    # Get ROI metadata (specific to GUI)
    roi_metadata = data_mgr.get_roi_gui_metadata_by_uid(rts_sopiuid, roi_number)
    roi_name = roi_metadata.get("ROIName", "-MISSING-")
    roi_template_name = roi_metadata.get("ROITemplateName", roi_name)
    use_template_name = roi_metadata.get("use_template_name", False)
    rt_roi_interpreted_type = roi_metadata.get("RTROIInterpretedType", "CONTROL")
    roi_phys_prop_value = roi_metadata.get("ROIPhysicalPropertyValue", None)
    roi_goals = roi_metadata.get("roi_goals", {})
    roi_rx_dose = roi_metadata.get("roi_rx_dose", None)
    roi_rx_fractions = roi_metadata.get("roi_rx_fractions", None)
    roi_rx_site = roi_metadata.get("roi_rx_site", None)
    
    # Determine displayed name
    displayed_name = roi_template_name if use_template_name else roi_name
    
    dpg.set_item_label(tag_roi_button, f"ROI #{roi_number}: {displayed_name}")
    safe_delete(tag_roi_tooltip)
    with dpg.tooltip(tag=tag_roi_tooltip, parent=tag_roi_button):
        dpg.add_text(
            (
                f"ROI #{roi_number}: {displayed_name}\n" +
                f"ROI Name: {roi_name}\n" +
                f"ROI Template Name: {roi_template_name} (Use Template Name: {'Yes' if use_template_name else 'No'})\n" +
                f"RT ROI Interpreted Type: {rt_roi_interpreted_type}\n" +
                f"ROI Physical Property Value: {roi_phys_prop_value if roi_phys_prop_value is not None else 'N/A'}\n" +
                f"ROI Goals: {roi_goals if roi_goals else 'N/A'}\n" +
                f"Rx Dose: {roi_rx_dose or 'N/A'}\n" if rt_roi_interpreted_type == "PTV" else "" +
                f"Rx Fractions: {roi_rx_fractions or 'N/A'}\n" if rt_roi_interpreted_type == "PTV" else "" +
                f"Rx Site: {roi_rx_site or 'N/A'}\n" if rt_roi_interpreted_type == "PTV" else ""
            ),
            wrap=size_dict["tooltip_width"]
        )


def _update_roi_meta_on_name_change(rts_sopiuid: str, roi_number: int) -> None:
    """ Updates ROI metadata based on its name, especially for PTVs. """
    # Get current metadata name (specific to GUI)
    data_mgr: DataManager = get_user_data("data_manager")
    current_roi_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIName", "-MISSING-")
    
    # Get cleaned lower name
    lower_name = current_roi_name.strip().lower()

    # Update RTROIInterpretedType based on name
    if lower_name == "external":
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "EXTERNAL")
    elif "ptv" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "PTV")
    elif "ctv" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "CTV")
    elif "gtv" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "GTV")
    elif "cavity" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "CAVITY")
    elif "bolus" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "BOLUS")
    elif "isocenter" in lower_name:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "ISOCENTER")
    elif any(x in lower_name for x in ["couch", "support", "data_table", "rail", "bridge", "mattress", "frame"]):
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "SUPPORT")
    else:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", "OAR")
    
    # Exit if not PTV
    if not (lower_name == "ptv" or lower_name.startswith("ptv_")):
        return

    # Read ROI name from DICOM dataset
    original_roi_name = data_mgr.get_rtstruct_roi_ds_value_by_uid(rts_sopiuid, roi_number, "ROIName", "-MISSING-")
    orig_dose_fx_dict = regex_find_dose_and_fractions(original_roi_name)
    
    # Get dose, fractions, and site
    roi_rx_dose = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_dose", None)
    roi_rx_fractions = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_fractions", None)
    roi_rx_site = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_site", None)

    # Get disease site base name
    cfg_mgr: ConfigManager = get_user_data("config_manager")
    disease_site_list_base = cfg_mgr.get_disease_sites(ready_for_dpg=True)[0]

    # Add site
    if not roi_rx_site:
        found_disease_site = find_disease_site(None, None, [current_roi_name, original_roi_name])
        if not found_disease_site or found_disease_site == disease_site_list_base:
            return
        roi_rx_site = found_disease_site
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_site", roi_rx_site)
    current_roi_name = f"{current_roi_name}_{roi_rx_site}"

    # Add dose
    if not isinstance(roi_rx_dose, int):
        if not any(char.isdigit() for char in original_roi_name) or not orig_dose_fx_dict.get("dose"):
            data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIName", current_roi_name)
            return
        roi_rx_dose = int(orig_dose_fx_dict["dose"])
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_dose", roi_rx_dose)
    current_roi_name = f"{current_roi_name}_{roi_rx_dose}"

    # Add fractions
    if not isinstance(roi_rx_fractions, int):
        if not any(char.isdigit() for char in original_roi_name) or not orig_dose_fx_dict.get("fractions"):
            data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIName", current_roi_name)
            return
        roi_rx_fractions = int(orig_dose_fx_dict["fractions"])
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_fractions", roi_rx_fractions)
    current_roi_name = f"{current_roi_name}_{roi_rx_fractions}"

    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIName", current_roi_name)
    return


def _on_gui_roi_template_filter(sender: Any, app_data: str, user_data: Any) -> None:
    """
    Filter templated ROI names based on user input.

    Args:
        sender: The filter input field tag.
        app_data: The filter text.
        user_data: Additional data (unused).
    """
    templated_name_input_tag = user_data
    conf_mgr: ConfigManager = get_user_data("config_manager")
    filter_text = app_data.lower()
    templated_items = conf_mgr.get_tg_263_names(ready_for_dpg=True)
    filtered = [item for item in templated_items if filter_text in item.lower()]
    dpg.configure_item(templated_name_input_tag, items=filtered)


def _on_gui_name_option_change(sender: Any, app_data: str, user_data: Any) -> None:
    """
    Handle changes to ROI naming options, toggling between templated and custom inputs.

    Args:
        sender: The radio button tag.
        app_data: The selected naming option.
        user_data: Additional data (unused).
    """
    data_mgr: DataManager = get_user_data("data_manager")
    (
        template_str, rts_sopiuid, roi_number, 
        custom_name_row_tag, templated_name_row_tag, templated_filter_row_tag,
        ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag
    ) = user_data

    use_templated = app_data == template_str
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "use_template_name", use_templated)
    dpg.configure_item(custom_name_row_tag, show=not use_templated)
    dpg.configure_item(templated_name_row_tag, show=use_templated)
    dpg.configure_item(templated_filter_row_tag, show=use_templated)
    new_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROITemplateName" if use_templated else "ROIName", "-MISSING-")
    is_ptv = "ptv" in new_name.lower()
    for ptv_tag in [ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag]:
        if dpg.does_item_exist(ptv_tag):
            dpg.configure_item(ptv_tag, show=is_ptv)


def _on_gui_name_change(sender: Any, app_data: str, user_data: Any) -> None:
    """
    Update the current ROI name based on user input.

    Args:
        sender: The tag of the ROI name input field.
        app_data: The new ROI name.
        user_data: Additional data (unused).
    """
    (
        templated_name_input_tag, custom_name_input_tag, tag_roi_button,
        ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag
    ) = user_data
    
    new_name = str(app_data)
    is_ptv = "ptv" in new_name.lower()
    for ptv_tag in [ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag]:
        if dpg.does_item_exist(ptv_tag):
            dpg.configure_item(ptv_tag, show=is_ptv)
    if sender == templated_name_input_tag:
        _update_roi_metadata(None, new_name, (tag_roi_button, "ROITemplateName"))
    elif sender == custom_name_input_tag:
        _update_roi_metadata(None, new_name, (tag_roi_button, "ROIName"))


def _update_roi_metadata(sender: Any, app_data: Any, user_data: Tuple[Any, str]) -> None:
    """ Update ROI metadata from user input. """
    data_mgr: DataManager = get_user_data("data_manager")
    new_value = app_data
    tag_roi_button, key = user_data
    rts_sopiuid, roi_number, tag_roi_tooltip = dpg.get_item_user_data(tag_roi_button)
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, key, new_value)
    if key == "ROIName" or key == "ROITemplateName":
        _update_roi_meta_on_name_change(rts_sopiuid, roi_number)
    update_roi_tooltip(tag_roi_button)


def _validate_roi_goal_inputs(sender: Any, app_data: str, user_data: Tuple[Any, Any]) -> None:
    """
    Validate ROI goal input and update metadata if valid.

    Args:
        sender: The input field tag.
        app_data: The ROI goal input string.
        user_data: Tuple containing (ROI button tag, goal text tag).
    """
    tag_roi_button, tag_goal_text = user_data
    roi_goals_str = app_data
    popup_width = dpg.get_item_width(get_tag("inspect_data_popup"))
    is_valid, errors = validate_roi_goals_format(roi_goals_str)
    if is_valid:
        rts_sopiuid, roi_number, tag_roi_tooltip = dpg.get_item_user_data(tag_roi_button)
        data_mgr: DataManager = get_user_data("data_manager")
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_goals", loads(roi_goals_str))
        update_roi_tooltip(tag_roi_button)
        dpg.configure_item(tag_goal_text, color=(39, 174, 96), wrap=round(popup_width * 0.9))
        dpg.set_value(tag_goal_text, "ROI Goal Input is valid and saved!")
    else:
        dpg.configure_item(tag_goal_text, color=(192, 57, 43), wrap=round(popup_width * 0.9))
        dpg.set_value(tag_goal_text, f"ROI Goal Input is invalid and will not be saved! Issues:\n{errors}")


def _popup_inspect_roi(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """ Open a popup window to display and allow modification of individual ROI metadata. """
    tag_inspect = get_tag("inspect_data_popup")
    size_dict = get_user_data(td_key="size_dict")
    conf_mgr: ConfigManager = get_user_data("config_manager")
    data_mgr: DataManager = get_user_data("data_manager")
    
    safe_delete(tag_inspect)
    
    tag_roi_button = sender
    rts_sopiuid, roi_number, tag_roi_tooltip = user_data
    
    # Get ROI metadata (specific to GUI)
    original_roi_name = data_mgr.get_rtstruct_roi_ds_value_by_uid(rts_sopiuid, roi_number, "ROIName", "-MISSING-")
    roi_metadata = data_mgr.get_roi_gui_metadata_by_uid(rts_sopiuid, roi_number)
    roi_name = roi_metadata.get("ROIName", unmatched_organ_name)
    roi_template_name = roi_metadata.get("ROITemplateName", roi_name)
    use_template_name = roi_metadata.get("use_template_name", False)
    roi_display_color = roi_metadata.get("ROIDisplayColor", [random.randint(0, 255) for _ in range(3)])
    rt_roi_interpreted_type = roi_metadata.get("RTROIInterpretedType", "CONTROL")
    roi_phys_prop_value = roi_metadata.get("ROIPhysicalPropertyValue", None)
    roi_goals = roi_metadata.get("roi_goals", {})
    roi_rx_dose = roi_metadata.get("roi_rx_dose", None)
    roi_rx_fractions = roi_metadata.get("roi_rx_fractions", None)
    roi_rx_site = roi_metadata.get("roi_rx_site", None)
    
    # Get necessary data from config_manager
    tg_263_oar_names_list = conf_mgr.get_tg_263_names(ready_for_dpg=True)
    organ_name_matching_dict = conf_mgr.get_organ_matching_dict()
    disease_site_list = conf_mgr.get_disease_sites(ready_for_dpg=True)
    unmatched_organ_name = conf_mgr.get_unmatched_organ_name()
    
    # Get popup parameters
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # Create unique DPG tags for the input fields
    name_option_tag = dpg.generate_uuid()
    custom_name_row_tag = dpg.generate_uuid()
    custom_name_input_tag = dpg.generate_uuid()
    templated_name_row_tag = dpg.generate_uuid()
    templated_filter_row_tag = dpg.generate_uuid()
    templated_name_input_tag = dpg.generate_uuid()
    ptv_dose_row_tag = dpg.generate_uuid()
    ptv_fractions_row_tag = dpg.generate_uuid()
    ptv_site_row_tag = dpg.generate_uuid()
    rx_dose_input_tag = dpg.generate_uuid()
    rx_fractions_input_tag = dpg.generate_uuid()
    rx_site_input_tag = dpg.generate_uuid()
    tag_goalerrortext = dpg.generate_uuid()
    
    # Name option selection
    match_by_temp_str = "Match by Templated ROI Name"
    set_custom_str = "Set Custom ROI Name"
    name_options = [match_by_temp_str, set_custom_str]
    default_option = match_by_temp_str if use_template_name else set_custom_str

    with dpg.window(
        tag=tag_inspect,
        label="ROI Info",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_open_over_existing_popup=False
    ):
        add_custom_button(label="ROI Details", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        add_custom_button(label="Editable ROI Name", theme_tag=get_hidden_button_theme(), add_spacer_after=True)
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            # Name option selection
            with dpg.table_row():
                dpg.add_text("Naming Option:")
                dpg.add_radio_button(
                    tag=name_option_tag, 
                    items=name_options, 
                    default_value=default_option, 
                    callback=_on_gui_name_option_change,
                    user_data=(
                        match_by_temp_str, rts_sopiuid, roi_number, 
                        custom_name_row_tag, templated_name_row_tag, templated_filter_row_tag,
                        ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag
                    )
                )
            
            # Templated name input (combo box)
            with dpg.table_row(tag=templated_name_row_tag, show=(default_option == match_by_temp_str)):
                dpg.add_text("Templated Name:")
                dpg.add_combo(
                    tag=templated_name_input_tag, 
                    items=tg_263_oar_names_list, 
                    default_value=roi_template_name, 
                    callback=_on_gui_name_change,
                    user_data=(
                        templated_name_input_tag, custom_name_input_tag, tag_roi_button,
                        ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag
                    )
                )

            # Templated name input (combo box)
            with dpg.table_row(tag=templated_name_row_tag, show=(default_option == match_by_temp_str)):
                dpg.add_text("Templated Name:")
                dpg.add_combo(
                    tag=templated_name_input_tag,
                    items=tg_263_oar_names_list,
                    default_value=roi_template_name,
                    callback=_on_gui_name_change,
                    user_data=(
                        templated_name_input_tag, custom_name_input_tag, tag_roi_button,
                        ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag
                    )
                )

            # Templated combo box filter
            with dpg.table_row(tag=templated_filter_row_tag, show=(default_option == match_by_temp_str)):
                dpg.add_text("Template Filter:")
                dpg.add_input_text(callback=_on_gui_roi_template_filter, user_data=templated_name_input_tag)

            # Custom name input
            with dpg.table_row(tag=custom_name_row_tag, show=(default_option == set_custom_str)):
                dpg.add_text("Custom Name:")
                dpg.add_input_text(
                    tag=custom_name_input_tag, 
                    default_value=roi_name, 
                    callback=_on_gui_name_change
                )
            
            # PTV-specific input fields
            is_ptv = "ptv" in roi_name.lower()
            with dpg.table_row(tag=ptv_dose_row_tag, show=is_ptv):
                dpg.add_text("PTV Rx Dose (cGy):")
                dpg.add_input_int(
                    tag=rx_dose_input_tag, 
                    default_value=roi_rx_dose, 
                    callback=_update_roi_metadata, 
                    user_data=(tag_roi_button, "roi_rx_dose")
                )
            with dpg.table_row(tag=ptv_fractions_row_tag, show=is_ptv):
                dpg.add_text("PTV Rx Fractions:")
                dpg.add_input_int(
                    tag=rx_fractions_input_tag, 
                    default_value=roi_rx_fractions,
                    callback=_update_roi_metadata, 
                    user_data=(tag_roi_button, "roi_rx_fractions")
                )
            with dpg.table_row(tag=ptv_site_row_tag, show=is_ptv):
                dpg.add_text("PTV Disease Site:")
                dpg.add_combo(
                    tag=rx_site_input_tag, 
                    items=disease_site_list, 
                    default_value=roi_rx_site or disease_site_list[0], 
                    callback=_update_roi_metadata, 
                    user_data=(tag_roi_button, "roi_rx_site")
                )
            
            # Goals input field
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("ROI Goals must be a dictionary that meet the rules described below.", wrap=size_dict["tooltip_width"])
                    dpg.add_text("ROI Goals:")
                dpg.add_input_text(
                    default_value=dumps(roi_goals) if roi_goals else "", 
                    callback=_validate_roi_goal_inputs, 
                    user_data=(tag_roi_button, tag_goalerrortext)
                )
            
            # Goals error output
            with dpg.table_row():
                dpg.add_text()
                dpg.add_text(tag=tag_goalerrortext, default_value="", color=(192, 57, 43), wrap=round(popup_width * 0.9))
        
        # Goals input field
        add_custom_button(label="Rules for ROI Goals", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
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
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            with dpg.table_row():
                dpg.add_text("Original Name:")
                dpg.add_input_text(default_value=original_roi_name, readonly=True)
            with dpg.table_row():
                dpg.add_text("ROI Number:")
                dpg.add_input_int(default_value=roi_number, readonly=True)
            with dpg.table_row():
                dpg.add_text("ROI Display Color:")
                dpg.add_input_intx(
                    default_value=roi_display_color, 
                    size=len(roi_display_color), 
                    readonly=True, 
                    min_value=0, 
                    max_value=255, 
                    min_clamped=True, 
                    max_clamped=True
                )
            with dpg.table_row():
                dpg.add_text("Interpreted Type:")
                dpg.add_input_text(default_value=rt_roi_interpreted_type, readonly=True)
            with dpg.table_row():
                dpg.add_text("ROI Relative Electron Density Override Value:")
                dpg.add_input_text(default_value=roi_phys_prop_value, readonly=True)


def _remove_roi(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any]) -> None:
    """
    Remove an ROI after user confirmation.

    Args:
        sender: The button tag that triggered removal.
        app_data: Additional event data.
        user_data: Tuple containing (ROI identifier keys, ROI group tag, checkbox tag).
    """
    tag_group_roi, roi_cbox_tag = user_data
    
    def on_confirm(sender, app_data, user_data) -> None:
        cb_userdata = dpg.get_item_user_data(roi_cbox_tag)
        _, rts_sopiuid, roi_number = cb_userdata
        if dpg.get_value(roi_cbox_tag):
            dpg.set_value(roi_cbox_tag, False)
            cb_callback = dpg.get_item_callback(roi_cbox_tag)
            if cb_callback:
                cb_callback(roi_cbox_tag, False, cb_userdata)
        safe_delete(tag_group_roi)
        data_mgr: DataManager = get_user_data(td_key="data_manager")
        data_mgr.remove_roi_from_rtstruct(rts_sopiuid, roi_number)
        logger.info(f"Removed the display of ROI #{roi_number} from structure set {rts_sopiuid}.")
    
    # Create the confirmation popup before performing the removal
    create_confirmation_popup(
        button_callback=on_confirm,
        button_theme=get_hidden_button_theme(),
        warning_string=f"Proceeding will remove the display of this ROI from the current structure set. Continue?"
    )


def _popup_roi_color_picker(sender: Union[str, int], app_data: Any, user_data: Tuple[str, int]) -> None:
    """
    Open a popup to choose a new ROI color.

    Args:
        sender: The tag of the button triggering the color picker.
        app_data: Additional event data.
        user_data: A tuple containing (RTStruct SOPInstanceUID, ROI number).
    """
    tag_colorpicker = get_tag("color_picker_popup")
    safe_delete(tag_colorpicker)
    
    rts_sopiuid, roi_number = user_data
    data_mgr: DataManager = get_user_data("data_manager")
    
    is_templated = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "use_template_name", False)
    if is_templated:
        roi_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROITemplateName", "-MISSING-")
    else:
        roi_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIName", "-MISSING-")
    
    current_color = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIDisplayColor")
    
    mouse_pos = dpg.get_mouse_pos(local=False)
    with dpg.window(
        tag=tag_colorpicker, 
        label=f"Choose Color For ROI #{roi_number}: {roi_name}", 
        popup=True, 
        pos=mouse_pos, 
    ):
        dpg.add_color_picker(
            default_value=current_color, 
            callback=_update_roi_color, 
            no_alpha=True, 
            user_data=(sender, rts_sopiuid, roi_number), 
            display_rgb=True
        )
        dpg.add_button(label="Close", callback=lambda: safe_delete(tag_colorpicker))


def _update_roi_color(sender: Union[str, int], app_data: List[float], user_data: Tuple[Any, str, int]) -> None:
    """
    Update the ROI color based on the selection in the color picker.

    Args:
        sender: The color picker tag.
        app_data: List of RGB values (floats).
        user_data: Tuple containing (ROI color button tag, RTStruct SOPInstanceUID, ROI number).
    """
    new_color_floats = app_data[:3]
    tag_colorbutton, rts_sopiuid, roi_number = user_data
    
    new_color = [round(min(max(255 * color, 0), 255)) for color in new_color_floats]
    data_mgr: DataManager = get_user_data("data_manager")
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIDisplayColor", new_color)
    dpg.bind_item_theme(item=tag_colorbutton, theme=get_colored_button_theme(new_color))
    request_texture_update(texture_action_type="update")


def _update_views_roi_center(sender: Union[str, int], app_data: Any, user_data: Union[str, int]) -> None:
    """
    Center the displayed views on the center of the ROI.

    Args:
        sender: The event handler tag.
        app_data: Additional event data.
        user_data: The tag of the ROI checkbox.
    """
    roi_cbox_tag, rts_sopiuid, roi_number = user_data
    data_mgr: DataManager = get_user_data("data_manager")
    img_tags = get_tag("img_tags")
    
    any_data_active_before = data_mgr.return_is_any_data_active()
    dpg.set_value(roi_cbox_tag, True)
    
    roi_center = data_mgr.get_roi_center_of_mass_by_uid(rts_sopiuid, roi_number)
    roi_extents = data_mgr.get_roi_extent_ranges_by_uid(rts_sopiuid, roi_number)
    
    any_data_active_after = data_mgr.return_is_any_data_active()
    if not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
        sleep(1/10) # Wait to ensure the callback has time to update state
    
    if not roi_center or not roi_extents:
        logger.warning(f"Cannot center views on ROI #{roi_number} as it has no center of mass. Center: {roi_center}, Extents: {roi_extents}")
        return
    
    # Modify the current view limits to display the ROI
    zoom_out = 1.05
    for i, dim_tag in enumerate([img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]):
        config = dpg.get_item_configuration(dim_tag)
        limit_min, limit_max = config["min_value"], config["max_value"]
        curr_range = tuple(dpg.get_value(dim_tag)[:2])
        roi_min, roi_max = roi_extents[i]
        # Do not allow values below limit min, and take the smallest of the three values: current min, roi min - 5% of limit size, limit max - 10% of limit size
        new_min = max(
            min(
                curr_range[0], 
                round(roi_min - (zoom_out * (limit_max - limit_min) / 2)), 
                round(limit_max - (limit_max - limit_min) * 0.10)
            ), 
            limit_min
        )
        # Do not allow values above limit max, and take the largest of the three values: current max, roi max + 5% of limit size, new min + 10% of limit size
        new_max = min(
            max(
                curr_range[1], 
                round(roi_max + (zoom_out * (limit_max - limit_min) / 2)), 
                round(new_min + (limit_max - limit_min) * 0.10)
            ), 
            limit_max
        )
        dpg.set_value(dim_tag, [new_min, new_max])
    dpg.set_value(img_tags["viewed_slices"], roi_center)
    request_texture_update(texture_action_type="update")
