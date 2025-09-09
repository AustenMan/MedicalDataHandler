from __future__ import annotations


import logging
from typing import Any, Dict, List, Tuple, Union, Callable, TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.widgets.settings.settings_utils import _reset_setting_callback, _get_screen_limits
from mdh_app.utils.dpg_utils import safe_delete, verify_input_directory


logger = logging.getLogger(__name__)


def add_gui_controls(
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
                        callback=_reset_setting_callback
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


def add_program_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    remove_all_callback: Callable,
) -> None:
    """ Add Program Data Controls """
    removal_tooltip = (
        "Removes all patient data from the program.\n"
        "This *will not* delete any files from your PC.\n"
        "This *will* remove all data associations from the program.\n"
        "This action *cannot be undone* and would require re-adding the data."
    )
    
    # Add to the window
    with dpg.tree_node(label="Program Data Controls", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)

            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=removal_tooltip,
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Remove All Data:")
                with dpg.group(horizontal=True):
                    # Button for removing all data
                    dpg.add_button(
                        label="Remove All Data",
                        width=size_dict["button_width"],
                        callback=remove_all_callback,
                    )
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            default_value=removal_tooltip,
                            wrap=size_dict["tooltip_width"]
                        )


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


