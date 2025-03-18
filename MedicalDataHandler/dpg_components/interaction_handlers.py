import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data
from dpg_components.texture_updates import request_texture_update
from utils.dpg_utils import safe_delete

def get_hovered_view_dict():
    """
    Identifies the currently hovered view based on mouse position and returns its dictionary.
    
    Returns:
        dict: The dictionary of the hovered view, or an empty dictionary if none are hovered.
    """
    dicts_to_check = [get_tag("axial_dict"), get_tag("coronal_dict"), get_tag("sagittal_dict")]
    for view_dict in dicts_to_check:
        image_tag = view_dict["image"]
        if dpg.does_item_exist(image_tag) and dpg.is_item_hovered(image_tag):
            dpg.focus_item(image_tag)
            return view_dict
    return {}

def get_mouse_slice_pos_xyz(view_dict):
    """
    Get the current slice values based on the mouse position within the hovered view.
    
    Returns:
        tuple: The slice values at the mouse position in (X, Y, Z) order.
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
    
    x_size = (curr_x_range[1] - curr_x_range[0] + 1) if curr_x_range[0] == 0 else (curr_x_range[1] - curr_x_range[0])
    y_size = (curr_y_range[1] - curr_y_range[0] + 1) if curr_y_range[0] == 0 else (curr_y_range[1] - curr_y_range[0])
    z_size = (curr_z_range[1] - curr_z_range[0] + 1) if curr_z_range[0] == 0 else (curr_z_range[1] - curr_z_range[0])
    
    # Slicer is based on NPY (Y, X, Z) order
    view_type = view_dict["view_type"]
    if view_type == "coronal":
        slice_pos = (
            round(min(max(ratio_lr * x_size + curr_x_range[0], min_x), max_x)),
            slice_y,
            round(min(max(ratio_tb * z_size + curr_z_range[0], min_z), max_z))
        )
    elif view_type == "sagittal":
        slice_pos = (
            slice_x,
            round(min(max((1.0 - ratio_lr) * y_size + curr_y_range[0], min_y), max_y)),
            round(min(max(ratio_tb * z_size + curr_z_range[0], min_z), max_z))
        )
    elif view_type == "axial":
        slice_pos = (
            round(min(max(ratio_lr * x_size + curr_x_range[0], min_x), max_x)),
            round(min(max(ratio_tb * y_size + curr_y_range[0], min_y), max_y)),
            slice_z
        )
    
    return slice_pos

def _handler_MouseLeftClick(sender, app_data, user_data):
    """ Toggles the visibility of the tooltip for the hovered view. """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    dpg.configure_item(view_dict["tooltip"], show=not dpg.is_item_shown(view_dict["tooltip"]))
    
def _handler_MouseRightClick(sender, app_data, user_data):
    """ Moves the viewing planes to the mouse location in the hovered view. """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    img_tags = get_tag("img_tags")
    
    old_slice_pos = tuple([i for i in dpg.get_value(img_tags["viewed_slices"])[:3]])
    
    new_slice_pos = get_mouse_slice_pos_xyz(view_dict)
    if not new_slice_pos or new_slice_pos == old_slice_pos:
        return
    
    # Set new slice values
    dpg.set_value(img_tags["viewed_slices"], new_slice_pos)

    # Refresh the texture asynchronously
    request_texture_update(texture_action_type="update")

def _handler_MouseMiddleClick(sender, app_data, user_data):
    """ Not implemented yet. """
    pass

def _handler_MouseMiddleRelease(sender, app_data, user_data):
    """
    Resets the mouse delta values after middle mouse button release.
    
    Args:
        sender (int): The tag of the mouse event handler.
    """
    dpg.set_item_user_data(sender, (0, 0))

def _handler_MouseMiddleDrag(sender, app_data, user_data):
    """
    Handles panning in the hovered view when the middle mouse button is dragged.
    
    Args:
        sender (int): The tag of the mouse event handler.
        app_data (tuple): Mouse drag event data.
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
    
    # Swap direction for sagittal y-axis movement
    if view_type == "sagittal":
        raw_delta_lr = -raw_delta_lr
    
    prev_mouse_delta = dpg.get_item_user_data(tag_mouse_release)
    smoothing_factor = 0.3  # Adjust this value (0.0 to 1.0) for desired smoothing of mouse movement
    smooth_delta_lr = smoothing_factor * raw_delta_lr + (1 - smoothing_factor) * prev_mouse_delta[0]
    smooth_delta_tb = smoothing_factor * raw_delta_tb + (1 - smoothing_factor) * prev_mouse_delta[1]
    new_mouse_delta = (smooth_delta_lr, smooth_delta_tb)
    dpg.set_item_user_data(tag_mouse_release, new_mouse_delta)
    
    xyz_range_inp_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
    xyz_range_tags_vals_mins_maxs = [(tag, tuple([i for i in dpg.get_value(tag)[:2]]), config["min_value"], config["max_value"]) for (tag, config) in [(tag, dpg.get_item_configuration(tag)) for tag in xyz_range_inp_tags]]
    
    pan_speed_key = dpg.get_value(img_tags["pan_speed"])
    pan_speed_dict = dpg.get_item_user_data(img_tags["pan_speed"])
    pan_speed = pan_speed_dict[pan_speed_key]
    for dim_idx, d_diff in zip(dims_LR_TB, new_mouse_delta):
        dim_tag, dim_range, dim_min, dim_max = xyz_range_tags_vals_mins_maxs[dim_idx]
        active_display_size = dim_range[1] - dim_range[0]
        new_lower = round(
            min(
                max(
                    dim_range[0] + (d_diff * pan_speed), 
                    dim_min
                ), 
                dim_max - active_display_size
            )
        )
        new_range = tuple([new_lower, new_lower + active_display_size])
        if dim_range != new_range:
            any_change = True
        
        dpg.set_value(dim_tag, new_range)
    
    # Trigger texture refresh on another thread
    if any_change:
        request_texture_update(texture_action_type="update")
    
def _handler_MouseWheel(sender, app_data, user_data):
    """
    Handles zoom or slice scrolling based on the mouse wheel input and keyboard state.
    
    Args:
        sender (int): The tag of the mouse event handler.
        app_data (int): Mouse wheel movement data.
    """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    img_tags = get_tag("img_tags")
    tag_key_down = get_tag("key_down_tag")
    
    # Whether the Ctrl key is pressed: zoom vs. scroll
    key_pressed = dpg.get_item_user_data(tag_key_down)
    
    # Track if any changes were made
    any_change = False
    
    # Zoom functionality
    if key_pressed:
        zoom_factor_key = dpg.get_value(img_tags["zoom_factor"])
        zoom_factor_dict = dpg.get_item_user_data(img_tags["zoom_factor"])
        zoom_factor = zoom_factor_dict[zoom_factor_key]
        
        xyz_range_inp_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
        xyz_range_tags_vals_mins_maxs = [(tag, tuple([i for i in dpg.get_value(tag)[:2]]), config["min_value"], config["max_value"]) for (tag, config) in [(tag, dpg.get_item_configuration(tag)) for tag in xyz_range_inp_tags]]
        xyz_slices = dpg.get_value(img_tags["viewed_slices"])[:3]
        
        for idx, (dim_tag, dim_range, dim_min, dim_max) in enumerate(xyz_range_tags_vals_mins_maxs):
            zoom_center = xyz_slices[idx]
            range_delta = dim_range[1] - dim_range[0]
            
            zoom_type = app_data > 0
            if zoom_type: # Zoom in
                span = range_delta * (1 - zoom_factor)
            else: # Zoom out
                span = range_delta / (1 - zoom_factor)
            
            min_val = round(zoom_center - span / 2)
            max_val = round(zoom_center + span / 2)
            
            if min_val < dim_min:
                max_val = min(max_val - (min_val - dim_min), dim_max)
                min_val = dim_min
            if max_val > dim_max:
                min_val = max(min_val - (max_val - dim_max), dim_min)
                max_val = dim_max
            
            # Ensure that the range is at least 16 units
            while max_val - min_val < 16:
                if min_val > dim_min:
                    min_val -= 1
                if max_val < dim_max:
                    max_val += 1
                if min_val == dim_min and max_val == dim_max:
                    break
            
            new_range = (min_val, max_val)
            
            if dim_range != new_range:
                any_change = True
            
            dpg.set_value(dim_tag, new_range)
        
        dpg.set_item_user_data(tag_key_down, False)
    
    # Scroll functionality
    else: 
        direction = -int(app_data) 
        view_type = view_dict["view_type"]
        
        slice_tag = img_tags["viewed_slices"]
        slices = tuple([i for i in dpg.get_value(slice_tag)[:3]])
        
        # Range and slice idx based on which dim is being scrolled through
        if view_type == "axial":
            range_tag = img_tags["zrange"]
            slice_idx = 2
        elif view_type == "coronal":
            range_tag = img_tags["yrange"]
            slice_idx = 1
        elif view_type == "sagittal":
            range_tag = img_tags["xrange"]
            slice_idx = 0
        
        range_min, range_max = dpg.get_value(range_tag)[:2]
        
        slices_copy = [i for i in slices]
        slices_copy[slice_idx] = int(min(max(slices_copy[slice_idx] + direction, range_min), range_max))
        slices_copy = tuple(slices_copy)
        
        if slices != slices_copy:
            any_change = True
        
        dpg.set_value(slice_tag, slices_copy)
        
        xyz_range_inp_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
        for idx, (dim_tag, dim_slice) in enumerate(zip(xyz_range_inp_tags, slices_copy)):
            range_config = dpg.get_item_configuration(dim_tag)
            dim_min_limit, dim_max_limit = range_config["min_value"], range_config["max_value"]
            dim_range = tuple([i for i in dpg.get_value(dim_tag)[:2]])
            dim_min, dim_max = dim_range
            
            # Ensure dim_slice is within the range
            new_dim_min = max(min(dim_min, dim_slice - 1, dim_max_limit - 1), dim_min_limit)
            new_dim_max = min(max(dim_max, dim_slice + 1, new_dim_min + 1), dim_max_limit)
            new_dim_range = (new_dim_min, new_dim_max)
            
            if dim_range != new_dim_range:
                any_change = True
            
            dpg.set_value(dim_tag, new_dim_range)
    
    # Trigger texture refresh on another thread
    if any_change:
        request_texture_update(texture_action_type="update")

def _handler_KeyPress(sender, app_data, user_data):
    """
    Handles key press events to enable specific interactions (e.g., zoom with Ctrl key).
    
    Args:
        sender (int): The tag of the keyboard event handler.
        app_data (list): Key press data (e.g., key code).
    """
    if app_data[0] == dpg.mvKey_LControl or app_data[0] == dpg.mvKey_RControl:
        dpg.set_item_user_data(sender, True)

def _handler_KeyRelease(sender, app_data, user_data):
    """
    Handles key release events to disable specific interactions (e.g., zoom with Ctrl key).
    
    Args:
        sender (int): The tag of the keyboard event handler.
        app_data (int): Key release data (e.g., key code).
    """
    if app_data == dpg.mvKey_LControl or app_data == dpg.mvKey_RControl:
        tag_key_down = get_tag("key_down_tag")
        dpg.set_item_user_data(tag_key_down, False)

def _itemhandler_MouseHover(sender, app_data, user_data):
    """ Displays tooltip text for the hovered view based on mouse position. """
    view_dict = get_hovered_view_dict()
    if not view_dict:
        return
    
    slicer_xyz = get_mouse_slice_pos_xyz(view_dict)
    if not slicer_xyz:
        return
    
    # Find values at location
    slicer_yxz = (slicer_xyz[1], slicer_xyz[0], slicer_xyz[2])
    data_manager = get_user_data(td_key="data_manager")
    roi_info_list = data_manager.return_roi_info_list_at_slice(slicer_yxz)
    img_value_list = data_manager.return_image_value_list_at_slice(slicer_yxz)
    dose_value_list = data_manager.return_dose_value_list_at_slice(slicer_yxz)
    
    # Update GUI
    safe_delete(view_dict["tooltip"], children_only=True)
    img_values = ", ".join([str(round(val)) for val in img_value_list]) if img_value_list else ""
    dose_values_sum = round(sum(dose_value_list) * 100) if dose_value_list else 0
    # dose_values = ", ".join([str(round(val * 100)) for val in dose_value_list]) if dose_value_list else ""
    with dpg.group(parent=view_dict["tooltip"]):
        dpg.add_text(
            f"Voxel location (X, Y, Z): {slicer_xyz}"
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
