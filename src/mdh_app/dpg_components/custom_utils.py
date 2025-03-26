import logging
import dearpygui.dearpygui as dpg
from time import strftime
from typing import Any, Callable, Optional, Union, Tuple

from mdh_app.managers.config_manager import ConfigManager

logger = logging.getLogger(__name__)

def get_tag(key: str) -> Any:
    """
    Retrieve the tag corresponding to a given key from the tag dictionary.
    
    Args:
        key: A string key to look up in the tag dictionary.
    
    Returns:
        The tag associated with the key.
    
    Raises:
        ValueError: If the key is not a string.
    """
    if not isinstance(key, str):
        raise ValueError("The key must be a string.")
    return dpg.get_item_user_data("tag_dict").get(key)

def get_user_data(td_key: Optional[str] = None, tag: Optional[Union[str, int]] = None) -> Any:
    """
    Retrieve user data either via a tag dictionary key or directly from a tag.
    
    Args:
        td_key: A key in the tag dictionary.
        tag: A specific tag (string or integer).
    
    Returns:
        The associated user data, or None if the item does not exist.
    
    Raises:
        ValueError: If neither or both parameters are provided, or if invalid types are passed.
    """
    valid_key: bool = isinstance(td_key, str)
    valid_tag: bool = isinstance(tag, (str, int))
    
    if not valid_key and not valid_tag:
        raise ValueError("Either a key in the tag dictionary or a tag must be provided.")
    if valid_key and valid_tag:
        raise ValueError("Only one of key or tag should be provided.")
    
    if valid_key:
        tag = get_tag(td_key)
        valid_tag = isinstance(tag, (str, int))
        if not valid_tag:
            raise ValueError(f"Invalid tag retrieved from tag dictionary key '{td_key}'.")
    
    if valid_tag:
        return dpg.get_item_user_data(tag) if dpg.does_item_exist(tag) else None
    
    raise ValueError(f"Invalid input. td_key must be a string and tag must be a string or integer: td_key={td_key}, tag={tag}")

def update_viewport_and_popups(
    new_screen_size: Tuple[int, int],
    current_screen_size: Optional[Tuple[int, int]] = None
) -> Tuple[float, float]:
    """
    Update the viewport dimensions and adjust open popups to the new screen size.
    
    Args:
        new_screen_size: New screen dimensions as (width, height).
        current_screen_size: Current screen dimensions as (width, height). Defaults to None.
    
    Returns:
        A tuple containing the width and height scaling factors.
    """
    # Update the viewport size
    dpg.configure_viewport(
        item=0,
        width=new_screen_size[0], height=new_screen_size[1],
        min_width=new_screen_size[0], min_height=new_screen_size[1],
        max_width=new_screen_size[0], max_height=new_screen_size[1]
    )
    
    # Get the width and height ratios between the new and current screen sizes
    if isinstance(current_screen_size, (tuple, list)) and len(current_screen_size) == 2:
        width_ratio = new_screen_size[0] / current_screen_size[0]
        height_ratio = new_screen_size[1] / current_screen_size[1]
        wh_ratios = (width_ratio, height_ratio)
    else:
        wh_ratios = (1.0, 1.0)
    
    # Update any open windows if the screen size has changed
    if wh_ratios != (1.0, 1.0):
        tag_dict = get_user_data(td_key="tag_dict")
        for tag in list(tag_dict.values()):
            if isinstance(tag, (int, str)) and dpg.does_item_exist(tag) and dpg.get_item_type(tag) == "mvAppItemType::mvWindowAppItem":
                prev_pos = dpg.get_item_pos(tag)
                prev_pos_percent = (prev_pos[0] / current_screen_size[0], prev_pos[1] / current_screen_size[1])
                new_pos = (round(new_screen_size[0] * prev_pos_percent[0]), round(new_screen_size[1] * prev_pos_percent[1]))
                
                prev_W, prev_H = dpg.get_item_rect_size(tag)
                new_W, new_H = min(round(prev_W * wh_ratios[0]), new_screen_size[0]), min(round(prev_H * wh_ratios[1]), new_screen_size[1])
                
                dpg.configure_item(tag, width=new_W, height=new_H, pos=new_pos)
    
    # Return the width and height ratios
    return wh_ratios

def update_font_scale(new_font_scale: float) -> None:
    """
    Update the global font scale in Dear PyGUI if it differs from the current value.
    
    Args:
        new_font_scale: The new font scale value.
    """
    current_scale = dpg.get_global_font_scale()
    if current_scale != new_font_scale:
        dpg.set_global_font_scale(new_font_scale)

def add_custom_separator(parent_tag: Optional[Union[str, int]] = None) -> None:
    """
    Add a custom separator with spacing before and after it.
    
    Args:
        parent_tag: The tag of the parent item to which the separator is added.
    """
    size_dict = get_user_data(td_key="size_dict")
    if parent_tag:
        dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        dpg.add_separator(parent=parent_tag)
        dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
    else:
        dpg.add_spacer(height=size_dict["spacer_height"])
        dpg.add_separator()
        dpg.add_spacer(height=size_dict["spacer_height"])

def add_custom_button(
    tag: Optional[Union[str, int]] = None,
    label: str = "",
    height: Optional[int] = None,
    width: Optional[int] = None,
    parent_tag: Optional[Union[str, int]] = None,
    theme_tag: Optional[Union[int, str]] = None,
    callback: Optional[Callable[..., None]] = None,
    user_data: Any = None,
    visible: bool = True,
    enabled: bool = True,
    add_spacer_before: bool = False,
    add_spacer_after: bool = False,
    add_separator_before: bool = False,
    add_separator_after: bool = False,
    tooltip_tag: Optional[Union[str, int]] = None,
    tooltip_text: str = ""
) -> Union[str, int]:
    """
    Create a customizable button with optional spacers, separators, tooltips, and theme.
    
    Args:
        tag: Unique identifier for the button; auto-generated if not provided.
        label: Button label text.
        height: Button height; defaults to a predefined value.
        width: Button width; defaults to a predefined value.
        parent_tag: Tag of the parent container.
        theme_tag: Theme to apply to the button.
        callback: Function to be called on button click.
        user_data: Additional data for the callback.
        visible: Initial visibility of the button.
        enabled: Initial enabled state of the button.
        add_spacer_before: If True, add a spacer before the button.
        add_spacer_after: If True, add a spacer after the button.
        add_separator_before: If True, add a separator before the button.
        add_separator_after: If True, add a separator after the button.
        tooltip_tag: Tag for the tooltip; auto-generated if not provided.
        tooltip_text: Tooltip text to display on hover.
    
    Returns:
        The tag of the created button.
    """
    size_dict = get_user_data(td_key="size_dict")
    tag = tag or dpg.generate_uuid()
    height = height or (size_dict["button_height"] if not label else 0)
    width = width or size_dict["button_width"]

    # Pre-button spacing/separators
    if add_separator_before:
        add_custom_separator(parent_tag)
    elif add_spacer_before:
        if parent_tag:
            dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        else:
            dpg.add_spacer(height=size_dict["spacer_height"])

    # Create button
    if parent_tag:
        dpg.add_button(
            tag=tag, label=label, width=width, height=height,
            callback=callback, user_data=user_data, show=visible, parent=parent_tag,
            enabled=enabled
        )
    else:
        dpg.add_button(
            tag=tag, label=label, width=width, height=height,
            callback=callback, user_data=user_data, show=visible, enabled=enabled
        )

    # Apply theme if provided
    if theme_tag:
        dpg.bind_item_theme(tag, theme_tag)

    # Post-button spacing/separators
    if add_separator_after:
        add_custom_separator(parent_tag)
    elif add_spacer_after:
        if parent_tag:
            dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        else:
            dpg.add_spacer(height=size_dict["spacer_height"])

    # Add tooltip if needed
    if tooltip_text or tooltip_tag:
        tooltip_tag = tooltip_tag or dpg.generate_uuid()
        with dpg.tooltip(parent=tag):
            dpg.add_text(f"{tooltip_text}", tag=tooltip_tag, wrap=size_dict["tooltip_width"])

    return tag

def add_custom_checkbox(
    default_value: bool,
    tag: Optional[Union[str, int]] = None,
    checkbox_label: str = "",
    tooltip_text: str = "",
    add_spacer_after: bool = False
) -> Union[str, int]:
    """
    Create a custom checkbox with an optional tooltip and spacer.
    
    Args:
        default_value: The initial state of the checkbox.
        tag: Unique identifier for the checkbox; auto-generated if not provided.
        checkbox_label: Label for the checkbox.
        tooltip_text: Tooltip text to show on hover.
        add_spacer_after: If True, add a spacer after the checkbox.
    
    Returns:
        The tag of the created checkbox.
    """
    size_dict = get_user_data(td_key="size_dict")
    tag = tag or dpg.generate_uuid()
    dpg.add_checkbox(tag=tag, default_value=bool(default_value), label=checkbox_label)
    if tooltip_text:
        with dpg.tooltip(parent=tag):
            dpg.add_text(f"{tooltip_text}", wrap=size_dict["tooltip_width"])
    if add_spacer_after:
        dpg.add_spacer(height=size_dict["spacer_height"])
    return tag

def capture_screenshot() -> None:
    """Capture the current viewport and save it as a PNG image with a timestamp."""
    # Build timestamped file name
    timestamp = strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"screenshot_{timestamp}.png"
    
    # Get the full file path
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    file_path = conf_mgr.get_screenshots_file_path(file_name)
    
    # Outputs frame buffer as png
    dpg.output_frame_buffer(file_path)
    logger.info(f"Screenshot saved at {file_path}.")

