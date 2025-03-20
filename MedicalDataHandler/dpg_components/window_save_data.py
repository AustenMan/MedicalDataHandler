import os
import json
import dearpygui.dearpygui as dpg
import SimpleITK as sitk
from dpg_components.custom_utils import get_tag, get_user_data, add_custom_button, add_custom_checkbox
from dpg_components.themes import get_hidden_button_theme
from utils.dpg_utils import get_popup_params, safe_delete
from utils.general_utils import validate_filename, get_traceback
from utils.numpy_utils import create_HU_to_RED_map
from utils.sitk_utils import sitk_to_array, array_to_sitk, sitk_resample_to_reference

def create_save_window(sender, app_data, user_data):
    """ Displays a popup window for saving SITK data, allowing customization of save settings. """
    tag_save_window = get_tag("save_sitk_window")
    tag_save_button = get_tag("save_button")
    config_manager = get_user_data(td_key="config_manager")
    data_manager = get_user_data(td_key="data_manager")
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    size_dict = get_user_data(td_key="size_dict")
    
    popup_width, popup_height, popup_pos = get_popup_params()
    popup_wrap = round(popup_width * 0.9)
    button_height = round(1.5 * dpg.get_text_size("A")[1])
    
    if dpg.does_item_exist(tag_save_window) and (shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive()):
        dpg.configure_item(tag_save_window, width=popup_width, height=popup_height, pos=popup_pos, show=True)
        print(f"An action is in progress. The save data window cannot be refreshed or regenerated until the action(s) complete, so the previous window will be shown.")
        return
    
    safe_delete(tag_save_window)
    
    save_settings_dict = config_manager.get_save_settings_dict()
    data_dict = dpg.get_item_user_data(tag_save_button)
    
    save_data_dict = {"main_checkboxes": {}, "images": [], "rois": [], "plans": [], "doses": []}
    with dpg.window(
        tag=tag_save_window, label="Save Data", width=popup_width, height=popup_height, pos=popup_pos, 
        no_open_over_existing_popup=False, popup=False, modal=False, no_title_bar=False, no_close=True, 
        horizontal_scrollbar=True, user_data=save_data_dict, 
        ):
        add_custom_button(
            label="Close Save Window", callback=_try_close_save_window, add_spacer_before=True, add_separator_after=True, user_data=tag_save_window,
            tooltip_text="Hides the save data window.")
        
        add_custom_button(label="Carefully review the save options below.", theme_tag=get_hidden_button_theme(), add_separator_after=True)
        
        add_custom_button(label="General Options", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_separator_after=True)
        save_data_dict["main_checkboxes"]["keep_custom_params"] = add_custom_checkbox(
            default_value=save_settings_dict["keep_custom_params"], checkbox_label="Save with your current custom data viewing parameters", add_spacer_after=True,
            tooltip_text="If checked, the current data viewing parameters will be saved with the data.\nIf unchecked, the data will be saved with its native/default parameters, such as the size/spacing."
            )
        
        add_custom_button(label="Images", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_separator_after=True)
        save_data_dict["main_checkboxes"]["convert_ct_hu_to_red"] = add_custom_checkbox(
            default_value=save_settings_dict["convert_ct_hu_to_red"], checkbox_label="Map CT Hounsfield Units to Relative Electron Densities", add_spacer_after=True,
            tooltip_text="If checked, the CT Hounsfield Units will be converted to Relative Electron Densities using the HU:RED conversion table."
        )
        save_data_dict["main_checkboxes"]["override_image_with_roi_RED"] = add_custom_checkbox(
            default_value=save_settings_dict["override_image_with_roi_RED"], checkbox_label="Override image(s) with ROI R.E.D. values", add_spacer_after=True,
            tooltip_text=(
                "If checked, the image(s) will be overridden with specified ROI Relative Electron Densities.\n"
                "For example, if titanium has an assigned RED of 4.5, the image will be overridden with this value.\n"
                "If unchecked, the image(s) will be saved as-is."
            )
        )
        with dpg.table(
            resizable=True, reorderable=True, hideable=False, sortable=False, scrollX=True, scrollY=True, row_background=True, 
            header_row=True, freeze_rows=1, borders_innerH=True, borders_innerV=True, borders_outerH=True, borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, context_menu_in_body=True, delay_search=False, pad_outerX=True,
            width=size_dict["table_w"], height=round(popup_height * 0.3)
        ):
            dpg.add_table_column(label="Modality", init_width_or_weight=round(dpg.get_text_size("RT Image")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.25))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.25))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for key, value in data_dict.items():
                if key[0] != "rtimage":
                    continue
                if value() is None:
                    continue
                image_modality = key[1].upper()
                file_date = (value().GetMetaData("SeriesDate") if value().HasMetaDataKey("SeriesDate") else value().GetMetaData("StudyDate") if value().HasMetaDataKey("StudyDate") else None) or "19000101"
                series_instance_uid = key[2]
                default_filename = f"IMAGE_{str(image_modality).replace(' ', '-').replace('_', '-')}_{str(file_date).replace(' ', '-').replace('_', '-')}_{str(series_instance_uid).replace(' ', '-').replace('_', '-')}"
                with dpg.table_row():
                    add_custom_button(
                        label=image_modality, height=button_height,
                        tooltip_text=(
                            f"RT Image Modality: {image_modality}\nFile Date: {file_date}\nSeries Instance UID: {series_instance_uid}\n"
                            f"Size: {value().GetSize()}\nSpacing: {value().GetSpacing()}\nDirection: {value().GetDirection()}\nOrigin: {value().GetOrigin()}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(label="Save", callback=_start_save_action, height=button_height)
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_data_dict["images"].append({"data": value, "modality": image_modality, "filename_tag": filename_tag, "bulksave_tag": bulksave_tag, "save_tag": save_tag})
        
        add_custom_button(label="ROIs", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_separator_after=True)
        with dpg.table(
            resizable=True, reorderable=True, hideable=False, sortable=False, scrollX=True, scrollY=True, row_background=True, 
            header_row=True, freeze_rows=1, borders_innerH=True, borders_innerV=True, borders_outerH=True, borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, context_menu_in_body=True, delay_search=False, pad_outerX=True,
            width=size_dict["table_w"], height=round(popup_height * 0.3)
        ):
            dpg.add_table_column(label="ROI", init_width_or_weight=round(dpg.get_text_size("00. ThisIsAnExampleROIName")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.25))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.25))
            dpg.add_table_column(label="Goals", init_width_or_weight=round(dpg.get_text_size("Goals")[0] * 1.25))
            dpg.add_table_column(label="Rel. Elec. Dens.", init_width_or_weight=round(dpg.get_text_size("00.000")[0] * 3))
            dpg.add_table_column(label="Filename", width_stretch=True)
            for key, value in data_dict.items():
                if key[0] != "rtstruct":
                    continue
                if value() is None:
                    continue
                
                roi_number = value().GetMetaData("roi_number")
                roi_name = value().GetMetaData("current_roi_name")
                rt_roi_interpreted_type = value().GetMetaData("rt_roi_interpreted_type")
                roi_goals = value().GetMetaData("roi_goals")
                roi_goals = json.loads(roi_goals) if roi_goals else {}
                
                roi_physical_properties = value().GetMetaData("roi_physical_properties")
                roi_physical_properties = json.loads(roi_physical_properties) if roi_physical_properties else []
                roi_physical_properties = roi_physical_properties[0] if roi_physical_properties else {}
                roi_physical_property = str(roi_physical_properties.get("roi_physical_property", ""))
                roi_physical_property_value = roi_physical_properties.get("roi_physical_property_value")
                if "bolus" in roi_name.lower() and roi_physical_property_value is None:
                    roi_physical_property_value = 1.0
                if (roi_physical_property and roi_physical_property.lower() != "rel_elec_density") or not isinstance(roi_physical_property_value, (float, int)) or 0.0 > roi_physical_property_value > 15.0:
                    roi_physical_property_value = -1.0
                
                structure_set_dict = data_manager.return_data_from_modality("rtstruct")[key[1]]
                StructureSetLabel = structure_set_dict.get("StructureSetLabel")
                StructureSetName = structure_set_dict.get("StructureSetName")
                StructureSetDate = structure_set_dict.get("StructureSetDate")
                StructureSetTime = structure_set_dict.get("StructureSetTime")
                ReferencedSeriesInstanceUID = structure_set_dict.get("ReferencedSeriesInstanceUID")
                
                default_filename = f"ROI_{roi_name}"
                row_tag = dpg.generate_uuid()
                with dpg.table_row(tag=row_tag):
                    add_custom_button(
                        label=f"{roi_number}. {roi_name}", height=button_height,
                        tooltip_text=(
                            f"ROI Number: {roi_number}\nROI Name: {roi_name}\nROI Type: {rt_roi_interpreted_type}\nSize: {value().GetSize()}\nSpacing: {value().GetSpacing()}\n"
                            f"Direction: {value().GetDirection()}\nOrigin: {value().GetOrigin()}\nStructure Set Label: {StructureSetLabel}\nStructure Set Name: "
                            f"{StructureSetName}\nStructure Set Date: {StructureSetDate}\nStructure Set Time: {StructureSetTime}\nReferenced Series Instance UID: "
                            f"{ReferencedSeriesInstanceUID}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(default_value=not roi_name.startswith("?UNIDENTIFIED?_"), tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(label="Save", callback=_start_save_action, height=button_height)
                    if roi_goals:
                        goals_tag = add_custom_button(label="Goals", height=button_height, tooltip_text=f"ROI Goals: {roi_goals}")
                    else:
                        goals_tag = None
                        dpg.add_text("N/A")
                    
                    roi_phys_prop_tag = dpg.add_input_float(default_value=roi_physical_property_value if not None else -1.0, min_value=-1.0, max_value=15.0, min_clamped=True, max_clamped=True, width=round(dpg.get_text_size("00.000")[0] * 2.5))
                    with dpg.tooltip(parent=roi_phys_prop_tag):
                        dpg.add_text("Relative Electron Density value for this ROI from [0.0 to 15.0]. Negative values will be ignored, so set to -1.0 to ignore.", wrap=size_dict["tooltip_width"])
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_data_dict["rois"].append({"data": value, "filename_tag": filename_tag, "bulksave_tag": bulksave_tag, "save_tag": save_tag, "goals_tag": goals_tag, "roi_phys_prop_tag": roi_phys_prop_tag})
        
        add_custom_button(label="RT Plans", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_separator_after=True)
        with dpg.table(
            resizable=True, reorderable=True, hideable=False, sortable=False, scrollX=True, scrollY=True, row_background=True, 
            header_row=True, freeze_rows=1, borders_innerH=True, borders_innerV=True, borders_outerH=True, borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, context_menu_in_body=True, delay_search=False, pad_outerX=True,
            width=size_dict["table_w"], height=round(popup_height * 0.3)
        ):
            dpg.add_table_column(label="RT Plan", init_width_or_weight=round(dpg.get_text_size("ThisIsAnExampleLabel")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.25))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.25))
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
                
                default_filename = f"PLAN_{str(Fxns).replace(' ', '-').replace('_', '-')}Fxns_{str(RTPlanLabel).replace(' ', '-').replace('_', '-')}_{str(RTPlanName).replace(' ', '-').replace('_', '-')}_{str(RTPlanDate).replace(' ', '-').replace('_', '-')}_{str(Machine).replace(' ', '-').replace('_', '-')}"
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(
                        label=RTPlanLabel, height=button_height,
                        tooltip_text=f"RT Plan Label: {RTPlanLabel}\nRT Plan Name: {RTPlanName}\nRT Plan Date: {RTPlanDate}\nDisease Site: {DiseaseSite}\nApproval Status: {ApprovalStatus}\nMachine: {Machine}\nDose: {Dose} cGy\nFractions: {Fxns}\nSOPIUID: {SOPIUID}"
                    )
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(label="Save", callback=_start_save_action, height=button_height)
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_data_dict["plans"].append({"data": value, "filename_tag": filename_tag, "bulksave_tag": bulksave_tag, "save_tag": save_tag})
        
        add_custom_button(label="RT Doses", theme_tag=get_hidden_button_theme(), add_separator_before=True, add_separator_after=True)
        save_data_dict["main_checkboxes"]["dosesum_name_tag"] = dpg.add_input_text(default_value="DOSE_PlanSum", width=size_dict["table_w"])
        with dpg.tooltip(parent=save_data_dict["main_checkboxes"]["dosesum_name_tag"]):
            dpg.add_text("Filename for the summed dose, if any will exist (based on user selections below).", wrap=size_dict["tooltip_width"])
        with dpg.table(
            resizable=True, reorderable=True, hideable=False, sortable=False, scrollX=True, scrollY=True, row_background=True, 
            header_row=True, freeze_rows=1, borders_innerH=True, borders_innerV=True, borders_outerH=True, borders_outerV=True, 
            policy=dpg.mvTable_SizingFixedFit, context_menu_in_body=True, delay_search=False, pad_outerX=True,
            width=size_dict["table_w"], height=round(popup_height * 0.3)
        ):
            dpg.add_table_column(label="RT Dose", init_width_or_weight=round(dpg.get_text_size("ThisIsAnExampleDose")[0] * 1.25))
            dpg.add_table_column(label="Bulk Save", init_width_or_weight=round(dpg.get_text_size("Bulk Save")[0] * 1.25))
            dpg.add_table_column(label="Save Item", init_width_or_weight=round(dpg.get_text_size("Save Item")[0] * 1.25))
            dpg.add_table_column(label="Add To Dose Sum", init_width_or_weight=round(dpg.get_text_size("Add To Dose Sum")[0] * 1.25))
            dpg.add_table_column(label="# Dose Fxns", init_width_or_weight=round(dpg.get_text_size("# Dose Fxns")[0] * 1.5))
            dpg.add_table_column(label="# Plan Fxns", init_width_or_weight=round(dpg.get_text_size("# Plan Fxns")[0] * 1.5))
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
                rtplan_dict = data_manager.return_data_from_modality("rtplan").get(referenced_rtplan_sopiuid, {})
                
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
                    default_filename = f"DOSE_{str(dose_type).replace(' ', '-').replace('_', '-')}_{str(num_fxn_planned).replace(' ', '-').replace('_', '-')}Fxns_{str(RTPlanLabel).replace(' ', '-').replace('_', '-')}_{str(RTPlanName).replace(' ', '-').replace('_', '-')}_{str(RTPlanDate).replace(' ', '-').replace('_', '-')}_{str(Machine).replace(' ', '-').replace('_', '-')}"
                else:
                    default_filename = f"DOSE_{str(dose_type).replace(' ', '-').replace('_', '-')}_{str(num_fxn_planned).replace(' ', '-').replace('_', '-')}Fxns_{str(SOPIUID).replace(' ', '-').replace('_', '-')}"
                
                with dpg.table_row(user_data=filename_tag):
                    add_custom_button(
                        label=dose_type, height=button_height,
                        tooltip_text=(
                            f"RT Dose Type: {dose_type}\nNumber of Fractions Planned: {num_fxn_planned}\nNumber of Fractions RT Dose: {num_fxn_rtdose}\nSOPIUID: {SOPIUID}\nReferenced RT Plan SOPIUID: {referenced_rtplan_sopiuid}"
                            f"\nRT Plan Label: {RTPlanLabel}\nRT Plan Name: {RTPlanName}\nRT Plan Date: {RTPlanDate}\nDisease Site: {DiseaseSite}\nApproval Status: {ApprovalStatus}\nMachine: {Machine}\nDose: {Dose} cGy\nFractions: {Fxns}"
                        )
                    )
                    bulksave_tag = add_custom_checkbox(default_value=True, tooltip_text="Add this item to the bulk save list.")
                    save_tag = add_custom_button(label="Save", callback=_start_save_action, height=button_height)
                    dosesum_checkbox_tag = add_custom_checkbox(default_value=False, tooltip_text="Any RT Dose items with this checked will be added to create a dose sum (like for a plan sum).")
                    num_dose_fxns_tag = dpg.add_input_int(default_value=int(num_fxn_rtdose), min_value=0, max_value=100, min_clamped=True, max_clamped=True, width=round(dpg.get_text_size("000......")[0] * 1.5))
                    with dpg.tooltip(parent=num_dose_fxns_tag):
                        dpg.add_text("Number of Fractions that the dose currently represents. Value of 0 is ok, but it will not scale the dose.", wrap=size_dict["tooltip_width"])
                    num_plan_fxns_tag = dpg.add_input_int(default_value=int(num_fxn_planned), min_value=0, max_value=100, min_clamped=True, max_clamped=True, width=round(dpg.get_text_size("000......")[0] * 1.5))
                    with dpg.tooltip(parent=num_plan_fxns_tag):
                        dpg.add_text("Number of Fractions that you WANT the dose to represent (typically based on the RT Plan Number of Fractions). Value of 0 is ok, but it will not scale the dose.", wrap=size_dict["tooltip_width"])
                    filename_tag = dpg.add_input_text(default_value=default_filename, width=size_dict["table_w"])
                save_data_dict["doses"].append({"data": value, "filename_tag": filename_tag, "bulksave_tag": bulksave_tag, "save_tag": save_tag, "dosesum_checkbox_tag": dosesum_checkbox_tag, "num_dose_fxns_tag": num_dose_fxns_tag, "num_plan_fxns_tag": num_plan_fxns_tag})
        
        execute_bulk_save_tag = add_custom_button(label="Execute Bulk Save", callback=_start_save_action, add_separator_before=True, add_spacer_after=True)
        save_data_dict["execute_bulk_save_tag"] = execute_bulk_save_tag

def _start_save_action(sender, app_data, user_data):
    """
    Initiates the save operation in a separate thread to avoid blocking the UI.
    
    Args:
        sender (int): The sender tag triggering the save.
        app_data (any): Additional data from the sender.
        user_data (any): Additional data passed by the user.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue() or shared_state_manager.is_cleanup_thread_alive():
        print("The program is already busy with another action. Please wait for the action to complete before starting a new action.")
        return
    
    shared_state_manager.add_action(_execute_saving, sender, app_data, user_data)

def _execute_saving(sender, app_data, user_data):
    """
    Executes the actual save operation for images, ROIs, RT plans, and doses, either in bulk or individually.
    
    Args:
        sender (int): The sender tag that triggered the save.
        app_data (any): Additional data from the sender.
        user_data (any): Additional data passed by the user.
    """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        tag_save_window = get_tag("save_sitk_window")
        tag_ptinfo_button = get_tag("ptinfo_button")
        config_manager = get_user_data(td_key="config_manager")
        
        if not dpg.does_item_exist(tag_ptinfo_button):
            print(f"Error: No patient information found. Cannot save. Please load a patient before saving data.")
            shared_state_manager.action_event.clear()
            return
        
        ptinfo_user_data = dpg.get_item_user_data(tag_ptinfo_button)
        if not isinstance(ptinfo_user_data, (list, tuple)) or len(ptinfo_user_data) != 2:
            print(f"Error: Invalid patient information found. Cannot save. Expected a list or tuple of length 2, but received: {ptinfo_user_data}")
            shared_state_manager.action_event.clear()
            return
        
        active_pt, active_frame_of_reference_uid = ptinfo_user_data
        
        if not active_pt or not active_frame_of_reference_uid:
            print(f"Error: Missing either patient data or frame of reference UID. Canot save. Received: {active_pt}, {active_frame_of_reference_uid}")
            shared_state_manager.action_event.clear()
            return
        
        if not dpg.does_item_exist(tag_save_window):
            shared_state_manager.action_event.clear()
            return
        
        print(f"Starting save action...")
        
        save_data_dict = dpg.get_item_user_data(tag_save_window)
        
        patient_id, patient_name = active_pt.return_patient_info()
        active_pt.update_last_processed()
        
        save_dir = config_manager.get_sitk_data_dir()
        base_save_path = os.path.join(save_dir, patient_id, patient_name, active_frame_of_reference_uid)
        os.makedirs(base_save_path, exist_ok=True)
        
        _process_image_saving(sender, save_data_dict, base_save_path)
        _process_roi_saving(sender, save_data_dict, base_save_path)
        _process_plan_saving(sender, save_data_dict, base_save_path)
        _process_dose_saving(sender, save_data_dict, base_save_path)
        
        if sender == save_data_dict["execute_bulk_save_tag"]:
            print(f"Save action is complete.")
            if dpg.does_item_exist(tag_save_window):
                dpg.hide_item(tag_save_window)
    except Exception as e:
        print(f"Error: An exception occurred during the save action. {get_traceback(e)}")
    finally:
        shared_state_manager.action_event.clear()

def _process_image_saving(sender, save_data_dict, base_save_path):
    """
    Processes the saving of images based on the user's settings. 
    
    Args:
        sender (int): The sender tag that triggered the save.
        save_data_dict (dict): The dictionary containing the save data.
        base_save_path (str): The base save path for the images.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_manager = get_user_data(td_key="data_manager")
    
    convert_ct_hu_to_red = dpg.get_value(save_data_dict["main_checkboxes"]["convert_ct_hu_to_red"])
    override_image_with_roi_RED = dpg.get_value(save_data_dict["main_checkboxes"]["override_image_with_roi_RED"])
    roi_overrides = [(roi_dict["data"], dpg.get_value(roi_dict["roi_phys_prop_tag"])) for roi_dict in save_data_dict["rois"] if dpg.get_value(roi_dict["roi_phys_prop_tag"]) >= 0.0] if override_image_with_roi_RED else []
    
    for image_dict in save_data_dict["images"]:
        if save_in_bulk and not dpg.get_value(image_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != image_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(image_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            print(f"Error: No filename specified for {image_dict['modality']} image. Received: {save_filename}, which was cleaned to: {validated_filename}. Skipping save.")
            continue
        validated_filename = validated_filename.replace("?UNIDENTIFIED?_", "").replace("...", "") # Remove the unidentified prefix, and the "..." if it exists (user forgot to change name and wants to keep struct)
        save_path = os.path.join(base_save_path, validated_filename + ".nii")
        
        image_sitk_ref = image_dict["data"]
        image_sitk = image_sitk_ref()
        if image_sitk is None:
            print(f"Error: No SITK image found for {image_dict['modality']} image. Skipping save.")
            continue
        
        modality = image_dict["modality"]
        if modality.upper().strip() == "CT" and convert_ct_hu_to_red:
            data_array = sitk_to_array(image_sitk)
            data_array = create_HU_to_RED_map()(data_array) # Convert HU to RED
            
            if roi_overrides:
                for roi_sitk_ref, roi_red in roi_overrides:
                    if roi_sitk_ref() is None or roi_red < 0.0:
                        continue
                    roi_array = sitk_to_array(roi_sitk_ref(), bool)
                    data_array[roi_array] = roi_red
            
            new_image_sitk = array_to_sitk(data_array, image_sitk, copy_metadata=True)
        else:
            new_image_sitk = image_sitk
        
        if keep_custom_params:
            new_image_sitk = data_manager._resample_sitk_to_cached_reference(new_image_sitk)
        
        sitk.WriteImage(new_image_sitk, save_path)
        print(f"SITK Image saved to: {save_path}")
    
def _process_roi_saving(sender, save_data_dict, base_save_path):
    """
    Processes the saving of ROIs based on the user's settings.
    
    Args:
        sender (int): The sender tag that triggered the save.
        save_data_dict (dict): The dictionary containing the save data.
        base_save_path (str): The base save path for the ROIs.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_manager = get_user_data(td_key="data_manager")
    
    # Initialize a dictionary to collect ROIs with the same filenames
    roi_files_dict = {}
    for roi_dict in save_data_dict["rois"]:
        if save_in_bulk and not dpg.get_value(roi_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != roi_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(roi_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            print(f"Error: No filename specified for ROI. Received: {save_filename}, which was cleaned to: {validated_filename}. Skipping save.")
            continue
        save_path = os.path.join(base_save_path, validated_filename + ".nii")
        
        roi_sitk_ref = roi_dict["data"]
        roi_sitk = roi_sitk_ref()
        if roi_sitk is None:
            continue
        
        if keep_custom_params:
            roi_sitk = data_manager._resample_sitk_to_cached_reference(roi_sitk)
        
        # Collect roi_sitk images for each validated filename
        if save_path not in roi_files_dict:
            roi_files_dict[save_path] = roi_sitk
        else:
            existing_roi_sitk = roi_files_dict[save_path]
            
            curr_roi_goals = json.loads(existing_roi_sitk.GetMetaData("roi_goals"))
            new_roi_goals = json.loads(data_sitk.GetMetaData("roi_goals"))
            new_roi_goals.update(curr_roi_goals)
            
            existing_roi_array = sitk_to_array(existing_roi_sitk, bool)
            roi_array = sitk_to_array(roi_sitk, bool)
            
            new_roi_array = existing_roi_array + roi_array
            new_roi_sitk = array_to_sitk(new_roi_array, existing_roi_sitk, copy_metadata=True)
            
            new_roi_sitk.SetMetaData("roi_goals", json.dumps(new_roi_goals))
            
            roi_files_dict[save_path] = new_roi_sitk
    
    # After collecting, combine and save the ROIs with the same filenames
    for save_path, data_sitk in roi_files_dict.items():
        sitk.WriteImage(data_sitk, save_path)
        print(f"SITK ROI saved to: {save_path}")

def _process_plan_saving(sender, save_data_dict, base_save_path):
    """
    Processes the saving of RT Plans based on the user's settings.
    
    Args:
        sender (int): The sender tag that triggered the save.
        save_data_dict (dict): The dictionary containing the save data.
        base_save_path (str): The base save path for the RT Plans.
    """
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    
    for plan_dict in save_data_dict["plans"]:
        if save_in_bulk and not dpg.get_value(plan_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != plan_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(plan_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            print(f"Error: No filename specified for RT Plan. Received: {save_filename}, which was cleaned to: {validated_filename}. Skipping save.")
            continue
        save_path = os.path.join(base_save_path, validated_filename + ".json")
        
        rtplan_dict = plan_dict["data"]
        with open(save_path, "wt") as json_file:
            json.dump(rtplan_dict, json_file)
        print(f"RT Plan saved to: {save_path}")

def _process_dose_saving(sender, save_data_dict, base_save_path):
    """
    Processes the saving of RT Doses based on the user's settings.
    
    Args:
        sender (int): The sender tag that triggered the save.
        save_data_dict (dict): The dictionary containing the save data.
        base_save_path (str): The base save path for the RT Doses.
    """
    keep_custom_params = dpg.get_value(save_data_dict["main_checkboxes"]["keep_custom_params"])
    save_in_bulk = sender == save_data_dict["execute_bulk_save_tag"]
    data_manager = get_user_data(td_key="data_manager")
    
    dosesum_name = dpg.get_value(save_data_dict["main_checkboxes"]["dosesum_name_tag"])
    
    dose_sum_list = [data_manager._resample_sitk_to_cached_reference(dose_dict["data"]()) if keep_custom_params else dose_dict["data"]() for dose_dict in save_data_dict["doses"] if dose_dict["data"]() is not None and dpg.get_value(dose_dict["dosesum_checkbox_tag"])]
    if len(dose_sum_list) > 1 and (save_in_bulk or any([sender == dose_dict["save_tag"] and dpg.get_value(dose_dict["dosesum_checkbox_tag"]) for dose_dict in save_data_dict["doses"]])):
        save_filename = dosesum_name
        validated_filename = validate_filename(save_filename)
        if validated_filename:
            save_path = os.path.join(base_save_path, validated_filename + ".nii")
            
            dose_sum_array = sitk_to_array(dose_sum_list[0])
            for dose_sitk in dose_sum_list[1:]:
                dose_sum_array += sitk_to_array(sitk_resample_to_reference(dose_sitk, dose_sum_list[0]))
            dose_sum_sitk = array_to_sitk(dose_sum_array, dose_sum_list[0], copy_metadata=True)
            dose_sum_sitk.SetMetaData("DoseSummationType", "MULTI_PLAN")
            
            sitk.WriteImage(dose_sum_sitk, save_path)
        else:
            print(f"Error: No filename specified for RT Dose Sum. Received: {save_filename}, which was cleaned to: {validated_filename}. Skipping save.")
    
    for dose_dict in save_data_dict["doses"]:
        if save_in_bulk and not dpg.get_value(dose_dict["bulksave_tag"]):
            continue
        elif not save_in_bulk and sender != dose_dict["save_tag"]:
            continue
        
        save_filename = dpg.get_value(dose_dict["filename_tag"])
        validated_filename = validate_filename(save_filename)
        if not validated_filename:
            print(f"Error: No filename specified for RT Dose. Received: {save_filename}, which was cleaned to: {validated_filename}. Skipping save.")
            continue
        save_path = os.path.join(base_save_path, validated_filename + ".nii")
        
        dose_sitk_ref = dose_dict["data"]
        dose_sitk = dose_sitk_ref()
        if dose_sitk is None:
            continue
        
        if keep_custom_params:
            dose_sitk = data_manager._resample_sitk_to_cached_reference(dose_sitk)
        
        num_dose_fxns = dpg.get_value(dose_dict["num_dose_fxns_tag"])
        num_plan_fxns = dpg.get_value(dose_dict["num_plan_fxns_tag"])
        if num_dose_fxns and num_plan_fxns and num_dose_fxns > 0 and num_plan_fxns > 0 and num_dose_fxns != num_plan_fxns:
            scaling_ratio = num_plan_fxns / num_dose_fxns
            dose_array = sitk_to_array(dose_sitk) * scaling_ratio
            new_dose_sitk = array_to_sitk(dose_array, dose_sitk, copy_metadata=True)
        else:
            new_dose_sitk = dose_sitk
        
        sitk.WriteImage(new_dose_sitk, save_path)
        print(f"SITK RT Dose saved to: {save_path}")

def _try_close_save_window():
    """ Attempts to close the save window if it exists. """
    tag_save_window = get_tag("save_sitk_window")
    if not dpg.does_item_exist(tag_save_window):
        return
    
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.is_action_in_queue():
        print("The program is currently busy saving data. Please wait for action completion.")
        return
    
    safe_delete(tag_save_window)

    
    
    