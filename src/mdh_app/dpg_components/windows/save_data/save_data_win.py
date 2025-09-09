from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict
from functools import partial
from json import loads

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
    unmatched_organ_name = conf_mgr.get_unmatched_organ_name()
    data_dict = dpg.get_item_user_data(tag_save_button)
    
    save_data_dict: Dict[str, Any] = {"main_checkboxes": {}, "images": [], "rois": [], "plans": [], "doses": []}
    with dpg.window(
        tag=tag_save_window, 
        label="Save Data", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        on_close=lambda: dpg.hide_item(tag_save_window),
        horizontal_scrollbar=True, 
        user_data=save_data_dict, 
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
        save_data_dict["main_checkboxes"]["keep_custom_params"] = add_custom_checkbox(
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
        save_data_dict["main_checkboxes"]["convert_ct_hu_to_red"] = add_custom_checkbox(
            default_value=save_settings_dict["convert_ct_hu_to_red"],
            checkbox_label="Map CT Hounsfield Units to Relative Electron Densities",
            add_spacer_after=True,
            tooltip_text="If selected, CT Hounsfield Units will be converted to Relative Electron Densities using a conversion table.",
        )
        save_data_dict["main_checkboxes"]["override_image_with_roi_RED"] = add_custom_checkbox(
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
            for key, value in data_dict.items():
                if key[0] != "image":
                    continue
                
                if value() is None:
                    continue
                
                image_modality = key[1].upper()
                series_instance_uid = key[2]
                
                file_date = (
                    value().GetMetaData("SeriesDate") 
                    if value().HasMetaDataKey("SeriesDate") 
                    else value().GetMetaData("StudyDate") 
                    if value().HasMetaDataKey("StudyDate") 
                    else None
                ) or "19000101"
                
                default_filename = (
                    f"IMAGE_{str(image_modality).replace(' ', '-').replace('_', '-')}_"
                    f"{str(file_date).replace(' ', '-').replace('_', '-')}_"
                    f"{str(series_instance_uid).replace(' ', '-').replace('_', '-')}"
                )
                
                with dpg.table_row():
                    add_custom_button(
                        label=image_modality,
                        height=button_height,
                        tooltip_text=(
                            f"Image Modality: {image_modality}\nFile Date: {file_date}\n"
                            f"Series Instance UID: {series_instance_uid}\nSize: {value().GetSize()}\n"
                            f"Spacing: {value().GetSpacing()}\nDirection: {value().GetDirection()}\nOrigin: {value().GetOrigin()}"
                        ),
                    )
                    bulksave_tag = add_custom_checkbox(
                        default_value=True,
                        tooltip_text="Include this item in the bulk save list.",
                    )
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height)
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_data_dict["images"].append(
                    {"data": value, "modality": image_modality, "filename_tag": filename_tag, "bulksave_tag": bulksave_tag, "save_tag": save_tag}
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
            for key, value in data_dict.items():
                if key[0] != "rtstruct":
                    continue
                if value() is None:
                    continue
                
                roi_number = value().GetMetaData("roi_number")
                roi_name = value().GetMetaData("current_roi_name")
                roi_matched = roi_name != unmatched_organ_name
                if not roi_matched:
                    roi_name = value().GetMetaData("original_roi_name")
                
                rt_roi_interpreted_type = value().GetMetaData("rt_roi_interpreted_type")
                roi_goals = value().GetMetaData("roi_goals")
                roi_goals = loads(roi_goals) if roi_goals else {}
                
                roi_physical_properties = value().GetMetaData("roi_physical_properties")
                roi_physical_properties = loads(roi_physical_properties) if roi_physical_properties else []
                roi_physical_properties = roi_physical_properties[0] if roi_physical_properties else {}
                roi_physical_property = str(roi_physical_properties.get("roi_physical_property", ""))
                roi_physical_property_value = roi_physical_properties.get("roi_physical_property_value")
                if "bolus" in roi_name.lower() and roi_physical_property_value is None:
                    roi_physical_property_value = 1.0
                if (
                    (roi_physical_property and roi_physical_property.lower() != "rel_elec_density") or 
                    not isinstance(roi_physical_property_value, (float, int)) or 
                    0.0 > roi_physical_property_value > 15.0
                ):
                    roi_physical_property_value = -1.0
                
                structure_set_dict = data_mgr.return_data_from_modality("rtstruct")[key[1]]
                StructureSetLabel = structure_set_dict.get("StructureSetLabel")
                StructureSetName = structure_set_dict.get("StructureSetName")
                StructureSetDate = structure_set_dict.get("StructureSetDate")
                StructureSetTime = structure_set_dict.get("StructureSetTime")
                ReferencedSeriesInstanceUID = structure_set_dict.get("ReferencedSeriesInstanceUID")
                
                default_filename = f"ROI_{roi_name}"
                row_tag = dpg.generate_uuid()
                with dpg.table_row(tag=row_tag):
                    add_custom_button(
                        label=f"{roi_number}. {roi_name}",
                        height=button_height,
                        tooltip_text=(
                            f"ROI Number: {roi_number}\nROI Name: {roi_name}\nROI Type: {rt_roi_interpreted_type}\n"
                            f"Size: {value().GetSize()}\nSpacing: {value().GetSpacing()}\nDirection: {value().GetDirection()}\n"
                            f"Origin: {value().GetOrigin()}\nStructure Set Label: {StructureSetLabel}\nStructure Set Name: {StructureSetName}\n"
                            f"Structure Set Date: {StructureSetDate}\nStructure Set Time: {StructureSetTime}\nReferenced Series Instance UID: {ReferencedSeriesInstanceUID}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(
                        default_value=roi_matched,
                        tooltip_text="Include this ROI in the bulk save list."
                    )
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
                
                save_data_dict["rois"].append({
                    "data": value,
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
            for key, value in data_dict.items():
                if key[0] != "rtplan":
                    continue
                
                RTPlanLabel = value.get("RTPlanLabel", "NoPlanLabel")
                RTPlanName = value.get("RTPlanName", "NoPlanName")
                RTPlanDate = value.get("RTPlanDate", "NoPlanDate")
                DiseaseSite = value.get("rt_plan_disease_site", "19000101")
                ApprovalStatus = value.get("ApprovalStatus", "NoApprovalStatus")
                Machine = value.get("rt_plan_machine", "NoMachine")
                Dose = value.get("target_prescription_dose_cgy", "NoDose")
                Fxns = value.get("number_of_fractions_planned", "NoFxns")
                SOPIUID = value.get("SOPInstanceUID", "NoSOPInstanceUID")
                
                default_filename = (
                    f"PLAN_{str(Fxns).replace(' ', '-').replace('_', '-')}Fxns_"
                    f"{str(RTPlanLabel).replace(' ', '-').replace('_', '-')}_"
                    f"{str(RTPlanName).replace(' ', '-').replace('_', '-')}_"
                    f"{str(RTPlanDate).replace(' ', '-').replace('_', '-')}_"
                    f"{str(Machine).replace(' ', '-').replace('_', '-')}"
                )
                
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(
                        label=RTPlanLabel, 
                        height=button_height,
                        tooltip_text=(
                            f"RT Plan Label: {RTPlanLabel}\nRT Plan Name: {RTPlanName}\n"
                            f"RT Plan Date: {RTPlanDate}\nDisease Site: {DiseaseSite}\n"
                            f"Approval Status: {ApprovalStatus}\nMachine: {Machine}\n"
                            f"Dose: {Dose} cGy\nFractions: {Fxns}\nSOPIUID: {SOPIUID}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(
                        label="Save", 
                        callback=lambda s, a, u: ss_mgr.submit_action(partial(_execute_saving, s, a, u)),
                        height=button_height
                    )
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                
                save_data_dict["plans"].append({
                    "data": value, 
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
            save_data_dict["main_checkboxes"]["dosesum_name_tag"] = dpg.add_input_text(default_value="DOSE_PlanSum", width=size_dict["table_w"])
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
            for key, value in data_dict.items():
                if key[0] != "rtdose":
                    continue
                if value() is None:
                    continue
                
                num_fxn_planned = value().GetMetaData("number_of_fractions_planned")
                num_fxn_rtdose = value().GetMetaData("number_of_fractions_rtdose")
                SOPIUID = value().GetMetaData("SOPInstanceUID")
                referenced_rtplan_sopiuid = key[1]
                rtplan_dict = data_mgr.return_data_from_modality("rtplan").get(referenced_rtplan_sopiuid, {})
                
                RTPlanLabel = rtplan_dict.get("RTPlanLabel", "NoPlanLabel")
                RTPlanName = rtplan_dict.get("RTPlanName", "NoPlanName")
                RTPlanDate = rtplan_dict.get("RTPlanDate", "NoPlanDate")
                DiseaseSite = rtplan_dict.get("rt_plan_disease_site", "19000101")
                ApprovalStatus = rtplan_dict.get("ApprovalStatus", "NoApprovalStatus")
                Machine = rtplan_dict.get("rt_plan_machine", "NoMachine")
                Dose = rtplan_dict.get("target_prescription_dose_cgy", "NoDose")
                Fxns = rtplan_dict.get("number_of_fractions_planned", "NoFxns")
                
                if "composite" in key[2]:
                    dose_type = "BeamComposite"
                else:
                    dose_type = value().GetMetaData("DoseSummationType").title()
                    if "beam" in dose_type.lower():
                        beam_num = value().GetMetaData("referenced_beam_number")
                        if beam_num:
                            dose_type += beam_num
                
                if rtplan_dict:
                    default_filename = (
                        f"DOSE_{str(dose_type).replace(' ', '-').replace('_', '-')}_"
                        f"{str(num_fxn_planned).replace(' ', '-').replace('_', '-')}Fxns_"
                        f"{str(RTPlanLabel).replace(' ', '-').replace('_', '-')}_"
                        f"{str(RTPlanName).replace(' ', '-').replace('_', '-')}_"
                        f"{str(RTPlanDate).replace(' ', '-').replace('_', '-')}_"
                        f"{str(Machine).replace(' ', '-').replace('_', '-')}"
                    )
                else:
                    default_filename = (
                        f"DOSE_{str(dose_type).replace(' ', '-').replace('_', '-')}_"
                        f"{str(num_fxn_planned).replace(' ', '-').replace('_', '-')}Fxns_"
                        f"{str(SOPIUID).replace(' ', '-').replace('_', '-')}"
                    )
                
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(
                        label=dose_type,
                        height=button_height,
                        tooltip_text=(
                            f"RT Dose Type: {dose_type}\nNumber of Fractions Planned: {num_fxn_planned}\n"
                            f"Number of Fractions RT Dose: {num_fxn_rtdose}\n"
                            f"SOPIUID: {SOPIUID}\nReferenced RT Plan SOPIUID: {referenced_rtplan_sopiuid}\n"
                            f"RT Plan Label: {RTPlanLabel}\nRT Plan Name: {RTPlanName}\n"
                            f"RT Plan Date: {RTPlanDate}\nDisease Site: {DiseaseSite}\n"
                            f"Approval Status: {ApprovalStatus}\nMachine: {Machine}\n"
                            f"Dose: {Dose} cGy\nFractions: {Fxns}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(
                        default_value=True,
                        tooltip_text="Include this item in the bulk save list."
                    )
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
                        default_value=int(num_fxn_rtdose), 
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
                        default_value=int(num_fxn_planned), 
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
                
                save_data_dict["doses"].append({
                    "data": value, 
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
        save_data_dict["execute_bulk_save_tag"] = execute_bulk_save_tag
