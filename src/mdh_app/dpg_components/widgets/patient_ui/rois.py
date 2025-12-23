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


### ROI POPUP ###


def show_roi_configuration_popup(sender: Union[str, int], app_data: Any, user_data: Tuple[str, int]) -> None:
    """Display the ROI configuration popup window."""
    roi_button_tag = sender
    rts_sopiuid, roi_number = user_data

    _create_roi_configuration_popup(roi_button_tag, rts_sopiuid, roi_number)


def _create_roi_configuration_popup(roi_button_tag: Union[str, int], rts_sopiuid: str, roi_number: int) -> None:
    """Create and display the ROI configuration popup window."""
    popup_tag = get_tag("inspect_data_popup")
    size_dict = get_user_data(td_key="size_dict")
    conf_mgr: ConfigManager = get_user_data("config_manager")
    data_mgr: DataManager = get_user_data("data_manager")

    # Get configuration data
    available_templates = conf_mgr.get_tg_263_names(ready_for_dpg=True)
    disease_sites = conf_mgr.get_disease_sites(ready_for_dpg=True)

    safe_delete(popup_tag)

    # Get current ROI metadata
    original_dicom_name = data_mgr.get_rtstruct_roi_ds_value_by_uid(rts_sopiuid, roi_number, "ROIName", "Unknown")
    roi_metadata = data_mgr.get_roi_gui_metadata_by_uid(rts_sopiuid, roi_number)

    display_name = roi_metadata.get("display_name", "Unknown")
    base_template_name = roi_metadata.get("base_template_name", display_name)
    is_template_based = roi_metadata.get("is_template_based", False)
    custom_suffix = roi_metadata.get("custom_suffix", "")
    roi_display_color = roi_metadata.get("ROIDisplayColor", [random.randint(0, 255) for _ in range(3)])
    rt_roi_interpreted_type = roi_metadata.get("RTROIInterpretedType", "CONTROL")
    roi_phys_prop_value = roi_metadata.get("ROIPhysicalPropertyValue", None)
    roi_goals = roi_metadata.get("roi_goals", {})
    roi_rx_dose = roi_metadata.get("roi_rx_dose", None)
    roi_rx_fractions = roi_metadata.get("roi_rx_fractions", None)
    roi_rx_site = roi_metadata.get("roi_rx_site", None)

    popup_width, popup_height, popup_pos = get_popup_params()

    # Generate unique tags for UI elements
    naming_mode_tag = dpg.generate_uuid()
    custom_name_row = dpg.generate_uuid()
    custom_name_input = dpg.generate_uuid()
    template_name_row = dpg.generate_uuid()
    template_filter_row = dpg.generate_uuid()
    template_combo = dpg.generate_uuid()
    ptv_dose_row = dpg.generate_uuid()
    ptv_fractions_row = dpg.generate_uuid()
    ptv_site_row = dpg.generate_uuid()
    validation_message_tag = dpg.generate_uuid()

    # Naming mode configuration
    template_mode_label = "Template-Based Naming"
    custom_mode_label = "Custom Naming"
    naming_modes = [template_mode_label, custom_mode_label]
    default_mode = template_mode_label if is_template_based else custom_mode_label

    with dpg.window(
        tag=popup_tag,
        label="ROI Configuration",
        width=popup_width,
        height=popup_height,
        pos=popup_pos,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_open_over_existing_popup=False
    ):
        # Configuration Section
        add_custom_button(label="ROI Display Name Configuration", theme_tag=get_hidden_button_theme(), add_separator_after=True)

        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)

            # Naming mode selection
            with dpg.table_row():
                dpg.add_text("Naming Mode:")
                dpg.add_radio_button(
                    tag=naming_mode_tag,
                    items=naming_modes,
                    default_value=default_mode,
                    callback=_on_naming_mode_changed,
                    user_data=(
                        template_mode_label, rts_sopiuid, roi_number,
                        custom_name_row, template_name_row, template_filter_row,
                        ptv_dose_row, ptv_fractions_row, ptv_site_row
                    )
                )

            # Template selection
            with dpg.table_row(tag=template_name_row, show=(default_mode == template_mode_label)):
                dpg.add_text("Base Template:")
                dpg.add_combo(
                    tag=template_combo,
                    items=available_templates,
                    default_value=base_template_name,
                    callback=_on_template_selected,
                    user_data=(roi_button_tag, ptv_dose_row, ptv_fractions_row, ptv_site_row)
                )

            # Template filter
            with dpg.table_row(tag=template_filter_row, show=(default_mode == template_mode_label)):
                dpg.add_text("Template Filter:")
                dpg.add_input_text(
                    callback=_on_template_filter_changed,
                    user_data=template_combo
                )

            # Custom name input
            with dpg.table_row(tag=custom_name_row, show=(default_mode == custom_mode_label)):
                dpg.add_text("Display Name:")
                dpg.add_input_text(
                    tag=custom_name_input,
                    default_value=display_name,
                    callback=_on_custom_name_changed,
                    user_data=(roi_button_tag, ptv_dose_row, ptv_fractions_row, ptv_site_row)
                )

            # PTV-specific parameters
            is_ptv = "ptv" in display_name.lower()

            with dpg.table_row(tag=ptv_dose_row, show=is_ptv):
                dpg.add_text("PTV Rx Dose (cGy):")
                dpg.add_input_int(
                    default_value=int(roi_rx_dose) if isinstance(roi_rx_dose, int) else 0,
                    callback=_on_ptv_parameter_changed,
                    user_data=(roi_button_tag, "roi_rx_dose")
                )

            with dpg.table_row(tag=ptv_fractions_row, show=is_ptv):
                dpg.add_text("PTV Rx Fractions:")
                dpg.add_input_int(
                    default_value=int(roi_rx_fractions) if isinstance(roi_rx_fractions, int) else 0,
                    callback=_on_ptv_parameter_changed,
                    user_data=(roi_button_tag, "roi_rx_fractions")
                )

            with dpg.table_row(tag=ptv_site_row, show=is_ptv):
                dpg.add_text("PTV Disease Site:")
                dpg.add_combo(
                    items=disease_sites,
                    default_value=roi_rx_site or disease_sites[0],
                    callback=_on_ptv_parameter_changed,
                    user_data=(roi_button_tag, "roi_rx_site")
                )

        # ROI Goals
        add_custom_button(label="ROI Goals Configuration", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)
            
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    dpg.add_text("ROI Goals:")
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text("ROI Goals must be a valid JSON dictionary format.", wrap=size_dict["tooltip_width"])
                dpg.add_input_text(
                    default_value=dumps(roi_goals) if roi_goals else "",
                    callback=_on_roi_goals_changed,
                    user_data=(roi_button_tag, validation_message_tag)
                )

            # Validation message
            with dpg.table_row():
                dpg.add_text()
                dpg.add_text(tag=validation_message_tag, default_value="", color=(192, 57, 43), wrap=round(popup_width * 0.9))
        
        # Goals documentation
        add_custom_button(label="Formatting Rules for ROI Goals", theme_tag=get_hidden_button_theme(), add_spacer_before=True, add_spacer_after=True)
        dpg.add_text(
            wrap=round(popup_width * 0.9),
            default_value=(
                "ROI GOAL FORMAT - Dictionary with metric keys and constraint values\n"
                "\n"
                "KEY FORMAT: {metric}_{value}_{unit}\n"
                "------------------------------------\n"
                "\t- metric: The dose metric type (V, D, DC, CV, CI, MAX, MEAN, MIN)\n"
                "\t- value: Number (integer or float)\n"
                "\t- unit: Dose unit (cGy, Gy, %) or volume unit (%, cc)\n"
                "\n"
                "VALUE FORMAT: List of constraint strings\n"
                "-----------------------------------------\n"
                "\t- Pattern: \"{operator}_{threshold}_{unit}\"\n"
                "\t- Operators: >, >=, <, <=, =\n"
                "\t- Exception: CI uses threshold only (no operator/unit)\n"
                "\n"
                "METRIC-SPECIFIC REQUIREMENTS\n"
                "-----------------------------\n"
                "\n"
                "V (Volume receiving dose):\n"
                "\t- Key: dose value (cGy or %), e.g., \"V_5000_cGy\"\n"
                "\t- Value: volume threshold (% or cc), e.g., [\"<_20_%\"]\n"
                "\n"
                "D (Dose to volume):\n"
                "\t- Key: volume value (% or cc), e.g., \"D_95_%\"\n"
                "\t- Value: dose threshold (cGy or %), e.g., [\">_6000_cGy\"]\n"
                "\n"
                "DC (Dose complement at volume):\n"
                "\t- Key: volume value (% or cc), e.g., \"DC_98_%\"\n"
                "\t- Value: dose threshold (cGy or %), e.g., [\">_5400_cGy\"]\n"
                "\n"
                "CV (Complement volume):\n"
                "\t- Key: dose value (must be cGy), e.g., \"CV_2000_cGy\"\n"
                "\t- Value: volume threshold (% or cc), e.g., [\">_30_cc\"]\n"
                "\n"
                "CI (Conformity Index):\n"
                "\t- Key: reference dose (must be cGy), e.g., \"CI_5000_cGy\"\n"
                "\t- Value: index value only (no operator/unit), e.g., [\"1.2\"]\n"
                "\n"
                "MAX/MEAN/MIN (Dose statistics):\n"
                "\t- Key: metric name only, e.g., \"MAX\"\n"
                "\t- Value: dose threshold (cGy or %), e.g., [\"<_7420_cGy\"]\n"
                "\n"
                "COMPLETE EXAMPLE\n"
                "----------------\n"
                "{\n"
                "\t\"V_7000_cGy\": [\">_95_%\"],\t\t\t# >95% volume gets 7000 cGy\n"
                "\t\"D_95_%\": [\">_6000_cGy\"],\t\t\t# 95% volume gets >6000 cGy\n"
                "\t\"MAX\": [\"<_7420_cGy\"],\t\t\t\t  # Max dose <7420 cGy\n"
                "\t\"CI_5000_cGy\": [\"1.25\"],\t\t\t\t  # Conformity index at 5000 cGy is 1.25\n"
                "\t\"CV_2000_cGy\": [\">_10_cc\"],\t\t# >10cc volume is spared from 2000 cGy\n"
                "\t\"DC_2_%\": [\">_5400_cGy\"]\t\t\t # The min dose covering 98% volume is >5400 cGy\n"
                "}"
            )
        )

        # Read-only information
        add_custom_button(label="Read-Only Information", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_spacer_after=True)
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.4)
            dpg.add_table_column(init_width_or_weight=0.6)

            with dpg.table_row():
                dpg.add_text("Original DICOM Name:")
                dpg.add_input_text(default_value=original_dicom_name, readonly=True)

            with dpg.table_row():
                dpg.add_text("ROI Number:")
                dpg.add_input_int(default_value=roi_number, readonly=True)

            with dpg.table_row():
                dpg.add_text("Current Display Name:")
                dpg.add_input_text(default_value=display_name, readonly=True)

            if is_template_based:
                with dpg.table_row():
                    dpg.add_text("Base Template:")
                    dpg.add_input_text(default_value=base_template_name, readonly=True)

                if custom_suffix:
                    with dpg.table_row():
                        dpg.add_text("Customization:")
                        dpg.add_input_text(default_value=custom_suffix, readonly=True)

            with dpg.table_row():
                dpg.add_text("Interpreted Type:")
                dpg.add_input_text(default_value=rt_roi_interpreted_type, readonly=True)

            with dpg.table_row():
                dpg.add_text("Display Color (RGB):")
                dpg.add_input_intx(
                    default_value=roi_display_color,
                    size=3,
                    readonly=True,
                    min_value=0,
                    max_value=255,
                    min_clamped=True,
                    max_clamped=True
                )

            with dpg.table_row():
                dpg.add_text("Relative Electron Density (RED) Override Value:")
                dpg.add_input_text(
                    default_value=str(roi_phys_prop_value) if roi_phys_prop_value is not None else "N/A",
                    readonly=True
                )


def update_roi_display_and_tooltip(roi_button_tag: Union[str, int]) -> None:
    """Update ROI button label and tooltip with current metadata."""
    if not dpg.does_item_exist(roi_button_tag):
        return

    data_mgr: DataManager = get_user_data("data_manager")
    rts_sopiuid, roi_number = dpg.get_item_user_data(roi_button_tag)
    tooltip_tag = f"{roi_button_tag}_tooltiptext"

    # Get current ROI metadata
    roi_metadata = data_mgr.get_roi_gui_metadata_by_uid(rts_sopiuid, roi_number)
    original_roi_name = roi_metadata.get("ROIName", "UnknownStruct")
    display_name = roi_metadata.get("display_name", "UnknownStruct")
    base_template_name = roi_metadata.get("base_template_name", None)
    is_template_based = roi_metadata.get("is_template_based", False)
    custom_suffix = roi_metadata.get("custom_suffix", "")
    rt_roi_interpreted_type = roi_metadata.get("RTROIInterpretedType", "CONTROL")
    roi_phys_prop_value = roi_metadata.get("ROIPhysicalPropertyValue", None)
    roi_goals = roi_metadata.get("roi_goals", {})
    roi_rx_dose = roi_metadata.get("roi_rx_dose", None)
    roi_rx_fractions = roi_metadata.get("roi_rx_fractions", None)
    roi_rx_site = roi_metadata.get("roi_rx_site", None)

    if is_template_based and rt_roi_interpreted_type == "PTV":
        display_name = base_template_name if base_template_name else "PTV"
        display_name += f"_{roi_rx_site}" if roi_rx_site is not None else "_NoSite"
        display_name += f"_{roi_rx_dose}" if roi_rx_dose is not None and roi_rx_dose > 0 else "_NoDose"
        display_name += f"_{roi_rx_fractions}" if roi_rx_fractions is not None and roi_rx_fractions > 0 else "_NoFxn"
    
    # Update button label
    dpg.set_item_label(roi_button_tag, f"ROI #{roi_number}: {display_name}")

    # Build comprehensive tooltip
    tooltip_text = f"ROI #{roi_number}: {display_name}\nOriginal ROI Name: {original_roi_name}\n"

    if is_template_based and original_roi_name != display_name:
        tooltip_text += f"Templated Name: {base_template_name}"
        if custom_suffix:
            tooltip_text += f" (customized: {custom_suffix})"
        tooltip_text += "\n"

    tooltip_text += (
        f"Type: {rt_roi_interpreted_type}\n"
        f"Relative Electron Density (RED) Override Value: {roi_phys_prop_value if roi_phys_prop_value is not None else 'N/A'}\n"
        f"Goals: {roi_goals if roi_goals else 'N/A'}"
    )

    if rt_roi_interpreted_type == "PTV":
        tooltip_text += f"\nRx Dose: {roi_rx_dose or 'N/A'} cGy"
        tooltip_text += f"\nRx Fractions: {roi_rx_fractions or 'N/A'}"
        tooltip_text += f"\nRx Site: {roi_rx_site or 'N/A'}"

    dpg.set_value(tooltip_tag, tooltip_text)


### ROI NAMING LOGIC ###


def _infer_roi_type_from_name(display_name: str) -> str:
    """Determine ROI interpreted type based on display name patterns."""
    name_lower = display_name.strip().lower()

    type_mapping = {
        "external": "EXTERNAL",
        "ptv": "PTV",
        "ctv": "CTV",
        "gtv": "GTV",
        "cavity": "CAVITY",
        "bolus": "BOLUS",
        "isocenter": "ISOCENTER"
    }

    # Check exact matches first
    if name_lower in type_mapping:
        return type_mapping[name_lower]

    # Check partial matches
    for keyword, roi_type in type_mapping.items():
        if keyword in name_lower:
            return roi_type

    # Check for support structures
    support_keywords = ["couch", "support", "data_table", "rail", "bridge", "mattress", "frame"]
    if any(keyword in name_lower for keyword in support_keywords):
        return "SUPPORT"

    return "OAR"


def _auto_populate_ptv_data_from_dicom(rts_sopiuid: str, roi_number: int) -> None:
    """Extract and populate PTV parameters from original DICOM ROI name."""
    data_mgr: DataManager = get_user_data("data_manager")

    # Get original DICOM name for parsing
    original_roi_name = data_mgr.get_rtstruct_roi_ds_value_by_uid(rts_sopiuid, roi_number, "ROIName", "")
    dose_fx_info = regex_find_dose_and_fractions(original_roi_name)

    # Auto-populate dose if available and not already set
    current_dose = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_dose", None)
    if not isinstance(current_dose, int) and dose_fx_info.get("dose"):
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_dose", int(dose_fx_info["dose"]))

    # Auto-populate fractions if available and not already set
    current_fractions = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_fractions", None)
    if not isinstance(current_fractions, int) and dose_fx_info.get("fractions"):
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_fractions", int(dose_fx_info["fractions"]))

    # Auto-populate disease site if not already set
    current_site = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_site", None)
    if not current_site:
        current_display_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", "")
        found_site = find_disease_site(None, None, [current_display_name, original_roi_name])

        cfg_mgr: ConfigManager = get_user_data("config_manager")
        default_site = cfg_mgr.get_disease_sites(ready_for_dpg=True)[0]

        if found_site and found_site != default_site:
            data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_site", found_site)


def _build_template_display_name(rts_sopiuid: str, roi_number: int) -> str:
    """Construct display name from base template and PTV customization parameters."""
    data_mgr: DataManager = get_user_data("data_manager")

    base_template = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "base_template_name", "")
    is_template_based = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "is_template_based", False)

    if not is_template_based or not base_template:
        return data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", "UnknownStruct")

    # Start with base template name
    display_name = base_template
    customization_parts = []

    # Add PTV-specific customizations
    if "ptv" in base_template.lower():
        site = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_site", None)
        dose = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_dose", None)
        fractions = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_rx_fractions", None)

        if site:
            customization_parts.append(site)
        if isinstance(dose, int):
            customization_parts.append(str(dose))
        if isinstance(fractions, int):
            customization_parts.append(str(fractions))

    # Build final display name with customizations
    if customization_parts:
        custom_suffix = "_" + "_".join(customization_parts)
        display_name = base_template + custom_suffix
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "custom_suffix", custom_suffix)
    else:
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "custom_suffix", "")

    return display_name


def _update_roi_derived_metadata(rts_sopiuid: str, roi_number: int) -> None:
    """Update all derived metadata when ROI configuration changes."""
    data_mgr: DataManager = get_user_data("data_manager")

    # Rebuild display name from current configuration
    new_display_name = _build_template_display_name(rts_sopiuid, roi_number)
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", new_display_name)

    # Update interpreted type based on display name
    inferred_type = _infer_roi_type_from_name(new_display_name)
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", inferred_type)

    # Auto-populate PTV data if this is a PTV
    if inferred_type == "PTV":
        _auto_populate_ptv_data_from_dicom(rts_sopiuid, roi_number)


def _on_naming_mode_changed(sender: Any, app_data: str, user_data: Tuple) -> None:
    """Handle switching between template-based and custom naming modes."""
    data_mgr: DataManager = get_user_data("data_manager")
    (
        template_mode_label, rts_sopiuid, roi_number,
        custom_name_row, template_name_row, template_filter_row,
        ptv_dose_row, ptv_fractions_row, ptv_site_row
    ) = user_data

    is_template_based = (app_data == template_mode_label)
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "is_template_based", is_template_based)

    # Show/hide appropriate UI rows
    dpg.configure_item(custom_name_row, show=not is_template_based)
    dpg.configure_item(template_name_row, show=is_template_based)
    dpg.configure_item(template_filter_row, show=is_template_based)

    # Update display name and PTV field visibility
    _update_roi_derived_metadata(rts_sopiuid, roi_number)
    current_display_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", "")
    _update_ptv_field_visibility(current_display_name, ptv_dose_row, ptv_fractions_row, ptv_site_row)


def _on_template_selected(sender: Any, app_data: str, user_data: Tuple) -> None:
    """Handle template selection from dropdown."""
    roi_button_tag, ptv_dose_row, ptv_fractions_row, ptv_site_row = user_data
    rts_sopiuid, roi_number = dpg.get_item_user_data(roi_button_tag)

    data_mgr: DataManager = get_user_data("data_manager")
    conf_mgr: ConfigManager = get_user_data("config_manager")
    
    # Get original DICOM name for matching
    original_roi_name = data_mgr.get_rtstruct_roi_ds_value_by_uid(rts_sopiuid, roi_number, "ROIName", "")

    # Remove from previous template's matching list (if any)
    previous_template = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "base_template_name", None)
    if previous_template and previous_template != app_data:
        conf_mgr.remove_item_organ_matching_by_template(previous_template, original_roi_name)

    # Add to new template's matching list
    conf_mgr.add_item_organ_matching(app_data, original_roi_name)

    # Update metadata
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "base_template_name", app_data)

    _update_roi_derived_metadata(rts_sopiuid, roi_number)
    _update_ptv_field_visibility(app_data, ptv_dose_row, ptv_fractions_row, ptv_site_row)
    update_roi_display_and_tooltip(roi_button_tag)


def _on_custom_name_changed(sender: Any, app_data: str, user_data: Tuple) -> None:
    """Handle custom display name input."""
    roi_button_tag, ptv_dose_row, ptv_fractions_row, ptv_site_row = user_data
    rts_sopiuid, roi_number = dpg.get_item_user_data(roi_button_tag)

    data_mgr: DataManager = get_user_data("data_manager")
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", app_data)

    # Update derived metadata for custom names
    inferred_type = _infer_roi_type_from_name(app_data)
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "RTROIInterpretedType", inferred_type)

    _update_ptv_field_visibility(app_data, ptv_dose_row, ptv_fractions_row, ptv_site_row)
    update_roi_display_and_tooltip(roi_button_tag)


def _on_ptv_parameter_changed(sender: Any, app_data: Any, user_data: Tuple[Any, str]) -> None:
    """Handle changes to PTV-specific parameters (dose, fractions, site)."""
    roi_button_tag, parameter_key = user_data
    rts_sopiuid, roi_number = dpg.get_item_user_data(roi_button_tag)

    data_mgr: DataManager = get_user_data("data_manager")
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, parameter_key, app_data)

    # For template-based ROIs, rebuild display name with new parameters
    is_template_based = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "is_template_based", False)
    if is_template_based:
        _update_roi_derived_metadata(rts_sopiuid, roi_number)
        new_param_value = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, parameter_key, None)
        if new_param_value is not None:
            dpg.set_value(sender, new_param_value if new_param_value is not None else "")

    update_roi_display_and_tooltip(roi_button_tag)


def _on_template_filter_changed(sender: Any, app_data: str, user_data: Any) -> None:
    """Filter template dropdown based on user input."""
    template_combo_tag = user_data
    conf_mgr: ConfigManager = get_user_data("config_manager")

    filter_text = app_data.lower()
    all_templates = conf_mgr.get_tg_263_names(ready_for_dpg=True)
    filtered_templates = [template for template in all_templates if filter_text in template.lower()]

    dpg.configure_item(template_combo_tag, items=filtered_templates)


def _on_roi_goals_changed(sender: Any, app_data: str, user_data: Tuple) -> None:
    """Validate and update ROI goals."""
    roi_button_tag, validation_message_tag = user_data

    popup_width = dpg.get_item_width(get_tag("inspect_data_popup"))
    is_valid, errors = validate_roi_goals_format(app_data)

    if is_valid:
        rts_sopiuid, roi_number = dpg.get_item_user_data(roi_button_tag)
        data_mgr: DataManager = get_user_data("data_manager")
        data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "roi_goals", loads(app_data))

        update_roi_display_and_tooltip(roi_button_tag)
        dpg.configure_item(validation_message_tag, color=(39, 174, 96), wrap=round(popup_width * 0.9))
        dpg.set_value(validation_message_tag, "ROI goals validated and saved successfully!")
    else:
        dpg.configure_item(validation_message_tag, color=(192, 57, 43), wrap=round(popup_width * 0.9))
        dpg.set_value(validation_message_tag, f"Invalid ROI goals format:\n{errors}")


def _update_ptv_field_visibility(display_name: str, ptv_dose_row: Any, ptv_fractions_row: Any, ptv_site_row: Any) -> None:
    """Show or hide PTV-specific input fields based on ROI type."""
    is_ptv = "ptv" in display_name.lower()

    for tag in [ptv_dose_row, ptv_fractions_row, ptv_site_row]:
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, show=is_ptv)


### ROI INTERACTIONS ###


def remove_roi_with_confirmation(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, Any]) -> None:
    """Remove ROI from display after user confirmation."""
    roi_group_tag, roi_checkbox_tag = user_data

    def confirm_removal(sender, app_data, user_data) -> None:
        checkbox_user_data = dpg.get_item_user_data(roi_checkbox_tag)
        _, rts_sopiuid, roi_number = checkbox_user_data

        # Uncheck and update checkbox if currently checked
        if dpg.get_value(roi_checkbox_tag):
            dpg.set_value(roi_checkbox_tag, False)
            checkbox_callback = dpg.get_item_callback(roi_checkbox_tag)
            if checkbox_callback:
                checkbox_callback(roi_checkbox_tag, False, checkbox_user_data)

        # Remove UI elements and data
        safe_delete(roi_group_tag)
        data_mgr: DataManager = get_user_data("data_manager")
        data_mgr.remove_roi_from_rtstruct(rts_sopiuid, roi_number)

        logger.info(f"Removed ROI #{roi_number} from structure set {rts_sopiuid}")

    create_confirmation_popup(
        button_callback=confirm_removal,
        button_theme=get_hidden_button_theme(),
        warning_string="This will remove the ROI from display until data is reloaded. Continue?"
    )


def show_roi_color_picker(sender: Union[str, int], app_data: Any, user_data: Tuple[str, int]) -> None:
    """Display color picker popup for ROI."""
    color_picker_tag = get_tag("color_picker_popup")
    safe_delete(color_picker_tag)

    rts_sopiuid, roi_number = user_data
    data_mgr: DataManager = get_user_data("data_manager")

    display_name = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "display_name", "Unknown")
    current_color = data_mgr.get_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIDisplayColor")

    mouse_pos = dpg.get_mouse_pos(local=False)

    with dpg.window(
        tag=color_picker_tag,
        label=f"Choose Color - ROI #{roi_number}: {display_name}",
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
        dpg.add_button(label="Close", callback=lambda: safe_delete(color_picker_tag))


def center_views_on_roi(sender: Union[str, int], app_data: Any, user_data: Tuple[Any, str, int]) -> None:
    """Center all views on the ROI's center of mass."""
    roi_checkbox_tag, rts_sopiuid, roi_number = user_data
    data_mgr: DataManager = get_user_data("data_manager")
    img_tags = get_tag("img_tags")

    # Check if any data is currently active
    any_data_active_before = data_mgr.return_is_any_data_active()
    
    # Ensure the ROI is active
    dpg.set_value(roi_checkbox_tag, True)
    checkbox_callback = dpg.get_item_callback(roi_checkbox_tag)
    checkbox_user_data = dpg.get_item_user_data(roi_checkbox_tag)
    if checkbox_callback:
        checkbox_callback(roi_checkbox_tag, True, checkbox_user_data)

    # Initialize texture if needed
    any_data_active_after = data_mgr.return_is_any_data_active()
    if not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
        sleep(0.1)  # Allow texture update to complete
    
    # Get ROI spatial information
    roi_center = data_mgr.get_roi_center_of_mass_by_uid(rts_sopiuid, roi_number)
    roi_extents = data_mgr.get_roi_extent_ranges_by_uid(rts_sopiuid, roi_number)

    if not roi_center or not roi_extents:
        logger.warning(f"Cannot center on ROI #{roi_number}: missing spatial data")
        return
    
    # Display limits
    range_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
    limits = [(int(dpg.get_item_configuration(t)["min_value"]), int(dpg.get_item_configuration(t)["max_value"])) for t in range_tags]
    limit_spans = [mx - mn + 1 for mn, mx in limits]
    
    # ROI extents -> voxel counts
    vox_counts = [max(1, int(rmax) - int(rmin) + 1) for rmin, rmax in roi_extents]
    
    # Bounding box = largest axis * 1.05 (5% margin), then clamp to smallest available axis span
    desired_span = round(max(vox_counts) * 1.05)
    desired_span = max(1, min(desired_span, min(limit_spans)))

    # Centers clipped to limits
    centers = [min(max(int(round(c)), limits[i][0]), limits[i][1]) for i, c in enumerate(roi_center[:3])]
    
    # Compute start/end per axis centered on center, shift if hitting limits (preserve span)
    half = desired_span // 2
    new_ranges = []
    for i in range(3):
        start = centers[i] - half
        end = start + desired_span - 1
        if start < limits[i][0]:
            start = limits[i][0]
            end = start + desired_span - 1
        if end > limits[i][1]:
            end = limits[i][1]
            start = end - desired_span + 1
        new_ranges.append((int(start), int(end)))

    for tag, rng in zip(range_tags, new_ranges):
        dpg.set_value(tag, (rng[0], rng[1]))
    
    dpg.set_value(img_tags["viewed_slices"], tuple(centers))
    request_texture_update(texture_action_type="update")


def _update_roi_color(sender: Union[str, int], app_data: List[float], user_data: Tuple[Any, str, int]) -> None:
    """Update ROI display color from color picker selection."""
    color_floats = app_data[:3]
    color_button_tag, rts_sopiuid, roi_number = user_data

    # Convert to RGB integers
    new_color = [round(min(max(255 * color, 0), 255)) for color in color_floats]

    # Update data and UI
    data_mgr: DataManager = get_user_data("data_manager")
    data_mgr.set_roi_gui_metadata_value_by_uid_and_key(rts_sopiuid, roi_number, "ROIDisplayColor", new_color)
    dpg.bind_item_theme(item=color_button_tag, theme=get_colored_button_theme(new_color))
    request_texture_update(texture_action_type="update")

