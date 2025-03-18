import pydicom
from pydicom.datadict import keyword_for_tag
from utils.general_utils import safe_type_conversion, get_traceback

def convert_VR_string_to_python_type(vr):
    """
    Convert a DICOM Value Representation (VR) to its corresponding Python type or description.
    
    Args:
        vr (str): The DICOM VR code (e.g., "DS", "IS", "PN").
    
    Returns:
        str: Description of the Python type or purpose for the VR.
    """
    VR_TO_PYTHON_TYPE = {
    "AE": "Application Entity (str)",
    "AS": "Age String (str)",
    "AT": "Attribute Tag (tuple)",
    "CS": "Code String (str)",
    "DA": "Date (str)",
    "DS": "Decimal String (float)",
    "DT": "DateTime (str)",
    "FL": "Floating Point Single (float)",
    "FD": "Floating Point Double (float)",
    "IS": "Integer String (int)",
    "LO": "Long String (str)",
    "LT": "Long Text (str)",
    "OB": "Other Byte (bytes)",
    "OD": "Other Double (bytes)",
    "OF": "Other Float (bytes)",
    "OL": "Other Long (bytes)",
    "OW": "Other Word (bytes)",
    "PN": "Person Name (str)",
    "SH": "Short String (str)",
    "SL": "Signed Long (int)",
    "SQ": "Sequence of Items (Sequence)",
    "SS": "Signed Short (int)",
    "ST": "Short Text (str)",
    "TM": "Time (str)",
    "UI": "Unique Identifier (UID)",
    "UL": "Unsigned Long (int)",
    "UN": "Unknown (bytes)",
    "US": "Unsigned Short (int)",
    "UT": "Unlimited Text (str)"
	}
    return VR_TO_PYTHON_TYPE.get(vr, "Unknown (str)")

def safe_keyword_for_tag(tag):
    """
    Attempt to get the DICOM keyword for a tag, based on formatting from SITK like '0008|0000' or '(0008|0000)'.
    
    Args:
        tag (str or int): The DICOM tag as a string (e.g., "0008|0060") or integer.
    
    Returns:
        str or None: The DICOM keyword for the tag, or None if not found.
    """
    try:
        if isinstance(tag, str):
            # Remove any non-hexadecimal characters (parentheses, commas, spaces)
            tag_clean = tag.replace("(", "").replace(")", "").replace(",", "").replace(" ", "")
            if '|' in tag_clean:
                group_str, element_str = tag_clean.split('|')
                if len(group_str) == 4 and len(element_str) == 4:
                    group = int(group_str, 16)
                    element = int(element_str, 16)
                    tag_int = (group << 16) + element
                    keyword = keyword_for_tag(tag_int)
                    return keyword if keyword else None
            elif len(tag_clean) == 8 and all(c in '0123456789ABCDEFabcdef' for c in tag_clean):
                tag_int = int(tag_clean, 16)
                keyword = keyword_for_tag(tag_int)
                return keyword if keyword else None
        elif isinstance(tag, int):
            keyword = keyword_for_tag(tag)
            return keyword if keyword else None
        else:
            return None
    except Exception:
        return None

def read_dcm_file(file_path, stop_before_pixels=True, to_json_dict=False):
    """
    Read a DICOM file and optionally convert it to a JSON dictionary.
    
    Args:
        file_path (str): Path to the DICOM file.
        stop_before_pixels (bool): Whether to stop reading before loading pixel data.
        to_json_dict (bool): Whether to return the dataset as a JSON dictionary.
    
    Returns:
        pydicom.Dataset or dict or None: The DICOM dataset or JSON dictionary, or None if an error occurs.
    """
    try:
        ds = pydicom.dcmread(str(file_path).strip(), force=True, stop_before_pixels=stop_before_pixels)
        if to_json_dict:
            return ds.to_json_dict()
        return ds
    except Exception as e:
        print(f"Error reading file: {file_path}\n{get_traceback(e)}")
        return None

def dcm_value_conversion(value_list, value_type=str):
    """
    Safely convert DICOM values to a specified type.
    
    Args:
        value_list (list or any): The DICOM value(s) to convert.
        value_type (type or None): The target type for conversion (e.g., int, float).
    
    Returns:
        Converted value(s) or None if the conversion fails.
    """
    if not value_list:
        return None
    
    if not isinstance(value_list, list):
        return safe_type_conversion(value_list, value_type) if value_type is not None else value_list
    
    if len(value_list) == 1:
        return safe_type_conversion(value_list[0], value_type) if value_type is not None else value_list[0]
    
    return [safe_type_conversion(x, value_type) for x in value_list] if value_type is not None else value_list

def get_tag_values(last_dict, tag=None):
    """
    Retrieve and convert values for a specific DICOM tag.
    
    Args:
        last_dict (dict): The DICOM data dictionary.
        tag (str or None): The specific tag to extract (optional).
    
    Returns:
        Converted tag values or the raw value list.
    """
    if tag is None:
        tag_dict = last_dict
    else:
        tag_dict = last_dict.get(tag, {})
    if not isinstance(tag_dict, dict):
        return tag_dict
    
    tag_vr = tag_dict.get("vr")
    if tag_vr == "SQ":
        return tag_dict.get("Value", [])
    elif tag_vr in ["DS", "FL", "FD"]:
        return dcm_value_conversion(tag_dict.get("Value"), float)
    elif tag_vr in ["IS", "SL", "SS", "SV", "UL", "US", "UV"]:
        return dcm_value_conversion(tag_dict.get("Value"), int)
    elif tag_vr in ["AE", "AS", "CS", "DA", "DT", "LO", "LT", "SH", "ST", "TM", "UC", "UI", "UR", "UT"]:
        return dcm_value_conversion(tag_dict.get("Value"), str)
    elif tag_vr == "PN":
        return dcm_value_conversion(tag_dict.get("Value"), None)
    else: 
        # Can also check these tag_vr : ["AT", "OB", "OD", "OF", "OL", "OV", "OW", "UN"]
        return tag_dict.get("Value")


