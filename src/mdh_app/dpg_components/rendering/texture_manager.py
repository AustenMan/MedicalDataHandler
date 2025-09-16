from __future__ import annotations


import logging
import math
from typing import Any, Dict, List, Tuple, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, update_viewport_and_popups
from mdh_app.utils.dpg_utils import safe_delete


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def request_texture_update(*args, **kwargs) -> None:
    """ Triggers a texture update request on the shared state manager. """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    ss_mgr.submit_texture_update(_update_textures, *args, **kwargs)


def _update_textures(*args, **kwargs) -> None:
    """ Updates the data in the DataManager and textures in the DearPyGUI interface. """
    # Get managers
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    img_tags = get_tag("img_tags")
    dpg_range_tags = (img_tags["xrange"], img_tags["yrange"], img_tags["zrange"])
    
    # Update viewport if any change in screen size. Returns the resulting W/H scaling factors.
    WH_scales = update_viewport_and_popups()
    image_length = _get_dpg_image_length(WH_scales)
    
    # Identify texture action type
    texture_action_type = kwargs.get("texture_action_type", "update")
    
    # Get raw data params
    data_raw_params = data_mgr.get_raw_data_params()
    data_raw_size, data_raw_spacing = data_raw_params["size"], data_raw_params["spacing"]
    # data_raw_physical_size = [data_raw_size[i] * data_raw_spacing[i] for i in range(len(data_raw_size))]
    # data_raw_max_phys_size = max(data_raw_physical_size)
    # data_raw_padding_phys = [data_raw_max_phys_size - data_raw_physical_size[i] if data_raw_max_phys_size > data_raw_physical_size[i] else 0 for i in range(3)]
    # data_raw_padding_idxs = [round(data_raw_padding_phys[i] / data_raw_spacing[i]) for i in range(3)]
    # data_raw_range_mins = [-data_raw_padding_idxs[i] // 2 for i in range(3)]  # min limits
    # data_raw_range_maxs = [data_raw_size[i] - 1 + (data_raw_padding_idxs[i] - data_raw_padding_idxs[i] // 2) for i in range(3)]  # max limits
    # data_raw_ranges = [(data_raw_range_mins[i], data_raw_range_maxs[i]) for i in range(3)]  # raw viewing range
    
    # Get current data params
    data_current_params = data_mgr.get_current_data_params()
    data_current_size, data_current_spacing = data_current_params["size"], data_current_params["spacing"]
    # data_current_physical_size = [data_current_size[i] * data_current_spacing[i] for i in range(len(data_current_size))]
    # data_current_max_phys_size = max(data_current_physical_size)
    # data_current_padding_phys = [data_current_max_phys_size - data_current_physical_size[i] if data_current_max_phys_size > data_current_physical_size[i] else 0 for i in range(3)]
    # data_current_padding_idxs = [round(data_current_padding_phys[i] / data_current_spacing[i]) for i in range(3)]
    # data_current_range_mins = [-data_current_padding_idxs[i] // 2 for i in range(3)]  # min limits
    # data_current_range_maxs = [data_current_size[i] - 1 + (data_current_padding_idxs[i] - data_current_padding_idxs[i] // 2) for i in range(3)]  # max limits
    # data_current_ranges = [(data_current_range_mins[i], data_current_range_maxs[i]) for i in range(3)]  # current viewing range
    
    # Store previous DPG state before updates (for mapping if spacing changed)
    prev_dpg_spacing = tuple([float(i) for i in data_current_spacing]) if texture_action_type == "update" else None
    prev_dpg_slices = list(dpg.get_value(img_tags["viewed_slices"])[:3]) if texture_action_type == "update" and dpg.does_item_exist(img_tags["viewed_slices"]) else None
    prev_dpg_view_indices = [dpg.get_value(tag)[:2] for tag in dpg_range_tags] if texture_action_type == "update" and all(dpg.does_item_exist(tag) for tag in dpg_range_tags) else None
    
    # Get new DPG spacing
    if dpg.does_item_exist(img_tags["force_voxel_spacing_isotropic_largest"]) and dpg.get_value(img_tags["force_voxel_spacing_isotropic_largest"]):
        dpg_spacing = [max(data_raw_spacing)] * len(data_raw_spacing)
    elif dpg.does_item_exist(img_tags["force_voxel_spacing_isotropic_smallest"]) and dpg.get_value(img_tags["force_voxel_spacing_isotropic_smallest"]):
        dpg_spacing = [min(data_raw_spacing)] * len(data_raw_spacing)
    elif dpg.does_item_exist(img_tags["force_voxel_spacing_config"]) and dpg.get_value(img_tags["force_voxel_spacing_config"]):
        dpg_spacing = conf_mgr.get_voxel_spacing()
    elif texture_action_type == "update" and dpg.does_item_exist(img_tags["voxel_spacing"]) and dpg.get_value(img_tags["voxel_spacing"]):
        dpg_spacing = dpg.get_value(img_tags["voxel_spacing"])[:3]
    else:
        dpg_spacing = data_raw_spacing
    dpg_spacing = tuple([float(i) for i in dpg_spacing])
    
    # Calculate new DPG size and padding based on new spacing
    dpg_size = [round(data_raw_size[i] * data_raw_spacing[i] / dpg_spacing[i]) for i in range(3)]
    dpg_physical_size = [dpg_size[i] * dpg_spacing[i] for i in range(3)]
    dpg_max_phys_size = max(dpg_physical_size)
    dpg_padding_phys = [dpg_max_phys_size - dpg_physical_size[i] if dpg_max_phys_size > dpg_physical_size[i] else 0 for i in range(3)]
    dpg_padding_idxs = [round(dpg_padding_phys[i] / dpg_spacing[i]) for i in range(3)]
    dpg_range_mins = [-dpg_padding_idxs[i] // 2 for i in range(3)]
    dpg_range_maxs = [dpg_size[i] - 1 + (dpg_padding_idxs[i] - dpg_padding_idxs[i] // 2) for i in range(3)]
    
    # Get the current viewing range and slices
    if texture_action_type == "reset" or texture_action_type == "initialize":
        dpg_ranges = [(dpg_range_mins[i], dpg_range_maxs[i]) for i in range(3)]
        dpg_viewed_slices = [dpg_size[i] // 2 for i in range(3)]
    elif (dpg_spacing != prev_dpg_spacing) and prev_dpg_slices and prev_dpg_view_indices:
        # Map previous bounding box physical extents to new indices; clamp to the limits
        prev_dpg_view_physical = [(
            prev_dpg_view_indices[i][0] * prev_dpg_spacing[i] - 0.5 * prev_dpg_spacing[i],
            prev_dpg_view_indices[i][1] * prev_dpg_spacing[i] + 0.5 * prev_dpg_spacing[i]
        ) for i in range(3)]
        dpg_ranges = [(math.floor(prev_dpg_view_physical[i][0] / dpg_spacing[i]), math.ceil(prev_dpg_view_physical[i][1] / dpg_spacing[i])) for i in range(3)]
        
        # Map previous physical slice positions to new indices
        prev_dpg_slices_physical = [prev_dpg_slices[i] * prev_dpg_spacing[i] for i in range(3)]
        dpg_viewed_slices = [(int(round(prev_dpg_slices_physical[i] / dpg_spacing[i]))) for i in range(3)]
    else:
        # No spacing change, keep existing values or use defaults
        dpg_ranges = [dpg.get_value(tag)[:2] for tag in dpg_range_tags] if all(dpg.does_item_exist(tag) for tag in dpg_range_tags) else [(dpg_range_mins[i], dpg_range_maxs[i]) for i in range(3)]
        dpg_viewed_slices = list(dpg.get_value(img_tags["viewed_slices"])[:3]) if dpg.does_item_exist(img_tags["viewed_slices"]) else [dpg_size[i] // 2 for i in range(3)]
    
    # DPG Range & View Adjustments
    for i in range(len(dpg_ranges)):
        # Ensure DPG ranges are within limits
        dpg_ranges[i] = (max(dpg_ranges[i][0], dpg_range_mins[i]), min(dpg_ranges[i][1], dpg_range_maxs[i]))
        
        # Ensure viewed slices are within the current ranges
        dpg_viewed_slices[i] = min(max(dpg_viewed_slices[i], dpg_ranges[i][0]), dpg_ranges[i][1])
        
        # Ensure dpg_range is at least 16 voxels per axis
        while dpg_ranges[i][1] - dpg_ranges[i][0] < 15:
            if dpg_ranges[i][0] > dpg_range_mins[i]:
                dpg_ranges[i] = (dpg_ranges[i][0] - 1, dpg_ranges[i][1])
            if dpg_ranges[i][1] < dpg_range_maxs[i]:
                dpg_ranges[i] = (dpg_ranges[i][0], dpg_ranges[i][1] + 1)
            if dpg_ranges[i][0] == dpg_range_mins[i] and dpg_ranges[i][1] == dpg_range_maxs[i]:
                break
        
    # Ensure isotropic physical space
    phys_extents = [(dpg_ranges[i][1] - dpg_ranges[i][0] + 1) * dpg_spacing[i] for i in range(3)]
    max_extent = max(phys_extents)
    for i in range(len(dpg_ranges)):
        target_voxels = int(round(max_extent / dpg_spacing[i]))
        current_voxels = dpg_ranges[i][1] - dpg_ranges[i][0] + 1
        extra = target_voxels - current_voxels
        while extra != 0:
            if dpg_ranges[i][0] > dpg_range_mins[i]:
                dpg_ranges[i] = (dpg_ranges[i][0] - 1, dpg_ranges[i][1])
                extra -= 1
            if extra == 0:
                break
            if dpg_ranges[i][1] < dpg_range_maxs[i]:
                dpg_ranges[i] = (dpg_ranges[i][0], dpg_ranges[i][1] + 1)
                extra -= 1
            if dpg_ranges[i][0] == dpg_range_mins[i] and dpg_ranges[i][1] == dpg_range_maxs[i]:
                break
    
    # Update DPG ranges items
    for i, tag in enumerate(dpg_range_tags):
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, min_value=dpg_range_mins[i], max_value=dpg_range_maxs[i], default_value=(dpg_range_mins[i], dpg_range_maxs[i]), user_data=(dpg_range_mins[i], dpg_range_maxs[i]))
            dpg.set_value(tag, dpg_ranges[i])

    # Update DPG viewed slices item
    if dpg.does_item_exist(img_tags["viewed_slices"]):
        reset_vals = [dpg_size[i] // 2 for i in range(3)]
        dpg.configure_item(img_tags["viewed_slices"], min_value=min(dpg_range_mins), max_value=max(dpg_range_maxs), default_value=reset_vals, user_data=reset_vals)
        dpg.set_value(img_tags["viewed_slices"], dpg_viewed_slices)
    
    # Update DPG spacing item
    if dpg.does_item_exist(img_tags["voxel_spacing"]):
        dpg.configure_item(img_tags["voxel_spacing"], default_value=data_raw_spacing, user_data=data_raw_spacing)
        dpg.set_value(img_tags["voxel_spacing"], dpg_spacing)
    
    # Get remaining DPG visual params
    dpg_rotation = int(dpg.get_value(img_tags["rotation"])) if dpg.does_item_exist(img_tags["rotation"]) else 0
    dpg_flips = [bool(dpg.get_value(tag)) if dpg.does_item_exist(tag) else False for tag in [img_tags["flip_lr"], img_tags["flip_ap"], img_tags["flip_si"]]]
    dpg_display_alphas, dpg_dose_range, dpg_contour_thickness, dpg_image_window_width, dpg_image_window_level = _get_visual_texture_params()
    
    # (z, y, x) order
    view_slicing_dict = {
        "axial": (
            dpg_viewed_slices[2], 
            slice(dpg_ranges[1][0], dpg_ranges[1][1] + 1, 1), 
            slice(dpg_ranges[0][0], dpg_ranges[0][1] + 1, 1),
        ),
        "coronal": (
            slice(dpg_ranges[2][0], dpg_ranges[2][1] + 1, 1), 
            dpg_viewed_slices[1], 
            slice(dpg_ranges[0][0], dpg_ranges[0][1] + 1, 1),
        ),
        "sagittal": (
            slice(dpg_ranges[2][0], dpg_ranges[2][1] + 1, 1), 
            slice(dpg_ranges[1][0], dpg_ranges[1][1] + 1, 1), 
            dpg_viewed_slices[0],
        )
    }
    
    texture_dict = {}
    for view_type, slicer in view_slicing_dict.items():
        texture_params = {
            "view_type": view_type, "xyz_slices": dpg_viewed_slices, "xyz_ranges": dpg_ranges, "slicer": slicer, 
            "image_length": image_length, "size": dpg_size, "voxel_spacing": dpg_spacing, 
            "rotation": dpg_rotation, "flips": dpg_flips, "contour_thickness": dpg_contour_thickness,
            "display_alphas": dpg_display_alphas, "dose_thresholds": dpg_dose_range,
            "image_window_level": dpg_image_window_level, "image_window_width": dpg_image_window_width,
            "show_crosshairs": dpg.get_value(img_tags["show_crosshairs"]) if dpg.does_item_exist(img_tags["show_crosshairs"]) else True,
            "show_orientation_labels": dpg.get_value(img_tags["show_orientation_labels"]) if dpg.does_item_exist(img_tags["show_orientation_labels"]) else True,
        }
        texture_dict[view_type] = data_mgr.return_texture_from_active_data(texture_params)

    _set_textures_and_images(image_length, texture_dict)


def _get_dpg_image_length(WH_scales: Tuple[float, float] = (1.0, 1.0)) -> int:
    """
    Calculate DPG image length using viewport width/height scaling factors.

    Args:
        WH_scales: Tuple of (width_scale, height_scale).

    Returns:
        DPG image length as an integer, ensuring a minimum of 100.
    """
    width_scale, height_scale = WH_scales
    ax_W, ax_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_topleft"))
    # misc_W, misc_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_topright"))
    cor_W, cor_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_bottomleft"))
    sag_W, sag_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_bottomright"))
    min_size = min(
        ax_W * width_scale, 
        ax_H * height_scale,
        # misc_W * width_scale,
        # misc_H * height_scale,
        cor_W * width_scale, 
        cor_H * height_scale,
        sag_W * width_scale,
        sag_H * height_scale,
    )
    return max(int(((min_size * 0.95) * 2) // 2), 100)  # Ensure even rounding, and minimum size of 100


def _get_visual_texture_params() -> Tuple[List[int], List[int], int, int, int]:
    """
    Retrieve visual texture parameters to customize texture display.

    Returns:
        A tuple of (display_alphas, dose_range, contour_thickness, image_window_width, image_window_level).
    """
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    img_tags = get_tag("img_tags")
    default_display_dict: Dict[str, Any] = get_user_data(td_key="default_display_dict")
    
    # Tags
    display_alphas_tag = img_tags["display_alphas"]
    dose_thresholds_tag = img_tags["dose_thresholds"]
    contour_thickness_tag = img_tags["contour_thickness"]
    image_window_preset_tag = img_tags["window_preset"]
    image_window_width_tag = img_tags["window_width"]
    image_window_level_tag = img_tags["window_level"]
    
    if dpg.does_item_exist(display_alphas_tag):
        display_alphas = [int(min(max(val, 0), 100)) for val in dpg.get_value(display_alphas_tag)[:3]]
        dpg.set_value(display_alphas_tag, display_alphas)
    else:
        display_alphas = default_display_dict["DISPLAY_ALPHAS"]
    
    if dpg.does_item_exist(dose_thresholds_tag):
        dose_range = dpg.get_value(dose_thresholds_tag)[:2]
        dose_range = [min(max(dose_range[0], 0), 99), min(max(dose_range[1], 1), 100)]
        dose_range = dose_range if dose_range[0] < dose_range[1] else [dose_range[0]-1, dose_range[1]] if dose_range[0] > 0 else [dose_range[0], dose_range[1]+1]
        dpg.set_value(dose_thresholds_tag, dose_range)
    else:
        dose_range = default_display_dict["DOSE_RANGE"]
    
    if dpg.does_item_exist(contour_thickness_tag):
        contour_thickness = min(max(dpg.get_value(contour_thickness_tag), 0), 10)
        dpg.set_value(contour_thickness_tag, contour_thickness)
    else:
        contour_thickness = default_display_dict["CONTOUR_THICKNESS"]
    
    if dpg.does_item_exist(image_window_preset_tag):
        image_window_preset = dpg.get_value(image_window_preset_tag)
    else:
        image_window_preset = default_display_dict["IMAGE_WINDOW_PRESET"]
    
    config_preset_dict = conf_mgr.get_window_presets()
    
    if dpg.does_item_exist(image_window_width_tag):
        image_window_width = dpg.get_value(image_window_width_tag) if image_window_preset == "Custom" else config_preset_dict[image_window_preset][0]
        dpg.set_value(image_window_width_tag, image_window_width)
    else:
        image_window_width = default_display_dict["IMAGE_WINDOW_WIDTH"]
    
    if dpg.does_item_exist(image_window_level_tag):
        image_window_level = dpg.get_value(image_window_level_tag) if image_window_preset == "Custom" else config_preset_dict[image_window_preset][1]
        dpg.set_value(image_window_level_tag, image_window_level)
    else:
        image_window_level = default_display_dict["IMAGE_WINDOW_LEVEL"]
    
    return display_alphas, dose_range, contour_thickness, image_window_width, image_window_level


def _set_textures_and_images(image_length: int, texture_dict: Dict[str, Any]) -> None:
    """
    Create or update textures and corresponding images for axial, coronal, and sagittal views.

    Args:
        image_length: Image length (width and height) for the textures.
        texture_dict: Mapping of view types ("axial", "coronal", "sagittal") to texture data.
    
    Raises:
        ValueError: If image_length is not an integer or texture_dict is missing required keys.
    """
    if not isinstance(image_length, int):
        raise ValueError(f"Image length must be an integer; received: {image_length}")
    if not texture_dict or not all(k in texture_dict for k in ["axial", "coronal", "sagittal"]):
        raise ValueError(f"Texture dictionary must contain keys 'axial', 'coronal', and 'sagittal'; received: {texture_dict}")

    tag_texture_registry = get_tag("texture_registry")
    tag_item_handler_registry = get_tag("item_handler_registry")
    
    dpg.configure_item("mw_ctr_topright", width=image_length, height=image_length) # Unused view
    for (view_type, texture), parent_tag in zip(texture_dict.items(), ["mw_ctr_topleft", "mw_ctr_bottomleft", "mw_ctr_bottomright"]):
        view_tag_dict: Dict[str, Any] = get_tag(f"{view_type}_dict")
        texture_tag = view_tag_dict["texture"]
        
        dpg.configure_item(parent_tag, width=image_length, height=image_length)
        
        old_width = dpg.get_item_width(texture_tag) if dpg.does_item_exist(texture_tag) else 0
        old_height = dpg.get_item_height(texture_tag) if dpg.does_item_exist(texture_tag) else 0
        
        if old_width != image_length or old_height != image_length or not dpg.does_item_exist(texture_tag):
            safe_delete(texture_tag)
            dpg.add_raw_texture(tag=texture_tag, parent=tag_texture_registry, width=image_length, height=image_length, default_value=texture, format=dpg.mvFormat_Float_rgb)
        else:
            dpg.configure_item(texture_tag, width=image_length, height=image_length, default_value=texture, format=dpg.mvFormat_Float_rgb)
        
        if not dpg.does_item_exist(view_tag_dict["image"]):
            dpg.add_image(tag=view_tag_dict["image"], parent=parent_tag, texture_tag=texture_tag, width=image_length, height=image_length)
            dpg.add_tooltip(tag=view_tag_dict["tooltip"], parent=view_tag_dict["image"], show=False)
            dpg.bind_item_handler_registry(view_tag_dict["image"], tag_item_handler_registry)
        else:
            dpg.configure_item(view_tag_dict["image"], width=image_length, height=image_length, texture_tag=texture_tag)
