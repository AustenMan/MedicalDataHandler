import logging
import dearpygui.dearpygui as dpg
from typing import Any, Dict, Tuple

from mdh_app.dpg_components.interaction_handlers import (
    _handler_MouseLeftClick, _handler_MouseRightClick, _handler_MouseMiddleClick,
    _handler_MouseMiddleRelease, _handler_MouseMiddleDrag, _handler_MouseWheel,
    _handler_KeyPress, _handler_KeyRelease, _itemhandler_MouseHover
)
from mdh_app.dpg_components.progress_bar import update_progress
from mdh_app.dpg_components.texture_updates import request_texture_update
from mdh_app.dpg_components.themes import get_global_theme, get_pbar_theme
from mdh_app.dpg_components.window_exit import create_exit_popup
from mdh_app.dpg_components.window_log import refresh_logger_messages
from mdh_app.dpg_components.window_main import create_main_window
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.data_manager import DataManager
from mdh_app.managers.dicom_manager import DicomManager
from mdh_app.utils.general_utils import get_traceback

logger = logging.getLogger(__name__)

def launch_gui(
    conf_mgr: ConfigManager, 
    dcm_mgr: DicomManager, 
    data_mgr: DataManager, 
    ss_mgr: SharedStateManager
) -> None:
    """ Launches the Dear PyGUI GUI. """
    # Create the Dear PyGUI context
    dpg.create_context()
    
    # Create registries, particularly for DPG references to the dictionaries and managers
    _create_registries(conf_mgr, dcm_mgr, data_mgr, ss_mgr)
    
    # Customize the theme
    dpg.bind_theme(get_global_theme())
    
    # Set font scale
    dpg.set_global_font_scale(conf_mgr.get_font_scale())
    
    # Set callbacks
    dpg.set_exit_callback(callback=create_exit_popup)
    dcm_mgr.set_progress_callback(update_progress)
    
    # Start the viewport
    _start_viewport(conf_mgr)
    
    # Create the main window
    create_main_window()
    
    # Request an initial texture update (need to test if necessary)
    request_texture_update(texture_action_type="reset")
    
    # Run the render loop
    _start_render_loop()

def _create_registries(
    conf_mgr: ConfigManager, 
    dcm_mgr: DicomManager, 
    data_mgr: DataManager, 
    ss_mgr: SharedStateManager
) -> None:
    """ Creates the handler, item handler, texture, and value registries in Dear PyGUI. """
    # Initialize the tag dictionary
    tag_dict = _create_tag_dict()
    size_dict = _create_size_dict(conf_mgr)
    default_display_dict = _create_default_display_dict()
    
    # Handlers
    dpg.add_handler_registry(tag=tag_dict["handler_registry"])
    dpg.add_mouse_click_handler(parent=tag_dict["handler_registry"], button=dpg.mvMouseButton_Left, callback=_handler_MouseLeftClick)
    dpg.add_mouse_click_handler(parent=tag_dict["handler_registry"], button=dpg.mvMouseButton_Right, callback=_handler_MouseRightClick)
    dpg.add_mouse_click_handler(parent=tag_dict["handler_registry"], button=dpg.mvMouseButton_Middle, callback=_handler_MouseMiddleClick)
    dpg.add_mouse_release_handler(tag=tag_dict["mouse_release_tag"], parent=tag_dict["handler_registry"], button=dpg.mvMouseButton_Middle, callback=_handler_MouseMiddleRelease, user_data=(0, 0))
    dpg.add_mouse_drag_handler(parent=tag_dict["handler_registry"], button=dpg.mvMouseButton_Middle, callback=_handler_MouseMiddleDrag)
    dpg.add_mouse_wheel_handler(parent=tag_dict["handler_registry"], callback=_handler_MouseWheel)
    dpg.add_key_down_handler(parent=tag_dict["handler_registry"], tag=tag_dict["key_down_tag"], callback=_handler_KeyPress, user_data=False)
    dpg.add_key_release_handler(parent=tag_dict["handler_registry"], callback=_handler_KeyRelease)
    
    # Item handlers
    dpg.add_item_handler_registry(tag=tag_dict["item_handler_registry"])
    dpg.add_item_hover_handler(parent=tag_dict["item_handler_registry"], callback=_itemhandler_MouseHover)
    
    # Texture registry
    dpg.add_texture_registry(tag=tag_dict["texture_registry"])
    
    # Value registry
    dpg.add_value_registry(tag=tag_dict["value_registry"])
    dpg.add_bool_value(tag="tag_dict", parent=tag_dict["value_registry"], default_value=True, user_data=tag_dict)
    dpg.add_bool_value(tag=tag_dict["size_dict"], parent=tag_dict["value_registry"], default_value=True, user_data=size_dict)
    dpg.add_bool_value(tag=tag_dict["default_display_dict"], parent=tag_dict["value_registry"], default_value=True, user_data=default_display_dict)
    dpg.add_bool_value(tag=tag_dict["config_manager"], parent=tag_dict["value_registry"], default_value=True, user_data=conf_mgr)
    dpg.add_bool_value(tag=tag_dict["dicom_manager"], parent=tag_dict["value_registry"], default_value=True, user_data=dcm_mgr)
    dpg.add_bool_value(tag=tag_dict["data_manager"], parent=tag_dict["value_registry"], default_value=True, user_data=data_mgr)
    dpg.add_bool_value(tag=tag_dict["shared_state_manager"], parent=tag_dict["value_registry"], default_value=True, user_data=ss_mgr)
    
    # Font registry update
    font_name = conf_mgr.get_user_config_font()
    if not font_name:
        logger.warning("No font specified in the user configuration. Sticking with DPG default font.")
        return
    font_dict = conf_mgr.get_fonts()
    font_size = font_dict.get(font_name)
    if not font_name in font_dict:
        logger.warning(f"The font '{font_name}' is not available in the font dictionary: {font_dict}. Sticking with DPG default font.")
        return
    if not isinstance(font_size, int) or font_size <= 0:
        logger.warning(f"The font '{font_name}' has an invalid size '{font_size}'. Sticking with DPG default font.")
        return
    font_fpath = conf_mgr.get_font_file_path(font_name + ".ttf")
    if font_fpath is not None:
        dpg.add_font_registry(tag=tag_dict["font_registry"])
        custom_font = dpg.add_font(tag=tag_dict["font"], parent=tag_dict["font_registry"], file=font_fpath, size=font_size)
        dpg.bind_font(custom_font)

def _start_viewport(conf_mgr: ConfigManager) -> None:
    """
    Create a Dear PyGUI viewport with specified screen and viewport dimensions.
    
    Args:
        conf_mgr (class): Manager for configuration settings.
    
    Raises:
        ValueError: If dimensions are not positive integers or provided as tuples of size 2.
    """
    # Retrieve the maximum screen size, the desired viewport size, and the icon file
    max_screen_size = conf_mgr.get_max_screen_size()
    viewport_WH = conf_mgr.get_screen_size()
    ico_file = conf_mgr.get_icon_file()
    
    # Validate
    if not isinstance(max_screen_size, (tuple, list)) or len(max_screen_size) != 2 or not all(isinstance(v, int) for v in max_screen_size) or not all(v > 0 for v in max_screen_size):
        raise ValueError(f"The maximum screen size must be a list or tuple of two integers greater than 0. Received: {max_screen_size}")
    if not isinstance(viewport_WH, (tuple, list)) or len(viewport_WH) != 2 or not all(isinstance(v, int) for v in viewport_WH) or not all(v > 0 for v in viewport_WH):
        raise ValueError(f"The viewport width and height must be a list or tuple of two integers greater than 0. Received: {viewport_WH}")
    if ico_file is None:
        logger.warning(f"Since an invalid icon file '{ico_file}' was provided, no icon will be used for the viewport.")
        ico_file = ""
    
    # Calculate the viewport position
    viewport_XY = tuple([round((max_screen_size[i] - viewport_WH[i]) / 2) for i in range(2)])
    
    # Create the viewport
    dpg.create_viewport(
        title="Medical Data Handler (Alpha v0.1) by Austen Maniscalco. Free & Open-Source. Questions? Austen.Maniscalco@UTSouthwestern.edu", 
        small_icon=ico_file,
        large_icon=ico_file,
        always_on_top=False, resizable=False, disable_close=True, vsync=True, decorated=True,
        x_pos=viewport_XY[0], y_pos=viewport_XY[1], 
        width=viewport_WH[0], height=viewport_WH[1], 
        min_width=viewport_WH[0], min_height=viewport_WH[1], 
        max_width=viewport_WH[0], max_height=viewport_WH[1],
        )

    # Setup Dear PyGUI and show the viewport
    dpg.setup_dearpygui()
    dpg.show_viewport()

def _start_render_loop() -> None:
    """ Starts the main rendering loop for the Dear PyGUI interface. Continuously refreshes the GUI and updates the logger messages. """
    while dpg.is_dearpygui_running():
        try:
            dpg.render_dearpygui_frame()
        except Exception as e:
            logger.error("Failed to render a GUI frame." + get_traceback(e))
            continue
        try:
            refresh_logger_messages()
        except Exception as e:
            logger.error("Failed to refresh logger messages." + get_traceback(e))

def _create_tag_dict() -> Dict[str, Any]:
    """
    Create a dictionary mapping names (str) to unique Dear PyGUI tags (str or int).
    
    Returns:
        A dictionary with keys as names and values as unique tags.
    
    Raises:
        ValueError: If the resulting dictionary does not meet type or uniqueness requirements.
    """
    tag_blue_cbar_theme = get_pbar_theme()
    tag_green_cbar_theme = get_pbar_theme(complete=True)
    tag_red_cbar_theme = get_pbar_theme(terminated_early=True)
    
    tag_dict: Dict[str, Any] = {
        "tag_dict": "tag_dict",
        "size_dict": dpg.generate_uuid(), 
        "default_display_dict": dpg.generate_uuid(), 
        "config_manager": dpg.generate_uuid(), 
        "dicom_manager": dpg.generate_uuid(), 
        "data_manager": dpg.generate_uuid(), 
        "shared_state_manager": dpg.generate_uuid(), 
    
        "handler_registry": dpg.generate_uuid(), 
        "item_handler_registry": dpg.generate_uuid(), 
        "texture_registry": dpg.generate_uuid(), 
        "value_registry": dpg.generate_uuid(),
        "font_registry": dpg.generate_uuid(),
        
        "font": dpg.generate_uuid(),
        
        "key_down_tag": dpg.generate_uuid(),
        "mouse_release_tag": dpg.generate_uuid(),
        
        "main_window": dpg.generate_uuid(),
        "log_window": dpg.generate_uuid(),
        "exit_window": dpg.generate_uuid(), 
        "data_display_window": dpg.generate_uuid(),
        "action_window": dpg.generate_uuid(), 
        "confirmation_popup": dpg.generate_uuid(), 
        
        # Tags to cleanup
        "settings_window": dpg.generate_uuid(), 
        "color_picker_popup": dpg.generate_uuid(), 
        "inspect_ptobj_window": dpg.generate_uuid(), 
        "inspect_dicom_popup": dpg.generate_uuid(), 
        "inspect_sitk_popup": dpg.generate_uuid(), 
        "save_sitk_window": dpg.generate_uuid(), 
        
        "pbar": dpg.generate_uuid(), 
        "data_table": dpg.generate_uuid(), 
        "table_reload_button": dpg.generate_uuid(),
        "table_rows_input": dpg.generate_uuid(),
        "table_page_input": dpg.generate_uuid(),
        
        "latest_gui_response": dpg.generate_uuid(), 
        "latest_gui_response_tooltip_text": dpg.generate_uuid(),
        
        "input_objectives_filename": dpg.generate_uuid(), 
        "input_objectives_filename_error": dpg.generate_uuid(),
        
        "ptinfo_button": dpg.generate_uuid(),
        "save_button": dpg.generate_uuid(),
        
        "axial_dict": {
            "view_type": "axial", 
            "dims_LR_TB": (0, 1), 
            "texture": dpg.generate_uuid(), 
            "image": dpg.generate_uuid(), 
            "tooltip": dpg.generate_uuid()
            },
        "coronal_dict": {
            "view_type": "coronal", 
            "dims_LR_TB": (0, 2), 
            "texture": dpg.generate_uuid(), 
            "image": dpg.generate_uuid(), 
            "tooltip": dpg.generate_uuid()
            },
        "sagittal_dict": {
            "view_type": "sagittal", 
            "dims_LR_TB": (1, 2), 
            "texture": dpg.generate_uuid(), 
            "image": dpg.generate_uuid(), 
            "tooltip": dpg.generate_uuid()
            },
        
        "img_tags":
            {
                "pan_speed": dpg.generate_uuid(),
                "rotation": dpg.generate_uuid(),
                "flip_lr": dpg.generate_uuid(),
                "flip_ap": dpg.generate_uuid(),
                "flip_si": dpg.generate_uuid(),
                "viewed_slices": dpg.generate_uuid(),
                "display_alphas": dpg.generate_uuid(),
                "dose_thresholds": dpg.generate_uuid(),
                "contour_thickness": dpg.generate_uuid(),
                "window_preset": dpg.generate_uuid(),
                "window_width": dpg.generate_uuid(),
                "window_level": dpg.generate_uuid(),
                "voxel_spacing": dpg.generate_uuid(), 
                "voxel_spacing_cbox": dpg.generate_uuid(),
                "zoom_factor": dpg.generate_uuid(),
                "xrange": dpg.generate_uuid(),
                "yrange": dpg.generate_uuid(),
                "zrange": dpg.generate_uuid(),
                "show_crosshairs": dpg.generate_uuid(),
                "show_orientation_labels": dpg.generate_uuid(),
            }, 
        
        "pbar_themes":
            {
                "green": tag_green_cbar_theme,
                "blue": tag_blue_cbar_theme,
                "red": tag_red_cbar_theme,
            }
    }
    
    # Validation
    if not isinstance(tag_dict, dict):
        raise ValueError("Tag dictionary must be a dictionary.")
    if not all(isinstance(key, str) for key in tag_dict.keys()):
        raise ValueError("All keys in tag dictionary must be strings.")
    if not (
        # Values are strings, or dictionaries with keys as strings
        all(
            isinstance(value, (str, int)) or
            (
                isinstance(value, dict) and 
                all(isinstance(subkey, str) for subkey in value.keys())
            )
            for value in tag_dict.values()
        )
    ):
        raise ValueError("All values in tag dictionary must be strings, integers, or dictionaries with string keys.")
    if len(set(val for val in tag_dict.values() if isinstance(val, str))) != len([val for val in tag_dict.values() if isinstance(val, str)]):
        raise ValueError("Tag dictionary contains non-unique string values.")
    
    return tag_dict

def _create_size_dict(conf_mgr: ConfigManager) -> Dict[str, int]:
    """
    Create a dictionary with preset sizes for UI elements.
    
    Args:
        conf_mgr: The configuration manager providing screen dimensions.
    
    Returns:
        A dictionary with size values (all integers).
    
    Raises:
        ValueError: If any size value is not an integer.
    """
    max_screen_size = conf_mgr.get_max_screen_size()
    size_dict: Dict[str, int] = {
        "table_w": -6, 
        "table_h": -6,
        "button_width": -6, 
        "button_height": 50, 
        "tooltip_width": round(max_screen_size[0] * 0.35),
        "spacer_height": 6
    }
    if not isinstance(size_dict, dict) or not all(isinstance(value, int) for value in size_dict.values()):
        raise ValueError(f"Size dictionary values must be integers; received: {size_dict}")
    return size_dict

def _create_default_display_dict() -> Dict[str, Any]:
    """
    Create a dictionary with default display settings for the GUI.
    
    Returns:
        A dictionary containing default display parameters.
    """
    default_data_size: Tuple[int, int, int] = (600, 600, 600)
    default_display_dict: Dict[str, Any] = {
        "DATA_SIZE": default_data_size,
        "SLICE_VALS": [round(default_data_size[0] / 2), round(default_data_size[1] / 2), round(default_data_size[2] / 2)],
        "DISPLAY_ALPHAS": [100, 100, 40],
        "DOSE_RANGE": [0, 100],
        "CONTOUR_THICKNESS": 1,
        "IMAGE_WINDOW_PRESET": "Custom",
        "IMAGE_WINDOW_WIDTH": 375,
        "IMAGE_WINDOW_LEVEL": 40,
        "RANGES": [(0, default_data_size[0] - 1), (0, default_data_size[1] - 1), (0, default_data_size[2] - 1)],
        "ROTATION": 0,
        "FLIP_LR": False,
        "FLIP_AP": False,
        "FLIP_SI": False,
        "VOXEL_SPACING": (3.0, 3.0, 3.0),
    }
    return default_display_dict
