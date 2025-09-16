from __future__ import annotations


import logging
from typing import Any, Dict, Optional, Tuple, Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.utils.dpg_utils import safe_delete, match_child_tags


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def get_hovered_view_dict() -> Dict[str, Any]:
    """
    Identify and return the dictionary for the currently hovered view.

    Returns:
        The view dictionary if a view's image is hovered; otherwise, an empty dictionary.
    """
    views_to_check = [get_tag("axial_dict"), get_tag("coronal_dict"), get_tag("sagittal_dict")]
    for view_dict in views_to_check:
        image_tag = view_dict.get("image")
        if image_tag and dpg.does_item_exist(image_tag) and dpg.is_item_hovered(image_tag):
            dpg.focus_item(image_tag)
            return view_dict
    return {}


def get_mouse_slice_pos_xyz(view_dict: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    """
    Determine the current slice position (X, Y, Z) based on mouse position within a view.

    Args:
        view_dict: The dictionary for the hovered view.

    Returns:
        A tuple with slice values (X, Y, Z) or None if view_dict is empty or invalid.
    """
    if not view_dict:
        return None

    img_tags = get_tag("img_tags")
    
    # Get mouse position and image position/size
    mouse_pos = dpg.get_mouse_pos(local=False)  # GUI mouse position (left/right, top/bottom)
    img_start_pos = dpg.get_item_rect_min(view_dict["image"])  # GUI image start position
    img_rect_size = dpg.get_item_rect_size(view_dict["image"]) # GUI image size
    
    # Avoid division by zero
    if img_rect_size[0] == 0 or img_rect_size[1] == 0:
        return
    
    # Calculate ratios for mouse position within the image
    ratio_lr = (mouse_pos[0] - img_start_pos[0]) / img_rect_size[0]
    ratio_tb = (mouse_pos[1] - img_start_pos[1]) / img_rect_size[1]
    
    # Map ratios to voxel location based on the view
    slice_x, slice_y, slice_z = dpg.get_value(img_tags["viewed_slices"])[:3]
    xyz_range_inp_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
    curr_x_range, curr_y_range, curr_z_range = [dpg.get_value(tag)[:2] for tag in xyz_range_inp_tags]
    min_x, min_y, min_z = [dpg.get_item_configuration(tag)["min_value"] for tag in xyz_range_inp_tags]
    max_x, max_y, max_z = [dpg.get_item_configuration(tag)["max_value"] for tag in xyz_range_inp_tags]
    
    # Calculate size of each range
    x_size = curr_x_range[1] - curr_x_range[0] + 1
    y_size = curr_y_range[1] - curr_y_range[0] + 1
    z_size = curr_z_range[1] - curr_z_range[0] + 1
    
    # Slicer is based on NPY (Y, X, Z) order
    view_type = view_dict.get("view_type")
    if view_type == "coronal":
        xyz_slice_pos = (
            round(min(max(ratio_lr * x_size + curr_x_range[0], min_x), max_x)),
            slice_y,
            round(min(max((1.0 - ratio_tb) * z_size + curr_z_range[0], min_z), max_z)),
        )
    elif view_type == "sagittal":
        xyz_slice_pos = (
            slice_x,
            round(min(max((1.0 - ratio_lr) * y_size + curr_y_range[0], min_y), max_y)),
            round(min(max((1.0 - ratio_tb) * z_size + curr_z_range[0], min_z), max_z)),
        )
    elif view_type == "axial":
        xyz_slice_pos = (
            round(min(max(ratio_lr * x_size + curr_x_range[0], min_x), max_x)),
            round(min(max(ratio_tb * y_size + curr_y_range[0], min_y), max_y)),
            slice_z,
        )
    else:
        xyz_slice_pos = None
    
    return xyz_slice_pos


def copy_log_text() -> None:
    """Copy the text from the log window to the clipboard."""
    try:
        tag_logger_window = get_tag("log_window")
        prepend_text = "Copied the hovered log text:"
        if dpg.does_item_exist(tag_logger_window) and dpg.is_item_shown(tag_logger_window):
            children_tags = match_child_tags(tag_logger_window, "logger_message_")
            for child_tag in children_tags:
                if dpg.is_item_hovered(child_tag):
                    child_text = dpg.get_value(child_tag)
                    if child_text and not prepend_text in child_text:
                        dpg.set_clipboard_text(child_text)
                        logger.info(f"{prepend_text} '{child_text[:75]}...'")
                    return
    except Exception as e:
        logger.debug(f"Failed to copy text from log window.", exc_info=True, stack_info=True)


def _handler_MouseLeftClick(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Toggle tooltip visibility for the hovered view."""
    view_dict = get_hovered_view_dict()
    if view_dict:
        tooltip_tag = view_dict.get("tooltip")
        is_tooltip_shown = dpg.is_item_shown(tooltip_tag)
        dpg.configure_item(tooltip_tag, show=not is_tooltip_shown)


def _handler_MouseRightClick(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Either copy the log text, or move viewing planes to the mouse location in a hovered view."""
    view_dict = get_hovered_view_dict()
    if not view_dict:
        copy_log_text()
        return
    
    # Check if slice positions have changed
    viewed_slices_tag = get_tag("img_tags")["viewed_slices"]
    old_slices = tuple(dpg.get_value(viewed_slices_tag)[:3])
    new_slices = get_mouse_slice_pos_xyz(view_dict)
    if new_slices is None or new_slices == old_slices:
        return  # No change
    
    # Update the slice values
    dpg.set_value(viewed_slices_tag, new_slices)
    request_texture_update(texture_action_type="update")


def _handler_MouseMiddleClick(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Placeholder for middle mouse click functionality."""
    pass


def _handler_MouseMiddleRelease(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Reset stored mouse delta values upon middle mouse release.

    Args:
        sender: The event handler tag.
    """
    dpg.set_item_user_data(sender, (0, 0))


def _handler_MouseMiddleDrag(sender: Union[str, int], app_data: Tuple[Any, ...], user_data: Any) -> None:
    """
    Pan the view when dragging with the middle mouse button.

    Args:
        sender: The event handler tag.
        app_data: Tuple containing mouse drag data.
    """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    img_tags = get_tag("img_tags")
    tag_mouse_release = get_tag("mouse_release_tag")
    any_change = False
    
    view_type = view_dict["view_type"]
    dims_LR_TB = view_dict["dims_LR_TB"]
    _, raw_delta_lr, raw_delta_tb = app_data
    
    # Swap direction for sagittal y-axis movement and sagittal/coronal z-axis movement
    if view_type == "sagittal":
        raw_delta_lr = -raw_delta_lr
        raw_delta_tb = -raw_delta_tb
    if view_type == "coronal":
        raw_delta_tb = -raw_delta_tb
    
    # Smoothen the mouse movement
    prev_mouse_delta = dpg.get_item_user_data(tag_mouse_release)
    smoothing_factor = 0.3  # Adjust this value (0.0 to 1.0) for desired smoothing of mouse movement
    smooth_delta_lr = smoothing_factor * raw_delta_lr + (1 - smoothing_factor) * prev_mouse_delta[0]
    smooth_delta_tb = smoothing_factor * raw_delta_tb + (1 - smoothing_factor) * prev_mouse_delta[1]
    new_mouse_delta = (smooth_delta_lr, smooth_delta_tb)
    dpg.set_item_user_data(tag_mouse_release, new_mouse_delta)
    
    # Get the range tags, values, and limits for each dimension (x/y/z)
    dims_vals = [
        (
            tag, 
            tuple(dpg.get_value(tag)[:2]), 
            dpg.get_item_configuration(tag)["min_value"],
            dpg.get_item_configuration(tag)["max_value"]
        )
        for tag in [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
    ]
    
    # Get the pan speed
    pan_speed_key = dpg.get_value(img_tags["pan_speed"])
    pan_speed_dict = dpg.get_item_user_data(img_tags["pan_speed"])
    pan_speed = pan_speed_dict[pan_speed_key]
    
    # Calculate the new range for each dimension
    for dim_idx, d_diff in zip(dims_LR_TB, new_mouse_delta):
        dim_tag, dim_range, dim_min, dim_max = dims_vals[dim_idx]
        active_display_size = dim_range[1] - dim_range[0]
        
        # Calculate new range based on pan
        new_lower = round(dim_range[0] + (d_diff * pan_speed))
        new_upper = new_lower + active_display_size
        
        # Clamp to bounds
        new_lower = max(dim_min, min(new_lower, dim_max - active_display_size))
        new_upper = new_lower + active_display_size
        
        new_range = (new_lower, new_upper)
        if dim_range != new_range:
            any_change = True
        
        dpg.set_value(dim_tag, new_range)
    
    # Trigger texture refresh on another thread
    if any_change:
        request_texture_update(texture_action_type="update")


def _handler_MouseWheel(sender: Union[str, int], app_data: int, user_data: Any) -> None:
    """
    Process mouse wheel events to perform zooming or slice scrolling.

    Args:
        sender: The event handler tag.
        app_data: Mouse wheel movement data.
    """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    img_tags = get_tag("img_tags")
    key_down_tag = get_tag("key_down_tag")
    ctrl_pressed = dpg.get_item_user_data(key_down_tag)
    any_change = False
    
    # Zoom functionality
    if ctrl_pressed:
        # Get zoom factor
        zoom_factor_key = dpg.get_value(img_tags["zoom_factor"])
        zoom_factor_dict = dpg.get_item_user_data(img_tags["zoom_factor"])
        zoom_factor = zoom_factor_dict[zoom_factor_key]
        
        # Calculate new ranges for all three dimensions
        dim_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
        dim_ranges = [tuple(dpg.get_value(tag)[:2]) for tag in dim_tags]
        dim_bounds = [(dpg.get_item_configuration(tag)["min_value"], dpg.get_item_configuration(tag)["max_value"]) for tag in dim_tags]
        dim_slices = dpg.get_value(img_tags["viewed_slices"])[:3]
        current_spans = [r[1] - r[0] + 1 for r in dim_ranges]
        
        # Scale: <1 for zoom-in, >1 for zoom-out
        if app_data > 0:  # zoom in
            scale = max(0.01, 1.0 - zoom_factor)
        else:  # zoom out
            scale = 1.0 / max(1e-6, (1.0 - zoom_factor))
        
        # Compute new spans proportionally, clamp to each axis's available span
        bounds_spans = [(b[1] - b[0] + 1) for b in dim_bounds]
        new_spans = [max(1, min(bounds_spans[i], int(round(current_spans[i] * scale)))) for i in range(3)]

        # If rounding produced no-change, force a 1-voxel step for all dims
        if all(new_spans[i] == current_spans[i] for i in range(3)):
            if app_data > 0:  # zoom in
                new_spans = [max(1, min(bounds_spans[i], current_spans[i] - 1)) for i in range(3)]
            else:  # zoom out
                new_spans = [min(bounds_spans[i], current_spans[i] + 1) for i in range(3)]
        
        # If no change after this, just exit
        if all(new_spans[i] == current_spans[i] for i in range(3)):
            dpg.set_item_user_data(key_down_tag, False)
            return
        
        any_change = True
        
        # Apply ranges centered on their slices, clamped to bounds
        for dim_tag, (min_b, max_b), slice_pos, span in zip(dim_tags, dim_bounds, dim_slices, new_spans):
            half = span // 2
            start = slice_pos - half
            end = start + span - 1
            if start < min_b:
                start = min_b
                end = min_b + span - 1
            if end > max_b:
                end = max_b
                start = max_b - span + 1
            dpg.set_value(dim_tag, (int(start), int(end)))
        
        dpg.set_item_user_data(key_down_tag, False)
    
    # Scroll functionality
    else:
        # Get current slices and determine which dimension to scroll based on view
        view_type = view_dict["view_type"]
        slice_tag = img_tags["viewed_slices"]
        current_slices = tuple(dpg.get_value(slice_tag)[:3])
        
        # Range and slice idx based on which dim is being scrolled through
        direction = _clip_direction(app_data)
        if direction == 0:
            return
        
        # Determine which dimension to adjust based on view
        xyz_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
        if view_type == "axial":
            slice_idx = 2
        elif view_type == "coronal":
            slice_idx = 1
            direction = -direction  # Invert direction for coronal view
        elif view_type == "sagittal":
            slice_idx = 0
            direction = -direction  # Invert direction for sagittal view

        # Ensure the slice is within the valid range
        range_cfg = dpg.get_item_configuration(xyz_tags[slice_idx])
        range_min, range_max = range_cfg["min_value"], range_cfg["max_value"]
        slices_list = list(current_slices)
        slices_list[slice_idx] = int(min(max(slices_list[slice_idx] + direction, range_min), range_max))
        new_slices = tuple(slices_list)
        if current_slices != new_slices:
            any_change = True
        dpg.set_value(slice_tag, new_slices)
        
        # Adjust ranges to ensure the new slice is visible
        for (dim_tag, dim_slice) in zip(xyz_tags, new_slices):
            curr_range = tuple(dpg.get_value(dim_tag)[:2])
            dim_min, dim_max = curr_range
            
            # Only adjust if slice is outside current range
            if dim_slice < dim_min or dim_slice > dim_max:
                range_cfg = dpg.get_item_configuration(dim_tag)
                dim_min_limit, dim_max_limit = range_cfg["min_value"], range_cfg["max_value"]
                
                # Keep the same range size, just shift it to include the slice
                range_size = dim_max - dim_min
                if dim_slice < dim_min:
                    new_dim_min = max(dim_slice, dim_min_limit)
                    new_dim_max = min(new_dim_min + range_size, dim_max_limit)
                else:  # dim_slice > dim_max
                    new_dim_max = min(dim_slice, dim_max_limit)
                    new_dim_min = max(new_dim_max - range_size, dim_min_limit)
                
                new_range = (new_dim_min, new_dim_max)
                if curr_range != new_range:
                    any_change = True
                    dpg.set_value(dim_tag, new_range)
        
    # Trigger texture refresh on another thread
    if any_change:
        request_texture_update(texture_action_type="update")


def _clip_direction(val: Any) -> int:
    """ Preserve sign and ensure it is always >= 1, 0, or <= -1 """
    try:
        val = float(val)
    except (ValueError, TypeError):
        return 0
    if val == 0:
        return 0
    if 0 < val < 1:
        return 1
    if -1 < val < 0:
        return -1
    return int(val)


def _itemhandler_MouseHover(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Update tooltip content for the hovered view based on current mouse location."""
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    xyz_slices = get_mouse_slice_pos_xyz(view_dict)
    if not xyz_slices:
        return

    zyx_slices = (xyz_slices[2], xyz_slices[1], xyz_slices[0])
    # Find values at location
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    roi_info_list = data_mgr.return_roi_info_list_at_slice(zyx_slices)
    img_value_list = data_mgr.return_image_value_list_at_slice(zyx_slices)
    dose_value_list = data_mgr.return_dose_value_list_at_slice(zyx_slices)
    
    # Build tooltip content
    img_values = ", ".join([str(round(val)) for val in img_value_list]) if img_value_list else "N/A"
    dose_values_sum = round(sum(dose_value_list) * 100) if dose_value_list else 0
    # dose_values = ", ".join([str(round(val * 100)) for val in dose_value_list]) if dose_value_list else ""
    
    # Update GUI
    safe_delete(view_dict["tooltip"], children_only=True)
    with dpg.group(parent=view_dict["tooltip"]):
        dpg.add_text(
            f"Voxel location (X, Y, Z): {xyz_slices}"
            f"\nImage value: {img_values}"
            f"\nDose value: {dose_values_sum} cGy",
        )
        if roi_info_list:
            dpg.add_text(f"Masks at voxel:")
            for (roi_number, current_roi_name, roi_display_color) in roi_info_list:
                with dpg.group(horizontal=True):
                    dpg.add_text(default_value=f"\t{roi_number}. ", color=[255, 255, 255])
                    dpg.add_text(default_value=current_roi_name, color=roi_display_color)
        else:
            dpg.add_text(default_value=f"\tNo masks found at this voxel.")


