from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict
from functools import partial

import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button, add_custom_checkbox
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme
from mdh_app.dpg_components.windows.save_data.save_data_utils import _execute_saving
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


def create_save_window(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Display a popup window for saving SimpleITK data with customizable save options.
    
    This window allows the user to specify various options such as keeping custom data viewing 
    parameters, converting CT Hounsfield Units (HU) to Relative Electron Densities (RED), 
    and overriding images with ROI RED values. It then builds tables for images, ROIs, RT plans, 
    and RT doses for individual or bulk saving.
    
    Args:
        sender: The UI element that triggered this action.
        app_data: Additional event data.
        user_data: Additional user data.
    """
    tag_save_window = get_tag("save_sitk_window")
    tag_save_button = get_tag("save_button")
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    size_dict = get_user_data(td_key="size_dict")
    
    inner_table_w = 4000
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.9, height_ratio=0.9)
    popup_wrap = round(popup_width * 0.9)
    button_height = round(1.5 * dpg.get_text_size("A")[1])
    
    # Action in progress, so show the existing window
    if dpg.does_item_exist(tag_save_window) and ss_mgr.is_action_in_progress():
        dpg.configure_item(tag_save_window, width=popup_width, height=popup_height, pos=popup_pos, show=True)
        logger.info("Save window NOT refreshed because an action is in progress. The save data window cannot be refreshed or regenerated until the action(s) complete.")
        return
    
    safe_delete(tag_save_window)
    
    tag_hidden_theme = get_hidden_button_theme()
    save_settings_dict = conf_mgr.get_save_settings_dict()
    
    # Data to show in the save window
    save_data_dict = dpg.get_item_user_data(tag_save_button)
    save_images_dict = {k: v for k, v in save_data_dict.items() if k[0] == "image" and dpg.does_item_exist(v)}  # Key is ("image", SeriesInstanceUID), value is button tag
    save_rois_dict = {k: v for k, v in save_data_dict.items() if k[0] == "roi" and dpg.does_item_exist(v)}  # Key is ("roi", SOPInstanceUID, ROINumber), value is button tag
    save_rtplans_dict = {k: v for k, v in save_data_dict.items() if k[0] == "rtplan" and dpg.does_item_exist(v)}  # Key is ("rtplan", SOPInstanceUID), value is button tag
    save_rtdoses_dict = {k: v for k, v in save_data_dict.items() if k[0] == "rtdose" and dpg.does_item_exist(v)}  # Key is ("rtdose", SOPInstanceUID), value is button tag
    
    # Tracks save selections made by the user in the save window
    save_selections_dict: Dict[str, Any] = {"main_checkboxes": {}, "images": [], "rois": [], "plans": [], "doses": []}
    
    with dpg.window(
        tag=tag_save_window, 
        label="Save Data", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        on_close=lambda: dpg.hide_item(tag_save_window),
        horizontal_scrollbar=True, 
        user_data=save_selections_dict, 
    ):
        add_custom_button(
            label="Carefully review the save options below.", 
            theme_tag=tag_hidden_theme, 
            add_separator_after=True
        )
        
        add_custom_button(
            label="General Options", 
            theme_tag=tag_hidden_theme, 
            add_spacer_after=True
        )
        save_selections_dict["main_checkboxes"]["keep_custom_params"] = add_custom_checkbox(
            default_value=save_settings_dict["keep_custom_params"], 
            checkbox_label="Save with your current custom data viewing parameters", 
            add_spacer_after=True,
            tooltip_text=(
                "If selected, the current data viewing parameters will be saved with the data.\n"
                "Otherwise, the data will be saved with its native/default parameters (e.g., size/spacing)."
            )
        )
        
        # Images
        add_custom_button(
            label="Images", 
            theme_tag=tag_hidden_theme, 
            add_separator_before=True, 
            add_spacer_after=True,
        )
        save_selections_dict["main_checkboxes"]["convert_ct_hu_to_red"] = add_custom_checkbox(
            default_value=save_settings_dict["convert_ct_hu_to_red"],
            checkbox_label="Map CT Hounsfield Units to Relative Electron Densities",
            add_spacer_after=True,
            tooltip_text="If selected, CT Hounsfield Units will be converted to Relative Electron Densities using a conversion table.",
        )
        save_selections_dict["main_checkboxes"]["override_image_with_roi_RED"] = add_custom_checkbox(
            default_value=save_settings_dict["override_image_with_roi_RED"],
            checkbox_label="Override image(s) with ROI R.E.D. values",
            add_spacer_after=True,
            tooltip_text=(
                "If selected, images will be overridden with specified ROI Relative Electron Densities.\n"
                "For instance, if titanium has an assigned RED of 4.5, the image will be overridden accordingly.\n"
                "If not, images will be saved as-is."
            ),
        )
        with dpg.table(
            resizable=True, 
            reorderable=True, 
            hideable=False, 
            sortable=False, 
            scrollX=False, 
            scrollY=False, 
            row_background=True, 
            header_row=True, 
            freeze_rows=1, 
            borders_innerH=True,
            borders_innerV=True, 
            borders_outerH=True, 
            borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, 
            context_menu_in_body=True, 
            delay_search=False, 
            pad_outerX=True,
            inner_width=inner_table_w,
            width=size_dict["table_w"], 
        ):
            dpg.add_table_column(label="Modality", init_width_or_weight=round(dpg.get_text_size("Image")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.05))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.05))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for ((_, img_siuid), img_button_tag) in save_images_dict.items():
                img_siuid = str(img_siuid)
                modality = str(data_mgr.get_image_metadata_by_series_uid_and_key(img_siuid, "Modality", "UNKNOWN"))
                series_date = str(data_mgr.get_image_metadata_by_series_uid_and_key(img_siuid, "SeriesDate", ""))
                study_date = str(data_mgr.get_image_metadata_by_series_uid_and_key(img_siuid, "StudyDate", ""))
                study_instance_uid = str(data_mgr.get_image_metadata_by_series_uid_and_key(img_siuid, "StudyInstanceUID", "UNKNOWN"))
                file_date = series_date or study_date or "19000101"
                
                img_label = dpg.get_item_label(img_button_tag)
                tooltip_text_tag = f"{img_button_tag}_tooltiptext"
                img_text = dpg.get_value(tooltip_text_tag) if dpg.does_item_exist(tooltip_text_tag) else f"Image Modality: {modality}\nFile Date: {file_date}\nSeries Instance UID: {img_siuid}"
                
                default_filename = (
                    f"IMAGE_{modality.replace(' ', '-').replace('_', '-')}_"
                    f"{file_date.replace(' ', '-').replace('_', '-')}_"
                    f"{img_siuid.replace(' ', '-').replace('_', '-')}"
                )
                
                with dpg.table_row():
                    add_custom_button(label=img_label, height=button_height, tooltip_text=img_text)
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Include this item in the bulk save list.")
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height)
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_selections_dict["images"].append(
                    {
                        "data_key": img_siuid, 
                        "study_instance_uid": study_instance_uid, 
                        "modality": modality, 
                        "series_instance_uid": img_siuid,
                        "filename_tag": filename_tag, 
                        "bulksave_tag": bulksave_tag, 
                        "save_tag": save_tag
                    }
                )
        
        # ROIs
        add_custom_button(
            label="ROIs", 
            theme_tag=tag_hidden_theme, 
            add_separator_before=True, 
            add_spacer_after=True,
        )
        with dpg.table(
            resizable=True, 
            reorderable=True, 
            hideable=False, 
            sortable=False, 
            scrollX=False, 
            scrollY=False, 
            row_background=True, 
            header_row=True, 
            freeze_rows=1, 
            borders_innerH=True,
            borders_innerV=True, 
            borders_outerH=True, 
            borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, 
            context_menu_in_body=True, 
            delay_search=False, 
            pad_outerX=True,
            inner_width=inner_table_w,
            width=size_dict["table_w"],
        ):
            dpg.add_table_column(label="ROI", init_width_or_weight=round(dpg.get_text_size("00. ThisIsAnExampleROIName")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.05))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.05))
            dpg.add_table_column(label="Goals", init_width_or_weight=round(dpg.get_text_size("Goals")[0] * 1.25))
            dpg.add_table_column(label="Rel. Elec. Dens.", init_width_or_weight=round(dpg.get_text_size("00.000")[0] * 2))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for ((_, rts_sopiuid, roi_number), roi_button_tag) in save_rois_dict.items():
                rts_sopiuid = str(rts_sopiuid)
                
                roi_metadata = data_mgr.get_roi_gui_metadata_by_uid(rts_sopiuid, roi_number)
                roi_use_templated_name = roi_metadata.get("use_template_name", False)
                roi_name = roi_metadata.get("ROITemplateName", "") if roi_use_templated_name else roi_metadata.get("ROIName", "")
                rt_roi_interpreted_type = roi_metadata.get("RTROIInterpretedType", "")
                roi_physical_property_value = roi_metadata.get("ROIPhysicalPropertyValue", -1.0)  # Relative Electron Density value, -1.0 if not set
                roi_goals = roi_metadata.get("roi_goals", {})
                
                if "bolus" in roi_name.lower() and roi_physical_property_value is None:
                    roi_physical_property_value = 1.0
                elif not isinstance(roi_physical_property_value, (float, int)) or not (0.0 < roi_physical_property_value < 15.0):
                    roi_physical_property_value = -1.0
                
                structure_set_label = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, "StructureSetLabel", "")
                structure_set_name = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, " StructureSetName", "")
                structure_set_date = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, "StructureSetDate", "")
                structure_set_time = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, "StructureSetTime", "")
                study_instance_uid = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, "StudyInstanceUID", "UNKNOWN")
                modality = data_mgr.get_rtstruct_ds_value_by_uid_and_key(rts_sopiuid, "Modality", "RTSTRUCT")

                roi_label = dpg.get_item_label(roi_button_tag)
                tooltip_text_tag = f"{roi_button_tag}_tooltiptext"
                roi_text = dpg.get_value(tooltip_text_tag) if dpg.does_item_exist(tooltip_text_tag) else (
                    f"ROI Number: {roi_number}\nROI Name: {roi_name}\nROI Type: {rt_roi_interpreted_type}\n"
                    f"Structure Set Label: {structure_set_label}\nStructure Set Name: {structure_set_name}\nStructure Set Date: {structure_set_date}\nStructure Set Time: {structure_set_time}\n"
                )
                
                default_filename = f"ROI_{roi_name}"
                row_tag = dpg.generate_uuid()
                with dpg.table_row(tag=row_tag):
                    add_custom_button(label=roi_label, height=button_height, tooltip_text=roi_text)
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Include this ROI in the bulk save list.")
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height
                    )
                    
                    if roi_goals:
                        goals_tag = add_custom_button(label="Goals", height=button_height, tooltip_text=f"ROI Goals: {roi_goals}")
                    else:
                        goals_tag = None
                        dpg.add_text("N/A")
                    
                    roi_phys_prop_tag = dpg.add_input_float(
                        default_value=roi_physical_property_value if roi_physical_property_value is not None else -1.0,
                        min_value=-1.0,
                        max_value=15.0,
                        step=0,
                        step_fast=0,
                        min_clamped=True,
                        max_clamped=True,
                        width=round(dpg.get_text_size("00.000")[0] * 2.5)
                    )
                    with dpg.tooltip(parent=roi_phys_prop_tag):
                        dpg.add_text("Relative Electron Density value (0.0 to 15.0). Set to -1.0 to ignore.", wrap=size_dict["tooltip_width"])
                    
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                
                save_selections_dict["rois"].append({
                    "data_key": (rts_sopiuid, roi_number),
                    "study_instance_uid": study_instance_uid,
                    "modality": modality,
                    "sop_instance_uid": rts_sopiuid,
                    "filename_tag": filename_tag,
                    "bulksave_tag": bulksave_tag,
                    "save_tag": save_tag,
                    "goals_tag": goals_tag,
                    "roi_phys_prop_tag": roi_phys_prop_tag
                })
        
        # RTPLANS
        add_custom_button(
            label="RT Plans", 
            theme_tag=tag_hidden_theme, 
            add_separator_before=True, 
            add_spacer_after=True,
        )
        with dpg.table(
            resizable=True, 
            reorderable=True, 
            hideable=False, 
            sortable=False, 
            scrollX=False, 
            scrollY=False, 
            row_background=True, 
            header_row=True, 
            freeze_rows=1, 
            borders_innerH=True,
            borders_innerV=True, 
            borders_outerH=True, 
            borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, 
            context_menu_in_body=True, 
            delay_search=False, 
            pad_outerX=True,
            inner_width=inner_table_w,
            width=size_dict["table_w"],
        ):
            dpg.add_table_column(label="RT Plan", init_width_or_weight=round(dpg.get_text_size("ThisIsAnExampleLabel")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.05))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.05))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for ((_, rtp_sopiuid), rtp_button_tag) in save_rtplans_dict.items():
                rtp_sopiuid = str(rtp_sopiuid)
                overall_beam_summary: Dict[str, Any] = data_mgr.get_rtplan_ds_overall_beam_summary_by_uid(rtp_sopiuid)
                
                rt_plan_label = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanLabel", "NoPlanLabel")
                rt_plan_name = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanName", "NoPlanName")
                rt_plan_date = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "RTPlanDate", "NoPlanDate")
                study_instance_uid = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "StudyInstanceUID", "UNKNOWN")
                modality = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "Modality", "RTPLAN")
                number_of_fractions_planned = data_mgr.get_rtplan_ds_value_by_uid(rtp_sopiuid, "NumberOfFractionsPlanned", 1)
                machines = overall_beam_summary.get("Unique Treatment Machines", ["NoMachine"])
                machines = [str(m).strip().title() for m in machines if str(m).strip()]
                machines = "".join(machines) if machines else "NoMachine"
                
                default_filename = (
                    f"PLAN_{str(number_of_fractions_planned).replace(' ', '-').replace('_', '-')}Fxns_"
                    f"{str(rt_plan_label).replace(' ', '-').replace('_', '-')}_"
                    f"{str(rt_plan_name).replace(' ', '-').replace('_', '-')}_"
                    f"{str(rt_plan_date).replace(' ', '-').replace('_', '-')}_"
                    f"{str(machines).replace(' ', '-').replace('_', '-')}"
                )
                
                rtp_label = dpg.get_item_label(rtp_button_tag)
                tooltip_text_tag = f"{rtp_button_tag}_tooltiptext"
                rtp_text = dpg.get_value(tooltip_text_tag) if dpg.does_item_exist(tooltip_text_tag) else (
                    f"RT Plan Label: {rt_plan_label}\nRT Plan Name: {rt_plan_name}\nRT Plan Date: {rt_plan_date}\n"
                    f"Machine(s): {machines}\n"
                )
                
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(label=rtp_label, height=button_height, tooltip_text=rtp_text)
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height
                    )
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                
                save_selections_dict["plans"].append({
                    "data_key": rtp_sopiuid,
                    "study_instance_uid": study_instance_uid,
                    "modality": modality,
                    "sop_instance_uid": rtp_sopiuid,
                    "filename_tag": filename_tag, 
                    "bulksave_tag": bulksave_tag, 
                    "save_tag": save_tag
                })
        
        # RTDOSES
        add_custom_button(
            label="RT Doses", 
            theme_tag=tag_hidden_theme, 
            add_separator_before=True, 
            add_spacer_after=True,
        )
        with dpg.group(horizontal=True):
            with dpg.tooltip(parent=dpg.last_item()):
                dpg.add_text("Filename for the summed dose, if any will exist (based on user selections below).", wrap=size_dict["tooltip_width"])
            dpg.add_text(f"Dose Sum Name: ")
            save_selections_dict["main_checkboxes"]["dosesum_name_tag"] = dpg.add_input_text(default_value="DOSE_PlanSum", width=size_dict["table_w"])
        with dpg.table(
            resizable=True, 
            reorderable=True, 
            hideable=False, 
            sortable=False, 
            scrollX=False, 
            scrollY=False, 
            row_background=True, 
            header_row=True, 
            freeze_rows=1, 
            borders_innerH=True,
            borders_innerV=True, 
            borders_outerH=True, 
            borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, 
            context_menu_in_body=True, 
            delay_search=False, 
            pad_outerX=True,
            inner_width=inner_table_w,
            width=size_dict["table_w"],
        ):
            dpg.add_table_column(label="RT Dose", init_width_or_weight=round(dpg.get_text_size("ThisIsAnExampleDose")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.05))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.05))
            dpg.add_table_column(label="Sum", init_width_or_weight=round(dpg.get_text_size("Sum")[0] * 1.05))
            dpg.add_table_column(label="# Dose Fxns", init_width_or_weight=round(dpg.get_text_size("# Dose Fxns")[0] * 1.05))
            dpg.add_table_column(label="# Plan Fxns", init_width_or_weight=round(dpg.get_text_size("# Plan Fxns")[0] * 1.05))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for ((_, rtd_sopiuid), rtd_button_tag) in save_rtdoses_dict.items():
                rtd_sopiuid = str(rtd_sopiuid)
                
                modality = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "Modality", "RT Dose")
                dose_summation_type = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "DoseSummationType", "")
                date = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ContentDate", "N/A")
                time = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ContentTime", "")
                ref_rtp_sopiuid = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReferencedRTPlanSOPInstanceUID", "")
                ref_beam_number = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "ReferencedRTPlanBeamNumber", "")
                num_fxns_planned = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractionsPlanned", "0")
                num_fxns = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "NumberOfFractions", "0")
                study_instance_uid = data_mgr.get_rtdose_metadata_by_uid_and_key(rtd_sopiuid, "StudyInstanceUID", "UNKNOWN")
                
                rtplan_label = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanLabel", "") if ref_rtp_sopiuid else ""
                rtplan_name = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanName", "") if ref_rtp_sopiuid else ""
                rtplan_date = data_mgr.get_rtplan_ds_value_by_uid(ref_rtp_sopiuid, "RTPlanDate", "") if ref_rtp_sopiuid else ""
                
                dose_name = f"{dose_summation_type.upper()}"
                dose_name = dose_name + ref_beam_number if "BEAM" in dose_name and ref_beam_number else dose_name
                
                rtd_label = dpg.get_item_label(rtd_button_tag)
                tooltip_text_tag = f"{rtd_button_tag}_tooltiptext"
                rtd_text = dpg.get_value(tooltip_text_tag) if dpg.does_item_exist(tooltip_text_tag) else (
                    f"RT Dose Type: {modality}\nDose Summation Type: {dose_summation_type}\nContent Date: {date}\nContent Time: {time}\n"
                    f"SOPInstanceUID: {rtd_sopiuid}\nReferenced RT Plan SOPIUID: {ref_rtp_sopiuid}\nReferenced RT Plan Beam Number: {ref_beam_number}\n"
                    f"RT Plan Label: {rtplan_label}\nRT Plan Name: {rtplan_name}\nRT Plan Date: {rtplan_date}\n"
                    f"Number of Fractions Planned: {num_fxns_planned}\nNumber of Fractions RT Dose: {num_fxns}\n"
                )
                
                if ref_rtp_sopiuid:
                    default_filename = (
                        f"DOSE_{str(dose_name).replace(' ', '-').replace('_', '-')}_" +
                        f"{str(num_fxns_planned).replace(' ', '-').replace('_', '-')}Fxns" + 
                        (f"_{str(rtplan_label).replace(' ', '-').replace('_', '-')}" if rtplan_label else "NoPlanLabel") +
                        (f"_{str(rtplan_name).replace(' ', '-').replace('_', '-')}" if rtplan_name else "NoPlanName") +
                        (f"_{str(rtplan_date).replace(' ', '-').replace('_', '-')}" if rtplan_date else "NoPlanDate")
                    )
                else:
                    default_filename = (
                        f"DOSE_{str(dose_name).replace(' ', '-').replace('_', '-')}_" +
                        f"{str(num_fxns_planned).replace(' ', '-').replace('_', '-')}Fxns" + 
                        f"_{rtd_sopiuid.replace(' ', '-').replace('_', '-')}"
                    )
                
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(label=rtd_label, height=button_height, tooltip_text=rtd_text)
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Include this item in the bulk save list.")
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height
                    )
                    dosesum_checkbox_tag = add_custom_checkbox(
                        default_value=False, 
                        tooltip_text=(
                            "Any RT Dose items with this checked will be added to "
                            "create a dose sum (like for a plan sum)."
                        )
                    )
                    
                    num_dose_fxns_tag = dpg.add_input_int(
                        default_value=int(num_fxns), 
                        min_value=0, 
                        max_value=100, 
                        min_clamped=True, 
                        max_clamped=True, 
                        width=round(dpg.get_text_size("000......")[0] * 1.5)
                    )
                    with dpg.tooltip(parent=num_dose_fxns_tag):
                        dpg.add_text(
                            default_value=(
                                "Number of Fractions that the dose currently represents. "
                                "Value of 0 is ok, but it will not scale the dose."
                            ),
                            wrap=size_dict["tooltip_width"]
                        )
                    
                    num_plan_fxns_tag = dpg.add_input_int(
                        default_value=int(num_fxns_planned), 
                        min_value=0, 
                        max_value=100, 
                        min_clamped=True,
                        max_clamped=True, 
                        width=round(dpg.get_text_size("000......")[0] * 1.5)
                    )
                    with dpg.tooltip(parent=num_plan_fxns_tag):
                        dpg.add_text(
                            default_value=(
                                "Number of Fractions that you WANT the dose to represent "
                                "(typically based on the RT Plan Number of Fractions). "
                                "Value of 0 is ok, but it will not scale the dose."
                            ), 
                            wrap=size_dict["tooltip_width"]
                        )
                    
                    filename_tag = dpg.add_input_text(
                        default_value=default_filename, 
                        width=size_dict["table_w"]
                    )
                
                save_selections_dict["doses"].append({
                    "data_key": rtd_sopiuid, 
                    "study_instance_uid": study_instance_uid,
                    "modality": modality,
                    "sop_instance_uid": rtd_sopiuid,
                    "filename_tag": filename_tag, 
                    "bulksave_tag": bulksave_tag, 
                    "save_tag": save_tag, 
                    "dosesum_checkbox_tag": dosesum_checkbox_tag, 
                    "num_dose_fxns_tag": num_dose_fxns_tag, 
                    "num_plan_fxns_tag": num_plan_fxns_tag
                })
        
        execute_bulk_save_tag = add_custom_button(
            label="Execute Bulk Save", 
            height=200,
            callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
            add_separator_before=True, 
            add_spacer_after=True
        )
        save_selections_dict["execute_bulk_save_tag"] = execute_bulk_save_tag

        dpg.add_spacer(height=size_dict["spacer_height"])
    