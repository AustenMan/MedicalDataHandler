from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, Tuple


import dearpygui.dearpygui as dpg


from mdh_app.database.db_session import init_engine
from mdh_app.dpg_components.interactions.mouse_handlers import (
    _handler_MouseLeftClick,
    _handler_MouseRightClick,
    _handler_MouseMiddleClick,
    _handler_MouseMiddleRelease,
    _handler_MouseMiddleDrag,
    _handler_MouseWheel,
    _itemhandler_MouseHover
)
from mdh_app.dpg_components.interactions.keyboard_handlers import (
    _handler_KeyPress,
    _handler_KeyRelease
)
from mdh_app.dpg_components.widgets.progress_bar import update_progress
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.themes.global_themes import get_global_theme
from mdh_app.dpg_components.themes.progress_themes import get_pbar_theme
from mdh_app.dpg_components.windows.exit.exit_window import create_exit_popup
from mdh_app.dpg_components.windows.logging.log_win_utils import refresh_logger_messages
from mdh_app.dpg_components.windows.main.main_win import create_main_window
from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.data_manager import DataManager
from mdh_app.managers.dicom_manager import DicomManager


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


class GUILauncher:
    """Main launcher for GUI."""
    
    def __init__(
        self,
        shared_state_manager: SharedStateManager
    ) -> None:
        """Initialize GUI launcher with required managers."""
        self.shared_state_manager = shared_state_manager
        self.config_manager: ConfigManager = ConfigManager()
        self.dicom_manager: DicomManager = DicomManager(self.config_manager, self.shared_state_manager)
        self.data_manager: DataManager = DataManager(self.config_manager, self.shared_state_manager)
        
        init_engine(self.config_manager.get_database_path(), echo=False)

        self.tag_dict: Dict[str, Any] = {}
        self.size_dict: Dict[str, int] = {}
        self.default_display_dict: Dict[str, Any] = {}

    def launch(self) -> None:
        """Launch DearPyGUI interface with a specific startup sequence."""
        try:
            # Create the Dear PyGUI context
            dpg.create_context()
            logger.debug("DearPyGUI context created successfully")
            
            # Create registries and initialize application state
            self._create_registries()
            logger.debug("DearPyGUI registries initialized")
            
            # Apply global theme
            dpg.bind_theme(get_global_theme())
            logger.debug("DearPyGUI global theme applied")
            
            # Set font scale
            font_scale = self.config_manager.get_font_scale()
            dpg.set_global_font_scale(font_scale)
            logger.debug(f"DearPyGUI font scale set to {font_scale}")
            
            # Set application callbacks
            self._configure_callbacks()
            logger.debug("DearPyGUI application callbacks configured")
            
            # Start the viewport
            self._start_viewport()
            logger.debug("DearPyGUI viewport started successfully")
            
            # Create the main window
            create_main_window()
            logger.debug("DearPyGUI main window created")

            # Request initial texture update
            request_texture_update(texture_action_type="reset")
            logger.debug("DearPyGUI initial texture update requested")
            
            # Run the render loop
            self._start_render_loop()
            
        except Exception as e:
            logger.critical(f"Failed to launch GUI!", exc_info=True, stack_info=True)
            raise
    
    def _create_registries(self) -> None:
        """
        Create and configure all DearPyGUI registries.
        
        This includes handler registries, texture registries, value registries,
        and font registries. Also stores manager references in the value registry
        for global access throughout the application.
        
        Raises:
            Exception: If registry creation fails
        """
        try:
            # Initialize core dictionaries
            self._update_tag_dictionary()
            self._update_size_dictionary()
            self._update_default_display_dictionary()
            
            # Initialize registries
            self._create_handler_registry()
            self._create_item_handler_registry()
            self._create_texture_registry()
            self._create_value_registry()
            self._configure_font_registry()
            
        except Exception as e:
            logger.critical("Failed to create registries!", exc_info=True, stack_info=True)
            raise
    
    def _create_handler_registry(self) -> None:
        """Create and populate the handler registry for user interactions."""
        # Add handler registry
        hreg = dpg.add_handler_registry(tag=self.tag_dict["handler_registry"])
        
        # Mouse handlers
        dpg.add_mouse_click_handler(
            parent=hreg,
            button=dpg.mvMouseButton_Left,
            callback=_handler_MouseLeftClick
        )
        dpg.add_mouse_click_handler(
            parent=hreg,
            button=dpg.mvMouseButton_Right,
            callback=_handler_MouseRightClick
        )
        dpg.add_mouse_click_handler(
            parent=hreg,
            button=dpg.mvMouseButton_Middle,
            callback=_handler_MouseMiddleClick
        )
        dpg.add_mouse_release_handler(
            tag=self.tag_dict["mouse_release_tag"],
            parent=hreg,
            button=dpg.mvMouseButton_Middle,
            callback=_handler_MouseMiddleRelease,
            user_data=(0, 0)
        )
        dpg.add_mouse_drag_handler(
            parent=hreg,
            button=dpg.mvMouseButton_Middle,
            callback=_handler_MouseMiddleDrag
        )
        dpg.add_mouse_wheel_handler(
            parent=hreg,
            callback=_handler_MouseWheel
        )
        
        # Keyboard handlers
        dpg.add_key_down_handler(
            parent=hreg,
            tag=self.tag_dict["key_down_tag"],
            callback=_handler_KeyPress,
            user_data=False
        )
        dpg.add_key_release_handler(
            parent=hreg,
            callback=_handler_KeyRelease
        )
    
    def _create_item_handler_registry(self) -> None:
        """Create and populate the item handler registry for hover events."""
        # Add item handler registry
        ireg = dpg.add_item_handler_registry(tag=self.tag_dict["item_handler_registry"])
        
        # Item hover handler
        dpg.add_item_hover_handler(parent=ireg, callback=_itemhandler_MouseHover)
    
    def _create_texture_registry(self) -> None:
        """Create texture registry for image display."""
        # Add texture registry
        dpg.add_texture_registry(tag=self.tag_dict["texture_registry"])
    
    def _create_value_registry(self) -> None:
        """Create value registry and store application state dictionaries and managers."""
        # Add value registry
        dpg.add_value_registry(tag=self.tag_dict["value_registry"])
        
        ### Maybe just update this to store a reference to self ###
        
        # Store dictionaries
        dpg.add_bool_value(
            tag="tag_dict",
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.tag_dict
        )
        dpg.add_bool_value(
            tag=self.tag_dict["size_dict"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.size_dict
        )
        dpg.add_bool_value(
            tag=self.tag_dict["default_display_dict"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.default_display_dict
        )
        
        # Store manager references
        dpg.add_bool_value(
            tag=self.tag_dict["config_manager"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.config_manager
        )
        dpg.add_bool_value(
            tag=self.tag_dict["dicom_manager"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.dicom_manager
        )
        dpg.add_bool_value(
            tag=self.tag_dict["data_manager"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.data_manager
        )
        dpg.add_bool_value(
            tag=self.tag_dict["shared_state_manager"],
            parent=self.tag_dict["value_registry"],
            default_value=True,
            user_data=self.shared_state_manager
        )
    
    def _configure_font_registry(self) -> None:
        """
        Configure custom font if specified in user configuration.
        
        Validates font availability and configuration before applying.
        Falls back to default DearPyGUI font if issues are detected.
        """
        font_name = self.config_manager.get_user_config_font()
        if not font_name:
            logger.info("No custom font specified. Using DearPyGUI default font.")
            return
        
        try:
            font_dict = self.config_manager.get_fonts()
            
            if font_name not in font_dict:
                logger.warning(
                    f"Font '{font_name}' not available in font dictionary: {font_dict}. "
                    "Using DearPyGUI default font."
                )
                return
            
            font_size = font_dict.get(font_name)
            if not isinstance(font_size, int) or font_size <= 0:
                logger.warning(
                    f"Font '{font_name}' has invalid size '{font_size}'. "
                    "Using DearPyGUI default font."
                )
                return
            
            font_path = self.config_manager.get_font_file_path(f"{font_name}.ttf")
            if font_path is None:
                logger.warning(
                    f"Font file path not found for '{font_name}'. "
                    "Using DearPyGUI default font."
                )
                return
            
            # Add font registry
            freg = dpg.add_font_registry(tag=self.tag_dict["font_registry"])
            
            # Add font
            custom_font = dpg.add_font(
                tag=self.tag_dict["font"],
                parent=freg,
                file=font_path,
                size=font_size
            )
            
            # Bind the font
            dpg.bind_font(custom_font)
            logger.debug(f"Custom font '{font_name}' applied successfully")
            
        except Exception as e:
            logger.warning(
                f"Failed to configure custom font '{font_name}'! Using DearPyGUI default font.", exc_info=True
            )
    
    def _configure_callbacks(self) -> None:
        """Configure application-level callbacks."""
        dpg.set_exit_callback(callback=create_exit_popup)
        self.dicom_manager.set_progress_callback(update_progress)
    
    def _start_viewport(self) -> None:
        """
        Sets up DearPyGUI viewport dimensions, position, icons, and display properties
        based on configuration settings.
        
        Raises:
            ValueError: If viewport configuration parameters are invalid
            Exception: If viewport creation fails
        """
        try:
            # Get configuration parameters
            max_screen_size = self.config_manager.get_max_screen_size()
            viewport_size = self.config_manager.get_screen_size()
            icon_file = self.config_manager.get_icon_file()
            
            # Validate parameters
            self._validate_viewport_parameters(max_screen_size, viewport_size)
            
            # Calculate centered viewport position
            viewport_position = self._calculate_viewport_position(max_screen_size, viewport_size)
            
            # Handle icon file
            if icon_file is None:
                logger.warning("Invalid icon file specified. No icon will be used.")
                icon_file = ""
            
            # Create viewport
            dpg.create_viewport(
                title=(
                    "Medical Data Handler v1.0 | GitHub: https://github.com/AustenMan/MedicalDataHandler/"
                ),
                small_icon=icon_file,
                large_icon=icon_file,
                always_on_top=False,
                resizable=False,
                disable_close=True,
                vsync=True,
                decorated=True,
                x_pos=viewport_position[0],
                y_pos=viewport_position[1],
                width=viewport_size[0],
                height=viewport_size[1],
                min_width=viewport_size[0],
                min_height=viewport_size[1],
                max_width=viewport_size[0],
                max_height=viewport_size[1]
            )
            
            # Setup and show viewport
            dpg.setup_dearpygui()
            dpg.show_viewport()
            
            logger.debug(
                f"DearPyGUI viewport created: {viewport_size[0]}x{viewport_size[1]} "
                f"at position ({viewport_position[0]}, {viewport_position[1]})"
            )
            
        except Exception as e:
            logger.critical("Failed to start DearPyGUI viewport!", exc_info=True, stack_info=True)
            raise
    
    def _validate_viewport_parameters(
        self,
        max_screen_size: Tuple[int, int],
        viewport_size: Tuple[int, int]
    ) -> None:
        """
        Validate viewport configuration parameters.
        
        Args:
            max_screen_size: Maximum screen dimensions
            viewport_size: Desired viewport dimensions
            
        Raises:
            ValueError: If parameters are invalid
        """
        if (not isinstance(max_screen_size, (tuple, list)) or 
            len(max_screen_size) != 2 or 
            not all(isinstance(v, int) and v > 0 for v in max_screen_size)):
            raise ValueError(
                f"Maximum screen size must be a tuple/list of two positive integers. "
                f"Received: {max_screen_size}"
            )
        
        if (not isinstance(viewport_size, (tuple, list)) or 
            len(viewport_size) != 2 or 
            not all(isinstance(v, int) and v > 0 for v in viewport_size)):
            raise ValueError(
                f"Viewport size must be a tuple/list of two positive integers. "
                f"Received: {viewport_size}"
            )
    
    def _calculate_viewport_position(
        self,
        max_screen_size: Tuple[int, int],
        viewport_size: Tuple[int, int]
    ) -> Tuple[int, int]:
        """
        Calculate centered viewport position.
        
        Args:
            max_screen_size: Maximum screen dimensions
            viewport_size: Viewport dimensions
            
        Returns:
            Tuple containing x and y position for centered viewport
        """
        return (
            round((max_screen_size[0] - viewport_size[0]) / 2),
            round((max_screen_size[1] - viewport_size[1]) / 2)
        )
    
    def _start_render_loop(self) -> None:
        """
        Start the main DearPyGUI render loop.
        
        Continuously renders GUI frames and refreshes logger messages
        until the application is closed. Handles exceptions gracefully
        to maintain application stability.
        """
        logger.debug("Starting main render loop")
        
        while dpg.is_dearpygui_running():
            try:
                dpg.render_dearpygui_frame()
            except Exception as e:
                logger.exception("Failed to render GUI frame!", exc_info=True, stack_info=True)
                continue
            
            try:
                refresh_logger_messages()
            except Exception as e:
                logger.exception("Failed to refresh logger messages!", exc_info=True, stack_info=True)

        logger.debug("Render loop terminated")
    
    def _update_tag_dictionary(self) -> None:
        """
        Updates the tag dictionary with unique DearPyGUI tags.
        
        This dictionary serves as a central registry for all GUI element tags,
        ensuring consistent access across the application.
        
        Raises:
            ValueError: If tag dictionary validation fails
        """
        # Get theme tags
        tag_blue_pbar_theme = get_pbar_theme()
        tag_green_pbar_theme = get_pbar_theme(complete=True)
        tag_red_pbar_theme = get_pbar_theme(terminated_early=True)
        
        self.tag_dict.update(
            {
                # Core registry tags
                "tag_dict": "tag_dict",
                "size_dict": dpg.generate_uuid(),
                "default_display_dict": dpg.generate_uuid(),
                "config_manager": dpg.generate_uuid(),
                "dicom_manager": dpg.generate_uuid(),
                "data_manager": dpg.generate_uuid(),
                "shared_state_manager": dpg.generate_uuid(),
                
                # Registry tags
                "handler_registry": dpg.generate_uuid(),
                "item_handler_registry": dpg.generate_uuid(),
                "texture_registry": dpg.generate_uuid(),
                "value_registry": dpg.generate_uuid(),
                "font_registry": dpg.generate_uuid(),
                
                # Font tag
                "font": dpg.generate_uuid(),
                
                # Handler tags
                "key_down_tag": dpg.generate_uuid(),
                "mouse_release_tag": dpg.generate_uuid(),
                
                # Window tags
                "main_window": dpg.generate_uuid(),
                "log_window": dpg.generate_uuid(),
                "exit_window": dpg.generate_uuid(),
                "data_display_window": dpg.generate_uuid(),
                "action_window": dpg.generate_uuid(),
                "confirmation_popup": dpg.generate_uuid(),
                
                # Cleanup window tags
                "settings_window": dpg.generate_uuid(),
                "color_picker_popup": dpg.generate_uuid(),
                "inspect_ptobj_window": dpg.generate_uuid(),
                "inspect_dicom_popup": dpg.generate_uuid(),
                "inspect_data_popup": dpg.generate_uuid(),
                "save_data_window": dpg.generate_uuid(),
                
                # Progress bar tag
                "pbar": dpg.generate_uuid(),
                
                # Data table tags
                "data_table": dpg.generate_uuid(),
                "table_reload_button": dpg.generate_uuid(),
                "table_rows_input": dpg.generate_uuid(),
                "table_page_input": dpg.generate_uuid(),
                "input_filter_processed": dpg.generate_uuid(),
                "input_filter_name": dpg.generate_uuid(),
                "input_filter_mrn": dpg.generate_uuid(),
                
                # Response tags
                "latest_gui_response": dpg.generate_uuid(),
                "latest_gui_response_tooltip_text": dpg.generate_uuid(),
                
                # Input tags
                "input_objectives_filename": dpg.generate_uuid(),
                "input_objectives_filename_error": dpg.generate_uuid(),
                
                # Button tags
                "ptinfo_button": dpg.generate_uuid(),
                "save_button": dpg.generate_uuid(),
                
                # View dictionaries
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
                
                # Image control tags
                "img_tags": {
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
                    "voxel_spacing_config": dpg.generate_uuid(),
                    "force_voxel_spacing_config": dpg.generate_uuid(),
                    "force_voxel_spacing_isotropic_largest": dpg.generate_uuid(),
                    "force_voxel_spacing_isotropic_smallest": dpg.generate_uuid(),
                    "zoom_factor": dpg.generate_uuid(),
                    "xrange": dpg.generate_uuid(),
                    "yrange": dpg.generate_uuid(),
                    "zrange": dpg.generate_uuid(),
                    "show_crosshairs": dpg.generate_uuid(),
                    "show_orientation_labels": dpg.generate_uuid(),
                },
                
                # Progress bar themes
                "pbar_themes": {
                    "green": tag_green_pbar_theme,
                    "blue": tag_blue_pbar_theme,
                    "red": tag_red_pbar_theme,
                }
            }
        )
        
        # Validate tag dictionary
        self._validate_tag_dictionary()
    
    def _validate_tag_dictionary(self) -> None:
        """
        Validate the tag dictionary structure and content.
        
        Raises:
            ValueError: If validation fails
        """
        if not isinstance(self.tag_dict, dict):
            raise ValueError("Tag dictionary must be a dictionary.")
        
        if not all(isinstance(key, str) for key in self.tag_dict.keys()):
            raise ValueError("All keys in tag dictionary must be strings.")
        
        # Validate values are appropriate types
        for value in self.tag_dict.values():
            if not (isinstance(value, (str, int)) or 
                   (isinstance(value, dict) and 
                    all(isinstance(subkey, str) for subkey in value.keys()))):
                raise ValueError(
                    "All values in tag dictionary must be strings, integers, "
                    "or dictionaries with string keys."
                )
        
        # Check uniqueness of string values
        string_values = [val for val in self.tag_dict.values() if isinstance(val, str)]
        if len(set(string_values)) != len(string_values):
            raise ValueError("Tag dictionary contains non-unique string values.")
    
    def _update_size_dictionary(self) -> None:
        """
        Update the size dictionary with GUI element dimensions.
        
        Raises:
            ValueError: If any size value is not an integer
        """
        max_screen_size = self.config_manager.get_max_screen_size()

        self.size_dict.update(
            {
                "table_w": -6,
                "table_h": -6,
                "button_width": -6,
                "button_height": 50,
                "tooltip_width": round(max_screen_size[0] * 0.35),
                "spacer_height": 6
            }
        )
        
        # Validate all values are integers
        if not all(isinstance(value, int) for value in self.size_dict.values()):
            raise ValueError(f"All size dictionary values must be integers: {self.size_dict}")

    def _update_default_display_dictionary(self) -> None:
        """ Update the default display settings dictionary. """
        default_data_size: Tuple[int, int, int] = (600, 600, 600)
        
        x_range = (0, default_data_size[0] - 1)
        y_range = (0, default_data_size[1] - 1)
        z_range = (0, default_data_size[2] - 1)
        
        x_slice = max(min(round(default_data_size[0] / 2), x_range[1]), x_range[0])
        y_slice = max(min(round(default_data_size[1] / 2), y_range[1]), y_range[0])
        z_slice = max(min(round(default_data_size[2] / 2), z_range[1]), z_range[0])
        
        self.default_display_dict.update(
            {
                "DATA_SIZE": default_data_size,
                "VOXEL_SPACING": (3.0, 3.0, 3.0),
                "SLICE_VALS": [x_slice, y_slice, z_slice],
                "RANGES": [x_range, y_range, z_range],
                "ROTATION": 0,
                "FLIP_LR": False,
                "FLIP_AP": False,
                "FLIP_SI": False,
                "DISPLAY_ALPHAS": [100, 100, 40],
                "DOSE_RANGE": [0, 100],
                "CONTOUR_THICKNESS": 1,
                "IMAGE_WINDOW_PRESET": "Custom",
                "IMAGE_WINDOW_WIDTH": 375,
                "IMAGE_WINDOW_LEVEL": 40,
            }
        )


def destroy_gui(shared_state_manager: SharedStateManager) -> None:
    """Destroy DPG context and remove lock file before exiting."""
    try:
        dpg.destroy_context()
    except Exception as e:
        logger.exception("Failed to destroy the DPG context!", exc_info=True, stack_info=True)

    try:
        shared_state_manager.shutdown_manager()
    except Exception as e:
        logger.exception("Failed to shut down the shared state manager!", exc_info=True, stack_info=True)
