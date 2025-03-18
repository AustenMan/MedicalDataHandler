import sys
import signal
import atexit
import multiprocessing
import dearpygui.dearpygui as dpg
from functools import partial
from dpg_components.launch import launch_gui
from managers.config_manager import ConfigManager
from managers.shared_state_manager import SharedStateManager
from managers.dicom_manager import DicomManager
from managers.data_manager import DataManager
from utils.general_utils import get_traceback
from utils.logger_utils import start_logger

def cleanup(shared_state_manager):
    """Destroy DPG context and remove lock file before exiting."""
    try:
        dpg.destroy_context()
    except Exception as e:
        print(get_traceback(e))
    
    try:
        shared_state_manager.shutdown_manager()
    except Exception as e:
        print(get_traceback(e))
    
def signal_handler(signum, frame, shared_state_manager):
    """Handle termination signals by invoking cleanup."""
    cleanup(shared_state_manager)
    sys.exit(0)

def register_exit_handlers(shared_state_manager):
    """Registers functions for exit and termination signals to ensure that resources are properly cleaned up."""
    atexit.register(partial(cleanup, shared_state_manager))
    signal.signal(signal.SIGTERM, partial(signal_handler, shared_state_manager=shared_state_manager))
    signal.signal(signal.SIGINT, partial(signal_handler, shared_state_manager=shared_state_manager))

def main():
    shared_state_manager = SharedStateManager()
    config_manager = ConfigManager()
    dicom_manager = DicomManager(config_manager, shared_state_manager)
    data_manager = DataManager(config_manager, shared_state_manager)
    
    register_exit_handlers(shared_state_manager)
    
    try:
        launch_gui(config_manager, dicom_manager, data_manager, shared_state_manager)
    except Exception as e:
        print(get_traceback(e))
    finally:
        cleanup(shared_state_manager)

if __name__ == "__main__":
    # Keep this in the if " __name__ == '__main__' " block to avoid issues with multiprocessing
    if sys.platform.lower().startswith("win"):
        multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    
    start_logger()
    main()
