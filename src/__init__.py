import sys
import signal
import atexit
import logging
import multiprocessing
from typing import Any
from functools import partial


from mdh_app.dpg_components.core.launcher import GUILauncher, destroy_gui
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.logger_utils import start_root_logger


logger = start_root_logger(logger_level=logging.INFO, buffer_length=300)


def signal_handler(signum: int, frame: Any, shared_state_manager: SharedStateManager) -> None:
    """Handle termination signals by invoking cleanup."""
    destroy_gui(shared_state_manager)
    sys.exit(0)


def register_exit_handlers(shared_state_manager: SharedStateManager) -> None:
    """Registers cleanup functions for exit and termination signals."""
    atexit.register(partial(destroy_gui, shared_state_manager))
    signal.signal(signal.SIGTERM, partial(signal_handler, shared_state_manager=shared_state_manager))
    signal.signal(signal.SIGINT, partial(signal_handler, shared_state_manager=shared_state_manager))


def main() -> None:
    shared_state_manager: SharedStateManager = SharedStateManager()
    register_exit_handlers(shared_state_manager)
    
    try:
        GUILauncher(shared_state_manager).launch()
    except Exception as e:
        logger.exception("Failed to run the GUI!", exc_info=True, stack_info=True)
    finally:
        destroy_gui(shared_state_manager)


if __name__ == "__main__":
    # Keep this block to avoid issues with multiprocessing
    if sys.platform.lower().startswith("win"):
        multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    
    main()

