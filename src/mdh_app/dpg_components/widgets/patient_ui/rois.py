from __future__ import annotations


import re
import logging
from typing import TYPE_CHECKING, Tuple, Any, Union, List, Callable, Optional
from time import sleep


import dearpygui.dearpygui as dpg
import SimpleITK as sitk


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme, get_colored_button_theme
from mdh_app.dpg_components.windows.confirmation.confirm_window import create_confirmation_popup
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params
from mdh_app.utils.general_utils import (
    find_disease_site, find_reformatted_mask_name, verify_roi_goals_format, regex_find_dose_and_fractions
)
from mdh_app.utils.sitk_utils import get_sitk_roi_display_color


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def _update_rts_roi_button_and_tooltip(tag_roi_button: Union[str, int]) -> None:
    """
    Update the tooltip and label for an ROI button in an RT Structure Set.

    Args:
        tag_roi_button: The button tag.
    """
    rts_sopiuid, roi_sitk_ref, tag_roi_tooltip = dpg.get_item_user_data(tag_roi_button)
    size_dict = get_user_data(td_key="size_dict")
    safe_delete(tag_roi_tooltip)
    keys_to_get = [
        "roi_number", "original_roi_name", "current_roi_name", 
        "rt_roi_interpreted_type", "roi_goals", "roi_physical_properties"
    ]
    
    roi_number = roi_sitk_ref().GetMetaData("roi_number") if roi_sitk_ref().HasMetaDataKey("roi_number") else "n/a"
    roi_curr_name = roi_sitk_ref().GetMetaData("current_roi_name") if roi_sitk_ref().HasMetaDataKey("current_roi_name") else "n/a"
    
    with dpg.tooltip(tag=tag_roi_tooltip, parent=tag_roi_button):
        dpg.add_text(f"ROI #{roi_number}: {roi_curr_name}", wrap=size_dict["tooltip_width"])
        for key in keys_to_get:
            value = roi_sitk_ref().GetMetaData(key) if roi_sitk_ref().HasMetaDataKey(key) else "n/a"
            dpg.add_text(f"{key}: {value}", wrap=size_dict["tooltip_width"])
    
    dpg.set_item_label(tag_roi_button, roi_curr_name)


def _popup_inspect_roi(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """
    Open a popup window to display and allow modification of individual ROI attributes.

    The SITK ROI MetaData includes:
      original_roi_name, current_roi_name, roi_number, roi_display_color, rt_roi_interpreted_type,
      roi_physical_properties, material_id, roi_goals, roi_rx_dose, roi_rx_fractions, roi_rx_site.

    Args:
        sender: The tag of the button that triggered the popup.
        app_data: Additional event data.
        user_data: Tuple containing (RT Struct SOPInstanceUID, ROI SITK reference, tooltip tag).
    """
    tag_inspect = get_tag("inspect_sitk_popup")
    size_dict = get_user_data(td_key="size_dict")
    conf_mgr: ConfigManager = get_user_data("config_manager")
    
    safe_delete(tag_inspect)
    
    tag_roi_button = sender
    rts_sopiuid, roi_sitk_ref, tag_roi_tooltip = user_data
    
    # Helper function to get metadata with default values and casting
    def get_metadata(
        roi_sitk_ref: Callable[[], Optional[sitk.Image]],
        key: str,
        default: Any = None,
        cast_func: Optional[Callable[[str], Any]] = None
    ) -> Any:
        """
        Retrieve ROI metadata with an optional default and type casting.

        Args:
            roi_sitk_ref: A callable returning the ROI SimpleITK image.
            key: Metadata key.
            default: Default value if key is missing.
            cast_func: Function to cast the value.

        Returns:
            The metadata value (casted if applicable) or the default.
        """
        roi_img = roi_sitk_ref()
        if roi_img is None:
            return default
        if roi_img.HasMetaDataKey(key):
            value = roi_img.GetMetaData(key)
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
    roi_color = [x for x in get_sitk_roi_display_color(roi_sitk_ref())][:3]
    
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
    name_options = ["Match by Templated ROI Name", "Set Custom ROI Name"]
    if any(current_roi_name == x for x in tg_263_oar_names_list):
        default_option = "Match by Templated ROI Name"
        templated_roi_name = current_roi_name
    else:
        default_option = "Set Custom ROI Name"
        templated_roi_name = find_reformatted_mask_name(original_roi_name, rt_roi_interpreted_type, tg_263_oar_names_list, organ_name_matching_dict, unmatched_organ_name)
        
    # Callback to update SITK metadata
    def update_roi_metadata(sender: Any, app_data: Any, user_data: Tuple[Any, str]) -> None:
        """
        Update ROI metadata from user input.

        Args:
            sender: The input field tag.
            app_data: The new value.
            user_data: Tuple containing (ROI SITK reference, metadata key).
        """
        roi_ref, meta_key = user_data
        roi_img = roi_ref()
        if roi_img is None:
            return
        roi_img.SetMetaData(meta_key, str(app_data))
        _update_new_roi_name(roi_ref, tag_roi_button, tag_roi_tooltip, tag_inspect)
        _update_rts_roi_button_and_tooltip(tag_roi_button)
        logger.info(f"Updated ROI metadata [{meta_key}] = {app_data}")
    
    # Callback to update DPG & SITK for name selection change
    def on_name_option_change(sender: Any, app_data: str, user_data: Any) -> None:
        """
        Handle changes to ROI naming options, toggling between templated and custom inputs.

        Args:
            sender: The radio button tag.
            app_data: The selected naming option.
            user_data: Additional data (unused).
        """
        use_templated = app_data == "Match by Templated ROI Name"
        dpg.configure_item(custom_name_row_tag, show=not use_templated)
        dpg.configure_item(templated_name_row_tag, show=use_templated)
        dpg.configure_item(templated_filter_row_tag, show=use_templated)
        new_name = dpg.get_value(templated_name_input_tag) if use_templated else dpg.get_value(custom_name_input_tag)
        on_name_change(None, new_name, None)
    
    # Callback to update SITK when name changes
    def on_name_change(sender: Any, app_data: str, user_data: Any) -> None:
        """
        Update the current ROI name based on user input.

        Args:
            sender: The tag of the ROI name input field.
            app_data: The new ROI name.
            user_data: Additional data (unused).
        """
        new_name = str(app_data)
        is_ptv = "ptv" in new_name.lower()
        for ptv_tag in [ptv_dose_row_tag, ptv_fractions_row_tag, ptv_site_row_tag]:
            if dpg.does_item_exist(ptv_tag):
                dpg.configure_item(ptv_tag, show=is_ptv)
        update_roi_metadata(None, new_name, (roi_sitk_ref, "current_roi_name"))
    
    # Callback function to filter the templated ROI names based on user input
    def on_roi_template_filter(sender: Any, app_data: str, user_data: Any) -> None:
        """
        Filter templated ROI names based on user input.

        Args:
            sender: The filter input field tag.
            app_data: The filter text.
            user_data: Additional data (unused).
        """
        filter_text = app_data.lower()
        templated_items = conf_mgr.get_tg_263_names(ready_for_dpg=True)
        filtered = [item for item in templated_items if filter_text in item.lower()]
        dpg.configure_item(templated_name_input_tag, items=filtered)
    
    def verify_roi_goal_input(sender: Any, app_data: str, user_data: Tuple[Any, Any, Any]) -> None:
        """
        Validate ROI goal input and update metadata if valid.

        Args:
            sender: The input field tag.
            app_data: The ROI goal input string.
            user_data: Tuple containing (ROI SITK reference, ROI button tag, error message tag).
        """
        roi_ref, tag_roi_btn, tag_goal_text = user_data
        roi_goals_str = app_data
        popup_width = dpg.get_item_width(get_tag("inspect_sitk_popup"))
        is_valid, errors = verify_roi_goals_format(roi_goals_str)
        if is_valid:
            update_roi_metadata(None, roi_goals_str, (roi_sitk_ref, "roi_goals"))
            dpg.configure_item(tag_goal_text, color=(39, 174, 96), wrap=round(popup_width * 0.9))
            dpg.set_value(tag_goal_text, "ROI Goal Input is valid and saved!")
        else:
            dpg.configure_item(tag_goal_text, color=(192, 57, 43), wrap=round(popup_width * 0.9))
            dpg.set_value(tag_goal_text, f"ROI Goal Input is invalid and will not be saved! Issues:\n{errors}")
    
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
                    callback=on_name_option_change
                )
            
            # Templated name input (combo box)
            with dpg.table_row(tag=templated_name_row_tag, show=(default_option == "Match by Templated ROI Name")):
                dpg.add_text("Templated Name:")
                dpg.add_combo(
                    tag=templated_name_input_tag, 
                    items=tg_263_oar_names_list, 
                    default_value=templated_roi_name, 
                    callback=on_name_change
                )
            
            # Templated combo box filter
            with dpg.table_row(tag=templated_filter_row_tag, show=(default_option == "Match by Templated ROI Name")):
                dpg.add_text("Template Filter:")
                dpg.add_input_text(callback=on_roi_template_filter)

            # Custom name input
            with dpg.table_row(tag=custom_name_row_tag, show=(default_option == "Set Custom ROI Name")):
                dpg.add_text("Custom Name:")
                dpg.add_input_text(
                    tag=custom_name_input_tag, 
                    default_value=current_roi_name or "", 
                    callback=on_name_change
                )
            
            # PTV-specific input fields
            is_ptv = "ptv" in current_roi_name.lower()
            with dpg.table_row(tag=ptv_dose_row_tag, show=is_ptv):
                dpg.add_text("PTV Rx Dose (cGy):")
                dpg.add_input_int(
                    tag=rx_dose_input_tag, 
                    default_value=roi_rx_dose, 
                    callback=update_roi_metadata, 
                    user_data=(roi_sitk_ref, "roi_rx_dose")
                )
            with dpg.table_row(tag=ptv_fractions_row_tag, show=is_ptv):
                dpg.add_text("PTV Rx Fractions:")
                dpg.add_input_int(
                    tag=rx_fractions_input_tag, 
                    default_value=roi_rx_fractions,
                    callback=update_roi_metadata, 
                    user_data=(roi_sitk_ref, "roi_rx_fractions")
                )
            with dpg.table_row(tag=ptv_site_row_tag, show=is_ptv):
                dpg.add_text("PTV Disease Site:")
                dpg.add_combo(
                    tag=rx_site_input_tag, 
                    items=disease_site_list, 
                    default_value=roi_rx_site or disease_site_list[0], 
                    callback=update_roi_metadata, 
                    user_data=(roi_sitk_ref, "roi_rx_site")
                )
            
            # Goals input field
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("ROI Goals must be a dictionary that meet the rules described below.", wrap=size_dict["tooltip_width"])
                    dpg.add_text("ROI Goals:")
                dpg.add_input_text(
                    default_value=roi_goals, 
                    callback=verify_roi_goal_input, 
                    user_data=(roi_sitk_ref, tag_roi_button, tag_goalerrortext)
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
                    default_value=roi_color, 
                    size=len(roi_color), 
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
                dpg.add_text("Physical Properties:")
                dpg.add_input_text(default_value=roi_physical_properties, readonly=True)
            with dpg.table_row():
                dpg.add_text("Material ID:")
                dpg.add_input_text(default_value=material_id, readonly=True)


def _remove_roi(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any, Any]) -> None:
    """
    Remove an ROI after user confirmation.

    Args:
        sender: The button tag that triggered removal.
        app_data: Additional event data.
        user_data: Tuple containing (ROI identifier keys, ROI group tag, checkbox tag).
    """
    keys, tag_group_roi, tag_checkbox = user_data
    
    def on_confirm(sender, app_data, user_data) -> None:
        if dpg.get_value(tag_checkbox):
            dpg.set_value(tag_checkbox, False)
            cb_callback = dpg.get_item_callback(tag_checkbox)
            if cb_callback:
                cb_callback(tag_checkbox, False, keys)
        safe_delete(tag_group_roi)
        data_mgr: DataManager = get_user_data(td_key="data_manager")
        data_mgr.remove_sitk_roi_from_rtstruct(keys)
        logger.info(f"Removed ROI with keys: {keys}")
    
    # Create the confirmation popup before performing the removal
    create_confirmation_popup(
        button_callback=on_confirm,
        button_theme=get_hidden_button_theme(),
        warning_string=f"Proceeding will remove this ROI from the current structure set. Continue?"
    )


def _update_new_roi_name(
    roi_sitk_ref: Callable[[], Optional[sitk.Image]],
    tag_roi_button: Optional[Union[str, int]] = None,
    tag_roitooltiptext: Optional[Union[str, int]] = None,
    tag_sitkwindow: Optional[Union[str, int]] = None
) -> None:
    """
    Update the current ROI name and adjust related metadata.

    Args:
        roi_sitk_ref: Callable returning the ROI SimpleITK image.
        tag_roi_button: Optional tag of the ROI button.
        tag_roitooltiptext: Optional tag of the ROI tooltip.
        tag_sitkwindow: Optional tag of the ROI inspection window.
    """
    roi_sitk = roi_sitk_ref()
    if roi_sitk is None:
        return
    
    def process_roi_name_update(roi_img: sitk.Image, final_name: str) -> None:
        roi_img.SetMetaData("current_roi_name", final_name)
        lower_name = final_name.lower()
        if lower_name == "external":
            roi_img.SetMetaData("rt_roi_interpreted_type", "EXTERNAL")
        elif "ptv" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "PTV")
        elif "ctv" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "CTV")
        elif "gtv" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "GTV")
        elif "cavity" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "CAVITY")
        elif "bolus" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "BOLUS")
        elif "isocenter" in lower_name:
            roi_img.SetMetaData("rt_roi_interpreted_type", "ISOCENTER")
        elif any(x in lower_name for x in ["couch", "support", "data_table", "rail", "bridge", "mattress", "frame"]):
            roi_img.SetMetaData("rt_roi_interpreted_type", "SUPPORT")
        else:
            roi_img.SetMetaData("rt_roi_interpreted_type", "OAR")
        roi_number = int(roi_img.GetMetaData("roi_number"))
        new_text = f"ROI #{roi_number}: {final_name}"
        if tag_roi_button and dpg.does_item_exist(tag_roi_button):
            dpg.configure_item(tag_roi_button, label=new_text)
        if tag_sitkwindow and dpg.does_item_exist(tag_sitkwindow):
            dpg.configure_item(tag_sitkwindow, label=new_text)
        if tag_roitooltiptext and dpg.does_item_exist(tag_roitooltiptext):
            dpg.set_value(tag_roitooltiptext, f"\tCurrent Name: {final_name}")
    
    conf_mgr: ConfigManager = get_user_data("config_manager")
    disease_site_list_base = conf_mgr.get_disease_sites(ready_for_dpg=True)[0]
    unmatched_organ_name = conf_mgr.get_unmatched_organ_name()
    
    current_roi_name = roi_sitk.GetMetaData("current_roi_name")
    original_roi_name = roi_sitk.GetMetaData("original_roi_name")
    
    # Skip if the current_roi_name is the default value
    if current_roi_name == "SELECT_MASK_NAME":
        process_roi_name_update(roi_sitk, unmatched_organ_name)
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


def _popup_roi_color_picker(sender: Union[str, int], app_data: Any, user_data: Callable[[], Optional[sitk.Image]]) -> None:
    """
    Open a popup to choose a new ROI color.

    Args:
        sender: The tag of the button triggering the color picker.
        app_data: Additional event data.
        user_data: A callable returning the ROI SITK reference.
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
            user_data=(sender, roi_sitk_ref), 
            display_rgb=True
        )
        dpg.add_button(label="Close", callback=lambda: safe_delete(tag_colorpicker))


def _update_roi_color(sender: Union[str, int], app_data: List[float], user_data: Tuple[Any, Callable[[], Optional[sitk.Image]]]) -> None:
    """
    Update the ROI color based on the selection in the color picker.

    Args:
        sender: The color picker tag.
        app_data: List of RGB values (floats).
        user_data: Tuple containing the color button tag and ROI SITK reference.
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


def _update_views_roi_center(sender: Union[str, int], app_data: Any, user_data: Union[str, int]) -> None:
    """
    Center the displayed views on the center of the ROI.

    Args:
        sender: The event handler tag.
        app_data: Additional event data.
        user_data: The tag of the ROI checkbox.
    """
    tag_checkbox = user_data
    keys_or_handle = dpg.get_item_user_data(tag_checkbox)
    data_mgr: DataManager = get_user_data("data_manager")
    img_tags = get_tag("img_tags")
    
    any_data_active_before = data_mgr.return_is_any_data_active()
    dpg.set_value(tag_checkbox, True)
    
    # Check if we have a handle or legacy keys
    from mdh_app.managers.data_manager import DataHandle
    if isinstance(keys_or_handle, DataHandle):
        # Use handle-based system
        handle = keys_or_handle
        data_mgr.update_active_data_with_handle(handle, True)
        roi_center = handle.get_center_of_mass()
        roi_extents = handle.get_extent_ranges()
    else:
        # Use legacy system
        keys = keys_or_handle
        data_mgr.update_active_data(True, keys)
        roi_center = data_mgr.return_npy_center_of_mass(keys)
        roi_extents = data_mgr.return_npy_extent_ranges(keys)
    
    any_data_active_after = data_mgr.return_is_any_data_active()
    
    if not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
        sleep(1/10) # Wait to ensure the callback has time to update state
    
    if not roi_center or not roi_extents:
        roi_identifier = handle.identifier if isinstance(keys_or_handle, DataHandle) else str(keys_or_handle[-1]) 
        logger.info(f"ROI '{roi_identifier}' has no center of mass or extents. Center: {roi_center}, Extents: {roi_extents}")
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
