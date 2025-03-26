import os
import re
import json
import string
import logging
import weakref
import traceback
import tempfile
import functools
from tkinter import Tk
from pathlib import Path
from itertools import islice
from typing import Any, Iterable, Iterator, List, Tuple, Union, Optional, Dict, Callable

logger = logging.getLogger(__name__)

def get_traceback(exception: Exception) -> str:
    """Return a formatted traceback string for the given exception."""
    return "\n" + "".join(traceback.TracebackException.from_exception(exception).format())

def get_callable_name(func: Callable) -> str:
    """Return the name of the underlying callable."""
    try:
        # If it's a functools.partial
        if isinstance(func, functools.partial):
            return get_callable_name(func.func)

        # If it's a named function
        if hasattr(func, '__name__') and func.__name__ != "<lambda>":
            return func.__name__

        # If it's a class/instance
        if hasattr(func, '__class__'):
            return f"{func.__class__.__name__} instance"

    except Exception:
        pass

    return repr(func)

def chunked_iterable(iterable: Iterable[Any], size: int) -> Iterator[List[Any]]:
    """Yield successive chunks of the given size from an iterable."""
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk

def weakref_nested_structure(structure: Any) -> Any:
    """Recursively replace items in a nested structure with weak references when applicable.
    
    Args:
        structure: The input structure (dict, list, tuple, or other objects).

    Returns:
        The structure with objects replaced by weak references when applicable.
    """
    if isinstance(structure, dict):
        # If it's a dictionary, apply weakref recursively to each value
        return {key: weakref_nested_structure(value) for key, value in structure.items()}
    
    elif isinstance(structure, list):
        # If it's a list, apply weakref recursively to each item
        return [weakref_nested_structure(item) for item in structure]
    
    elif isinstance(structure, tuple):
        # If it's a tuple, apply weakref recursively to each item (and return a tuple)
        return tuple(weakref_nested_structure(item) for item in structure)
    
    # Check if the object supports weak references
    elif hasattr(structure, '__weakref__'):
        # If it's an object that can be weak-referenced, create a weakref
        return weakref.ref(structure)
    
    # For other types (such as int, float, str), return the object itself
    return structure

def atomic_save(
    filepath: str,
    write_func: Callable[[Any], None],
    mode: str = "w",
    encoding: str = "utf-8",
    suffix: str = ".tmp",
    success_message: str = "",
    error_message: str = ""
) -> bool:
    """
    Atomically write to a file by first writing to a temp file and then replacing the target.

    Args:
        filepath: Final path to save the file to.
        write_func: A function that accepts a writable file object and writes the content.
        mode: File open mode ('w' for text, 'wb' for binary).
        encoding: Encoding for text mode.
        suffix: Suffix to use for the temporary file.
        success_message: Message to log if the file is saved successfully.
        error_message: Message to log if an error occurs.

    Returns:
        True if saved successfully, False otherwise.
    """
    directory = os.path.dirname(filepath)
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(mode=mode, dir=directory, delete=False, suffix=suffix, encoding=encoding if "b" not in mode else None) as tmp_file:
            temp_path = tmp_file.name
            write_func(tmp_file)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        
        os.replace(temp_path, filepath)
        if success_message:
            logger.info(success_message)
        return True
    except Exception as e:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if error_message:
            logger.error(error_message + get_traceback(e))
        else:
            logger.error(f"Failed to save file '{filepath}'." + get_traceback(e))
        return False

def get_source_dir() -> str:
    """Return the source directory of the project."""
    this_fpath = os.path.abspath(__file__)
    utils_dir = os.path.dirname(this_fpath)
    mdh_app_dir = os.path.dirname(utils_dir)
    source_dir = os.path.dirname(mdh_app_dir)
    return source_dir

def format_time(seconds: Optional[float]) -> str:
    """Convert seconds to a formatted string HH:MM:SS."""
    if seconds is None:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"

def get_main_screen_size() -> Tuple[int, int]:
    """Return the width and height of the main screen."""
    root = Tk()
    root.withdraw()
    root.update_idletasks()
    width = root.winfo_screenwidth()
    height = root.winfo_screenheight()
    root.destroy()
    return width, height

def format_name(
    mask_name: str, 
    replace_nonallowable: str = "", 
    lowercase: bool = False, 
    uppercase: bool = False
) -> str:
    """Format a string by replacing non-alphanumeric characters and adjusting its case."""
    if not isinstance(mask_name, str):
        raise ValueError(f"Expected a string for mask_name, got {type(mask_name)}")
    formatted = re.sub(r'[^a-zA-Z0-9]', replace_nonallowable, mask_name)
    if lowercase and not uppercase:
        return formatted.lower()
    if uppercase and not lowercase:
        return formatted.upper()
    return formatted

def get_flat_list(
    nested_structure: Any,
    return_unique_list: bool = False,
    remove_none_vals: bool = False,
    return_without_list_if_one_item: bool = False
) -> Union[List[Any], Any]:
    """
    Recursively flatten a nested structure into a list.

    Optionally, return only unique elements, remove None values,
    or return a single item directly if the result contains one element.
    """
    flat_list: List[Any] = []

    def _flatten(item: Any) -> None:
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

def any_exist_in_nested_dict(d: Any) -> bool:
    """Return True if any non-None value exists in a nested structure (dict or list)."""
    if isinstance(d, dict):
        # Recursively check each value in the dictionary
        return any(any_exist_in_nested_dict(v) for v in d.values())
    elif isinstance(d, list):
        # Recursively check each item in the list
        return any(any_exist_in_nested_dict(item) for item in d)
    else:
        # If the value is not a dict or list, just check if it's not None
        return d is not None

def safe_type_conversion(value: Any, req_type: type, uppercase: bool = False, lowercase: bool = False) -> Any:
    """
    Convert a value to a specified type (str, int, float, or bool) with optional string case formatting.

    Returns the converted value or the original value if conversion is unsuccessful.
    """
    if req_type not in {str, int, float, bool}:
        raise ValueError(f"Unsupported conversion type: {req_type}. Allowed types: str, int, float, bool.")
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
        logger.warning(f"Conversion unsuccessful for value {value} to {req_type}. Returning original value.")
        return value

def validate_directory(path_str: str) -> Tuple[bool, Optional[str], str]:
    """
    Validate a directory path and return a tuple:
    (is_valid, absolute_path if valid else None, message).
    """
    if not path_str:
        return False, None, "No directory provided."

    path = Path(path_str.strip())
    for part in path.parts:
        # Skip the drive letter check on Windows
        if os.name == 'nt' and re.match(r'^[A-Za-z]:\\?$', part):
            continue
        invalid_chars = r'[<>:"/\\|?*\x00-\x1F]' if os.name == 'nt' else r'[<>:"|?*\x00-\x1F]'
        if re.search(invalid_chars, part):
            return False, None, f"Invalid characters in path: {path_str}"

    if not path.is_absolute():
        return False, None, f"Path is not absolute: {path_str}"

    existing_path = path
    while not existing_path.exists() and existing_path != existing_path.parent:
        existing_path = existing_path.parent

    if not existing_path.exists():
        return False, None, f"Path does not exist: {path_str}"

    if not os.access(existing_path, os.W_OK):
        return False, None, f"Path is not writable: {path_str}"

    abs_path = os.path.abspath(path)
    return True, abs_path, f"Valid directory: {abs_path}"

def validate_filename(filename_str: str) -> str:
    """
    Clean a filename by removing any directory parts, invalid characters,
    and known file extensions. Returns an empty string if the filename is empty.
    """
    if not filename_str:
        return ""

    filename = os.path.basename(filename_str.strip()).strip()
    known_extensions = {
        '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.png', '.jpg', '.jpeg',
        '.gif', '.bmp', '.tiff', '.csv', '.json', '.xml', '.html', '.htm', '.zip',
        '.tar', '.gz', '.rar', '.7z', '.exe', '.dll', '.py', '.java', '.c', '.cpp',
        '.js', '.css', '.md', '.ini', '.log', '.mov', '.mp4', '.mp3', '.wav', ".dcm",
        ".nii", ".nii.gz", ".npy", ".npz", ".mat", ".mha", ".mhd", ".stl", ".obj",
    }
    root, ext = os.path.splitext(filename)
    if ext.lower() in known_extensions:
        filename = root

    if not filename.strip():
        return ""

    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]' if os.name == 'nt' else r'[<>:"|?*\x00-\x1F]'
    filename = re.sub(invalid_chars, "", filename)
    return filename[:255]

def regex_find_dose_and_fractions(roi_name: str) -> Dict[str, Optional[Union[float, int]]]:
    """
    Extract dose (in cGy) and fraction count from an ROI name using regular expressions.

    Returns a dictionary with keys 'dose' and 'fractions'.
    """
    dose_pattern = r'(\d+\.?\d*)(gy|Gy|GY|cGy|CGY|cGY)?'
    # Broaden the fraction_pattern to capture expressions like "in 35 fx"
    fraction_pattern = r'(\d+)\s*(fx|FX|f|F|x|X)?\.?$'
    in_fraction_pattern = r'in\s*(\d+)\s*(fx|FX|f|F|x|X)\.?'
    
    # Initialize dose, extract, and convert to cGy
    dose: Optional[float] = None
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
    fractions_match = re.search(in_fraction_pattern, roi_name, re.IGNORECASE)
    fractions: Optional[int] = int(fractions_match.group(1)) if fractions_match else None
    if fractions is None:
        fractions_match = re.search(fraction_pattern, roi_name, re.IGNORECASE)
        fractions = int(fractions_match.group(1)) if fractions_match else None
        
    # Reasonable limits for fractions
    if fractions is not None and (fractions > 46 or (dose is not None and (fractions < 10 and dose > 5500))): 
        fractions = None
        
    return {'dose': dose, 'fractions': fractions}

def check_for_valid_dicom_string(input_string: str) -> bool:
    """Return True if the input string meets DICOM character standards."""
    valid_chars = set(string.ascii_letters + string.digits + string.punctuation + string.whitespace)
    valid_chars.remove('\\')  # Remove backslash
    control_chars = {chr(i) for i in range(32)}  # ASCII control characters
    valid_chars -= control_chars  # Exclude control characters
    return all(char in valid_chars for char in input_string)

def struct_name_priority_key(mask_name: str) -> Tuple[int, str]:
    """Return a sorting key (priority, original name) for a structure name."""
    lower = mask_name.lower()
    if lower.startswith('ptv'):
        return 0, mask_name
    elif lower.startswith('ctv'):
        return 1, mask_name
    elif lower.startswith('gtv'):
        return 2, mask_name
    elif lower.startswith('bolus'):
        return 3, mask_name
    elif 'prv' in lower:
        return 4, mask_name
    return 5, mask_name

def find_reformatted_mask_name(
    mask_name: str,
    mask_type: str,
    combo_mask_names: List[str],
    organ_name_matching_dict: Dict[str, List[str]],
    unmatched_name: str
) -> str:
    """
    Reformat a mask name using its type, a list of combined mask names, and an organ alias dictionary.
    """
    reformatted = re.sub(r'(new)', '', format_name(mask_name, lowercase=True), flags=re.IGNORECASE)
    reformatted_type = format_name(mask_type, lowercase=True)

    if reformatted_type == "external":
        return "External"

    if (re.search(r'^(old|donotuse|dontuse|dnu|skip|ignore|testing)', reformatted, re.IGNORECASE) or
        ("test" in reformatted and not re.search(r'^(testis|teste|testic|testa|testo)', reformatted, re.IGNORECASE))):
        return unmatched_name
    
    # Sometimes, a mask is named 'External' but it is not *the* external structure...
    if reformatted == "external": 
        return "Body"
    
    if not any([reformatted.startswith(x) for x in ["w", "x", "y", "z"]]):
        if (
            reformatted.startswith("ptv") and
            not reformatted.startswith("ptvall") and
            not any([reformatted.endswith(x) for x in ["opti", "eval", "dvh", "planning", "temp", "test", "max", "cool", "ev", "mm", "cm", "exp"]])
            ):
            return "PTV"
        
        if (
            reformatted.startswith("ctv") and
            not any([reformatted.endswith(x) for x in ["temp", "test"]])
            ):
            return "CTV"
        
        if (
            reformatted.startswith("itv") and
            not any([reformatted.endswith(x) for x in ["temp", "test"]])
            ):
            return "ITV"
        
        if (
            reformatted.startswith("gtv") and
            not any([reformatted.endswith(x) for x in ["temp", "test"]])
            ):
            return "GTV"
        
        for absolute_mask_name in combo_mask_names:
            if reformatted == format_name(absolute_mask_name, lowercase=True):
                return absolute_mask_name
    
    for support in [
        "Z1-Bridge", "Z2a-Bridge", "Z2b-Bridge", "Z3-Bridge", "Z4-Couch Support", 
        "Z5-Hard-plate", "Z6-Couch Support", "Z7-Couch Support", "Z8-Mattress", 
        "Z10-Couch Support"
    ]:
        if format_name(support, lowercase=True) in reformatted:
            return support
    
    for key, names in organ_name_matching_dict.items():
        for item in names:
            if reformatted == format_name(item, lowercase=True):
                return key
    
    return unmatched_name

def find_disease_site(
    plan_label: Optional[str],
    plan_name: Optional[str],
    struct_names: Union[str, List[str], None]
) -> str:
    """
    Determine the disease site from plan label, plan name, and structure names.
    Returns a site code or 'SELECT_MAIN_SITE' if no match is found.
    """
    names_to_check: List[str] = []
    if plan_label:
        names_to_check.append(format_name(str(plan_label), uppercase=True))
    if plan_name:
        names_to_check.append(format_name(str(plan_name), uppercase=True))
    if struct_names:
        if isinstance(struct_names, str):
            struct_names = [struct_names]
        names_to_check.extend(format_name(str(x), uppercase=True) for x in struct_names)
    
    for name in names_to_check:
        if name is None:
            continue
        if any([sub in name for sub in ["ABD",]]):
            return "ABDOMEN"
        if any([sub in name for sub in ["ADR",]]):
            return "ADRENAL"
        if any([sub in name for sub in ["BLAD",]]):
            return "BLADDER"
        if any([sub in name for sub in ["BONE", "RIB", "SCAP", "STERN", "ILIUM", "FEMUR"]]):
            return "BONE"
        if any([sub in name for sub in ["BRAI",]]):
            return "BRAIN"
        if any([sub in name for sub in ["BREA", "BRST"]]):
            return "BREAST"
        if any([sub in name for sub in ["CW", "CHST", "CHEST"]]):
            return "CHESTWALL"
        if any([sub in name for sub in ["CSI",]]):
            return "CSI"
        if any([sub in name for sub in ["ESO", "ESP"]]):
            return "ESOPHAGUS"
        if any([sub in name for sub in ["STOM", "STM", "BOW", "SMBW", "LGBW"]]):
            return "GI"
        if any([sub in name for sub in ["URET",]]):
            return "GU"
        if any([sub in name for sub in ["GYN", "UTER", "OVAR", "CERVIX", "VAG", "VULV"]]):
            return "GYN"
        if any([sub in name for sub in ["HEART", "HRT"]]):
            return "HEART"
        if any([sub in name for sub in ["HEAD", "NECK", "HN", "PAR", "LARY", "ORAL", "MAND", "NASO", "PHAR", "NASAL", "SALIV", "TON", "OPX", "HPX", "BOT", "SINUS", "PALAT"]]):
            return "HN"
        if any([sub in name for sub in ["KID",]]):
            return "KIDNEY"
        if any([sub in name for sub in ["LIV",]]):
            return "LIVER"
        if any([sub in name for sub in ["LNG", "LUNG", "HEMITHOR"]]):
            return "LUNG"
        if any([sub in name for sub in ["LYM",]]):
            return "LYMPHOMA"
        if any([sub in name for sub in ["MED",]]):
            return "MEDIASTINUM"
        if any([sub in name for sub in ["PAN",]]):
            return "PANCREAS"
        if any([sub in name for sub in ["PLV", "PELV", "ANUS"]]):
            return "PELVIS"
        if any([sub in name for sub in ["PROS", "PRS", "FOSSA"]]):
            return "PROSTATE"
        if any([sub in name for sub in ["RECT", "RCT"]]):
            return "RECTUM"
        if any([sub in name for sub in ["SARC",]]):
            return "SARCOMA"
        if any([sub in name for sub in ["SKIN",]]):
            return "SKIN"
        if any([sub in name for sub in ["SPINE", "SPN", "VER"]]):
            return "SPINE"
        if any([sub in name for sub in ["TBI",]]):
            return "TBI"
    
    return "SELECT_MAIN_SITE"

def verify_roi_goals_format(roi_goals_string: str) -> Tuple[bool, List[str]]:
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
    errors: List[str] = []
    if not roi_goals_string or not isinstance(roi_goals_string, str):
        errors.append(f"ROI goals must be a string, but received: {roi_goals_string}.")
        return False, errors
    
    try:
        roi_goals = json.loads(roi_goals_string)
    except json.JSONDecodeError:
        errors.append(f"Invalid JSON string; could not convert to a dictionary: {roi_goals_string} (type {type(roi_goals_string)}).")
        return False, errors
    
    if not isinstance(roi_goals, dict):
        errors.append(f"ROI goals must be a dictionary, but found: {roi_goals}.")
        return False, errors
    
    # Regular expressions for general format checks
    key_pattern = re.compile(r"^(V|D|DC|CV|CI)_(\d+(\.\d+)?)_(cGy|Gy|%|cc)$")
    value_pattern = re.compile(r"^(>|>=|<|<=|=)_(\d+(\.\d+)?)_(cGy|Gy|%|cc)$")
    
    # Specific rules for each metric
    key_rules: Dict[str, Any] = {
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
            errors.append(f"ROI goal keys must be strings, but received: {key}.")
            continue
        
        # Validate key format
        match = key_pattern.match(key)
        if match:
            metric, _, _, key_unit = match.groups()
        elif key in {"MAX", "MEAN", "MIN"}:
            metric = key
            key_unit = None
        else:
            errors.append(
                f"Key format invalid for '{key}'. Expected format: {{metric}}_{{value}}_{{unit}} "
                f"with metric in V, D, DC, CV, CI, MAX, MEAN, MIN."
            )
            continue
        
        # Check specific rules for the metric
        rules = key_rules.get(metric)
        if rules:
            if rules.get("allowed_ending"):
                # Validate key unit
                allowed_endings = rules.get("allowed_endings", [rules.get("allowed_ending")])
                if key_unit not in allowed_endings:
                    errors.append(f"For key '{key}', {metric} must end in one of {', '.join(allowed_endings)}; got '{key_unit}'.")
                    continue
            
            # Validate value format
            if not isinstance(values, list):
                errors.append(f"Values for key '{key}' must be a list, but received: {values}.")
                continue
            
            # Validate CI values
            if metric == "CI":
                try:
                    if not all(isinstance(val, str) for val in values) or not all(isinstance(float(val), (int, float)) for val in values):
                        errors.append(f"For key '{key}', all values must be strings convertible to numbers; received: {values}.")
                        continue
                except ValueError:
                    errors.append(f"For key '{key}', all values must be convertible to numbers; received: {values}.")
                    continue
                # No further checks needed for CI values
                continue
            
            for value in values:
                if not value_pattern.match(value):
                    errors.append(f"Value format invalid for key '{key}': '{value}'. Expected format: {{comparison}}_{{value}}_{{unit}}.")
                    continue
                
                # Validate value unit
                value_unit = value.split("_")[-1]
                if value_unit not in rules["value_endings"]:
                    errors.append(f"For key '{key}', {metric} values must end in one of {', '.join(rules['value_endings'])}; got '{value_unit}'.")
    
    # If there are no errors, the format is valid
    return len(errors) == 0, errors

def parse_struct_goal(
    struct_name: str,
    struct_goal_type: str,
    struct_goal_value: str,
    total_organ_volume: float,
    rx_dose: float
) -> Optional[Tuple[str, float, float]]:
    """
    Parse a structure goal string to extract its constraint type and compute corresponding metrics.
    
    Returns a tuple (goal_type, spare_volume, spare_dose) or None if parsing fails.
    """
    split_goaltype = struct_goal_type.split("_")
    split_goalvalue = struct_goal_value.split("_")
    goal_type = split_goaltype[0]
    goal_sign = split_goalvalue[0]
    
    # Max/Mean/Min: goaltype must not have any units, and goalvalue must have units of cGy or %
    if (
        any([goal_type == x for x in ["MAX", "MEAN", "MIN"]]) and 
        (
            len(split_goaltype) != 1 or 
            len(split_goalvalue) != 3 or 
            (split_goalvalue[2] != "%" and split_goalvalue[2] != "cGy")
        )
    ):
        logger.error(
            msg=(
                f"Structure {struct_name}: goal type '{struct_goal_type}' and value '{struct_goal_value}' "
                f"do not meet format requirements (parts: {len(split_goaltype)}, {len(split_goalvalue)}, "
                f"unit: {split_goalvalue[2]})."
            )
        )
        return None
    
    # CI: goaltype must have units of cGy, goalvalue must be a float or int
    if (
        any([goal_type == x for x in ["CI"]]) and 
        (
            len(split_goaltype) != 3 or 
            split_goaltype[2] != "cGy" or 
            len(split_goalvalue) != 1
        )
    ):
        logger.error(
            msg=(
                f"Structure {struct_name}: goal type '{struct_goal_type}' and value '{struct_goal_value}' "
                f"do not meet format requirements (parts: {len(split_goaltype)}, {len(split_goalvalue)})."
            )
        )
        return None
    
    # DC/D: goaltype must have units of cc or %, goalvalue must have units of cGy or %
    if (
        any([goal_type == x for x in ["DC", "D"]]) and 
        (
            len(split_goaltype) != 3 or 
            (split_goaltype[2] != "cc" and split_goaltype[2] != "%") or 
            len(split_goalvalue) != 3 or 
            (split_goalvalue[2] != "%" and split_goalvalue[2] != "cGy")
        )
    ):
        logger.error(
            msg=(
                f"Structure {struct_name}: goal type '{struct_goal_type}' and value '{struct_goal_value}' "
                f"do not meet format requirements (parts: {len(split_goaltype)}, {len(split_goalvalue)}, "
                f"unit: {split_goalvalue[2]})."
            )
        )
        return None
    
    # CV: goaltype must have units of cGy, goalvalue must have units of cc or %
    if (
        any([goal_type == x for x in ["CV"]]) and 
        (
            len(split_goaltype) != 3 or 
            split_goaltype[2] != "cGy" or 
            len(split_goalvalue) != 3 or 
            (split_goalvalue[2] != "%" and split_goalvalue[2] != "cc")
        )
    ):
        logger.error(
            msg=(
                f"Structure {struct_name}: goal type '{struct_goal_type}' and value '{struct_goal_value}' "
                f"do not meet format requirements (parts: {len(split_goaltype)}, {len(split_goalvalue)}, "
                f"unit: {split_goalvalue[2]})."
            )
        )
        return None
    
    # V: goaltype must have units of cGy or %, goalvalue must have units of % or cc
    if (
        any([goal_type == x for x in ["V"]]) and 
        (
            len(split_goaltype) != 3 or 
            (split_goaltype[2] != "%" and split_goaltype[2] != "cGy") or 
            len(split_goalvalue) != 3 or 
            (split_goalvalue[2] != "%" and split_goalvalue[2] != "cc")
        )
    ):
        logger.error(
            msg=(
                f"Structure {struct_name}: goal type '{struct_goal_type}' and value '{struct_goal_value}' "
                f"do not meet format requirements (parts: {len(split_goaltype)}, {len(split_goalvalue)}, "
                f"unit: {split_goalvalue[2]})."
            )
        )
        return None
    
    spare_volume: Optional[float] = None
    spare_dose: Optional[float] = None
    
    if ">" in goal_sign:
        logger.warning(f"Structure {struct_name} has a goal sign of >, which is not yet supported. Omitting this goal.")
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
        logger.warning(f"Structure {struct_name} has a MIN goal type, which is not yet supported. Omitting this goal.")
        return None
    
    elif goal_type == "CI":
        logger.warning(f"Structure {struct_name} has a CI goal type, which is not yet supported. Omitting this goal.")
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
        logger.error(
            msg=(
                f"Structure {struct_name} could not be parsed: struct_goal_type: {struct_goal_type}, "
                f"struct_goal_value: {struct_goal_value}, goal type: {goal_type}, spare_volume: {spare_volume}, "
                f"spare_dose: {spare_dose}. Omitting this goal."
            )
        )
        return None
    
    return goal_type, spare_volume, spare_dose
