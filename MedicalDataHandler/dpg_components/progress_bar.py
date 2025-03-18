from time import time
from math import floor
import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag
from utils.general_utils import format_time

def update_progress(value, max_value, description=""):
    """
    Updates the progress bar's value and overlay text in Dear PyGUI.
    
    Args:
        value (int | float): The current progress value. Must be non-negative.
        max_value (int | float): The maximum progress value. Must be non-negative.
        description (str, optional): Additional text to display in the progress bar overlay. Default is an empty string.
    """
    # Check if the progress bar exists
    tag_progress_bar = get_tag("pbar")
    if not dpg.does_item_exist(tag_progress_bar):
        return
    
    # Ensure values are non-negative
    value = max(0, value)
    max_value = max(0, max_value)
    
    # Handle time tracking
    start_time = dpg.get_item_user_data(tag_progress_bar)
    if max_value > 0 and start_time is None:
        start_time = time()  # Start tracking
        dpg.set_item_user_data(tag_progress_bar, start_time)
    elapsed_time = time() - start_time if start_time else None
    elapsed_time_str = f"Time Elapsed: {format_time(elapsed_time)}" if elapsed_time else ""
    
    # Estimate time remaining
    remaining_time = None
    if elapsed_time and value > 0:
        time_per_unit = elapsed_time / value  # Time taken per unit progress
        remaining_time = (max_value - value) * time_per_unit
    remaining_time_str = f"ETA: {format_time(remaining_time)}" if remaining_time else "ETA: --:--:--"
    
    # Reset start time if progress completes or resets
    if max_value == 0 or value >= max_value:
        start_time = None 
        dpg.set_item_user_data(tag_progress_bar, start_time)
    
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
    
    # Print the untrimmed overlay text and update the progress bar's value
    print(overlay_text)
    
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
