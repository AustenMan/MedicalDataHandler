from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, List, Union


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def _update_orientation_label_color(sender: Union[str, int], app_data: List[float], user_data: Any) -> None:
    """
    Update the orientation label color using the color selected in the color picker.
    
    Args:
        sender: The tag of the color picker.
        app_data: A list of RGBA float values.
        user_data: Additional user data (unused).
    """
    new_color = tuple([round(min(max(255 * x, 0), 255)) for x in app_data])
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    conf_mgr.update_user_config({"orientation_label_color": new_color})
    request_texture_update(texture_action_type="update")
