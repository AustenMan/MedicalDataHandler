import logging
import pydicom
from typing import Any, Dict, List, Optional, Union
from pydicom.datadict import keyword_for_tag

from mdh_app.utils.general_utils import safe_type_conversion, get_traceback

logger = logging.getLogger(__name__)

def convert_VR_string_to_python_type(vr: str) -> str:
    """
    Map a DICOM Value Representation (VR) code to a description of its corresponding Python type.

    Args:
        vr: A DICOM VR code (e.g., "DS", "IS", "PN").

    Returns:
        A string describing the Python type or intended purpose for the VR.
    """
    VR_TO_PYTHON_TYPE: Dict[str, str] = {
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

def safe_keyword_for_tag(tag: Union[str, int]) -> Optional[str]:
    """
    Retrieve the DICOM keyword corresponding to a tag.

    The tag may be provided as a string (formatted like "0008|0060" or "(0008|0060)") or an integer.

    Args:
        tag: The DICOM tag as a string or integer.

    Returns:
        The associated DICOM keyword if found, otherwise None.
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

def read_dcm_file(
    file_path: str, 
    stop_before_pixels: bool = True, 
    to_json_dict: bool = False
) -> Optional[Union[pydicom.Dataset, Dict[str, Any]]]:
    """
    Read a DICOM file and optionally return its content as a JSON dictionary.

    Args:
        file_path: Path to the DICOM file.
        stop_before_pixels: If True, avoid loading pixel data.
        to_json_dict: If True, convert the dataset to a JSON dictionary.

    Returns:
        The DICOM dataset (or its JSON dictionary) if read successfully, otherwise None.
    """
    try:
        ds = pydicom.dcmread(str(file_path).strip(), force=True, stop_before_pixels=stop_before_pixels)
        return ds.to_json_dict() if to_json_dict else ds
    except Exception as e:
        logger.error(f"Failed to read file '{file_path}'." + get_traceback(e))
        return None

def dcm_value_conversion(
    value_list: Any, 
    value_type: Optional[type] = str
) -> Optional[Union[Any, List[Any]]]:
    """
    Convert DICOM values safely to a specified type.

    Args:
        value_list: A single value or a list of values from a DICOM element.
        value_type: The target type for conversion (e.g., int, float). If None, no conversion is applied.

    Returns:
        The converted value(s) or None if conversion is not possible.
    """
    if not value_list:
        return None

    if not isinstance(value_list, list):
        return safe_type_conversion(value_list, value_type) if value_type is not None else value_list

    if len(value_list) == 1:
        return safe_type_conversion(value_list[0], value_type) if value_type is not None else value_list[0]

    return [safe_type_conversion(x, value_type) for x in value_list] if value_type is not None else value_list

def get_dict_tag_values(
    last_dict: Dict[str, Any], 
    tag: Optional[str] = None
) -> Any:
    """
    Retrieve and convert values for a specific DICOM tag from a dictionary.

    Args:
        last_dict: The dictionary containing DICOM tag data.
        tag: Specific tag key to extract. If None, the entire dictionary is used.

    Returns:
        The converted value(s) for the tag or the raw value if conversion rules do not apply.
    """
    tag_dict: Any = last_dict if tag is None else last_dict.get(tag, {})
    if not isinstance(tag_dict, dict):
        return tag_dict

    tag_vr: Optional[str] = tag_dict.get("vr")
    if tag_vr == "SQ":
        return tag_dict.get("Value", [])
    elif tag_vr in {"DS", "FL", "FD"}:
        return dcm_value_conversion(tag_dict.get("Value"), float)
    elif tag_vr in {"IS", "SL", "SS", "SV", "UL", "US", "UV"}:
        return dcm_value_conversion(tag_dict.get("Value"), int)
    elif tag_vr in {"AE", "AS", "CS", "DA", "DT", "LO", "LT", "SH", "ST", "TM", "UC", "UI", "UR", "UT"}:
        return dcm_value_conversion(tag_dict.get("Value"), str)
    elif tag_vr == "PN":
        return dcm_value_conversion(tag_dict.get("Value"), None)
    else: # Can also check these tag_vr : ["AT", "OB", "OD", "OF", "OL", "OV", "OW", "UN"]
        return tag_dict.get("Value")

def get_ds_tag_value(
    dicom_data: pydicom.Dataset, 
    tag: Union[int, str], 
    reformat_str: bool = False
) -> Optional[str]:
    """
    Safely retrieve the value of a specified DICOM tag from a dataset.

    Args:
        dicom_data: The pydicom dataset.
        tag: The tag to retrieve, either as an integer or in string format.
        reformat_str: If True, replace '^' and spaces with underscores.

    Returns:
        The tag's value as a string (after optional reformatting), or None if unavailable.
    """
    element = dicom_data.get(tag)
    if element and element.value:
        value: str = str(element.value).strip()
        if reformat_str:
            value = value.replace("^", "_").replace(" ", "_")
        return value
    return None
