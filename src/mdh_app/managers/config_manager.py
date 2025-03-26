import os
import json
import logging
from typing import Any, Dict, List, Tuple, Optional, Union

from mdh_app.utils.general_utils import (
    atomic_save,
    get_traceback,
    get_source_dir,
    get_main_screen_size, 
    validate_directory, 
    format_name
)

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages configuration settings and RT data lists.

    Attributes:
        config_dirs (Dict[str, str]): Mapping of key directories.
        config_files (Dict[str, Tuple[str, type]]): Mapping of config keys to their file paths and expected types.
        configs (Dict[str, Any]): Loaded configuration data.
    """

    def __init__(self) -> None:
        self._set_directories()
        self._ensure_directories_exist()
        self._set_config_files()
        self._load_configs()

    def _set_directories(self) -> None:
        """Set up key project directories."""
        source_dir = get_source_dir()
        project_dir = os.path.dirname(source_dir) # Named "MDH"
        resources_dir = os.path.join(source_dir, "resources")
        app_data_dir = os.path.join(source_dir, "_app_data")
        
        self.dirs: Dict[str, str] = {
            "project": project_dir,
            "source": source_dir,
            "config_files": os.path.join(project_dir, "config_files"),
            "logs": os.path.join(project_dir, "logs"),
            "processed_nifti_data": os.path.join(project_dir, "processed_nifti_data"),
            "screenshots": os.path.join(project_dir, "screenshots"),
            "assets": os.path.join(resources_dir, "assets"),
            "fonts": os.path.join(resources_dir, "fonts"),
            "patient_objs": os.path.join(app_data_dir, "patient_objects"), 
        }

    def _ensure_directories_exist(self) -> None:
        """Ensure all required directories exist."""
        for path in self.dirs.values():
            os.makedirs(path, exist_ok=True)

    def _set_config_files(self) -> None:
        """Define configuration file paths and their expected types."""
        initial_files: Dict[str, Tuple[str, type]] = {
            "fonts": ("fonts.json", dict),
            "user_config": ("user_config.json", dict),
            "organ_matching": ("organ_matching.json", dict),
            "window_presets": ("window_presets.json", dict),
            "ct_HU_map_vals": ("ct_HU_map_vals.json", list),
            "ct_RED_map_vals": ("ct_RED_map_vals.json", list),
            "disease_sites": ("disease_sites.json", list),
            "machine_names": ("machine_names.json", list),
            "tg_263_names": ("tg263_names.json", list),
        }
        self.config_files = {
            key: (os.path.join(self.dirs["config_files"], filename), expected_type)
            for key, (filename, expected_type) in initial_files.items()
        }
        self.ico_file: str = os.path.join(self.dirs["assets"], "MDH_Logo_Credit_DALL-E.ico")

    def _load_configs(self) -> None:
        """Load and validate configuration files from disk."""
        self.configs: Dict[str, Any] = {}
        for key, (file_path, expected_type) in self.config_files.items():
            loaded_data = self._load_config(file_path) or expected_type()
            if not isinstance(loaded_data, expected_type):
                logger.warning(
                    f"Configuration file '{file_path}' has data of type {type(loaded_data).__name__} "
                    f"(expected {expected_type.__name__}); using default configuration."
                )
                loaded_data = expected_type()
            self.configs[key] = loaded_data
    
    def _load_config(self, file_path: str) -> Optional[Any]:
        """
        Load a JSON configuration file.

        Returns:
            The loaded JSON data, or None if loading fails.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Unable to load configuration file '{file_path}'." + get_traceback(e))
            return None
    
    def _save_config(self, key: str, new_config: Union[dict, list]) -> bool:
        """
        Validate and save an updated configuration.

        Args:
            key: The configuration key (e.g., "fonts", "user_config").
            new_config: The new configuration data.

        Returns:
            True if the configuration was successfully saved, False otherwise.
        """
        if key not in self.config_files:
            logger.error(f"Configuration key '{key}' is invalid; cannot update configuration.")
            return False

        file_path, expected_type = self.config_files[key]
        if not isinstance(new_config, expected_type):
            logger.error(
                f"Configuration update for '{key}' has invalid data type: expected {expected_type.__name__}, "
                f"got {type(new_config).__name__}."
            )
            return False
        
        if atomic_save(
            filepath=file_path, 
            write_func=lambda file: json.dump(new_config, file),
            error_message=f"Failed to save configuration for '{key}' to '{file_path}'."
        ):
            self.configs[key] = new_config
            setattr(self, key, new_config)
            return True
        return False
    
    ### Update methods for saving without specifying the key ###
    
    def update_user_config(self, updates: dict) -> None:
        """
        Update the user_config settings with new key-value pairs.

        Args:
            updates: Dictionary of updates to merge into user_config.
        """
        if not isinstance(updates, dict):
            logger.error(f"Configuration update for 'user_config' must be a dict, got {type(updates).__name__}.")
            return

        key = "user_config"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        user_config: Dict[str, Any] = self.configs[key]
        user_config.update(updates)
        self._save_config(key, user_config)
        logger.info(f"Updated user configuration settings: {updates}")

    def add_item_organ_matching(self, organ: str, new_item: str) -> None:
        """
        Add an item to the organ_matching configuration.

        Args:
            organ: The organ name.
            new_item: The new item to add.
        """
        key = "organ_matching"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        if not isinstance(new_item, str):
            logger.error(f"Organ matching item must be a str, got {type(new_item).__name__}.")
            return

        organ_matching = self.configs[key]
        if organ not in organ_matching:
            organ_matching[organ] = []

        current_set = set(organ_matching[organ])
        formatted_item = format_name(new_item, lowercase=True)
        current_set.add(formatted_item)
        organ_matching[organ] = sorted(list(current_set))
        self._save_config(key, organ_matching)
        logger.info(f"Added item '{new_item}' to organ matching for '{organ}'.")
    
    def remove_item_organ_matching(self, organ: str, item_to_remove: str) -> None:
        """
        Remove an item from the organ_matching configuration.

        Args:
            organ: The organ name.
            item_to_remove: The item to remove.
        """
        key = "organ_matching"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        if not isinstance(item_to_remove, str):
            logger.error(f"Organ matching item to remove must be a str, got {type(item_to_remove).__name__}.")
            return

        organ_matching = self.configs[key]
        if organ not in organ_matching:
            logger.error(f"Organ '{organ}' not found in organ matching configuration.")
            return

        current_set = set(organ_matching[organ])
        formatted_item = format_name(item_to_remove, lowercase=True)
        if formatted_item in current_set:
            current_set.remove(formatted_item)
            organ_matching[organ] = sorted(list(current_set))
            self._save_config(key, organ_matching)
            logger.info(f"Removed item '{item_to_remove}' from organ matching for '{organ}'.")
    
    def add_machine_name(self, machine_name: str) -> None:
        """
        Add a machine name to the machine_names list.

        Args:
            machine_name: The machine name to add.
        """
        if not isinstance(machine_name, str):
            logger.error(f"Machine name must be a str, got {type(machine_name).__name__}.")
            return

        key = "machine_names"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        machine_names: List[str] = self.configs[key]
        if machine_name not in machine_names:
            machine_names.append(machine_name)
            self._save_config(key, machine_names)
            logger.info(f"Added machine name '{machine_name}' to configuration.")
    
    def remove_machine_name(self, machine_name: str) -> None:
        """
        Remove a machine name from the machine_names list.

        Args:
            machine_name: The machine name to remove.
        """
        key = "machine_names"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        machine_names: List[str] = self.configs[key]
        if machine_name in machine_names:
            machine_names.remove(machine_name)
            self._save_config(key, machine_names)
            logger.info(f"Removed machine name '{machine_name}' from configuration.")
    
    def add_disease_site(self, disease_site: str) -> None:
        """
        Add a disease site to the disease_sites list.

        Args:
            disease_site: The disease site to add.
        """
        if not isinstance(disease_site, str):
            logger.error(f"Disease site must be a str, got {type(disease_site).__name__}.")
            return

        key = "disease_sites"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        disease_sites: List[str] = self.configs[key]
        if disease_site not in disease_sites:
            disease_sites.append(disease_site)
            self._save_config(key, disease_sites)
            logger.info(f"Added disease site '{disease_site}' to configuration.")

    def remove_disease_site(self, disease_site: str) -> None:
        """
        Remove a disease site from the disease_sites list.

        Args:
            disease_site: The disease site to remove.
        """
        key = "disease_sites"
        if key not in self.configs:
            logger.error(f"Configuration key '{key}' is missing; cannot update configuration.")
            return

        disease_sites: List[str] = self.configs[key]
        if disease_site in disease_sites:
            disease_sites.remove(disease_site)
            self._save_config(key, disease_sites)
            logger.info(f"Removed disease site '{disease_site}' from configuration.")
    
    ### Getters for general configuration settings ###
    def get_project_dir(self) -> str:
        """Return the project directory."""
        project_dir = self.dirs.get("project")
        if project_dir is not None:
            os.makedirs(project_dir, exist_ok=True)
        return project_dir or ""
    
    def get_configs_dir(self) -> Optional[str]:
        """Return the configuration directory path."""
        configs_dir = self.dirs.get("config_files")
        if configs_dir is not None:
            os.makedirs(configs_dir, exist_ok=True)
        return configs_dir

    def get_patient_objects_dir(self) -> Optional[str]:
        """Return the patient objects directory path."""
        pt_obj_dir = self.dirs.get("patient_objs")
        if pt_obj_dir is not None:
            os.makedirs(pt_obj_dir, exist_ok=True)
        return pt_obj_dir

    def get_font_dir(self) -> Optional[str]:
        """Return the fonts directory path."""
        font_dir = self.dirs.get("fonts")
        if font_dir is not None:
            os.makedirs(font_dir, exist_ok=True)
        return font_dir
    
    def get_font_file_path(self, filename: str) -> Optional[str]:
        """Return the full path for a font file."""
        font_dir = self.get_font_dir()
        if not font_dir:
            return None
        file_path = os.path.join(font_dir, filename)
        if not os.path.exists(file_path):
            logger.error(f"Font file '{filename}' not found in '{font_dir}'.")
            return None
        return file_path

    def get_nifti_data_dir(self) -> Optional[str]:
        """Return the SITK data directory path."""
        nifti_data_dir = self.dirs.get("processed_nifti_data")
        if nifti_data_dir is not None:
            os.makedirs(nifti_data_dir, exist_ok=True)
        return nifti_data_dir

    def get_nifti_data_save_dir(self, folder_names: List[str]) -> Optional[str]:
        """Return the full path for a SITK data file."""
        if not folder_names or not isinstance(folder_names, list):
            logger.error(f"Folder names must be provided as a list of strings. Received: {folder_names}.")
            return None
        nifti_data_dir = self.get_nifti_data_dir()
        if not nifti_data_dir:
            return None
        folder_names = [str(name) for name in folder_names]
        save_dir = os.path.join(nifti_data_dir, *folder_names)
        os.makedirs(save_dir, exist_ok=True)
        return save_dir
    
    def get_screenshots_dir(self) -> Optional[str]:
        """Return the screenshots directory path."""
        screenshot_dir = self.dirs.get("screenshots")
        if screenshot_dir is not None:
            os.makedirs(screenshot_dir, exist_ok=True)
        return screenshot_dir

    def get_screenshots_file_path(self, filename: str) -> Optional[str]:
        """Return the full path for a screenshot file."""
        screenshots_dir = self.get_screenshots_dir()
        os.makedirs(screenshots_dir, exist_ok=True)
        if not screenshots_dir:
            return None
        return os.path.join(screenshots_dir, filename)
    
    def get_fonts(self) -> Dict[str, Any]:
        """Return the fonts configuration dictionary."""
        return self.configs.get("fonts", {})
    
    def get_font_size(self, font_name: str) -> Optional[int]:
        """
        Return the size for a given font.

        Args:
            font_name: Name of the font.

        Returns:
            The font size, or None if not found.
        """
        return self.get_fonts().get(font_name)

    def get_icon_file(self) -> Optional[str]:
        """Return the icon file path."""
        if not self.ico_file or not self.ico_file.endswith(".ico") or not os.path.exists(self.ico_file):
            logger.error(f"Invalid icon file path: '{self.ico_file}', must be a valid .ico file.")
            return None
        return self.ico_file

    def get_user_config(self) -> Dict[str, Any]:
        """Return the user configuration dictionary."""
        return self.configs.get("user_config", {})

    def get_user_setting(self, key: str, default: Any = None) -> Any:
        """
        Return a specific setting from user_config.

        Args:
            key: The key of the setting.
            default: The default value if the setting is not found.

        Returns:
            The value of the setting or None if not found.
        """
        return self.get_user_config().get(key, default)

    def get_unmatched_organ_name(self) -> str:
        """Return the unmatched organ name setting."""
        return self.get_user_setting("unmatched_organ_name", "")
    
    def get_organ_matching_dict(self) -> Dict[str, Any]:
        """Return the organ matching configuration dictionary."""
        return self.configs.get("organ_matching", {})

    def get_window_presets(self) -> Dict[str, Any]:
        """Return the window presets configuration dictionary."""
        return self.configs.get("window_presets", {})

    def get_ct_HU_map_vals(self) -> List[Any]:
        """Return the CT HU map values list."""
        return self.configs.get("ct_HU_map_vals", [])

    def get_ct_RED_map_vals(self) -> List[Any]:
        """Return the CT RED map values list."""
        return self.configs.get("ct_RED_map_vals", [])
    
    def get_disease_sites(self, ready_for_dpg: bool = False) -> List[str]:
        """
        Return the disease sites list.

        Args:
            ready_for_dpg: If True, prepend standard options.

        Returns:
            The list of disease sites.
        """
        sites: List[str] = self.configs.get("disease_sites", [])
        if ready_for_dpg:
            prepend_list = ["SELECT_MAIN_SITE", "UNKNOWN_SITE", "MULTIPLE_SITES"]
            return prepend_list + sorted(sites)
        return sites

    def get_machine_names(self, ready_for_dpg: bool = False) -> List[str]:
        """
        Return the machine names list.

        Args:
            ready_for_dpg: If True, prepend standard options.

        Returns:
            The list of machine names.
        """
        names: List[str] = self.configs.get("machine_names", [])
        if ready_for_dpg:
            prepend_list = ["SELECT_MACHINE", "Unspecified-Machine"]
            return prepend_list + sorted(names)
        return names

    def get_tg_263_names(self, ready_for_dpg: bool = False) -> List[str]:
        """
        Return the TG-263 OAR names list.

        Args:
            ready_for_dpg: If True, prepend standard options.

        Returns:
            The list of TG-263 names.
        """
        names: List[str] = self.configs.get("tg_263_names", [])
        if ready_for_dpg:
            prepend_list = ["SELECT_MASK_NAME", "PTV", "CTV", "GTV", "ITV"]
            return prepend_list + sorted(names)
        return names
    
    ### Specific getters ###
    def get_user_config_font(self) -> Optional[str]:
        """
        Return the user-configured font if valid.

        Returns:
            The font name or None if invalid.
        """
        font_dict = self.get_fonts()
        fallback_font: Optional[str] = next(iter(font_dict.keys())) if font_dict else None
        
        font = self.get_user_setting("font", fallback_font)
        
        if not font or not isinstance(font, str) or font not in font_dict:
            logger.error(
                f"Configuration font '{font}' is not valid. It must be one of the available fonts. Using default font."
            )
            return None
        return font

    def get_max_screen_size(self) -> Tuple[int, int]:
        """Return the maximum screen size."""
        return get_main_screen_size()

    def get_screen_size(self) -> Tuple[int, int]:
        """
        Return the configured screen size.

        Ensures the size is a tuple of 2 positive integers not exceeding the maximum screen dimensions.
        """
        max_screen_size = get_main_screen_size()
        fallback_screen_size = (round(max_screen_size[0] * 0.7), round(max_screen_size[1] * 0.7))
        
        screen_size = self.get_user_setting("screen_size", fallback_screen_size)

        if not (
            isinstance(screen_size, (list, tuple))
            and len(screen_size) == 2
            and all(isinstance(x, int) for x in screen_size)
            and all(0 < x <= max_screen_size[i] for i, x in enumerate(screen_size))
        ):
            return fallback_screen_size

        return tuple(screen_size)

    def get_screen_size_input_mode(self) -> str:
        """
        Return the screen input mode ('Percentage' or 'Pixels').

        Returns a fallback of 'Percentage' if invalid.
        """
        fallback_input_mode = "Percentage"
        
        screen_input_mode = self.get_user_setting("screen_input_mode", fallback_input_mode)

        if not (isinstance(screen_input_mode, str) and screen_input_mode in ["Percentage", "Pixels"]):
            logger.error(
                f"Screen input mode '{screen_input_mode}' is not valid. Using fallback value: {fallback_input_mode}."
            )
            return fallback_input_mode

        return screen_input_mode
    
    def get_font_scale(self) -> Union[int, float]:
        """
        Return the configured font scale.

        Returns a fallback value of 1.0 if the setting is invalid.
        """
        fallback_font_scale: Union[int, float] = 1.0
        
        font_scale = self.get_user_setting("font_scale", fallback_font_scale)

        if not isinstance(font_scale, (int, float)) or font_scale <= 0:
            logger.error(
                f"Font scale '{font_scale}' is not valid. Using fallback value: {fallback_font_scale}."
            )
            return fallback_font_scale

        return font_scale

    def get_objectives_filename(self) -> Optional[str]:
        """
        Return the JSON objectives filename.

        If not set, returns None.
        """
        filename = self.get_user_setting("json_objective_filename")
        if not filename:
            logger.info("The objectives JSON filename is not set; it will not be used.")
            return None
        return filename

    def get_objectives_filepath(self) -> Optional[str]:
        """
        Return the full path for the objectives JSON file.

        Returns None if the filename is not set or the location is invalid.
        """
        filename = self.get_objectives_filename()
        config_dir = self.get_configs_dir()
        filepath = os.path.join(config_dir, filename) if filename and config_dir else None

        if not filepath or not self._check_provided_location(filepath):
            logger.info(f"The JSON objectives file location is invalid or not set. Received: {filepath}")
            return None

        return filepath

    def _check_provided_location(self, location: str) -> bool:
        """
        Validate a provided directory location.

        Returns:
            True if valid, False otherwise.
        """
        is_valid, _, message = validate_directory(location)
        if not is_valid:
            logger.error(f"Location validation failed: {message}")
            return False
        return True
    
    def get_pan_speed(self) -> Union[int, float]:
        """
        Return the configured pan speed.

        Returns a fallback value of 0.02 if invalid.
        """
        fallback_pan_speed: Union[int, float] = 0.02
        
        pan_speed = self.get_user_setting("pan_speed", fallback_pan_speed)

        if not isinstance(pan_speed, (int, float)) or pan_speed <= 0:
            logger.error(
                f"Pan speed '{pan_speed}' is not valid. Using fallback value: {fallback_pan_speed}."
            )
            return fallback_pan_speed

        return pan_speed

    def get_zoom_factor(self) -> Union[int, float]:
        """
        Return the configured zoom factor.

        Returns a fallback value of 0.1 if invalid.
        """
        fallback_zoom_factor: Union[int, float] = 0.1
        
        zoom_factor = self.get_user_setting("zoom_factor", fallback_zoom_factor)

        if not isinstance(zoom_factor, (int, float)) or zoom_factor <= 0:
            logger.error(
                f"Zoom factor '{zoom_factor}' is not valid. Using fallback value: {fallback_zoom_factor}."
            )
            return fallback_zoom_factor

        return zoom_factor

    def get_orientation_label_color(self) -> Tuple[int, int, int, int]:
        """
        Return the orientation label color as an RGBA tuple.

        Returns a fallback color of (255, 255, 255, 255) if invalid.
        """
        fallback_color: Tuple[int, int, int, int] = (255, 255, 255, 255)
        
        orientation_label_color = self.get_user_setting("orientation_label_color", fallback_color)

        if not (
            isinstance(orientation_label_color, (list, tuple))
            and len(orientation_label_color) == 4
            and all(isinstance(x, int) for x in orientation_label_color)
            and all(0 <= x <= 255 for x in orientation_label_color)
        ):
            logger.error(
                f"Orientation label color '{orientation_label_color}' is invalid. Using fallback value: {fallback_color}."
            )
            return fallback_color

        return tuple(orientation_label_color)
    
    def get_dpg_padding(self) -> int:
        """
        Return the DPG padding setting.

        Defaults to 8 if the setting is invalid.
        """
        fallback_padding = 8
        
        dpg_padding = self.get_user_setting("dpg_padding", fallback_padding)
        
        if not isinstance(dpg_padding, int) or dpg_padding < 0:
            logger.error(
                f"DPG padding '{dpg_padding}' is not valid. Using fallback value: {fallback_padding}."
            )
            return fallback_padding

        return dpg_padding
    
    def get_voxel_spacing(self) -> List[Union[int, float]]:
        """
        Return the default voxel spacing (X, Y, Z).

        Defaults to [2.0, 2.0, 2.0] if the configuration is invalid.
        """
        fallback_spacing: List[Union[int, float]] = [2.0, 2.0, 2.0]
        
        voxel_spacing = self.get_user_setting("voxel_spacing", fallback_spacing)
        
        if not (
            isinstance(voxel_spacing, (list, tuple))
            and len(voxel_spacing) == 3
            and all(isinstance(x, (int, float)) for x in voxel_spacing)
        ):
            logger.error(
                f"Voxel spacing '{voxel_spacing}' is invalid. Using fallback value: {fallback_spacing}."
            )
            return fallback_spacing

        return list(voxel_spacing)
    
    def get_bool_use_config_voxel_spacing(self) -> bool:
        """
        Return whether to use the default voxel spacing.

        Defaults to False if the configuration is invalid.
        """
        fallback_value = False
        
        use_config_voxel_spacing = self.get_user_setting("use_config_voxel_spacing", fallback_value)
        
        if not isinstance(use_config_voxel_spacing, bool):
            logger.error(
                f"Value for using config voxel spacing '{use_config_voxel_spacing}' is invalid. Using fallback: {fallback_value}."
            )
            return fallback_value

        return use_config_voxel_spacing

    def get_save_settings_dict(self) -> Dict[str, bool]:
        """
        Return the save settings dictionary.

        Defaults to a preset dictionary if the configuration is invalid.
        """
        fallback_dict: Dict[str, bool] = {
            "keep_custom_params": False,
            "convert_ct_hu_to_red": True,
            "override_image_with_roi_RED": True,
        }
        
        save_settings_dict = self.get_user_setting("save_settings_dict", fallback_dict)
        
        if not (isinstance(save_settings_dict, dict) and all(isinstance(save_settings_dict.get(key), bool) for key in fallback_dict)):
            logger.error(
                f"Save settings dictionary '{save_settings_dict}' is invalid. Using fallback: {fallback_dict}."
            )
            return fallback_dict

        return save_settings_dict
