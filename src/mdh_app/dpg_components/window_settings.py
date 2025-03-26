import logging
import dearpygui.dearpygui as dpg
from typing import Any, Union, Dict, Tuple, List, Set

from mdh_app.dpg_components.custom_utils import get_tag, get_user_data
from mdh_app.dpg_components.texture_updates import request_texture_update
from mdh_app.dpg_components.popup_orientation_labels import create_orientation_label_color_picker
from mdh_app.managers.config_manager import ConfigManager
from mdh_app.utils.dpg_utils import get_popup_params, safe_delete, verify_input_directory

logger = logging.getLogger(__name__)

def create_settings_window(refresh: bool = False) -> None:
    """
    Create and manage the Settings window with various configuration options.
    
    If refresh is True, the window is deleted and recreated.
    Otherwise, if the window exists, its visibility and dimensions are toggled.
    """
    # Get tag and check if the window should be refreshed
    tag_isw = get_tag("settings_window")
    
    # Get popup params
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # If refresh is requested, delete the window and make a new one
    if refresh:
        safe_delete(tag_isw)
    # Toggle the window, also keep its size/position updated
    elif dpg.does_item_exist(tag_isw):
        show_popup = not dpg.is_item_shown(tag_isw)
        if show_popup:
            dpg.configure_item(tag_isw, width=popup_width, height=popup_height, pos=popup_pos, show=show_popup)
        else:
            dpg.configure_item(tag_isw, show=show_popup)
        return
    
    # Get necessary parameters
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    size_dict: Dict[str, Any] = get_user_data(td_key="size_dict")
    default_display_dict: Dict[str, Any] = get_user_data(td_key="default_display_dict")
    
    # Create the window
    dpg.add_window(
        tag=tag_isw, 
        label="Settings", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos,
        no_open_over_existing_popup=False, 
        show=False, 
        on_close=lambda: dpg.configure_item(tag_isw, show=False)
    )
    
    # Fill the window
    _fill_gui_settings(tag_isw, size_dict, conf_mgr)
    _fill_overlay_settings(tag_isw, size_dict)
    _fill_interactivity_settings(tag_isw, size_dict, conf_mgr)
    _fill_data_rot_flip_controls(tag_isw, size_dict, default_display_dict)
    _fill_data_view_controls(tag_isw, size_dict, default_display_dict)
    _fill_windowing_controls(tag_isw, size_dict, conf_mgr, default_display_dict)
    _fill_spacing_controls(tag_isw, size_dict, conf_mgr, default_display_dict)

def _fill_gui_settings(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    conf_mgr: ConfigManager
) -> None:
    """ Add GUI Settings """
    # Pre-generate tags for the input fields
    tag_WH_mode_toggle = dpg.generate_uuid()
    tag_width = dpg.generate_uuid()
    tag_height = dpg.generate_uuid()
    tags_popup_settings: Tuple[str, str, str] = (tag_WH_mode_toggle, tag_width, tag_height)
    
    # Get screen mode settings
    mode_options: List[str] = ["Percentage", "Pixels"]
    default_mode = conf_mgr.get_screen_size_input_mode()
    if not default_mode or not default_mode in mode_options:
        default_mode = "Percentage"
    
    # Get screen size settings
    current_screen_size = conf_mgr.get_screen_size()
    max_screen_size = conf_mgr.get_max_screen_size()
    default_width = round(current_screen_size[0] / max_screen_size[0] * 100) if default_mode == "Percentage" else current_screen_size[0]
    default_height = round(current_screen_size[1] / max_screen_size[1] * 100) if default_mode == "Percentage" else current_screen_size[1]
    width_limits, height_limits = _get_screen_limits(default_mode)
    default_width = min(max(default_width, width_limits[0]), width_limits[1])
    default_height = min(max(default_height, height_limits[0]), height_limits[1])
    
    # Get font settings
    font_dict: Dict[str, int] = conf_mgr.get_fonts() or {}
    font_items: List[str] = list(font_dict.keys())
    default_font: str = conf_mgr.get_user_config_font()
    if not default_font or default_font not in font_dict:
        default_font = next(iter(font_dict.keys())) if font_dict else ""
    default_font_scale: float = conf_mgr.get_font_scale()
    font_scale_limits: Tuple[float, float] = (0.5, 1.5)
    
    # Add GUI settings input fields
    with dpg.tree_node(label="GUI", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)
            
            # App W/H Mode Toggle
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Toggle between percentage of screen size and pixel values for the application size.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Application Size Mode: ")
                dpg.add_radio_button(
                    items=mode_options, 
                    horizontal=True, 
                    tag=tag_WH_mode_toggle, 
                    default_value=default_mode, 
                    user_data=tags_popup_settings, 
                    callback=_update_gui_size_mode
                )

            # App Width
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the application's total width (% of screen size or # pixels)", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Application Width: ")
                dpg.add_input_int(
                    tag=tag_width, 
                    default_value=default_width, 
                    user_data=tags_popup_settings, 
                    min_clamped=False, 
                    max_clamped=False, 
                    on_enter=True,
                    width=size_dict["button_width"], 
                    callback=_update_gui_size
                )
                
            # App Height
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the application's total height (% of screen size or # pixels)", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Application Height: ")
                dpg.add_input_int(
                    tag=tag_height, 
                    default_value=default_height, 
                    user_data=tags_popup_settings, 
                    min_clamped=False, 
                    max_clamped=False, 
                    on_enter=True,
                    width=size_dict["button_width"], 
                    callback=_update_gui_size
                )
            
            # App Font Choice
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the application's font type.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Application Font Choice: ")
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        items=font_items,
                        default_value=default_font, 
                        user_data=default_font, 
                        width=size_dict["button_width"], 
                        callback=_update_gui_font
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # App Font Scale
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the application's font scale (multiplicative factor).", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Application Font Scale: ")
                dpg.add_input_float(
                    default_value=default_font_scale, 
                    min_value=font_scale_limits[0], 
                    max_value=font_scale_limits[1],
                    min_clamped=True, 
                    max_clamped=True, 
                    on_enter=True,
                    width=size_dict["button_width"], 
                    callback=_update_gui_font_scale
                )
            
            # JSON Objectives Filename
            tag_json_obj_fn_error = dpg.generate_uuid()
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Setting for JSON objectives filename (Note: default location is assumed to be the config folder)", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("JSON Objectives Filename: ")
                with dpg.group(horizontal=False):
                    dpg.add_input_text(
                        tag=get_tag("input_objectives_filename"),
                        default_value=conf_mgr.get_objectives_filename(),
                        user_data=("json_objective_filename", tag_json_obj_fn_error), # Config key, error tag
                        width=size_dict["button_width"],
                        callback=_update_filename_settings,
                    )
                    # JSON objectives filename error message
                    dpg.add_text(
                        tag=tag_json_obj_fn_error, 
                        default_value="", 
                        wrap=size_dict["button_width"], 
                        color=(192, 57, 43)
                    )

def _fill_overlay_settings(tag_parent: Union[str, int], size_dict: Dict[str, Any]) -> None:
    """ Add Image Overlay Settings """
    with dpg.tree_node(label="Image Overlay", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)

            # Toggle Crosshairs
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Toggle the display of slice crosshairs", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Toggle Crosshairs:")
                dpg.add_checkbox(
                    tag=get_tag("img_tags")["show_crosshairs"], 
                    default_value=True, 
                    callback=request_texture_update, 
                    user_data=True
                )
            
            # Toggle Orientation Labels
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Toggle the display of orientation labels", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Toggle Orientation Labels:")
                dpg.add_checkbox(
                    tag=get_tag("img_tags")["show_orientation_labels"], 
                    default_value=True, 
                    callback=request_texture_update, 
                    user_data=True
                )
            
            # Orientation Label Color
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Change the color of the orientation labels", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Orientation Label Color:")
                dpg.add_button(
                    label="Change orientation label color", 
                    width=size_dict["button_width"], 
                    callback=create_orientation_label_color_picker
                )

def _fill_interactivity_settings(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    conf_mgr: ConfigManager
) -> None:
    """ Add Image Interactivity Settings """
    # Get panning parameters
    current_pan_speed = conf_mgr.get_pan_speed()
    pan_speed_dict = {"Slow": 0.01, "Medium": 0.02, "Fast": 0.04}
    pan_speed_default_val = next((speed for speed, val in pan_speed_dict.items() if val == current_pan_speed), "Medium")
    
    # Get zoom factor parameters
    current_zoom_factor = conf_mgr.get_zoom_factor()
    zoom_factor_dict = {"Slow": 0.05, "Medium": 0.1, "Fast": 0.15}
    zoom_factor_default_val = next((zf for zf, val in zoom_factor_dict.items() if val == current_zoom_factor), "Medium")
    
    # Add to the window
    with dpg.tree_node(label="Interactivity", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)
        
            # Panning Speed
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the panning speed", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Panning Speed:")
                dpg.add_combo(
                    tag=get_tag("img_tags")["pan_speed"], 
                    items=list(pan_speed_dict.keys()), 
                    default_value=pan_speed_default_val, 
                    user_data=pan_speed_dict, 
                    width=size_dict["button_width"], 
                    callback=_update_panning_speed
                )
            
            # Zoom Speed
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the zoom speed", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Zoom Speed:")
                dpg.add_combo(
                    tag=get_tag("img_tags")["zoom_factor"], 
                    items=list(zoom_factor_dict.keys()), 
                    default_value=zoom_factor_default_val, 
                    user_data=zoom_factor_dict, 
                    width=size_dict["button_width"], 
                    callback=_update_zoom_factor
                )

def _fill_data_rot_flip_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    default_display_dict: Dict[str, Any]
) -> None:
    """ Add Data Rotations and Flips Settings """
    # Get rotation parameters
    rotations: List[str] = ["0", "90", "180", "270"]
    backup_rotation: str = rotations[0]
    default_rotation: str = str(default_display_dict.get("ROTATION", backup_rotation))
    if default_rotation not in rotations:
        default_rotation = backup_rotation
    
    # Get flip parameters
    flip_defaults = [
        bool(default_display_dict.get("FLIP_LR", False)), 
        bool(default_display_dict.get("FLIP_AP", False)), 
        bool(default_display_dict.get("FLIP_SI", False))
    ]
    flip_tag_dict = {
        "LR": get_tag("img_tags")["flip_lr"], 
        "AP": get_tag("img_tags")["flip_ap"], 
        "SI": get_tag("img_tags")["flip_si"]
    }
    
    # Update default display dict
    default_display_dict.update({
        "ROTATION": default_rotation, 
        "FLIP_LR": flip_defaults[0], 
        "FLIP_AP": flip_defaults[1], 
        "FLIP_SI": flip_defaults[2]
    })
    
    with dpg.tree_node(label="Data Rotations and Flip Controls", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)

            # Rotate Data
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Rotate the data orientation by 0, 90, 180, or 270 degrees.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Rotate Data (degrees):")
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        tag=get_tag("img_tags")["rotation"], 
                        items=rotations, 
                        default_value=default_rotation, 
                        user_data=default_rotation, 
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # Flip Data
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Flip the data orientation along the chosen axis.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Flip Data:")
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Reset", 
                        user_data=list(flip_tag_dict.values()), 
                        callback=_reset_setting
                    )
                    for (axis, tag), flip_default in zip(flip_tag_dict.items(), flip_defaults):
                        if axis == "LR":
                            flip_type = "left/right"
                        elif axis == "AP":
                            flip_type = "anterior/posterior"
                        elif axis == "SI":
                            flip_type = "superior/inferior"
                        else:
                            flip_type = "unknown"
                        
                        with dpg.group(horizontal=True):
                            with dpg.tooltip(parent=dpg.last_item()):
                                dpg.add_text(
                                    f"Flip data along the {flip_type} axis.", 
                                    wrap=size_dict["tooltip_width"]
                                )
                            dpg.add_text(f"{axis}:")
                            dpg.add_checkbox(
                                tag=tag, 
                                default_value=flip_default, 
                                callback=request_texture_update, 
                                user_data=flip_default
                            )
    
def _fill_data_view_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    default_display_dict: Dict[str, Any]
) -> None:
    """ Add Data View Controls """
    # Get dim ranges
    backup_dim_ranges: List[Tuple[int, int]] = [(0, 599), (0, 599), (0, 599)]
    default_dim_ranges = default_display_dict.get("RANGES", backup_dim_ranges)
    if not (
        isinstance(default_dim_ranges, (list, tuple)) and 
        len(default_dim_ranges) == 3 and 
        all(
            isinstance(val, (list, tuple)) and 
            len(val) == 2 and 
            all(isinstance(v, int) for v in val) 
            for val in default_dim_ranges
        )
    ):
        default_dim_ranges = backup_dim_ranges
    # Clamp to >= 0, and dim_max at least 1 greater than dim_min
    default_dim_ranges = [(max(dim_min, 0), max(max(dim_min, 0) + 1, dim_max)) for dim_min, dim_max in default_dim_ranges]
    
    # Get viewed slices
    backup_view_slices: List[int] = [(dim_max + 1) // 2 for _, dim_max in default_dim_ranges]
    default_view_slices = default_display_dict.get("SLICE_VALS", backup_view_slices)
    if not (
        isinstance(default_view_slices, (list, tuple)) and 
        len(default_view_slices) == 3 and 
        all(isinstance(val, int) for val in default_view_slices)
    ):
        default_view_slices = backup_view_slices
    # Clamp to the dimension ranges
    default_view_slices = [min(max(val, dim_min), dim_max) for val, (dim_min, dim_max) in zip(default_view_slices, default_dim_ranges)]
    
    # Get alphas
    backup_alphas: List[int] = [100, 100, 40]
    alpha_limits: Tuple[int, int] = (0, 100)
    default_alphas = default_display_dict.get("DISPLAY_ALPHAS", backup_alphas)
    if not (
        isinstance(default_alphas, (list, tuple)) and 
        len(default_alphas) == 3 and 
        all(isinstance(val, int) for val in default_alphas)
    ):
        default_alphas = backup_alphas
    # Clamp to limits
    default_alphas = [min(max(val, alpha_limits[0]), alpha_limits[1]) for val in default_alphas]
    
    # Get dose range
    backup_dose_range: List[int] = [0, 100]
    dose_range_limits: Tuple[int, int] = (0, 100)
    default_dose_range = default_display_dict.get("DOSE_RANGE", backup_dose_range)
    if not (
        isinstance(default_dose_range, (list, tuple)) and 
        len(default_dose_range) == 2 and 
        all(isinstance(val, int) for val in default_dose_range)
    ):
        default_dose_range = backup_dose_range
    # Clamp to limits
    default_dose_range = [min(max(val, dose_range_limits[0]), dose_range_limits[1]) for val in default_dose_range]
    
    # Get contour thickness
    backup_contour_thickness: int = 1
    cthick_limits: Tuple[int, int] = (0, 10)
    default_contour_thickness = default_display_dict.get("CONTOUR_THICKNESS", backup_contour_thickness)
    if not isinstance(default_contour_thickness, int):
        default_contour_thickness = backup_contour_thickness
    # Clamp to limits
    default_contour_thickness = min(max(default_contour_thickness, cthick_limits[0]), cthick_limits[1])
    
    # Update default display dict
    default_display_dict.update({
        "RANGES": default_dim_ranges,
        "SLICE_VALS": default_view_slices,
        "DISPLAY_ALPHAS": default_alphas,
        "DOSE_RANGE": default_dose_range,
        "CONTOUR_THICKNESS": default_contour_thickness
    })
    
    # Add to the window
    with dpg.tree_node(label="Data View Controls", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)
        
            # Viewed Slices
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust viewed slices for X, Y, and Z dimensions.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Viewed Slices:")
                with dpg.group(horizontal=True):
                    dpg.add_input_intx(
                        tag=get_tag("img_tags")["viewed_slices"], 
                        size=len(default_view_slices), 
                        default_value=default_view_slices, 
                        user_data=default_view_slices, 
                        min_value=min([dim_min for dim_min, _ in default_dim_ranges]),
                        max_value=max([dim_max for _, dim_max in default_dim_ranges]),
                        min_clamped=True, 
                        max_clamped=True, 
                        on_enter=True,
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # Display Alphas
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust alpha blending for: Images / Masks / Doses", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Display Percentage:")
                with dpg.group(horizontal=True):
                    dpg.add_input_intx(
                        tag=get_tag("img_tags")["display_alphas"], 
                        size=len(default_alphas), 
                        default_value=default_alphas, 
                        user_data=default_alphas, 
                        min_value=alpha_limits[0], 
                        max_value=alpha_limits[1], 
                        min_clamped=True, 
                        max_clamped=True, 
                        on_enter=True,
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # Dose Display Range
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the minimum and maximum percentages for dose display.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Dose Display Range (% DMax):")
                with dpg.group(horizontal=True):
                    dpg.add_input_intx(
                        tag=get_tag("img_tags")["dose_thresholds"], 
                        size=len(default_dose_range), 
                        default_value=default_dose_range, 
                        user_data=default_dose_range, 
                        min_value=dose_range_limits[0], 
                        max_value=dose_range_limits[1], 
                        min_clamped=True, 
                        max_clamped=True, 
                        on_enter=True,
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # Contour Thickness
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the contour thickness.", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Contour Thickness:")
                with dpg.group(horizontal=True):
                    dpg.add_input_int(
                        tag=get_tag("img_tags")["contour_thickness"], 
                        default_value=default_contour_thickness, 
                        user_data=default_contour_thickness, 
                        min_value=cthick_limits[0], 
                        max_value=cthick_limits[1],
                        min_clamped=True, 
                        max_clamped=True, 
                        on_enter=True,
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
            
            # Dimension Ranges
            for axis, default_dim_range in zip(["X", "Y", "Z"], default_dim_ranges):
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        with dpg.tooltip(parent=dpg.last_item()):
                            dpg.add_text(
                                f"Adjust the range of the {axis} dimension.", 
                                wrap=size_dict["tooltip_width"]
                            )
                        dpg.add_text(f"{axis} Dimension Range:")
                    with dpg.group(horizontal=True):
                        dpg.add_input_intx(
                            tag=get_tag("img_tags")[f"{axis.lower()}range"], 
                            size=len(default_dim_range),
                            default_value=default_dim_range, 
                            user_data=default_dim_range, 
                            min_value=default_dim_range[0], 
                            max_value=default_dim_range[1], 
                            min_clamped=True, 
                            max_clamped=True, 
                            on_enter=True,
                            width=size_dict["button_width"], 
                            callback=request_texture_update
                        )
                        dpg.add_button(
                            label="Reset", 
                            before=dpg.last_item(), 
                            user_data=dpg.last_item(), 
                            callback=_reset_setting
                        )

def _fill_windowing_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    conf_mgr: ConfigManager,
    default_display_dict: Dict[str, Any]
) -> None:
    """ Add Windowing Controls """
    # Get preset dict
    window_preset_dict = conf_mgr.get_window_presets()
    
    # Get default preset
    backup_preset = "Custom" if not window_preset_dict else list(window_preset_dict.keys())[0]
    default_preset: str = default_display_dict.get("IMAGE_WINDOW_PRESET", backup_preset)
    if not window_preset_dict or not default_preset in window_preset_dict:
        default_preset = backup_preset
    
    # Get window width
    backup_ww: int = 375
    ww_limits: Tuple[int, int] = (0, 4000)
    default_ww = default_display_dict.get("IMAGE_WINDOW_WIDTH", backup_ww)
    if not isinstance(default_ww, (int, float)):
        default_ww = backup_ww
    default_ww = int(min(max(default_ww, ww_limits[0]), ww_limits[1]))
    
    # Get window level
    backup_wl: int = 40
    wl_limits: Tuple[int, int] = (-1024, 1024)
    default_wl = default_display_dict.get("IMAGE_WINDOW_LEVEL", backup_wl)
    if not isinstance(default_wl, (int, float)):
        default_wl = backup_wl
    default_wl = int(min(max(default_wl, wl_limits[0]), wl_limits[1]))
    
    # Backup if no preset dict
    if not window_preset_dict:
        window_preset_dict = {default_preset: (default_ww, default_wl)}
    
    window_preset_items: List[str] = list(window_preset_dict.keys())
    
    # Update default display dict
    default_display_dict.update({
        "IMAGE_WINDOW_PRESET": default_preset,
        "IMAGE_WINDOW_WIDTH": default_ww,
        "IMAGE_WINDOW_LEVEL": default_wl
    })
    
    # Add to the window
    with dpg.tree_node(label="Windowing Controls", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)
        
            # Window Presets
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the window presets", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Window Presets:")
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        tag=get_tag("img_tags")["window_preset"], 
                        items=window_preset_items, 
                        default_value=default_preset, 
                        user_data=default_preset, 
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
                
            # Window Width
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the window width", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Window Width:")
                with dpg.group(horizontal=True):
                    dpg.add_slider_int(
                        tag=get_tag("img_tags")["window_width"], 
                        default_value=default_ww, 
                        user_data=default_ww, 
                        min_value=ww_limits[0], 
                        max_value=ww_limits[1], 
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )
                
            # Window Level
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the window level", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Window Level:")
                with dpg.group(horizontal=True):
                    dpg.add_slider_int(
                        tag=get_tag("img_tags")["window_level"], 
                        default_value=default_wl, 
                        user_data=default_wl, 
                        min_value=wl_limits[0], 
                        max_value=wl_limits[1], 
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )

def _fill_spacing_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    conf_mgr: ConfigManager,
    default_display_dict: Dict[str, Any]
) -> None:
    """ Add Voxel Spacing Controls """
    # Get the default voxel spacing
    backup_voxel_spacing: List[float] = [3.0, 3.0, 3.0]
    voxel_spacing_limits: Tuple[float, float] = (0.5, 10.0)
    default_voxel_spacing = default_display_dict.get("VOXEL_SPACING", backup_voxel_spacing)
    if not (
        isinstance(default_voxel_spacing, (list, tuple)) and 
        len(default_voxel_spacing) == 3 and 
        all(isinstance(val, (int, float)) for val in default_voxel_spacing)
    ):
        default_voxel_spacing = backup_voxel_spacing
    # Clamp to limits
    default_voxel_spacing = [min(max(val, voxel_spacing_limits[0]), voxel_spacing_limits[1]) for val in default_voxel_spacing]
    
    # Update default display dict
    default_display_dict.update({"VOXEL_SPACING": default_voxel_spacing})
    
    # Add to the window
    with dpg.tree_node(label="Voxel Spacing Controls", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)

            # Voxel Spacing
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=(
                                "Adjust the voxel spacing in mm (X, Y, Z). Type, then press Enter to "
                                "confirm change. Input will be contained to values between 0.5mm and 10mm."
                            ),
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Voxel Spacing (mm):")
                with dpg.group(horizontal=True):
                    # Checkbox for using config voxel spacing
                    dpg.add_checkbox(
                        tag=get_tag("img_tags")["voxel_spacing_cbox"], 
                        default_value=conf_mgr.get_bool_use_config_voxel_spacing(),
                        callback=_update_spacing_settings
                    )
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=(
                                "Checked: Use the config voxel spacing (a standardized spacing) for all "
                                "patients. Unchecked: Only use the data's native voxel spacing."
                            ), 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_input_floatx(
                        tag=get_tag("img_tags")["voxel_spacing"], 
                        size=len(default_voxel_spacing), 
                        default_value=default_voxel_spacing, 
                        user_data=default_voxel_spacing, 
                        min_value=voxel_spacing_limits[0],
                        max_value=voxel_spacing_limits[1], 
                        min_clamped=True, 
                        max_clamped=True, 
                        on_enter=True,
                        width=size_dict["button_width"], 
                        callback=request_texture_update
                    )
                    dpg.add_button(
                        label="Reset", 
                        before=dpg.last_item(), 
                        user_data=dpg.last_item(), 
                        callback=_reset_setting
                    )

def _reset_setting(
    sender: Union[str, int], 
    app_data: Any, 
    user_data: Union[List, Tuple, Set, str, int]
) -> None:
    """
    Reset a UI element to its default value and trigger its callback.
    
    Args:
        sender: The item that triggered the reset.
        app_data: Additional data from the sender.
        user_data: The tag(s) of the item(s) to reset.
    """
    if isinstance(user_data, (list, tuple, set)):
        for item_tag in user_data:
            _reset_setting(sender, app_data, item_tag)
        return
    
    item_tag = user_data
    
    item_default_value = dpg.get_item_user_data(item_tag)
    item_callback = dpg.get_item_callback(item_tag)
    
    dpg.set_value(item=item_tag, value=item_default_value)
    if callable(item_callback):
        item_callback(item_tag, item_default_value, item_default_value)

def _update_spacing_settings(sender: Union[str, int], app_data: bool, user_data: Any) -> None:
    """
    Update the voxel spacing based on the checkbox state and config settings.
    
    Args:
        sender: The checkbox item.
        app_data: The new checkbox state.
        user_data: Additional user data.
    """
    # Update the config manager checkbox setting
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    use_config_voxel_spacing = app_data
    conf_mgr.update_user_config({"use_config_voxel_spacing": use_config_voxel_spacing})
    
    tag_spacing = get_tag("img_tags")["voxel_spacing"]
    if use_config_voxel_spacing:
        config_spacing = conf_mgr.get_voxel_spacing()
        dpg.set_value(tag_spacing, config_spacing)
    else:
        default_spacing = dpg.get_item_user_data(tag_spacing)
        dpg.set_value(tag_spacing, default_spacing)
    
    request_texture_update(texture_action_type="update")

def _update_gui_font(sender: Union[str, int], app_data: str, user_data: Any) -> None:
    """
    Update the GUI font based on the selected font name.
    
    Args:
        sender: The font selection widget.
        app_data: The selected font name.
        user_data: Additional user data.
    """
    font_name: str = app_data
    if not font_name:
        logger.error(f"No font name was selected; no change will be made.")
        dpg.set_value(sender, "")
        return
    
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    font_dict: Dict[str, int] = conf_mgr.get_fonts()
    if not font_dict or font_name not in font_dict:
        logger.error(f"Font '{font_name}' is not valid in the configuration; no change will be made.")
        dpg.set_value(sender, "")
        return
    
    font_size: int = font_dict.get(font_name)
    if not font_size or not isinstance(font_size, int) or font_size <= 0:
        logger.error(f"Font size '{font_size}' for font '{font_name}' is invalid; no change will be made.")
        dpg.set_value(sender, "")
        return

    font_tag = get_tag("font")
    if not dpg.does_item_exist(font_tag):
        logger.error(f"Font tag '{font_tag}' does not exist; no change will be made.")
        dpg.set_value(sender, "")
        return

    font_fpath = conf_mgr.get_font_file_path(font_name + ".ttf")
    if font_fpath is None:
        logger.error(f"The specified font file '{font_name}' does not exist in the font folder; no change will be made.")
        dpg.set_value(sender, "")
        return
    
    # Update the font in the configuration file
    conf_mgr.update_user_config({"font": font_name})
    
    # Update the displayed font
    dpg.set_value(sender, font_name)
    
    safe_delete(font_tag)
    dpg.add_font(tag=font_tag, parent=get_tag("font_registry"), file=font_fpath, size=font_size)
    dpg.bind_font(font_tag)
    
    request_texture_update(texture_action_type="update")

def _update_gui_size(
    sender: Union[str, int],
    app_data: Any, 
    user_data: Tuple[Union[str, int], Union[str, int], Union[str, int]]
) -> None:
    """
    Update the application viewport size based on user input.
    
    Args:
        sender: The widget that triggered the update.
        app_data: The new value.
        user_data: A tuple containing tags for size mode toggle, width, and height.
    """
    tag_WH_mode_toggle, tag_width, tag_height = user_data
    
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    max_screen_size = conf_mgr.get_max_screen_size()
    mode = dpg.get_value(tag_WH_mode_toggle)
    width_limits, height_limits = _get_screen_limits(mode)
    
    width = min(max(dpg.get_value(tag_width), width_limits[0]), width_limits[1])
    height = min(max(dpg.get_value(tag_height), height_limits[0]), height_limits[1])
    new_screen_size = (round(max_screen_size[0] * width / 100), round(max_screen_size[1] * height / 100)) if mode == "Percentage" else (width, height)
    
    dpg.set_value(tag_width, width)
    dpg.set_value(tag_height, height)
    
    conf_mgr.update_user_config({"screen_size": new_screen_size})
    
    request_texture_update(texture_action_type="update")

def _update_gui_size_mode(
    sender: Union[str, int], 
    app_data: str, 
    user_data: Tuple[Union[str, int], Union[str, int], Union[str, int]]
) -> None:
    """
    Update the screen size mode and adjust width/height values accordingly.
    
    Args:
        sender: The widget that triggered the update.
        app_data: The new mode ('Percentage' or 'Pixels').
        user_data: A tuple containing tags for mode toggle, width, and height.
    """
    mode: str = app_data
    tag_WH_mode_toggle, tag_width, tag_height = user_data
    
    if mode not in ["Percentage", "Pixels"]:
        logger.error(f"Mode '{mode}' is invalid; defaulting to 'Percentage'.")
        mode = "Percentage"
        dpg.set_value(tag_WH_mode_toggle, mode)
    
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    prev_mode = conf_mgr.get_screen_size_input_mode()
    max_screen_size = conf_mgr.get_max_screen_size()
    width_limits, height_limits = _get_screen_limits(mode)
    width, height = dpg.get_value(tag_width), dpg.get_value(tag_height)
    
    # Convert width/height values if mode changed and update config
    if mode != prev_mode:
        if mode == "Percentage":
            width = round(width / max_screen_size[0] * 100)
            height = round(height / max_screen_size[1] * 100)
        elif mode == "Pixels":
            width = round(width * max_screen_size[0] / 100)
            height = round(height * max_screen_size[1] / 100)
        conf_mgr.update_user_config({"screen_size_input_mode": mode})
    
    # Ensure width and height are within limits
    width = min(max(width, width_limits[0]), width_limits[1])
    height = min(max(height, height_limits[0]), height_limits[1])
    
    dpg.set_value(tag_width, width)
    dpg.set_value(tag_height, height)
    request_texture_update(texture_action_type="update")

def _update_gui_font_scale(sender: Union[str, int], app_data: float, user_data: Any) -> None:
    """
    Update the GUI font scale.
    
    Args:
        sender: The font scale widget.
        app_data: The new font scale value.
        user_data: Additional user data.
    """
    font_scale = app_data
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"font_scale": font_scale})
    dpg.set_global_font_scale(font_scale)
    request_texture_update(texture_action_type="update")

def _update_filename_settings(
    sender: Union[str, int], 
    app_data: str, 
    user_data: Tuple[Union[str, int], Union[str, int]]
) -> None:
    """
    Update settings based on the JSON objectives filename input.
    
    Args:
        sender: The input text widget.
        app_data: The new filename.
        user_data: A tuple containing the config key and error message tag.
    """
    input_tag = sender
    input_text = app_data
    config_key, error_tag = user_data
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    previous_text = conf_mgr.get_user_setting(config_key)

    configs_dir = conf_mgr.get_configs_dir()
    if not verify_input_directory(configs_dir, input_tag, error_tag):
        dpg.set_value(input_tag, previous_text)
        return

    conf_mgr.update_user_config({config_key: input_text})
    dpg.configure_item(error_tag, default_value=f"Filename saved for {config_key}: {input_text}", color=(39, 174, 96))

def _update_panning_speed(
    sender: Union[str, int],
    app_data: str,
    user_data: Dict[str, Union[float, int]]
) -> None:
    """
    Update the panning speed setting.
    
    Args:
        sender: The panning speed widget.
        app_data: The selected speed key ('Slow', 'Medium', 'Fast').
        user_data: A dictionary mapping speed keys to their numerical values.
    """
    pan_speed_key = app_data
    pan_speed_dict = user_data
    pan_speed_value = pan_speed_dict[pan_speed_key]
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"pan_speed": pan_speed_value})

def _update_zoom_factor(
    sender: Union[str, int],
    app_data: str,
    user_data: Dict[str, Union[float, int]]
) -> None:
    """
    Update the zoom factor setting.
    
    Args:
        sender: The zoom factor widget.
        app_data: The selected speed key ('Slow', 'Medium', 'Fast').
        user_data: A dictionary mapping speed keys to their numerical values.
    """
    zoom_factor_key = app_data
    zoom_factor_dict = user_data
    zoom_factor_value = zoom_factor_dict[zoom_factor_key]
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"zoom_factor": zoom_factor_value})

def _get_screen_limits(mode: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Retrieve width and height limits based on the current screen size mode.
    
    Args:
        mode: Either "Percentage" or "Pixels".
        
    Returns:
        A tuple with (width_limits, height_limits).
    """
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    max_screen_size = conf_mgr.get_max_screen_size()

    if mode not in ["Percentage", "Pixels"]:
        logger.error(f"Mode '{mode}' is invalid; defaulting to 'Percentage'.")
        mode = "Percentage"

    # These are specified limits
    width_p_limits = (10, 100)
    height_p_limits = (10, 100)
    width_px_limits = (1200, max_screen_size[0])
    height_px_limits = (600, max_screen_size[1])
    
    # Calculate actual limits based on both specified limits for percentage and pixels
    actual_width_px_limits = (
            min(max(round(width_p_limits[0] * max_screen_size[0] / 100), width_px_limits[0]), width_px_limits[1]),
            min(max(round(width_p_limits[1] * max_screen_size[0] / 100), width_px_limits[0]), width_px_limits[1])
    )
    actual_height_px_limits = (
        min(max(round(height_p_limits[0] * max_screen_size[1] / 100), height_px_limits[0]), height_px_limits[1]),
        min(max(round(height_p_limits[1] * max_screen_size[1] / 100), height_px_limits[0]), height_px_limits[1])
    )
    
    if mode == "Pixels":
        return actual_width_px_limits, actual_height_px_limits
    else:  # Percentage
        actual_width_p_limits = (
            min(max(round(actual_width_px_limits[0] / max_screen_size[0] * 100), width_p_limits[0]), width_p_limits[1]),
            min(max(round(actual_width_px_limits[1] / max_screen_size[0] * 100), width_p_limits[0]), width_p_limits[1])
        )
        actual_height_p_limits = (
            min(max(round(actual_height_px_limits[0] / max_screen_size[1] * 100), height_p_limits[0]), height_p_limits[1]),
            min(max(round(actual_height_px_limits[1] / max_screen_size[1] * 100), height_p_limits[0]), height_p_limits[1])
        )
        return actual_width_p_limits, actual_height_p_limits
