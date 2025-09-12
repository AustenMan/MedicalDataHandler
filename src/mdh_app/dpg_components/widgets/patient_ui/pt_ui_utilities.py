from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Tuple, Any


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager, DataHandle


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
    if user_data is None or user_data[0] not in ("image", "roi", "dose"):
        logger.error(f"Invalid user_data provided to checkbox callback: {user_data}")
        return
    
    data_mgr: DataManager = get_user_data("data_manager")
    any_data_active_before = data_mgr.return_is_any_data_active()
    
    if user_data[0] == "image":
        series_uid = user_data[1]
        data_mgr.update_cached_data(app_data, ("image", series_uid,))
    elif user_data[0] == "roi":
        rts_sopiuid, roi_number = user_data[1], user_data[2]
        data_mgr.build_rtstruct_roi(rts_sopiuid, roi_number)
        data_mgr.update_cached_data(app_data, ("roi", rts_sopiuid, roi_number,))
    elif user_data[0] == "dose":
        rtd_sopiuid = user_data[1]
        data_mgr.update_cached_data(app_data, ("dose", rtd_sopiuid,))
    
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
