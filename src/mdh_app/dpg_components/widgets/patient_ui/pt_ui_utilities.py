from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Tuple, Any, Union


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update


if TYPE_CHECKING:
    from mdh_app.managers.data_manager import DataManager


logger = logging.getLogger(__name__)


def update_cbox_callback(sender: Union[str, int], app_data: bool, user_data: Tuple[Any, ...]) -> None:
    """
    Update the display state based on the checkbox state.
    
    Args:
        sender: The checkbox tag.
        app_data: The state of the checkbox (True if checked, else False).
        user_data: Tuple containing keys for identifying data in the Data Manager.
            Identifier is either SeriesInstanceUID (image) or SOPInstanceUID (non-image)
            Key is the dictionary key to check for
            Value is the SITK Image
    """
    load_data = app_data
    display_data_keys = user_data
    data_mgr: DataManager = get_user_data("data_manager")
    
    any_data_active_before = data_mgr.return_is_any_data_active()
    data_mgr.update_active_data(load_data, display_data_keys)
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
