from __future__ import annotations


import logging
from typing import Any, List, Union, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, capture_screenshot
from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def _handler_KeyPress(sender: Union[str, int], app_data: List[Any], user_data: Any) -> None:
    """
    Process key press events to trigger interactions such as zooming, screenshot capture, or cleanup.

    Args:
        sender: Tag of the keyboard event handler.
        app_data: List containing the key code and press duration.
    """
    key_code, press_duration = app_data
    
    # If Ctrl key is pressed, set user data to true (store that ctrl is pressed)
    if key_code in (dpg.mvKey_LControl, dpg.mvKey_RControl):
        dpg.set_item_user_data(sender, True)
        return

    # If Ctrl+Z is pressed, popup cleanup confirmation
    if key_code == dpg.mvKey_Z and dpg.get_item_user_data(sender):
        cleanup_action = wrap_with_cleanup()
        cleanup_action(sender, app_data, user_data)
        return

    # If Ctrl+S or Print key are pressed, and press_duration is 0, capture screenshot.
    ctrl_s = (key_code == dpg.mvKey_S and dpg.get_item_user_data(sender))
    print_key = (key_code == dpg.mvKey_Print)
    if (ctrl_s or print_key) and press_duration == 0:
        capture_screenshot()
        return


def _handler_KeyRelease(sender: Union[str, int], app_data: int, user_data: Any) -> None:
    """
    Process key release events to disable key-dependent interactions.

    Args:
        sender: Tag of the keyboard event handler.
        app_data: The released key code.
    """
    key_code = app_data
    if key_code in (dpg.mvKey_LControl, dpg.mvKey_RControl):
        tag_key_down = get_tag("key_down_tag")
        dpg.set_item_user_data(tag_key_down, False)

