import logging
import dearpygui.dearpygui as dpg
from typing import Any, Callable, Optional, Union

from mdh_app.dpg_components.custom_utils import get_tag
from mdh_app.dpg_components.themes import get_hidden_button_theme
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params

logger = logging.getLogger(__name__)

def create_confirmation_popup(
    button_callback: Callable[[], None],
    button_theme: Optional[Union[int, str, None]] = None,
    no_close: bool = False,
    confirmation_text: str = "Proceeding, please wait...",
    warning_string: str = "Confirm action: ",
    close_callback: Optional[Callable[[], None]] = None,
    second_confirm: bool = False
) -> None:
    """
    Create a confirmation popup window with customizable options.

    This popup displays a warning message and provides buttons for the user
    to either proceed with or cancel the action. Once the user confirms, the
    specified callback is executed.

    Args:
        button_callback: Function to call when the confirmation button is clicked.
        button_theme: Theme tag (int or str) to style the confirmation button; or None.
        no_close: If True, the popup window cannot be closed by the user. Defaults to False.
        confirmation_text: Text to display on the confirmation button.
        warning_string: Warning message to display on the initial button.
        close_callback: Optional function to call when the popup is closed.
        second_confirm: If True, a second confirmation is added to the popup.
    
    Raises:
        ValueError: If button_callback is not callable or if button_theme is invalid.
    """
    if not callable(button_callback):
        raise ValueError(f"Button callback must be callable; received: {button_callback}")
    if button_theme is not None and (not isinstance(button_theme, (int, str)) or not dpg.does_item_exist(button_theme)):
        raise ValueError(f"Button theme must be None or a valid tag (int or str); received: {button_theme}")
    
    if button_theme is None:
        button_theme = get_hidden_button_theme()
    
    tag_conf_popup = get_tag("confirmation_popup")
    safe_delete(tag_conf_popup)
    
    # Get popup dimensions and position
    popup_width, popup_height, popup_pos = get_popup_params(width_ratio=0.75, height_ratio=0.75)
    button_height = round(popup_height // 10)
    
    def final_submit(sender, app_data, user_data):
        safe_delete(tag_conf_popup, children_only=True)
        dpg.add_button(parent=tag_conf_popup, label=confirmation_text, width=-1, height=button_height)
        dpg.bind_item_theme(item=dpg.last_item(), theme=button_theme)
        button_callback(sender, app_data, user_data)
        safe_delete(tag_conf_popup)
    
    def first_submit(sender, app_data, user_data):
        if second_confirm:
            first_btn_tag = user_data
            orig_label = dpg.get_item_label(first_btn_tag)
            dpg.configure_item(first_btn_tag, label=f"Final confirmation: {orig_label}")
            dpg.configure_item(sender, label="Yes, proceed", callback=final_submit)
        else:
            final_submit(sender, app_data, user_data)
    
    def wrapped_close_callback(sender: Any, app_data: Any, user_data: Any) -> None:
        """Execute the close callback if provided, then delete the popup."""
        if close_callback is not None:
            close_callback()
        safe_delete(tag_conf_popup)
    
    # Create the confirmation popup window
    with dpg.window(
        tag=tag_conf_popup,
        label="User Confirmation Request",
        width=popup_width,
        pos=popup_pos,
        no_open_over_existing_popup=False,
        popup=True,
        modal=True,
        no_title_bar=False,
        no_close=no_close,
        on_close=wrapped_close_callback
    ):
        # new button for each newline
        first_btn_tag = None
        for line in warning_string.split("\n"):
            new_tag = dpg.add_button(label=line, width=-1, height=button_height)
            dpg.bind_item_theme(item=dpg.last_item(), theme=button_theme)
            if first_btn_tag is None:
                first_btn_tag = new_tag
        dpg.add_separator()
        dpg.add_spacer(height=button_height // 2)
        dpg.add_button(label="Proceed", width=-1, height=button_height, callback=first_submit, user_data=first_btn_tag)
        dpg.add_spacer(height=button_height // 2)
        dpg.add_button(label="Go back", width=-1, height=button_height, callback=wrapped_close_callback)
