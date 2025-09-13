from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Tuple, Any, List


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def update_cbox_callback(sender: Union[str, int], app_data: bool, user_data: Tuple[Any]) -> None:
    """
    Update the display state based on the checkbox state.
    
    Args:
        sender: The checkbox tag.
        app_data: The state of the checkbox (True if checked, else False).
        user_data: Tuple containing data type and identifier(s).
    """
    if not isinstance(app_data, bool):
        logger.error(f"Invalid app_data provided to checkbox callback: {app_data}")
        return
    if user_data is None or user_data[0] not in ("image", "roi", "toggle_all_rois", "dose"):
        logger.error(f"Invalid user_data provided to checkbox callback: {user_data}. Expected first element to be one of ('image', 'roi', 'toggle_all_rois', 'dose').")
        return
    
    data_mgr: DataManager = get_user_data("data_manager")
    any_data_active_before = data_mgr.return_is_any_data_active()
    if user_data[0] == "toggle_all_rois":
        struct_uid = user_data[1]
        roi_numbers = data_mgr.get_rtstruct_roi_numbers_by_uid(struct_uid, sort_by_name=True)
        for roi_num in roi_numbers:
            data_mgr.update_cached_data(app_data, ("roi", struct_uid, roi_num))
    else:
        data_mgr.update_cached_data(app_data, user_data)
    any_data_active_after = data_mgr.return_is_any_data_active()
    
    # Data is now cleared -> reset the texture
    if any_data_active_before and not any_data_active_after:
        request_texture_update(texture_action_type="reset")
    # Data is now shown -> initialize the texture
    elif not any_data_active_before and any_data_active_after:
        request_texture_update(texture_action_type="initialize")
    # No change -> update the texture
    else:
        request_texture_update(texture_action_type="update")


def toggle_all_rois(sender: Union[str, int], app_data: Any, user_data: Tuple[List[Any], str]) -> None:
    """
    Toggle display for all ROIs in the RT Structure Set.

    Args:
        sender: The triggering button tag.
        app_data: Additional event data.
        user_data: Tuple of (list of ROI checkbox tags, struct SOPInstanceUID).
    """
    # Disable the button to prevent rapid re-clicks
    dpg.disable_item(sender)
    roi_checkboxes, struct_uid = user_data
    valid_checkboxes = [chk for chk in roi_checkboxes if dpg.does_item_exist(chk)]
    if not valid_checkboxes:
        # Re-enable the button and exit if no valid checkboxes
        dpg.enable_item(sender)
        return
    
    # Disable other checkboxes too
    [dpg.disable_item(chk) for chk in valid_checkboxes]
    
    should_load = not any(dpg.get_value(chk) for chk in valid_checkboxes)
    for chk in valid_checkboxes:
        dpg.set_value(chk, should_load)
    update_cbox_callback(sender, should_load, ("toggle_all_rois", struct_uid))
    
    # Re-enable all items
    [dpg.enable_item(chk) for chk in valid_checkboxes + [sender]]
    

