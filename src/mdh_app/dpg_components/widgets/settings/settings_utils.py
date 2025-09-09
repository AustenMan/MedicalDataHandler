from __future__ import annotations


import logging
from typing import Any, Set, List, Tuple, Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


from mdh_app.dpg_components.core.utils import get_user_data


logger = logging.getLogger(__name__)


def _reset_setting_callback(
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
            _reset_setting_callback(sender, app_data, item_tag)
        return
    
    item_tag = user_data
    
    item_default_value = dpg.get_item_user_data(item_tag)
    item_callback = dpg.get_item_callback(item_tag)
    
    dpg.set_value(item=item_tag, value=item_default_value)
    if callable(item_callback):
        item_callback(item_tag, item_default_value, item_default_value)


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

