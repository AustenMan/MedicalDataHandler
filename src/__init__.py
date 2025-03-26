import sys
import signal
import atexit
import logging
import multiprocessing
import dearpygui.dearpygui as dpg
from typing import Any
from functools import partial

from mdh_app.dpg_components.launch import launch_gui
from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.managers.dicom_manager import DicomManager
from mdh_app.managers.data_manager import DataManager
from mdh_app.utils.general_utils import get_traceback
from mdh_app.utils.logger_utils import start_root_logger

logger = start_root_logger(logger_level=logging.INFO, buffer_length=300)

def cleanup(shared_state_manager: SharedStateManager) -> None:
    """Destroy DPG context and remove lock file before exiting."""
    try:
        dpg.destroy_context()
    except Exception as e:
        logger.error("Failed to destroy the DPG context." + get_traceback(e))
    
    try:
        shared_state_manager.shutdown_manager()
    except Exception as e:
        logger.error("Failed to shut down the shared state manager." + get_traceback(e))

def signal_handler(signum: int, frame: Any, shared_state_manager: SharedStateManager) -> None:
    """Handle termination signals by invoking cleanup."""
    cleanup(shared_state_manager)
    sys.exit(0)

def register_exit_handlers(shared_state_manager: SharedStateManager) -> None:
    """
    Registers functions for exit and termination signals to ensure that resources are properly cleaned up.
    """
    atexit.register(partial(cleanup, shared_state_manager))
    signal.signal(signal.SIGTERM, partial(signal_handler, shared_state_manager=shared_state_manager))
    signal.signal(signal.SIGINT, partial(signal_handler, shared_state_manager=shared_state_manager))

def main() -> None:
    shared_state_manager: SharedStateManager = SharedStateManager()
    config_manager: ConfigManager = ConfigManager()
    dicom_manager: DicomManager = DicomManager(config_manager, shared_state_manager)
    data_manager: DataManager = DataManager(config_manager, shared_state_manager)
    
    register_exit_handlers(shared_state_manager)
    
    try:
        launch_gui(config_manager, dicom_manager, data_manager, shared_state_manager)
    except Exception as e:
        logger.error("Failed to run the GUI." + get_traceback(e))
    finally:
        cleanup(shared_state_manager)

if __name__ == "__main__":
    # Keep this block to avoid issues with multiprocessing
    if sys.platform.lower().startswith("win"):
        multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    
    main()
