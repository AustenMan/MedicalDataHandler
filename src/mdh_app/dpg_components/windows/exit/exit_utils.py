from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.utils.dpg_utils import safe_delete


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


def exit_callback(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Callback function to exit the program safely.

    This function disables the exit button, updates its label to indicate the exit process,
    shuts down the shared state manager, and stops the Dear PyGUI context.

    Args:
        sender: The tag of the exit button that triggered this callback.
        app_data: Additional event data (unused).
        user_data: The return button tag to be removed.
    """
    # Get & remove the return button
    return_button = user_data
    safe_delete(return_button)
    
    # Disable the exit button and update its text
    dpg.disable_item(sender)
    dpg.configure_item(sender, label="SAFELY EXITING, PLEASE WAIT...")
    
    # Shutdown the shared state manager
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    ss_mgr.shutdown_manager()
    
    # Stop the DPG context, which returns to the __init__.py cleanup function
    dpg.stop_dearpygui()
