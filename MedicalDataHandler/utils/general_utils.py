import os
import re
import json
import string
import traceback
from tkinter import Tk
from pathlib import Path

def get_traceback(exception):
    """
    Generates a formatted traceback string from an exception.
    
    Args:
        exception (Exception): The exception to format.
    
    Returns:
        str: A formatted string of the traceback.
    """
    return "".join(traceback.TracebackException.from_exception(exception).format())

def get_project_root():
    """ Returns the root directory of the project. """
    utils_dir = os.path.dirname(os.path.realpath(__file__))
    project_root = os.path.dirname(utils_dir)
    return project_root

def format_time( seconds):
    """
    Converts seconds into a formatted hh:mm:ss string.
    
    Args:
        seconds (float): Time elapsed in seconds.
    
    Returns:
        str: Formatted time string.
    """
    if seconds is None:
        return "00:00:00"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def get_main_screen_size():
    """
    Retrieves the width and height of the main screen.
    
    Returns:
        tuple: A tuple (screen_width, screen_height) with the screen dimensions.
    """
    root = Tk()
    root.withdraw()
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    root.destroy()
    return screen_width, screen_height

def format_name(mask_name, replace_nonallowable="", lowercase=False, uppercase=False):
    """
    Formats a name by replacing non-alphanumeric characters and adjusting case.
    
    Args:
        mask_name (str): The name to format.
        replace_nonallowable (str): Replacement string for non-alphanumeric characters. Defaults to "".
        lowercase (bool): Whether to convert the name to lowercase. Defaults to False.
        uppercase (bool): Whether to convert the name to uppercase. Defaults to False.
    
    Returns:
        str: The formatted name.
    
    Raises:
        ValueError: If `mask_name` is not a string.
    """
    if not isinstance(mask_name, str):
        raise ValueError(f"Cannot format the name of a variable that is not a string. mask_name is type: {type(mask_name)}")
    formatted_name = re.sub(r'[^a-zA-Z0-9]', replace_nonallowable, str(mask_name))
    if lowercase and not uppercase:
        formatted_name = formatted_name.lower()
    if uppercase and not lowercase:
        formatted_name = formatted_name.upper()
    return formatted_name

def get_flat_list(nested_structure, return_unique_list=False, remove_none_vals=False, return_without_list_if_one_item=False):
    """
    Recursively flattens a nested structure into a flat list.
    
    Args:
        nested_structure (Any): The nested structure to flatten.
        return_unique_list (bool): Whether to return unique elements only. Defaults to False.
        remove_none_vals (bool): Whether to remove None values. Defaults to False.
        return_without_list_if_one_item (bool): Whether to return a single item directly if the result contains only one. Defaults to False.
    
    Returns:
        list: A flattened list, or a single value if applicable.
    """
    flat_list = []
    
    def _flatten(item):
        if isinstance(item, (list, tuple, set)):
            for subitem in item:
                _flatten(subitem)
        elif isinstance(item, dict):
            for subitem in item.values():
                _flatten(subitem)
        else:
            flat_list.append(item)
    
    _flatten(nested_structure)
    
    if remove_none_vals:
        flat_list = [x for x in flat_list if x is not None]
    if return_unique_list:
        flat_list = list(set(flat_list))
    if len(flat_list) == 1 and return_without_list_if_one_item:
        return flat_list[0]
    return flat_list

def any_exist_in_nested_dict(d):
    """
    Checks whether any value exists in a nested dictionary or list.
    
    Args:
        d (dict or list): The dictionary or list to check.
    
    Returns:
        bool: True if any non-None value exists, otherwise False.
    """
    if isinstance(d, dict):
        # Recursively check each value in the dictionary
        return any(any_exist_in_nested_dict(v) for v in d.values())
    elif isinstance(d, list):
        # Recursively check each item in the list
        return any(any_exist_in_nested_dict(item) for item in d)
    else:
        # If the value is not a dict or list, just check if it's not None
        return d is not None

def safe_type_conversion(value, req_type, uppercase=False, lowercase=False):
    """
    Safely converts a value to a specified type, with optional case formatting for strings.
    
    Args:
        value (Any): The value to convert.
        req_type (type): The desired type (`str`, `int`, `float`, or `bool`).
        uppercase (bool): Whether to convert strings to uppercase. Defaults to False.
        lowercase (bool): Whether to convert strings to lowercase. Defaults to False.
    
    Returns:
        Any: The converted value, or the original value if conversion fails.
    
    Raises:
        ValueError: If `req_type` is not a supported type.
    """
    if not (req_type == str or req_type == int or req_type == float or req_type == bool):
        raise ValueError(f"Cannot convert value to type {req_type}. Must be one of: str, int, float, bool.")
    if value is None:
        return None
    
    try:
        if req_type == str:
            result = str(value)
            if uppercase and not lowercase:
                return result.upper()
            if lowercase and not uppercase:
                return result.lower()
            return result
        elif req_type == int:
            return int(value)
        elif req_type == float:
            return float(value)
        elif req_type == bool:
            return bool(value)
    except ValueError:
        print(f"Failed to convert value {value} to type {req_type}. Returning as-is.")
        return value

def validate_directory(path_str):
    """
    Validates a directory path.
    
    Args:
        path_str (str): The directory path to validate.
    
    Returns:
        tuple: (is_valid, abs_path, error_message)
            - is_valid (bool): True if the path is valid, False otherwise.
            - abs_path (str or None): The absolute path if valid, else None.
            - error_message (str): Description of the validation result.
    """
    if not path_str:
        return False, None, "Invalid entry, no directory found."
    
    path = Path(path_str.strip())
    
    for part in path.parts:
        # Skip the drive letter check on Windows
        if os.name == 'nt' and re.match(r'^[A-Za-z]:\\?$', part):
            continue
        
        invalid_chars = r'[<>:"/\\|?*\x00-\x1F]' if os.name == 'nt' else r'[<>:"|?*\x00-\x1F]'
        if re.search(invalid_chars, part):
            return False, None, f"Invalid characters found in path: {path_str}"
    
    if not path.is_absolute():
        return False, None, f"Invalid path, it is not absolute: {path_str}"
    
    existing_path_from_base = path
    while not existing_path_from_base.exists() and existing_path_from_base != existing_path_from_base.parent:
        existing_path_from_base = existing_path_from_base.parent
    
    if not existing_path_from_base.exists():
        return False, None, f"Invalid path, it does not exist: {path_str}"
    
    if not os.access(existing_path_from_base, os.W_OK):
        return False, None, f"Invalid path, cannot write to it: {path_str}"
    
    abs_path = os.path.abspath(path)
    return True, abs_path, f"Valid directory: {abs_path}"

def validate_filename(filename_str):
    """
    Validates and cleans a filename by removing invalid characters and known file extensions.
    
    Args:
        filename_str (str): The filename to validate.
    
    Returns:
        str: The cleaned filename, or an empty string if invalid.
    """
    if not filename_str:
        return ""
    
    # Remove any directory components
    filename = os.path.basename(filename_str.strip())
    
    # Remove leading/trailing whitespace
    filename = filename.strip()
    
    # Define known file extensions
    known_extensions = {
        '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.png', '.jpg', '.jpeg',
        '.gif', '.bmp', '.tiff', '.csv', '.json', '.xml', '.html', '.htm', '.zip',
        '.tar', '.gz', '.rar', '.7z', '.exe', '.dll', '.py', '.java', '.c', '.cpp',
        '.js', '.css', '.md', '.ini', '.log', '.mov', '.mp4', '.mp3', '.wav', ".dcm", 
        ".nii", ".nii.gz", ".npy", ".npz", ".mat", ".mha", ".mhd", ".stl", ".obj",
    }
    
    # Remove file extension if it's a known extension
    root, ext = os.path.splitext(filename)
    if ext.lower() in known_extensions:
        filename = root
    
    if not filename.strip():
        return ""
    
    # Define invalid characters
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]' if os.name == 'nt' else r'[<>:"|?*\x00-\x1F]'
    
    # Remove invalid characters
    filename = re.sub(invalid_chars, "", filename)
    
    # Trim filename length
    filename = filename[:255]
    
    return filename

def regex_find_dose_and_fractions(roi_name):
    """
    Extracts dose and fractions from an ROI name using regular expressions.
    
    Args:
        roi_name (str): The name of the ROI.
    
    Returns:
        dict: A dictionary with keys 'dose' (float) and 'fractions' (int).
    """
    dose_pattern = r'(\d+\.?\d*)(gy|Gy|GY|cGy|CGY|cGY)?'
    # Broaden the fraction_pattern to capture expressions like "in 35 fx"
    fraction_pattern = r'(\d+)\s*(fx|FX|f|F|x|X)?\.?$'
    in_fraction_pattern = r'in\s*(\d+)\s*(fx|FX|f|F|x|X)\.?'
    
    # Initialize dose, extract, and convert to cGy
    dose = None
    dose_match = re.search(dose_pattern, roi_name.replace(" ", ""), re.IGNORECASE)
    if dose_match:
        dose_value = float(dose_match.group(1))
        dose_unit = dose_match.group(2)
        
        # Check if the unit is specified and convert to cGy if necessary
        if dose_unit and 'gy' in dose_unit.lower() and dose_value <= 100:
            dose = dose_value * 100  # Convert to cGy
        elif dose_value > 100:
            dose = dose_value  # Assume already in cGy
        else:
            dose = dose_value * 100  # Default to Gy conversion if unclear but ≤ 100
        
        if dose > 9999:
            dose = None
    
    # Extract fractions if available
    fractions_match_in = re.search(in_fraction_pattern, roi_name, re.IGNORECASE)
    fractions = int(fractions_match_in.group(1)) if fractions_match_in else None
    if fractions is None:
        fractions_match = re.search(fraction_pattern, roi_name, re.IGNORECASE)
        fractions = int(fractions_match.group(1)) if fractions_match else None
        
    if fractions is not None and (fractions > 46 or (dose is not None and (fractions < 10 and dose > 5500))): # Reasonable limits for fractions
        fractions = None
        
    return {'dose': dose, 'fractions': fractions}

def check_for_valid_dicom_string(input_string):
    """
    Checks if a string conforms to DICOM standards for valid characters.
    
    Args:
        input_string (str): The string to validate.
    
    Returns:
        bool: True if the string is valid, otherwise False.
    """
    valid_chars = set(string.ascii_letters + string.digits + string.punctuation + string.whitespace)
    valid_chars.remove('\\')  # Remove backslash
    control_chars = {chr(i) for i in range(32)}  # ASCII control characters
    valid_chars -= control_chars  # Exclude control characters
    return all(char in valid_chars for char in input_string)

def struct_name_priority_key(mask_name):
    """
    Generates a priority key for sorting based on the structure name.
    
    Args:
        mask_name (str): The name of the structure.
    
    Returns:
        tuple: A tuple containing the priority (int) and the original name (str).
    """
    lower_mask_name = mask_name.lower()
    if lower_mask_name.startswith('ptv'):
        return (0, mask_name)
    elif lower_mask_name.startswith('ctv'):
        return (1, mask_name)
    elif lower_mask_name.startswith('gtv'):
        return (2, mask_name)
    elif lower_mask_name.startswith('bolus'):
        return (3, mask_name)
    elif 'prv' in lower_mask_name:
        return (4, mask_name)
    else:
        return (5, mask_name)

def find_reformatted_mask_name(mask_name, mask_type, combo_mask_names, organ_name_matching_dict):
    """
    Reformats a mask name based on its type and matching dictionaries.
    
    Args:
        mask_name (str): The original mask name.
        mask_type (str): The type of the mask.
        combo_mask_names (list): A list of combined mask names for matching.
        organ_name_matching_dict (dict): A dictionary of organ names and their aliases.
    
    Returns:
        str: The reformatted mask name.
    """
    reformatted_mask_name = re.sub(r'(new)', '', format_name(mask_name, lowercase=True), flags=re.IGNORECASE)
    reformatted_mask_type = format_name(mask_type, lowercase=True)
    
    if reformatted_mask_type == "external":
        return "External"
    
    if (
        re.match(r'(old|donotuse|dontuse|dnu|skip|ignore|testing)', reformatted_mask_name, flags=re.IGNORECASE) or
        ("test" in reformatted_mask_name and not re.match(r'(testis|teste|testic|testa|testo)', reformatted_mask_name, flags=re.IGNORECASE))
        ):
        return f"?UNIDENTIFIED?_{reformatted_mask_name[:10]}..."
    
    # Sometimes, a mask is named 'External' but it is not *the* external structure...
    if reformatted_mask_name == "external": 
        return "Body"
    
    if not any([reformatted_mask_name.startswith(x) for x in ["w", "x", "y", "z"]]):
        if (
            reformatted_mask_name.startswith("ptv") and
            not reformatted_mask_name.startswith("ptvall") and
            not any([reformatted_mask_name.endswith(x) for x in ["opti", "eval", "dvh", "planning", "temp", "test", "max", "cool", "ev", "mm", "cm", "exp"]])
            ):
            return "PTV"
        
        if (
            reformatted_mask_name.startswith("ctv") and
            not any([reformatted_mask_name.endswith(x) for x in ["temp", "test"]])
            ):
            return "CTV"
        
        if (
            reformatted_mask_name.startswith("itv") and
            not any([reformatted_mask_name.endswith(x) for x in ["temp", "test"]])
            ):
            return "ITV"
        
        if (
            reformatted_mask_name.startswith("gtv") and
            not any([reformatted_mask_name.endswith(x) for x in ["temp", "test"]])
            ):
            return "GTV"
        
        for absolute_mask_name in combo_mask_names:
            if reformatted_mask_name == format_name(absolute_mask_name, lowercase=True):
                return absolute_mask_name
    
    for support_struct in ["Z1-Bridge", "Z2a-Bridge", "Z2b-Bridge", "Z3-Bridge", "Z4-Couch Support", "Z5-Hard-plate", "Z6-Couch Support", "Z7-Couch Support", "Z8-Mattress", "Z10-Couch Support"]:
        if format_name(support_struct, lowercase=True) in reformatted_mask_name:
            return support_struct
    
    for mask_key, list_of_mask_names in organ_name_matching_dict.items():
        for item in list_of_mask_names:
            if reformatted_mask_name == format_name(item, lowercase=True):
                return mask_key
    
    return f"?UNIDENTIFIED?_{reformatted_mask_name[:10]}..."

def find_disease_site(plan_label, plan_name, struct_names):
    """
    Determines the disease site based on plan labels, plan names, and structure names.
    
    Args:
        plan_label (str): The label of the plan.
        plan_name (str): The name of the plan.
        struct_names (list or str): A list of structure names or a single structure name.
    
    Returns:
        str: The identified disease site, or "SELECT_MAIN_SITE" if no match is found.
    """
    all_names_to_check = []
    if plan_label:
        plan_label = format_name(str(plan_label), uppercase=True)
        all_names_to_check.append(plan_label)
    if plan_name:
        plan_name = format_name(str(plan_name), uppercase=True)
        all_names_to_check.append(plan_name)
    if struct_names:
        if isinstance(struct_names, str):
            struct_names = [struct_names]
        all_names_to_check.extend([format_name(str(x), uppercase=True) for x in struct_names])
    
    for name_to_check in all_names_to_check:
        if name_to_check is None:
            continue
        if any([x in name_to_check for x in ["ABD",]]):
            return "ABDOMEN"
        if any([x in name_to_check for x in ["ADR",]]):
            return "ADRENAL"
        if any([x in name_to_check for x in ["BLAD",]]):
            return "BLADDER"
        if any([x in name_to_check for x in ["BONE", "RIB", "SCAP", "STERN", "ILIUM", "FEMUR"]]):
            return "BONE"
        if any([x in name_to_check for x in ["BRAI",]]):
            return "BRAIN"
        if any([x in name_to_check for x in ["BREA", "BRST"]]):
            return "BREAST"
        if any([x in name_to_check for x in ["CW", "CHST", "CHEST"]]):
            return "CHESTWALL"
        if any([x in name_to_check for x in ["CSI",]]):
            return "CSI"
        if any([x in name_to_check for x in ["ESO", "ESP"]]):
            return "ESOPHAGUS"
        if any([x in name_to_check for x in ["STOM", "STM", "BOW", "SMBW", "LGBW"]]):
            return "GI"
        if any([x in name_to_check for x in ["URET",]]):
            return "GU"
        if any([x in name_to_check for x in ["GYN", "UTER", "OVAR", "CERVIX", "VAG", "VULV"]]):
            return "GYN"
        if any([x in name_to_check for x in ["HEART", "HRT"]]):
            return "HEART"
        if any([x in name_to_check for x in ["HEAD", "NECK", "HN", "PAR", "LARY", "ORAL", "MAND", "NASO", "PHAR", "NASAL", "SALIV", "TON", "OPX", "HPX", "BOT", "SINUS", "PALAT"]]):
            return "HN"
        if any([x in name_to_check for x in ["KID",]]):
            return "KIDNEY"
        if any([x in name_to_check for x in ["LIV",]]):
            return "LIVER"
        if any([x in name_to_check for x in ["LNG", "LUNG", "HEMITHOR"]]):
            return "LUNG"
        if any([x in name_to_check for x in ["LYM",]]):
            return "LYMPHOMA"
        if any([x in name_to_check for x in ["MED",]]):
            return "MEDIASTINUM"
        if any([x in name_to_check for x in ["PAN",]]):
            return "PANCREAS"
        if any([x in name_to_check for x in ["PLV", "PELV", "ANUS"]]):
            return "PELVIS"
        if any([x in name_to_check for x in ["PROS", "PRS", "FOSSA"]]):
            return "PROSTATE"
        if any([x in name_to_check for x in ["RECT", "RCT"]]):
            return "RECTUM"
        if any([x in name_to_check for x in ["SARC",]]):
            return "SARCOMA"
        if any([x in name_to_check for x in ["SKIN",]]):
            return "SKIN"
        if any([x in name_to_check for x in ["SPINE", "SPN", "VER"]]):
            return "SPINE"
        if any([x in name_to_check for x in ["TBI",]]):
            return "TBI"
    
    return "SELECT_MAIN_SITE"

def verify_roi_goals_format(roi_goals_string):
    """
    Verifies that the ROI goals follow the expected template and specific rules for each metric.
    
    Expected format:
        Keys should follow the pattern: {metric}_{value}_{unit}
            Metric can be V, D, DC, CV, CI, MAX, MEAN, MIN, etc.
            Value should be a number (can be integer or float)
            Unit can be cGy, Gy, %, cc, etc.
        Values should be a list of strings with comparison signs:
            Format: {comparison}_{value}_{unit}
            Comparison can be >, >=, <, <=, =
    
    Rules:
        Key: CI metric must have a value in units of cGy, Values: CI values units must be float or int.
        Key: CV metric must have a value in units of cGy, Values: CV values units must be cc or %.
        Key: DC metric must have a value in units of cc or %, Values: DC values units must be cGy or %.
        Key: D metric must have a value in units of cc or %, Values: D values units must be cGy or %.
        Keys: MAX, MEAN, MIN metrics must have values in units of cGy or %.
        Key: V metric must have a value in units of cGy or %, Values: V values units must be % or cc.
    
    Args:
        roi_goals_string (str): The ROI goals as a JSON-encoded string.
    
    Returns:
        tuple:
                bool: True if all ROI goals are valid, otherwise False.
                list: A list of error messages for invalid goals.
    """
    errors = []
    
    if not roi_goals_string or not isinstance(roi_goals_string, str):
        errors.append(f"ROI goals must be a string, but found: {roi_goals_string}.")
        return False, errors
    
    try:
        roi_goals = json.loads(roi_goals_string)
    except json.JSONDecodeError:
        errors.append(f"Invalid JSON string, cannot convert it to a dictionary: {roi_goals_string} has type {type(roi_goals_string)}.")
        return False, errors
    
    if not isinstance(roi_goals, dict):
        errors.append(f"ROI goals must be a dictionary, but found: {roi_goals}.")
        return False, errors
    
    # Regular expressions for general format checks
    key_pattern = re.compile(r"^(V|D|DC|CV|CI)_(\d+(\.\d+)?)_(cGy|Gy|%|cc)$")
    value_pattern = re.compile(r"^(>|>=|<|<=|=)_(\d+(\.\d+)?)_(cGy|Gy|%|cc)$")
    
    # Specific rules for each metric
    key_rules = {
        "CI": {"allowed_ending": "cGy", "value_endings": []},
        "CV": {"allowed_ending": "cGy", "value_endings": ["cc", "%"]},
        "DC": {"allowed_endings": ["cc", "%"], "value_endings": ["cGy", "%"]},
        "D": {"allowed_endings": ["cc", "%"], "value_endings": ["cGy", "%"]},
        "MAX": {"value_endings": ["cGy", "%"]},
        "MEAN": {"value_endings": ["cGy", "%"]},
        "MIN": {"value_endings": ["cGy", "%"]},
        "V": {"allowed_endings": ["cGy", "%"], "value_endings": ["%", "cc"]},
    }
    
    for key, values in roi_goals.items():
        if not isinstance(key, str):
            errors.append(f"Keys for ROI goals must be strings, but found: {key}.")
            continue
        
        # Validate key format
        match = key_pattern.match(key)
        if match:
            metric, _, _, key_unit = match.groups()
        elif any([key == x for x in ["MAX", "MEAN", "MIN"]]):
            metric = key
            key_unit = None
        else:
            errors.append(
                f"Invalid key format: {key}. Expected format: {{metric}}_{{value}}_{{unit}}. "
                f"Metric can be V, D, DC, CV, CI, MAX, MEAN, MIN. Value should be a number, and unit can be cGy, %, cc."
            )
            continue
        
        # Check specific rules for the metric
        rules = key_rules.get(metric)
        if rules:
            if rules.get("allowed_ending"):
                # Validate key unit
                allowed_endings = rules.get("allowed_endings", [rules.get("allowed_ending")])
                if key_unit not in allowed_endings:
                    errors.append(f"Invalid unit for key {key}. {metric} must end in {', '.join(allowed_endings)}, but found: {key_unit}.")
                    continue
            
            # Validate value format
            if not isinstance(values, list):
                errors.append(f"Values for key {key} must be a list, but found: {values}.")
                continue
            
            # Validate CI values
            if metric == "CI":
                try:
                    if not all(isinstance(val, str) for val in values) or not all(isinstance(float(val), (int, float)) for val in values):
                        errors.append(f"Values for key {key} must be strings that can convert into floats or ints, but found: {values}.")
                        continue
                except ValueError:
                    errors.append(f"Values for key {key} must be strings that can convert into floats or ints, but found: {values}.")
                    continue
                # No need to further validate values for CI metric
                continue
            
            for value in values:
                if not value_pattern.match(value):
                    errors.append(f"Invalid value format for key {key}: {value}. Expected format: {{comparison}}_{{value}}_{{unit}}.")
                    continue
                
                # Validate value unit
                value_unit = value.split("_")[-1]
                if value_unit not in rules["value_endings"]:
                    errors.append(f"Invalid unit for value {value} under key {key}. {metric} values must end in {', '.join(rules['value_endings'])}, but found: {value_unit}.")
    
    # If there are no errors, the format is valid
    is_valid = len(errors) == 0
    return is_valid, errors

def parse_struct_goal(struct_name, struct_goal_type, struct_goal_value, total_organ_volume, rx_dose):
    """
    Parses a structure goal to extract the type of constraint and its metric.
    
    Args:
        struct_name (str): The name of the structure.
        struct_goal_type (str): The type of the structure goal.
        struct_goal_value (str): The value of the structure goal.
        total_organ_volume (float): The total volume of the structure.
        rx_dose (float): The prescription dose in cGy.
    
    Returns:
        tuple: A tuple containing:
            - str: The type of value required ("volume" or "dose").
            - float: The calculated spare volume percentage.
            - float: The calculated spare dose.
    
    Raises:
        None: Prints an error and returns None if parsing fails.
    """
    split_goaltype = struct_goal_type.split("_")
    split_goalvalue = struct_goal_value.split("_")
    
    goal_type = split_goaltype[0]
    goal_sign = split_goalvalue[0]
    
    # Max/Mean/Min: goaltype must not have any units, and goalvalue must have units of cGy or %
    if any([goal_type == x for x in ["MAX", "MEAN", "MIN"]]) and (len(split_goaltype) != 1 or len(split_goalvalue) != 3 or (split_goalvalue[2] != "%" and split_goalvalue[2] != "cGy")):
        print(f"ERROR: Structure {struct_name}, failed to parse an unrecognized structure goal type string: {struct_goal_type} and goal value: {struct_goal_value}. Found goal type: {goal_type}, len(split_goaltype): {len(split_goaltype)}, len(split_goalvalue): {len(split_goalvalue)}, split_goalvalue[2]: {split_goalvalue[2]}")
        return None
    
    # CI: goaltype must have units of cGy, goalvalue must be a float or int
    if any([goal_type == x for x in ["CI"]]) and (len(split_goaltype) != 3 or split_goaltype[2] != "cGy" or len(split_goalvalue) != 1):
        print(f"ERROR: Structure {struct_name}, failed to parse an unrecognized structure goal type string: {struct_goal_type} and goal value: {struct_goal_value}. Found goal type: {goal_type}, len(split_goaltype): {len(split_goaltype)}, len(split_goalvalue): {len(split_goalvalue)}, split_goalvalue[2]: {split_goalvalue[2]}")
        return None
    
    # DC/D: goaltype must have units of cc or %, goalvalue must have units of cGy or %
    if any([goal_type == x for x in ["DC", "D"]]) and (len(split_goaltype) != 3 or (split_goaltype[2] != "cc" and split_goaltype[2] != "%") or len(split_goalvalue) != 3 or (split_goalvalue[2] != "%" and split_goalvalue[2] != "cGy")):
        print(f"ERROR: Structure {struct_name}, failed to parse an unrecognized structure goal type string: {struct_goal_type} and goal value: {struct_goal_value}. Found goal type: {goal_type}, len(split_goaltype): {len(split_goaltype)}, len(split_goalvalue): {len(split_goalvalue)}, split_goalvalue[2]: {split_goalvalue[2]}")
        return None
    
    # CV: goaltype must have units of cGy, goalvalue must have units of cc or %
    if any([goal_type == x for x in ["CV"]]) and (len(split_goaltype) != 3 or split_goaltype[2] != "cGy" or len(split_goalvalue) != 3 or (split_goalvalue[2] != "%" and split_goalvalue[2] != "cc")):
        print(f"ERROR: Structure {struct_name}, failed to parse an unrecognized structure goal type string: {struct_goal_type} and goal value: {struct_goal_value}. Found goal type: {goal_type}, len(split_goaltype): {len(split_goaltype)}, len(split_goalvalue): {len(split_goalvalue)}, split_goalvalue[2]: {split_goalvalue[2]}")
        return None
    
    # V: goaltype must have units of cGy or %, goalvalue must have units of % or cc
    if any([goal_type == x for x in ["V"]]) and (len(split_goaltype) != 3 or (split_goaltype[2] != "%" and split_goaltype[2] != "cGy") or len(split_goalvalue) != 3 or (split_goalvalue[2] != "%" and split_goalvalue[2] != "cc")):
        print(f"ERROR: Structure {struct_name}, failed to parse an unrecognized structure goal type string: {struct_goal_type} and goal value: {struct_goal_value}. Found goal type: {goal_type}, len(split_goaltype): {len(split_goaltype)}, len(split_goalvalue): {len(split_goalvalue)}, split_goalvalue[2]: {split_goalvalue[2]}")
        return None
    
    spare_volume, spare_dose = None, None
    
    if ">" in goal_sign:
        print(f"Structure {struct_name} has a goal sign of >, which is not yet supported. Omitting this goal.")
        return None
    
    if goal_type == "MAX":
        spare_volume = 100.0
        
        if split_goalvalue[2] == "%":
            dose_percent = float(split_goalvalue[1])
            spare_dose = rx_dose * dose_percent / 100.0
        elif split_goalvalue[2] == "cGy":
            spare_dose = float(split_goalvalue[1])
    
    elif goal_type == "MEAN":
        spare_volume = 100.0
        
        if split_goalvalue[2] == "%":
            dose_percent = float(split_goalvalue[1])
            spare_dose = rx_dose * dose_percent / 100.0
        elif split_goalvalue[2] == "cGy":
            spare_dose = float(split_goalvalue[1])
    
    elif goal_type == "MIN":
        print(f"Structure {struct_name} has a MIN goal type, which is not yet supported. Omitting this goal.")
        return None
    
    elif goal_type == "CI":
        print(f"Structure {struct_name} has a CI goal type, which is not yet supported. Omitting this goal.")
        return None
    
    elif goal_type == "D" or goal_type == "DC":
        # DC example:  "DC_1500_cc": "1400_cGy" --> Up to 1500cc can receive >1400cGy
        # D example: "D_1500_cc": "1400_cGy" --> Dose to 1500cc <= 1400cGy
        
        if split_goalvalue[2] == "%":
            dose_percent = float(split_goalvalue[1])
            spare_dose = rx_dose * dose_percent / 100.0
        elif split_goalvalue[2] == "cGy":
            spare_dose = float(split_goalvalue[1])
        
        if split_goaltype[2] == "%":
            spare_volume = 100.0 - float(split_goaltype[1])
        if split_goaltype[2] == "cc":
            max_irradiated_cc = float(split_goaltype[1])
            
            if max_irradiated_cc >= total_organ_volume:
                spare_volume = 100.0
            else:
                spare_volume = ((total_organ_volume - max_irradiated_cc) / total_organ_volume) * 100.0
    
    elif goal_type == "CV" or goal_type == "V":
        # CV example: "CV_1800_cGy": "950_cc" --> Up to 950cc of the structure can receive >1800cGy
        # V example: "V_20_Gy": "20%" --> Up to 20% of the structure can receive >20Gy
        
        if split_goalvalue[2] == "%":
            spare_volume = 100.0 - float(split_goalvalue[1]) # If V20Gy < 20%, then 80% of the volume is spared
        elif split_goalvalue[2] == "cc":
            max_irradiated_cc = float(split_goalvalue[1])
            if max_irradiated_cc >= total_organ_volume:
                spare_volume = 100.0
            else:
                spare_volume = ((total_organ_volume - max_irradiated_cc) / total_organ_volume) * 100.0
        
        if split_goaltype[2] == "%":
            dose_percent = float(split_goaltype[1])
            spare_dose = rx_dose * dose_percent / 100.0
        elif split_goaltype[2] == "cGy":
            spare_dose = float(split_goaltype[1])
    
    if goal_type is None or spare_volume is None or spare_dose is None:
        print(f"Structure {struct_name} could not be parsed: struct_goal_type: {struct_goal_type}, struct_goal_value: {struct_goal_value}, goal type: {goal_type}, spare_volume: {spare_volume}, spare_dose: {spare_dose}. Omitting this goal.")
        return None
    
    return goal_type, spare_volume, spare_dose
