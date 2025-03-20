import os
import json
from utils.general_utils import (
    get_traceback,
    get_project_root,
    get_main_screen_size, 
    validate_directory, 
    format_name
)

class ConfigManager:
    """
    A manager for configuration settings and RT data lists.

    Attributes:
        project_root (str): The root directory of the project.
        config_dirs (dict): Dictionary of important directories.
        config_files (dict): Dictionary mapping config file names to their paths.
        configs (dict): Loaded configuration data, mapped by file key.
    """

    def __init__(self):
        self.project_root = get_project_root()
        self._set_directories()
        self._ensure_directories_exist()
        self._set_config_files()
        self._load_configs()

    def _set_directories(self):
        """ Set up project directories. """
        self.config_dirs = {
            "config": os.path.join(self.project_root, "configs"),
            "assets": os.path.join(self.project_root, "assets"),
            "fonts": os.path.join(self.project_root, "fonts"),
            "patient_objs": os.path.join(self.project_root, "patient_objects"),
            "sitk_data": os.path.join(os.path.dirname(self.project_root), "SITK_DATA"),
            "screenshots": os.path.join(os.path.dirname(self.project_root), "screenshots_mdh"),
        }

    def _ensure_directories_exist(self):
        """ Ensure necessary directories exist. """
        for path in self.config_dirs.values():
            os.makedirs(path, exist_ok=True)

    def _set_config_files(self):
        """ Define configuration file paths. """
        self.config_files = {
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
        
        # Store full paths in the dictionary
        self.config_files = {
            key: (os.path.join(self.config_dirs["config"], filename), expected_type)
            for key, (filename, expected_type) in self.config_files.items()
        }
        
        # Additional files
        self.ico_file = os.path.join(self.config_dirs["assets"], "MDH_Logo_Credit_DALL-E.ico")

    def _load_configs(self):
        """ Load and validate configuration files. """
        self.configs = {}  # Stores loaded configurations
        
        for key, (file_path, expected_type) in self.config_files.items():
            loaded_data = self._load_config(file_path) or expected_type()  # Default to empty dict/list
            
            if not isinstance(loaded_data, expected_type):
                print(f"Invalid {key} configuration file: {file_path}. Expected {expected_type.__name__}, using default.")
                loaded_data = expected_type()
            
            self.configs[key] = loaded_data  # Store validated config data as class attribute
    
    def _load_config(self, file_path):
        """ Load JSON configuration files. Returns None if the file cannot be read. """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as e:
            print(f"Warning! Unable to load configuration file '{file_path}' with error: {get_traceback(e)}")
            return None
    
    def _save_config(self, key, new_config):
        """
        Validate and save the updated configuration to its corresponding JSON file.

        Args:
            key (str): The configuration key (e.g., "fonts", "user_config").
            new_config (dict or list): The new configuration data to save.

        Raises:
            ValueError: If the key is invalid or the new_config does not match the expected type.
        """
        if key not in self.config_files:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return False

        file_path, expected_type = self.config_files[key]

        if not isinstance(new_config, expected_type):
            print(f"Invalid data type for {key}. Expected {expected_type.__name__}, got {type(new_config).__name__}.")
            return False

        # Save to JSON with atomic write to avoid file corruption
        try:
            temp_file = file_path + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as file:
                json.dump(new_config, file, indent=4)

            os.replace(temp_file, file_path)  # Atomic replace

            # Update the in-memory configuration
            self.configs[key] = new_config
            setattr(self, key, new_config)  # Update class attribute
        except Exception as e:
            print(f"Error saving {key} to {file_path}: {get_traceback(e)}")
            return False

        return True
    
    ### Update methods for saving without specifying the key ###
    
    def update_user_config(self, updates):
        """
        Update the user_config dictionary with new key-value pairs and save.
        
        Args:
            updates (dict): Dictionary of key-value pairs to update in user_config.
        """
        if not isinstance(updates, dict):
            print(f"Invalid updates for user_config. Expected dict, got {type(updates).__name__}.")
            return

        key = "user_config"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        user_config = self.configs[key]
        user_config.update(updates)
        self._save_config(key, user_config)

    def add_item_organ_matching(self, organ, new_item):
        """
        Adds an item in the organ_matching dictionary.
        
        Args:
            organ (str): The organ name.
            new_item (str): The new item to add to the list.
        """
        key = "organ_matching"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        if not isinstance(new_item, str):
            print(f"Invalid new_item for organ_matching. Expected str, got {type(new_item).__name__}.")
            return
        
        organ_matching = self.configs[key]
        
        if organ not in organ_matching:
            organ_matching[organ] = []

        current_set = set(organ_matching[organ])
        formatted_item = format_name(new_item, lowercase=True)
        current_set.add(formatted_item)
        organ_matching[organ] = sorted(list(current_set))
        
        self._save_config(key, organ_matching)
    
    def remove_item_organ_matching(self, organ, item_to_remove):
        """
        Remove an item from the organ_matching dictionary.
        
        Args:
            organ (str): The organ name.
            item_to_remove (str): The item to remove from the list.
        """
        key = "organ_matching"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        if not isinstance(item_to_remove, str):
            print(f"Invalid item_to_remove for organ_matching. Expected str, got {type(item_to_remove).__name__}.")
            return
        
        organ_matching = self.configs[key]
        
        if organ not in organ_matching:
            print(f"The organ provided was not found in the organ name matching dictionary: {organ}")
            return
        
        current_set = set(organ_matching[organ])
        formatted_item = format_name(item_to_remove, lowercase=True)
        
        if formatted_item in current_set:
            current_set.remove(formatted_item)
            organ_matching[organ] = sorted(list(current_set))
            self._save_config(key, organ_matching)
    
    def add_machine_name(self, machine_name):
        """
        Add a machine name to the machine_names list.
        
        Args:
            machine_name (str): The machine name to add.
        """
        if not isinstance(machine_name, str):
            print(f"Invalid machine_name. Expected str, got {type(machine_name).__name__}.")
            return
        
        key = "machine_names"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        machine_names = self.configs[key]
        
        if machine_name not in machine_names:
            machine_names.append(machine_name)
            self._save_config("machine_names", machine_names)
    
    def remove_machine_name(self, machine_name):
        """
        Remove a machine name from the machine_names list.
        
        Args:
            machine_name (str): The machine name to remove.
        """
        key = "machine_names"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        machine_names = self.configs[key]
        
        if machine_name in machine_names:
            machine_names.remove(machine_name)
            self._save_config("machine_names", machine_names)
    
    def add_disease_site(self, disease_site):
        """
        Add a disease site to the disease_sites list.
        
        Args:
            disease_site (str): The disease site to add.
        """
        if not isinstance(disease_site, str):
            print(f"Invalid disease_site. Expected str, got {type(disease_site).__name__}.")
            return
        
        key = "disease_sites"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        disease_sites = self.configs[key]
        
        if disease_site not in disease_sites:
            disease_sites.append(disease_site)
            self._save_config("disease_sites", disease_sites)
    
    def remove_disease_site(self, disease_site):
        """
        Remove a disease site from the disease_sites list.
        
        Args:
            disease_site (str): The disease site to remove.
        """
        key = "disease_sites"
        if key not in self.configs:
            print(f"Invalid configuration key: {key}, cannot update its configuration.")
            return
        
        disease_sites = self.configs[key]
        
        if disease_site in disease_sites:
            disease_sites.remove(disease_site)
            self._save_config("disease_sites", disease_sites)
    
    ### Getters for general configuration settings ###
    def get_project_parent_dir(self):
        """ Retrieve the parent directory of the project. """
        return os.path.dirname(self.project_root)
    
    def get_configs_dir(self):
        """ Retrieve the config directory path. """
        return self.config_dirs.get("config")
    
    def get_patient_objects_dir(self):
        """ Retrieve the patient_objects directory path. """
        return self.config_dirs.get("patient_objs")
    
    def get_font_dir(self):
        """ Retrieve the fonts directory path. """
        return self.config_dirs.get("fonts")
    
    def get_sitk_data_dir(self):
        """ Retrieve the SITK_DATA directory path. """
        return self.config_dirs.get("sitk_data")
    
    def get_screenshots_dir(self):
        """ Retrieve the screenshots directory path. """
        return self.config_dirs.get("screenshots")
    
    def get_fonts(self):
        """ Retrieve the fonts dictionary. """
        return self.configs.get("fonts", {})
    
    def get_font_size(self, font_name):
        """
        Retrieve the font size for a specific font.
        
        Args:
            font_name (str): The font name to retrieve the size for.
        
        Returns:
            int: The font size, or None if the font name is not found.
        """
        return self.get_fonts().get(font_name)
    
    def get_icon_file(self):
        """ Retrieve the icon file path. """
        return self.ico_file
    
    def get_user_config(self):
        """ Retrieve the user_config dictionary. """
        return self.configs.get("user_config", {})
    
    def get_user_setting(self, key):
        """
        Retrieve a single setting from the user_config.
        
        Args:
            key (str): The setting key to retrieve.
        
        Returns:
            Any: The value of the setting, or None if the key is not found.
        """
        return self.get_user_config().get(key)
    
    def get_organ_matching_dict(self):
        """ Retrieve the organ_matching dictionary. """
        return self.configs.get("organ_matching", {})
    
    def get_window_presets(self):
        """ Retrieve the window_presets dictionary. """
        return self.configs.get("window_presets", {})
    
    def get_ct_HU_map_vals(self):
        """ Retrieve the CT HU map values list. """
        return self.configs.get("ct_HU_map_vals", [])

    def get_ct_RED_map_vals(self):
        """ Retrieve the CT RED map values list. """
        return self.configs.get("ct_RED_map_vals", [])
    
    def get_disease_sites(self, ready_for_dpg=False):
        """ Retrieve the disease_sites list. """
        if not ready_for_dpg:
            return self.configs.get("disease_sites", [])
        
        prepend_list = ["SELECT_MAIN_SITE", "UNKNOWN_SITE", "MULTIPLE_SITES"]
        return prepend_list + sorted(self.configs.get("disease_sites", []))
    
    def get_machine_names(self, ready_for_dpg=False):
        """ Retrieve the machine_names list. """
        if not ready_for_dpg:
            return self.configs.get("machine_names", [])
        
        prepend_list = ["SELECT_MACHINE", "Unspecified-Machine"]
        return prepend_list + sorted(self.configs.get("machine_names", []))
    
    def get_tg_263_names(self, ready_for_dpg=False):
        """ Retrieve the TG-263 OAR names list. """
        if not ready_for_dpg:
            return self.configs.get("tg_263_names", [])
        
        prepend_list = ["SELECT_MASK_NAME", "PTV", "CTV", "GTV", "ITV"]
        combo_mask_names = prepend_list + sorted(self.configs.get("tg_263_names", []))
        
        return combo_mask_names
    
    ### Specific getters ###
    def get_user_config_font(self):
        """ Retrieve the user_config font setting. """
        font_dict = self.get_fonts()
        backup_font = next(iter(font_dict.keys())) if font_dict else None
        
        user_config = self.configs.get("user_config", {})
        font = user_config.get("font") or backup_font
        
        if not font or not isinstance(font, str) or not font in font_dict:
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid font: {font}. It must be one of the available fonts. Using DPG default font.")
            return None
        
        return font
    
    def get_max_screen_size(self):
        """
        Retrieve the maximum screen size from the configuration.
        """
        return get_main_screen_size()
    
    def get_screen_size(self):
        """
        Retrieve the screen size from the configuration. 
        Ensures the value is a list or tuple of 2 integers, and each value is between 1 and the maximum screen size.
        """
        user_config = self.configs.get("user_config", {})
        screen_size = user_config.get("screen_size")
        
        max_screen_size = get_main_screen_size()
        fallback_screen_size = (round(max_screen_size[0] * 0.7), round(max_screen_size[1] * 0.7))
        
        if not screen_size:
            return fallback_screen_size
        
        if not (isinstance(screen_size, (list, tuple)) and 
                len(screen_size) == 2 and 
                all(isinstance(x, int) for x in screen_size) and 
                all(0 < x <= max_screen_size[i] for i, x in enumerate(screen_size))):
            return fallback_screen_size 
        
        return tuple(screen_size)
    
    def get_screen_size_input_mode(self):
        """ Retrieve the screen input mode setting. Ensures the value is a string of either "Percentage" or "Pixels". """
        user_config = self.configs.get("user_config", {})
        screen_input_mode = user_config.get("screen_size_input_mode")
        fallback_input_mode = "Percentage"
        
        if not screen_input_mode:
            return fallback_input_mode
        
        if not isinstance(screen_input_mode, str) or screen_input_mode not in ["Percentage", "Pixels"]:
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid screen input mode: {screen_input_mode}. It must be 'Percentage' or 'Pixels'. Using a fallback value: {fallback_input_mode}")
            return fallback_input_mode
        
        return screen_input_mode
    
    def get_font_scale(self):
        """ Retrieve the font scale setting. Ensures the value is an integer or float greater than 0. """
        user_config = self.configs.get("user_config", {})
        font_scale = user_config.get("font_scale")
        fallback_font_scale = 1.0
        
        if not font_scale:
            return fallback_font_scale
        
        if not isinstance(font_scale, (int, float)) or font_scale <= 0:
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid font scale: {font_scale}. It must be an integer or float greater than 0. Using a fallback value: {fallback_font_scale}")
            return fallback_font_scale  # Default fallback value
        
        return font_scale
    
    def get_objectives_filename(self):
        """
        Retrieve the JSON objective file name string. If it doesn't exist or is invalid, it will default to None.
        """
        user_config = self.configs.get("user_config", {})
        filename = user_config.get("json_objective_filename")
        if not filename:
            print(f"CONFIG NOTE: The objectives JSON file name is not set, so it will not be used.")
            return None
        return filename
    
    def get_objectives_filepath(self):
        """
        Retrieve the objective file location string. If it doesn't exist or is invalid, it will default to None.
        """
        filename = self.get_objectives_filename()
        config_dir = self.config_dirs.get("config")
        filepath = os.path.join(config_dir, filename) if filename else None
        
        if not filepath or not self._check_provided_location(filepath):
            print(f"CONFIG NOTE: The JSON objective file location is invalid or not set, so it will not be used. Received: {filepath}")
            return None
        
        return filepath
    
    def _check_provided_location(self, location):
        """ Check if the provided location is valid. """
        is_valid, abs_path, message = validate_directory(location)
        if not is_valid:
            print(f"Error: {message}")
            return False
        return True
    
    def get_pan_speed(self):
        """
        Retrieve the current pan speed. Ensures the value is an integer or float greater than 0.
        """
        user_config = self.configs.get("user_config", {})
        pan_speed = user_config.get("pan_speed")
        fallback_pan_speed = 0.02
        
        if not pan_speed:
            return fallback_pan_speed
        
        if not isinstance(pan_speed, (int, float)) or pan_speed <= 0:
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid pan speed: {pan_speed}. It must be an integer or float greater than 0. Using a fallback value: {fallback_pan_speed}")
            return fallback_pan_speed
        
        return pan_speed
    
    def get_zoom_factor(self):
        """
        Retrieve the current zoom factor. Ensures the value is an integer or float greater than 0.
        """
        user_config = self.configs.get("user_config", {})
        zoom_factor = user_config.get("zoom_factor")
        fallback_zoom_factor = 0.1
        
        if not zoom_factor:
            return fallback_zoom_factor
        
        if not isinstance(zoom_factor, (int, float)) or zoom_factor <= 0:
            print(f"CHECK CONFIG. Invalid zoom factor: {zoom_factor}. It must be an integer or float greater than 0. Using a fallback value: {fallback_zoom_factor}")
            return fallback_zoom_factor
        
        return zoom_factor
    
    def get_orientation_label_color(self):
        """
        Retrieve the orientation label color setting. Ensures the value is a list or tuple of 4 integers.
        """
        user_config = self.configs.get("user_config", {})
        orientation_label_color = user_config.get("orientation_label_color")
        fallback_ol_color = (255, 255, 255, 255)
        
        if not orientation_label_color:
            return fallback_ol_color
        
        if not (isinstance(orientation_label_color, (list, tuple)) and 
                len(orientation_label_color) == 4 and 
                all(isinstance(x, int) for x in orientation_label_color) and
                all(0 <= x <= 255 for x in orientation_label_color)):
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid orientation label color: {orientation_label_color}. It must be a list or tuple of 4 integers between 0 and 255. Using a fallback value: {fallback_ol_color}")
            return fallback_ol_color
        
        return tuple(orientation_label_color)
    
    def get_dpg_padding(self):
        """
        Retrieve the DPG padding setting. Ensures the value is an integer greater than or equal to 0. Default is 8.
        """
        user_config = self.configs.get("user_config", {})
        dpg_padding = user_config.get("dpg_padding")
        fallback_dpg_padding = 8
        
        if not dpg_padding:
            return fallback_dpg_padding
        
        if not isinstance(dpg_padding, int) or dpg_padding < 0:
            print(f"CHECK CONFIG. Invalid DPG padding: {dpg_padding}. It must be an integer greater than or equal to 0. Using a fallback value: {fallback_dpg_padding}")
            return fallback_dpg_padding
        
        return dpg_padding
    
    def get_voxel_spacing(self):
        """
        Retrieve the default voxel spacing (X, Y, Z order) setting. Ensures the value is a list or tuple of 3 floats.
        """
        user_config = self.configs.get("user_config", {})
        voxel_spacing = user_config.get("voxel_spacing")
        fallback_spacing = [2.0, 2.0, 2.0]
        
        if not voxel_spacing:
            return fallback_spacing
        
        if not (isinstance(voxel_spacing, (list, tuple)) and 
                len(voxel_spacing) == 3 and 
                all(isinstance(x, (int, float)) for x in voxel_spacing)):
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid config voxel spacing: {voxel_spacing}. It must be a list or tuple of 3 floats. Using a fallback value: {fallback_spacing}")
            return fallback_spacing
        
        return voxel_spacing
    
    def get_bool_use_config_voxel_spacing(self):
        """
        Retrieve the boolean setting for using the default voxel spacing. Ensures the value is a boolean.
        """
        user_config = self.configs.get("user_config", {})
        use_config_voxel_spacing = user_config.get("use_config_voxel_spacing")
        fallback_value = False
        
        if not use_config_voxel_spacing:
            return fallback_value
        
        if not isinstance(use_config_voxel_spacing, bool):
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid boolean for using config voxel spacing: {use_config_voxel_spacing}. It must be a boolean. Using a fallback value: {fallback_value}.")
            return fallback_value
        
        return use_config_voxel_spacing
    
    def get_save_settings_dict(self):
        """ Retrieve the save settings dictionary. """
        user_config = self.configs.get("user_config", {})
        save_settings_dict = user_config.get("save_settings_dict")
        fallback_dict = {
            "keep_custom_params": False,
            "convert_ct_hu_to_red": True,
            "override_image_with_roi_RED": True,
        }
        
        if not save_settings_dict:
            return fallback_dict
        
        if not isinstance(save_settings_dict, dict) or not all(isinstance(save_settings_dict.get(key), bool) for key in fallback_dict):
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid save settings dictionary: {save_settings_dict}. It must be a dictionary with boolean values for all keys. Using a fallback value: {fallback_dict}")
            return fallback_dict
        
        return save_settings_dict

