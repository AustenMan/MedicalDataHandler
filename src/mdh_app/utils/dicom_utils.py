from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Dict, Optional, Union


import pydicom
from pydicom.datadict import keyword_for_tag


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def convert_VR_string_to_python_type(vr: str) -> str:
    """Map DICOM Value Representation code to Python type description."""
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
    """Retrieve DICOM keyword for tag (string or integer format)."""
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


def get_first_ref_series_uid(ds: pydicom.Dataset) -> str:
    """Retrieve the first Referenced Series Instance UID from the dataset."""
    matched_ref_series_uid = ""
    try:
        for frame_item in ds.get("ReferencedFrameOfReferenceSequence", []):
            for study_item in frame_item.get("RTReferencedStudySequence", []):
                for series_item in study_item.get("RTReferencedSeriesSequence", []):
                    series_uid = series_item.get("SeriesInstanceUID", "")
                    if series_uid:
                        found_series_uid = str(series_uid).strip()
                        if not matched_ref_series_uid:
                            matched_ref_series_uid = found_series_uid
                        elif matched_ref_series_uid != found_series_uid:
                            logger.warning(
                                f"Multiple SeriesInstanceUIDs found in structure set! "
                                f"First one encountered: {matched_ref_series_uid}, another one found: {found_series_uid}. "
                                f"Using the first one encountered."
                            )
        if not matched_ref_series_uid:
            logger.error("No Referenced Series Instance UID found in RT Structure Set.")
    except Exception as e:
        logger.error("Error retrieving Referenced Series Instance UID.", exc_info=True)
    return matched_ref_series_uid


def get_first_ref_struct_sop_uid(ds: pydicom.Dataset) -> str:
    """Retrieve the first Referenced Structure Set SOP Instance UID from an RT Plan dataset."""
    matched_ref_rts_sop_uid = ""
    try:
        for struct_ds in ds.get("ReferencedStructureSetSequence", []):
            found_ref_rts_sop_uid = struct_ds.get("ReferencedSOPInstanceUID", None)
            if found_ref_rts_sop_uid and not matched_ref_rts_sop_uid:
                matched_ref_rts_sop_uid = found_ref_rts_sop_uid
            elif found_ref_rts_sop_uid and matched_ref_rts_sop_uid != found_ref_rts_sop_uid:
                logger.warning(
                    f"Multiple Referenced Structure Set SOP Instance UIDs found in the plan file! "
                    f"First one encountered: {matched_ref_rts_sop_uid}, another one found: {found_ref_rts_sop_uid}. "
                    f"Using the first one encountered."
                )
        if not matched_ref_rts_sop_uid:
            logger.error("No Referenced Structure Set SOP Instance UID found in the plan file.")
    except Exception as e:
        logger.error("Error retrieving Referenced Structure Set SOP Instance UID.", exc_info=True)
    return matched_ref_rts_sop_uid


def get_first_ref_plan_sop_uid(ds: pydicom.Dataset) -> str:
    """Retrieve the first Referenced SOP Instance UID from an RT Dose dataset."""
    matched_ref_rtp_sop_uid = ""
    try:
        for plan_ds in ds.get("ReferencedRTPlanSequence", []):
            found_ref_rtp_sop_uid = plan_ds.get("ReferencedSOPInstanceUID", None)
            if found_ref_rtp_sop_uid and not matched_ref_rtp_sop_uid:
                matched_ref_rtp_sop_uid = found_ref_rtp_sop_uid
            elif found_ref_rtp_sop_uid and matched_ref_rtp_sop_uid != found_ref_rtp_sop_uid:
                logger.warning(
                    f"Multiple Referenced RT Plan SOP Instance UIDs found in the dose file! "
                    f"First one encountered: {matched_ref_rtp_sop_uid}, another one found: {found_ref_rtp_sop_uid}. "
                    f"Using the first one encountered."
                )
        if not matched_ref_rtp_sop_uid:
            logger.error("No Referenced RT Plan SOP Instance UID found in the dose file.")
    except Exception as e:
        logger.error("Error retrieving Referenced RT Plan SOP Instance UID.", exc_info=True)
    return matched_ref_rtp_sop_uid


def get_first_num_fxns_planned(ds: pydicom.Dataset) -> Optional[int]:
    """Retrieve the Number of Fractions Planned from the RT Plan dataset."""    
    matched_num_fxns_planned: Optional[int] = None
    try:
        for fraction_group_ds in ds.get("FractionGroupSequence", []):
            try:
                found_num_fxns_planned = int(fraction_group_ds.get("NumberOfFractionsPlanned", None))
            except (TypeError, ValueError):
                continue
            if matched_num_fxns_planned is None:
                matched_num_fxns_planned = found_num_fxns_planned
            elif matched_num_fxns_planned != found_num_fxns_planned:
                logger.warning(
                    f"Multiple Number of Fractions Planned found in RT Plan! "
                    f"First one encountered: {matched_num_fxns_planned}, another one found: {found_num_fxns_planned}. "
                    f"Using the first one encountered."
                )
        if matched_num_fxns_planned is None:
            logger.info("No Number of Fractions Planned found in RT Plan.")
    except Exception as e:
        logger.error("Error retrieving Number of Fractions Planned.", exc_info=True)
    return matched_num_fxns_planned


def get_first_ref_beam_number(ds: pydicom.Dataset) -> Optional[int]:
    """Retrieve the first Referenced Beam Number from the RT Plan dataset."""
    try:
        for ref_fxn_grp_ds in ds.get("ReferencedFractionGroupSequence", []):
            for ref_beam_ds in ref_fxn_grp_ds.get("ReferencedBeamSequence", []):
                try:
                    return int(ref_beam_ds.get("ReferencedBeamNumber"))
                except (TypeError, ValueError):
                    continue
    except Exception as e:
        logger.error("Error retrieving Referenced Beam Number.", exc_info=True)
    return None


def read_dcm_file(
    file_path: str,
    **kwargs
) -> Optional[pydicom.Dataset]:
    """Read a DICOM file safely with optional arguments passed to pydicom.dcmread.

    Args:
        file_path: Path to the DICOM file.
        **kwargs: Additional keyword arguments for `pydicom.dcmread`,
                  e.g., stop_before_pixels=True, force=True.

    Returns:
        A pydicom.Dataset if successful, otherwise None.
    """
    try:
        return pydicom.dcmread(str(file_path).strip(), **kwargs)
    except Exception as e:
        logger.error(f"Failed to read file '{file_path}'.", exc_info=True)
        return None


def get_ds_tag_value(
    dicom_data: pydicom.Dataset, 
    tag: Union[int, str], 
    reformat_str: bool = False
) -> Optional[str]:
    """Safely retrieve DICOM tag value with optional string formatting."""
    element = dicom_data.get(tag)
    if element and element.value:
        value: str = str(element.value).strip()
        if reformat_str:
            value = value.replace("^", "_").replace(" ", "_")
        return value
    return None


def get_first_available_tag(ds, tags, reformat_str: bool = False) -> Optional[str]:
    for tag in tags:
        val = get_ds_tag_value(ds, tag, reformat_str=reformat_str)
        if val not in (None, ""):
            return val
    return None

