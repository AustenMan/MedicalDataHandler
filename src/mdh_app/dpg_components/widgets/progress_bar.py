from __future__ import annotations


import logging
from time import time
from math import floor
from typing import Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag
from mdh_app.utils.general_utils import format_time


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def update_progress(
    value: Union[int, float],
    max_value: Union[int, float],
    description: str = "",
    terminated: bool = False
) -> None:
    """
    Update the progress bar's value and overlay text in Dear PyGUI.

    Args:
        value: The current progress value (non-negative).
        max_value: The maximum progress value (non-negative).
        description: Additional text to display in the overlay.
        terminated: Indicates if the progress was terminated early.
    """
    tag_progress_bar = get_tag("pbar")
    if not dpg.does_item_exist(tag_progress_bar):
        return
    
    # Ensure values are non-negative
    value = max(0, value)
    max_value = max(0, max_value)
    
    # Handle time tracking
    user_data = dpg.get_item_user_data(tag_progress_bar)
    if not user_data:
        user_data = (None, None)  # (initialization_time, first_progress_time)
        dpg.set_item_user_data(tag_progress_bar, user_data)
    
    initialization_time, first_progress_time = user_data
    
    # Set initialization timestamp once when progress bar is first used
    if max_value > 0 and initialization_time is None:
        initialization_time = time()
        user_data = (initialization_time, first_progress_time)
        dpg.set_item_user_data(tag_progress_bar, user_data)
    
    # Elapsed time since bar initialization
    elapsed_time = time() - initialization_time if initialization_time else None
    elapsed_time_str = f"Time Elapsed: {format_time(elapsed_time)}" if elapsed_time else ""
    
    # Set timestamp of first actual progress > 0
    if value > 0 and first_progress_time is None:
        first_progress_time = time()
        user_data = (initialization_time, first_progress_time)
        dpg.set_item_user_data(tag_progress_bar, user_data)
    
    # ETA based on progress since first_progress_time
    remaining_time = None
    if first_progress_time and value > 0:
        elapsed_since_first_progress = time() - first_progress_time
        time_per_unit = elapsed_since_first_progress / value
        remaining_time = (max_value - value) * time_per_unit
    remaining_time_str = f"ETA: {format_time(remaining_time, at_least='m')}" if remaining_time else "ETA: --:--:--"
    
    # Reset timestamps if done
    if max_value == 0 or value >= max_value:
        dpg.set_item_user_data(tag_progress_bar, (None, None))
    
    # Format numbers with commas for readability
    formatted_value = f"{value:,}"
    formatted_max_value = f"{max_value:,}"
    progress_percent = int(floor((value / max_value) * 100)) if max_value > 0 else 0
    
    # Construct overlay text
    if max_value == 0:
        overlay_text = description if description else ""
        item_val = 0.0
    elif value >= max_value:
        overlay_text = (
            f"[100%] [{formatted_value} / {formatted_max_value}]" + 
            (f" | {elapsed_time_str}" if elapsed_time else "") + 
            (f" | {description}" if description else "")
        )
        item_val = 1.0
    else:
        item_val = min(value / max_value, 0.99)
        overlay_text = (
            f"[{progress_percent}%] [{formatted_value} / {formatted_max_value}]" + 
            (f" | {elapsed_time_str}" if elapsed_time else "") + 
            (f" | {remaining_time_str}" if remaining_time else "") + 
            (f" | {description}" if description else "")
        )
    
    # Log the untrimmed overlay text and update the progress bar's value
    logger.info(overlay_text)
    
    # Get the available width for the progress bar text
    parent = dpg.get_item_parent(tag_progress_bar)
    width = None
    while width is None and dpg.does_item_exist(parent) and (dpg.get_item_type(parent) != "mvAppItemType::mvChildWindow" or dpg.get_item_type(parent) != "mvAppItemType::mvWindowAppItem"):
        width = dpg.get_item_rect_size(parent)[0]
        parent = dpg.get_item_parent(parent)
    
    # Use 90% of the available width for text, 400 as a backup
    width = round(width * 0.9)  if width is not None else 400 
    
    # Trim the overlay text if it exceeds the available width
    text_W = dpg.get_text_size(overlay_text)[0]
    if text_W > width:
        overlay_text = overlay_text[:round(len(overlay_text) * width / text_W) - 3] + "..."
    
    # Update the progress bar's overlay text and value
    dpg.configure_item(tag_progress_bar, overlay=overlay_text)
    dpg.set_value(tag_progress_bar, item_val)
    
    # Update the progress bar's theme based on the progress state
    pbar_themes = get_tag("pbar_themes") # dict with green, blue, red keys
    if (max_value > 0 and value == max_value):
        dpg.bind_item_theme(tag_progress_bar, pbar_themes["green"])
    elif terminated:
        dpg.bind_item_theme(tag_progress_bar, pbar_themes["red"])
    else:
        dpg.bind_item_theme(tag_progress_bar, pbar_themes["blue"])

