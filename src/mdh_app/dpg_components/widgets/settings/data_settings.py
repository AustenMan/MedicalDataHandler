from __future__ import annotations


import logging
from typing import Any, Dict, List, Tuple, Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.widgets.settings.settings_utils import _reset_setting_callback


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def add_spacing_controls(
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
                        callback=_reset_setting_callback
                    )


def add_rot_flip_controls(
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
                        callback=_reset_setting_callback
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
                        callback=_reset_setting_callback
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

