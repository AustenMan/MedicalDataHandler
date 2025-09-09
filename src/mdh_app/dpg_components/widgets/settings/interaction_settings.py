from __future__ import annotations


import logging
from typing import Any, Dict, Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


from mdh_app.dpg_components.core.utils import get_tag, get_user_data


logger = logging.getLogger(__name__)


def add_interaction_controls(
    tag_parent: Union[str, int],
    size_dict: Dict[str, Any],
    conf_mgr: ConfigManager
) -> None:
    """ Add Image Interactivity Settings """
    # Get panning parameters
    current_pan_speed = conf_mgr.get_pan_speed()
    pan_speed_dict = {"Slow": 0.01, "Medium": 0.02, "Fast": 0.04}
    pan_speed_default_val = next((speed for speed, val in pan_speed_dict.items() if val == current_pan_speed), "Medium")
    
    # Get zoom factor parameters
    current_zoom_factor = conf_mgr.get_zoom_factor()
    zoom_factor_dict = {"Slow": 0.05, "Medium": 0.1, "Fast": 0.15}
    zoom_factor_default_val = next((zf for zf, val in zoom_factor_dict.items() if val == current_zoom_factor), "Medium")
    
    # Add to the window
    with dpg.tree_node(label="Interactivity", parent=tag_parent, default_open=False):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
            dpg.add_table_column(init_width_or_weight=0.3)
            dpg.add_table_column(init_width_or_weight=0.7)
        
            # Panning Speed
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the panning speed", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Panning Speed:")
                dpg.add_combo(
                    tag=get_tag("img_tags")["pan_speed"], 
                    items=list(pan_speed_dict.keys()), 
                    default_value=pan_speed_default_val, 
                    user_data=pan_speed_dict, 
                    width=size_dict["button_width"], 
                    callback=_update_panning_speed
                )
            
            # Zoom Speed
            with dpg.table_row():
                with dpg.group(horizontal=True):
                    with dpg.tooltip(parent=dpg.last_item()):
                        dpg.add_text(
                            "Adjust the zoom speed", 
                            wrap=size_dict["tooltip_width"]
                        )
                    dpg.add_text("Zoom Speed:")
                dpg.add_combo(
                    tag=get_tag("img_tags")["zoom_factor"], 
                    items=list(zoom_factor_dict.keys()), 
                    default_value=zoom_factor_default_val, 
                    user_data=zoom_factor_dict, 
                    width=size_dict["button_width"], 
                    callback=_update_zoom_factor
                )

def _update_panning_speed(
    sender: Union[str, int],
    app_data: str,
    user_data: Dict[str, Union[float, int]]
) -> None:
    """
    Update the panning speed setting.
    
    Args:
        sender: The panning speed widget.
        app_data: The selected speed key ('Slow', 'Medium', 'Fast').
        user_data: A dictionary mapping speed keys to their numerical values.
    """
    pan_speed_key = app_data
    pan_speed_dict = user_data
    pan_speed_value = pan_speed_dict[pan_speed_key]
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"pan_speed": pan_speed_value})

def _update_zoom_factor(
    sender: Union[str, int],
    app_data: str,
    user_data: Dict[str, Union[float, int]]
) -> None:
    """
    Update the zoom factor setting.
    
    Args:
        sender: The zoom factor widget.
        app_data: The selected speed key ('Slow', 'Medium', 'Fast').
        user_data: A dictionary mapping speed keys to their numerical values.
    """
    zoom_factor_key = app_data
    zoom_factor_dict = user_data
    zoom_factor_value = zoom_factor_dict[zoom_factor_key]
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"zoom_factor": zoom_factor_value})
