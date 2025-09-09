from __future__ import annotations


import logging
from typing import Any, Dict, Union, List, Tuple, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.widgets.settings.settings_utils import _reset_setting_callback
from mdh_app.dpg_components.windows.orientation_labels.ori_labels_window import create_orientation_label_color_picker


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def add_data_view_controls(
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
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
                            callback=_reset_setting_callback
                        )


def add_data_windowing_controls(
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
                    )


def add_overlay_controls(tag_parent: Union[str, int], size_dict: Dict[str, Any]) -> None:
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
