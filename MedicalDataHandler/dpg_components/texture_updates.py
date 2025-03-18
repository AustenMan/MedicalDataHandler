import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data, update_viewport_and_popups, update_font_scale
from utils.dpg_utils import safe_delete

def request_texture_update(*args, **kwargs):
    """ Triggers a texture update request on the shared state manager. """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.add_texture_render(_update_textures, *args, **kwargs)

def _update_textures(*args, **kwargs):
    """ Updates the textures in the DearPyGUI interface. """
    # Get necessary params
    texture_action_type = kwargs.get("texture_action_type", "update")
    config_manager = get_user_data(td_key="config_manager")
    data_manager = get_user_data(td_key="data_manager")
    img_tags = get_tag("img_tags")
    tag_show_crosshairs = img_tags["show_crosshairs"]
    tag_show_OL = img_tags["show_orientation_labels"]
    
    # Get texture params
    size, spacing, slices, xyz_ranges, rotation, flips = _get_core_texture_params(texture_action_type)
    display_alphas, dose_range, contour_thickness, image_window_width, image_window_level = _get_visual_texture_params()
    
    # Update general display & viewport, then get image length & texture size
    update_font_scale(config_manager.get_font_scale())
    current_screen_size = (dpg.get_viewport_width(), dpg.get_viewport_height())
    new_screen_size = config_manager.get_screen_size()
    WH_ratios = update_viewport_and_popups(new_screen_size, current_screen_size)
    image_length = _get_image_length(WH_ratios)
    
    view_slicing_dict = {
        "axial": (slice(xyz_ranges[1][0], xyz_ranges[1][1] + 1, 1), slice(xyz_ranges[0][0], xyz_ranges[0][1] + 1, 1), slices[2]),
        "coronal": (slices[1], slice(xyz_ranges[0][0], xyz_ranges[0][1] + 1, 1), slice(xyz_ranges[2][0], xyz_ranges[2][1] + 1, 1)),
        "sagittal": (slice(xyz_ranges[1][0], xyz_ranges[1][1] + 1, 1), slices[0], slice(xyz_ranges[2][0], xyz_ranges[2][1] + 1, 1))
    }
    
    texture_dict = {}
    for view_type, slicer in view_slicing_dict.items():
        texture_params = {
            "view_type": view_type, "slices": slices, "xyz_ranges": xyz_ranges, "slicer": slicer, 
            "image_length": image_length, "size": size, "voxel_spacing": spacing, 
            "rotation": rotation, "flips": flips, "contour_thickness": contour_thickness,
            "display_alphas": display_alphas, "dose_thresholds": dose_range,
            "image_window_level": image_window_level, "image_window_width": image_window_width,
            "show_crosshairs": dpg.get_value(tag_show_crosshairs) if dpg.does_item_exist(tag_show_crosshairs) else True,
            "show_orientation_labels": dpg.get_value(tag_show_OL) if dpg.does_item_exist(tag_show_OL) else True
        }
        texture_dict[view_type] = data_manager.return_texture_from_active_data(texture_params)
    
    _set_textures_and_images(image_length, texture_dict)

def _get_core_texture_params(texture_action_type):
    """ 
    Returns the core texture parameters for generating the patient's data. 
    
    Args:
        texture_action_type (str): The type of action to perform on the texture.
    
    Returns:
        tuple: A tuple containing the size, spacing, slices, xyz_ranges, rotation, and flips.
    """
    # Get necessary params
    config_manager = get_user_data(td_key="config_manager")
    data_manager = get_user_data(td_key="data_manager")
    img_tags = get_tag("img_tags")
    default_display_dict = get_user_data(td_key="default_display_dict")
    
    # Tags
    viewed_slices_tag = img_tags["viewed_slices"]
    xyz_range_tags = [img_tags["xrange"], img_tags["yrange"], img_tags["zrange"]]
    rotation_tag = img_tags["rotation"]
    flip_tags = [img_tags["flip_lr"], img_tags["flip_ap"], img_tags["flip_si"]]
    spacing_tag = img_tags["voxel_spacing"]
    spacing_cbox_tag = img_tags["voxel_spacing_cbox"]
    
    # Get unmodified params for size and spacing
    original_size = data_manager.return_sitk_reference_param("original_size") or default_display_dict["DATA_SIZE"]
    original_spacing = data_manager.return_sitk_reference_param("original_spacing") or default_display_dict["VOXEL_SPACING"]
    
    # Get core data viewing parameters
    if texture_action_type == "reset":
        spacing = config_manager.get_voxel_spacing() if (dpg.does_item_exist(spacing_cbox_tag) and dpg.get_value(spacing_cbox_tag)) else original_spacing
        size = original_size
        slices = default_display_dict["SLICE_VALS"]
        xyz_ranges = default_display_dict["RANGES"]
        rotation = int(default_display_dict["ROTATION"])
        flips = [default_display_dict["FLIP_LR"], default_display_dict["FLIP_AP"], default_display_dict["FLIP_SI"]]
    elif texture_action_type == "initialize":
        spacing = config_manager.get_voxel_spacing() if (dpg.does_item_exist(spacing_cbox_tag) and dpg.get_value(spacing_cbox_tag)) else original_spacing
        size = [round(original_size[i] * original_spacing[i] / spacing[i]) for i in range(len(spacing))]
        slices = [round(size[i] / 2) for i in range(len(size))]
        xyz_ranges = [(0, size[i] - 1) for i in range(len(size))]
        rotation = int(default_display_dict["ROTATION"])
        flips = [default_display_dict["FLIP_LR"], default_display_dict["FLIP_AP"], default_display_dict["FLIP_SI"]]
    else:
        spacing = dpg.get_value(spacing_tag)[:3] if dpg.does_item_exist(spacing_tag) else original_spacing
        size = [round(original_size[i] * original_spacing[i] / spacing[i]) for i in range(len(spacing))]
        slices = dpg.get_value(viewed_slices_tag)[:3] if dpg.does_item_exist(viewed_slices_tag) else default_display_dict["SLICE_VALS"]
        xyz_ranges = [dpg.get_value(tag)[:2] for tag in xyz_range_tags] if all([dpg.does_item_exist(tag) for tag in xyz_range_tags]) else default_display_dict["RANGES"]
        rotation = int(dpg.get_value(rotation_tag)) if dpg.does_item_exist(rotation_tag) else default_display_dict["ROTATION"]
        flips = [dpg.get_value(tag) for tag in flip_tags] if all([dpg.does_item_exist(tag) for tag in flip_tags]) else [default_display_dict["FLIP_LR"], default_display_dict["FLIP_AP"], default_display_dict["FLIP_SI"]]
        # Get previous display range limits
        if all([dpg.does_item_exist(tag) for tag in xyz_range_tags]):
            prev_range_limits = [max(config["max_value"] - config["min_value"], 1) for config in [dpg.get_item_configuration(tag) for tag in xyz_range_tags]]
        else: 
            prev_range_limits = [default_display_dict["RANGES"][i][1] - default_display_dict["RANGES"][i][0] for i in range(len(default_display_dict["RANGES"]))]
        # Compute new xyz display ranges based on relative percentages
        xyz_ranges = [(round((size[i] - 1) * (xyz_ranges[i][0] / prev_range_limits[i])), round((size[i] - 1) * (xyz_ranges[i][1] / prev_range_limits[i]))) for i in range(len(slices))]
        # Compute new slices based on relative percentages
        slices = [round((size[i] - 1) * (slices[i] / prev_range_limits[i])) for i in range(len(slices))]
    
    # Validate and update DPG elements
    slices = [int(min(max(val, xyz_ranges[idx][0]), xyz_ranges[idx][1])) for idx, val in enumerate(slices)]
    reset_slices = [int(min(max(round((xyz_ranges[idx][1] - xyz_ranges[idx][0]) / 2), xyz_ranges[idx][0]), xyz_ranges[idx][1])) for idx in range(len(xyz_ranges))]
    if dpg.does_item_exist(viewed_slices_tag):
        dpg.configure_item(viewed_slices_tag, default_value=reset_slices, user_data=reset_slices, min_value=0, max_value=max(size)-1)
        dpg.set_value(viewed_slices_tag, slices)
    
    for dim, (range_tag, dim_range) in enumerate(zip(xyz_range_tags, xyz_ranges)):
        dim_range = [int(min(max(dim_range[0], 0), size[dim] - 2)), int(min(max(dim_range[1], 1), size[dim] - 1))]
        dim_range = dim_range if dim_range[0] < dim_range[1] else [dim_range[0]-1, dim_range[1]] if dim_range[0] > 0 else [dim_range[0], dim_range[1]+1]
        reset_dim_range = (0, size[dim]-1)
        if dpg.does_item_exist(range_tag):
            dpg.configure_item(range_tag, default_value=reset_dim_range, user_data=reset_dim_range, max_value=size[dim]-1)
            dpg.set_value(range_tag, dim_range)
    
    if dpg.does_item_exist(rotation_tag):
        dpg.set_value(rotation_tag, str(rotation))
    for flip_tag, flip in zip(flip_tags, flips):
        if dpg.does_item_exist(flip_tag):
            dpg.set_value(flip_tag, value=flip)
    
    if dpg.does_item_exist(spacing_tag):
        dpg.configure_item(spacing_tag, default_value=original_spacing, user_data=original_spacing)
        dpg.set_value(spacing_tag, spacing)
    
    return size, spacing, slices, xyz_ranges, rotation, flips

def _get_visual_texture_params():
    """
    Returns the visual texture parameters to customize the texture display.
    
    Returns:
        tuple: A tuple containing the display alphas, dose range, contour thickness, image window width, and image window level.
    """
    config_manager = get_user_data(td_key="config_manager")
    img_tags = get_tag("img_tags")
    default_display_dict = get_user_data(td_key="default_display_dict")
    
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
    
    config_preset_dict = config_manager.get_window_presets()
    
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
    
def _get_image_length(WH_ratios=(1.0, 1.0)):
    """
    Uses width/height ratios in case DPG has not updated the screen size yet.
    
    Args:
        WH_ratios (tuple, optional): Width and height ratios. Defaults to (1.0, 1.0).
    
    Returns:
        int: Image length based on the minimum of all possible sizes.
    """
    width_ratio, height_ratio = WH_ratios
    ax_W, ax_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_topleft"))
    misc_W, misc_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_topright"))
    cor_W, cor_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_bottomleft"))
    sag_W, sag_H = dpg.get_item_rect_size(dpg.get_item_parent("mw_ctr_bottomright"))
    min_size = min(
        ax_W * width_ratio, 
        ax_H * height_ratio,
        misc_W * width_ratio,
        misc_H * height_ratio,
        cor_W * width_ratio, 
        cor_H * height_ratio,
        sag_W * width_ratio,
        sag_H * height_ratio,
    )
    return max(int(((min_size * 0.95) * 2) // 2), 100)  # Ensure even rounding, and minimum size of 100
    
def _set_textures_and_images(image_length, texture_dict):
    """
    Creates the textures and images for the axial, coronal, and sagittal views.
    
    Args:
        image_length (int): Image length for the textures.
        texture_dict (dict): Dictionary containing the axial, coronal, and sagittal textures.
    """
    if not isinstance(image_length, int):
        raise ValueError(f"Error creating textures: The image length must be an integer. Received: {image_length}")
    if not texture_dict or not all(x in texture_dict for x in ["axial", "coronal", "sagittal"]):
        raise ValueError(f"Error creating textures: The texture dictionary must contain 'axial', 'coronal', and 'sagittal' keys. Received: {texture_dict}")
    
    tag_texture_registry = get_tag("texture_registry")
    tag_item_handler_registry = get_tag("item_handler_registry")
    
    dpg.configure_item("mw_ctr_topright", width=image_length, height=image_length) # Unused view
    for (view_type, texture), parent_tag in zip(texture_dict.items(), ["mw_ctr_topleft", "mw_ctr_bottomleft", "mw_ctr_bottomright"]):
        view_tag_dict = get_tag(f"{view_type}_dict")
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
