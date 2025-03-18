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
        
        config_dir (str): Directory containing configuration files.
        assets_dir (str): Directory containing assets.
        dcm_processor_objs_dir (str): Directory containing DICOM processor objects.
        sitk_save_dir (str): Directory to save SimpleITK images.
    
        config_file (str): JSON configuration file.
        ico_file (str): Icon file.
        data_lists_file (str): JSON file containing RT data lists.
        
        settings (dict): Loaded settings from the configuration file.
        rt_data_lists (dict): RT data lists loaded from the associated JSON file.
    """
    
    def __init__(self):
        self.project_root = get_project_root()
        
        self.config_dir = os.path.join(self.project_root, "configs")
        self.assets_dir = os.path.join(self.project_root, "assets")
        self.dcm_processor_objs_dir = os.path.join(self.project_root, "dicom_processor_objects")
        self.sitk_save_dir = os.path.join(os.path.dirname(self.project_root), "SITK_DATA")
        
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        os.makedirs(self.dcm_processor_objs_dir, exist_ok=True)
        os.makedirs(self.sitk_save_dir, exist_ok=True)
        
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.ico_file = os.path.join(self.assets_dir, "MDH_Logo_Credit_DALL-E.ico")
        self.data_lists_file = os.path.join(self.config_dir, "RT_DATA_LISTS.json")
        
        self.settings = self.load_config()
        self.rt_data_lists = self.load_data_lists()
    
    def load_config(self):
        """
        Load settings from the JSON configuration file.
        
        Returns:
            dict: Configuration settings, or an empty dictionary if the file is missing or invalid.
        """
        if not os.path.exists(self.config_file):
            print(f"Config file not found at: '{self.config_file}'")
            return {}
        
        try:
            with open(self.config_file, "r") as f:
                settings = json.load(f)
            print(f"Config loaded from: '{self.config_file}'")
            return settings
        except (json.JSONDecodeError, IOError) as e:
            print(get_traceback(e))
            return {}
    
    def load_data_lists(self):
        """
        Load RT data lists from a JSON file in the same directory as the config file.
        
        Returns:
            dict: RT data lists, or an empty dictionary if the file is missing or invalid.
        """
        try:
            with open(self.data_lists_file, "r") as f:
                rt_data_lists = json.load(f)
            print(f"RT DATA lists loaded from: '{self.data_lists_file}'")
            return rt_data_lists
        except (json.JSONDecodeError, IOError) as e:
            print(get_traceback(e))
            return {}
    
    def save_config(self, new_settings=None):
        """
        Save the current or updated settings to the configuration file.
        
        Args:
            new_settings (dict, optional): Additional settings to update before saving.
        """
        if new_settings:
            self.settings.update(new_settings)
        
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.settings, f, indent=4)
            print(f"Config updated at: {self.config_file}")
        except IOError as e:
            print(get_traceback(e))
    
    def save_data_lists(self, new_data_lists=None):
        """
        Save the current or updated RT data lists to the JSON file.
        
        Args:
            new_data_lists (dict, optional): Additional data lists to update before saving.
        """
        if not new_data_lists:
            return
        
        self.rt_data_lists.update(new_data_lists)
        
        try:
            with open(self.data_lists_file, "w") as f:
                json.dump(self.rt_data_lists, f, indent=4)
            print(f"RT DATA lists updated at: {self.data_lists_file}")
        except IOError as e:
            print(get_traceback(e))
    
    def get_setting(self, key):
        """
        Retrieve a single setting from the configuration.
        
        Args:
            key (str): The setting key to retrieve.
        
        Returns:
            Any: The value of the setting, or None if the key is not found.
        """
        return self.settings.get(key)
    
    def update_setting(self, key, value):
        """
        Update a single setting and save the configuration file.
        
        Args:
            key (str): The setting key to update.
            value: The new value for the setting.
        """
        self.settings[key] = value
        self.save_config()
        print(f"Setting updated: {key} = {value}")
    
    def update_rt_data_disease_site_list(self, new_list):
        """
        Update the disease site list in the RT data lists.
        
        Args:
            new_list (list): The updated disease site list.
        """
        self.rt_data_lists["DISEASE_SITES_LIST"] = new_list
        self.save_data_lists()
    
    def update_rt_data_machine_names_list(self, new_list):
        """
        Update the machine names list in the RT data lists.
        
        Args:
            new_list (list): The updated machine names list.
        """
        self.rt_data_lists["MACHINE_NAMES_LIST"] = new_list
        self.save_data_lists()
    
    def update_rt_data_single_organ_match_list(self, organ, new_item):
        """
        Update the organ name matching dictionary with a new item.
        
        Args:
            organ (str): The organ key in the organ name matching dictionary.
            new_item (str): The new item to add.
        """
        if organ not in self.rt_data_lists["ORGAN_NAME_MATCHING_DICT"]:
            print(f"The organ provided was not found in the organ name matching dictionary: {organ}")
            return
        
        current_set = set(self.rt_data_lists["ORGAN_NAME_MATCHING_DICT"][organ])
        formatted_item = format_name(new_item, lowercase=True)
        current_set.add(formatted_item)
        self.rt_data_lists["ORGAN_NAME_MATCHING_DICT"][organ] = sorted(list(current_set))
        self.save_data_lists()
    
    def get_max_screen_size(self):
        """
        Retrieve the maximum screen size from the configuration.
        """
        return get_main_screen_size()
    
    def get_screen_size(self):
        """
        Retrieve the screen size from the configuration. Ensures the value is a list or tuple of 2 integers, and each value is between 1 and the maximum screen size.
        """
        screen_size = self.settings.get("screen_size")
        
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
    
    def get_font_scale(self):
        """
        Retrieve the font scale setting. Ensures the value is an integer or float greater than 0.
        """
        font_scale = self.settings.get("font_scale")
        fallback_font_scale = 1.0
        
        if not font_scale:
            return fallback_font_scale
        
        if not isinstance(font_scale, (int, float)) or font_scale <= 0:
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid font scale: {font_scale}. It must be an integer or float greater than 0. Using a fallback value: {fallback_font_scale}")
            return fallback_font_scale  # Default fallback value
        
        return font_scale
    
    def get_json_objective_filename(self):
        """
        Retrieve the JSON objective file name string. If it doesn't exist or is invalid, it will default to None.
        """
        filename = self.settings.get("json_objective_filename")
        if not filename:
            print(f"CONFIG NOTE: The JSON objective file name is not set, so it will not be used.")
            return None
        
        return filename
    
    def get_json_objective_filepath(self):
        """
        Retrieve the JSON objective file location string. If it doesn't exist or is invalid, it will default to None.
        """
        filename = self.get_json_objective_filename()
        filepath = os.path.join(self.config_dir, filename) if filename else None
        
        if not filepath or not self._check_provided_location(filepath):
            print(f"CONFIG NOTE: The JSON objective file location is invalid or not set, so it will not be used. Received: {filepath}")
            return None
        
        return filepath
    
    def _check_provided_location(self, location):
        """
        Check if the provided location is valid.
        """
        is_valid, abs_path, message = validate_directory(location)
        if not is_valid:
            print(f"Error: {message}")
            return False
        return True
    
    def get_pan_speed(self):
        """
        Retrieve the current pan speed. Ensures the value is an integer or float greater than 0.
        """
        pan_speed = self.settings.get("pan_speed")
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
        zoom_factor = self.settings.get("zoom_factor")
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
        orientation_label_color = self.settings.get("orientation_label_color")
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
        dpg_padding = self.settings.get("dpg_padding")
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
        voxel_spacing = self.settings.get("voxel_spacing")
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
        use_config_voxel_spacing = self.settings.get("use_config_voxel_spacing")
        fallback_value = False
        
        if not use_config_voxel_spacing:
            return fallback_value
        
        if not isinstance(use_config_voxel_spacing, bool):
            print(f"CHECK CONFIG OR EDIT SETTINGS. Invalid boolean for using config voxel spacing: {use_config_voxel_spacing}. It must be a boolean. Using a fallback value: {fallback_value}.")
            return fallback_value
        
        return use_config_voxel_spacing
    
    def get_save_settings_dict(self):
        """
        Retrieve the save settings dictionary.
        """
        save_settings_dict = self.settings.get("save_settings_dict")
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
    
    def get_window_presets(self):
        """
        Retrieve the window presets setting.
        Dictionary of pre-set window values (Window Width, Window Level). Source: https://radiopaedia.org/articles/windowing-ct?lang=us
        """
        window_preset_dict = { 
            "Custom": (375, 40), "Brain: General": (80, 40), "Brain: Subdural": (200, 75), "Brain: Stroke": (8, 32),
            "Bone: Option 1": (1800, 400), "Bone: Option 2": (2800, 600), "Bone: Option 3": (4000, 700), "Soft Tissue: Option 1": (250, 50),
            "Soft Tissue: Option 2": (350, 20), "Soft Tissue: Option 3": (400, 60), "Soft Tissue: Option 4": (375, 40), "Lung": (1500, -600),
            "Liver": (150, 30),
        }
        
        return window_preset_dict
    
    def get_disease_site_list(self, ready_for_dpg=False):
        """
        Retrieve the disease site list.
        """
        if not ready_for_dpg:
            return self.rt_data_lists.get("DISEASE_SITES_LIST", [])
        
        return ["SELECT_MAIN_SITE", "UNKNOWN_SITE", "MULTIPLE_SITES"] + sorted(self.rt_data_lists.get("DISEASE_SITES_LIST", []))
    
    def get_machine_names_list(self, ready_for_dpg=False):
        """
        Retrieve the machine names list.
        """
        if not ready_for_dpg:
            return self.rt_data_lists.get("MACHINE_NAMES_LIST", [])
        
        return ["SELECT_MACHINE", "Unspecified-Machine"] + sorted(self.rt_data_lists.get("MACHINE_NAMES_LIST", []))
    
    def get_tg_263_oar_names_list(self, ready_for_dpg=False):
        """
        Retrieve the TG-263 OAR names list.
        """
        if not ready_for_dpg:
            return self.rt_data_lists.get("TG_263_OAR_NAMES_LIST", [])
        
        top_mask_names = ["SELECT_MASK_NAME", "PTV", "CTV", "GTV", "ITV"]
        combo_mask_names = top_mask_names + sorted(self.rt_data_lists.get("TG_263_OAR_NAMES_LIST", []))
        
        return combo_mask_names
    
    def get_organ_name_matching_dict(self):
        """
        Retrieve the organ name matching dictionary.
        """
        return self.rt_data_lists.get("ORGAN_NAME_MATCHING_DICT", {})
    
