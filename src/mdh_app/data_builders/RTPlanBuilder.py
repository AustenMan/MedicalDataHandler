from __future__ import annotations


import logging
from os.path import exists
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from concurrent.futures import as_completed, Future


from mdh_app.managers.shared_state_manager import should_exit
from mdh_app.utils.dicom_utils import read_dcm_file, get_dict_tag_values, safe_keyword_for_tag


if TYPE_CHECKING:
    from typing import TypeAlias
    from mdh_app.managers.shared_state_manager import SharedStateManager
    
    # Type aliases for clearer code documentation
    BeamNumber: TypeAlias = Union[int, str]
    ROINumber: TypeAlias = Union[int, str]
    DeviceType: TypeAlias = str
    TagValue: TypeAlias = str


logger = logging.getLogger(__name__)


class RTPDicomTags:
    """DICOM tags for RT Plan processing."""
    
    # Plan-level tags
    RT_PLAN_LABEL = "300A0002"
    RT_PLAN_NAME = "300A0003"
    RT_PLAN_DESCRIPTION = "300A0004"
    RT_PLAN_DATE = "300A0006"
    RT_PLAN_TIME = "300A0007"
    
    # Approval tags
    APPROVAL_STATUS = "300E0002"
    REVIEW_DATE = "300E0004"
    REVIEW_TIME = "300E0005"
    REVIEWER_NAME = "300E0008"
    
    # Dose reference tags
    DOSE_REFERENCE_SEQUENCE = "300A0010"
    DELIVERY_MAXIMUM_DOSE = "300A0023"
    TARGET_PRESCRIPTION_DOSE = "300A0026"
    
    # Fraction group tags
    FRACTION_GROUP_SEQUENCE = "300A0070"
    NUMBER_OF_FRACTIONS_PLANNED = "300A0078"
    NUMBER_OF_BEAMS = "300A0080"
    REFERENCED_BEAM_SEQUENCE = "300C0004"
    REFERENCED_BEAM_NUMBER = "300C0006"
    BEAM_DOSE = "300A0084"
    BEAM_METERSET_VALUE = "300A0086"
    
    # Patient setup tags
    PATIENT_SETUP_SEQUENCE = "300A0180"
    PATIENT_SETUP_NUMBER = "300A0182"
    PATIENT_POSITION = "00185100"
    SETUP_TECHNIQUE = "300A01B0"
    
    # Beam sequence tags
    BEAM_SEQUENCE = "300A00B0"
    BEAM_NUMBER = "300A00C0"
    BEAM_NAME = "300A00C2"
    BEAM_DESCRIPTION = "300A00C3"
    BEAM_TYPE = "300A00C4"
    RADIATION_TYPE = "300A00C6"
    TREATMENT_DELIVERY_TYPE = "300A00CE"
    
    # Equipment tags
    MANUFACTURERS_MODEL_NAME = "00081090"
    DEVICE_SERIAL_NUMBER = "00181000"
    TREATMENT_MACHINE_NAME = "300A00B2"
    PRIMARY_DOSIMETER_UNIT = "300A00B3"
    SOURCE_AXIS_DISTANCE = "300A00B4"
    
    # Beam limiting devices
    BEAM_LIMITING_DEVICE_SEQUENCE = "300A00B6"
    RT_BEAM_LIMITING_DEVICE_TYPE = "300A00B8"
    SOURCE_TO_BEAM_LIMITING_DEVICE_DISTANCE = "300A00BA"
    NUMBER_OF_LEAF_JAW_PAIRS = "300A00BC"
    LEAF_POSITION_BOUNDARIES = "300A00BE"
    LEAF_JAW_POSITIONS = "300A011C"
    
    # Control points
    CONTROL_POINT_SEQUENCE = "300A0111"
    CONTROL_POINT_INDEX = "300A0112"
    NOMINAL_BEAM_ENERGY = "300A0114"
    DOSE_RATE_SET = "300A0115"
    WEDGE_POSITION_SEQUENCE = "300A0116"
    BEAM_LIMITING_DEVICE_POSITION_SEQUENCE = "300A011A"
    GANTRY_ANGLE = "300A011E"
    GANTRY_ROTATION_DIRECTION = "300A011F"
    BEAM_LIMITING_DEVICE_ANGLE = "300A0120"
    PATIENT_SUPPORT_ANGLE = "300A0122"
    CUMULATIVE_METERSET_WEIGHT = "300A0134"
    
    # Accessories and modifiers
    WEDGE_SEQUENCE = "300A00D1"
    COMPENSATOR_SEQUENCE = "300A00E3"
    BLOCK_SEQUENCE = "300A00F4"
    APPLICATOR_SEQUENCE = "300A0107"
    
    # Referenced structures
    REFERENCED_DOSE_SEQUENCE = "300C0080"
    REFERENCED_BOLUS_SEQUENCE = "300C00B0"
    REFERENCED_SOP_CLASS_UID = "00081150"
    REFERENCED_SOP_INSTANCE_UID = "00081155"
    REFERENCED_ROI_NUMBER = "30060084"


class RTConstants:
    """Constants (e.g., ones used as values for DICOM tags)."""
    
    # Treatment delivery types
    TREATMENT_DELIVERY_TYPE = "TREATMENT"
    SETUP_DELIVERY_TYPE = "SETUP"
    
    # Beam types
    STATIC_BEAM = "STATIC"
    DYNAMIC_BEAM = "DYNAMIC"
    
    # Radiation types
    PHOTON = "PHOTON"
    ELECTRON = "ELECTRON"
    NEUTRON = "NEUTRON"
    PROTON = "PROTON"
    
    # Beam limiting device types
    DEVICE_TYPE_X = "X"
    DEVICE_TYPE_Y = "Y"
    DEVICE_TYPE_ASYMX = "ASYMX"
    DEVICE_TYPE_ASYMY = "ASYMY"
    DEVICE_TYPE_MLCX = "MLCX"
    DEVICE_TYPE_MLCY = "MLCY"
    
    # Wedge types
    WEDGE_TYPE_STATIC = "STATIC"
    WEDGE_TYPE_DYNAMIC = "DYNAMIC"
    WEDGE_TYPE_MOTORIZED = "MOTORIZED"
    
    # Rotation directions
    CLOCKWISE = "CW"
    COUNTERCLOCKWISE = "CC"
    
    # Dose conversion factor (Gy to cGy)
    GY_TO_CGY_FACTOR = 100


def _extract_fluence_mode_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> tuple[Optional[str], Optional[str]]:
    """Extract primary fluence mode and ID from beam sequence item."""
    primary_fluence_mode_sequence = get_dict_tag_values(beam_sequence_item, "30020050") or []
    primary_fluence_mode: Optional[str] = None
    primary_fluence_mode_id: Optional[str] = None
    
    for fluence_item in primary_fluence_mode_sequence:
        mode = get_dict_tag_values(fluence_item, "30020051")
        if mode and primary_fluence_mode is None:
            primary_fluence_mode = mode
        elif mode and primary_fluence_mode != mode:
            logger.warning(
                f"Multiple primary fluence modes found for beam #{beam_number}: "
                f"{primary_fluence_mode}, {mode}. Using the first one."
            )

        mode_id = get_dict_tag_values(fluence_item, "30020052")
        if mode_id and primary_fluence_mode_id is None:
            primary_fluence_mode_id = mode_id
        elif mode_id and primary_fluence_mode_id != mode_id:
            logger.warning(
                f"Multiple primary fluence mode IDs found for beam #{beam_number}: "
                f"{primary_fluence_mode_id}, {mode_id}. Using the first one."
            )
    
    return primary_fluence_mode, primary_fluence_mode_id


def _extract_beam_limiting_devices(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[str, Dict[str, Any]]:
    """
    Extract beam limiting device information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping device types to their configuration data
    """
    rt_beam_limiting_device_dict: Dict[str, Dict[str, Any]] = {}
    beam_limiting_device_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.BEAM_LIMITING_DEVICE_SEQUENCE) or []
    
    for device_item in beam_limiting_device_sequence:
        device_type = get_dict_tag_values(device_item, RTPDicomTags.RT_BEAM_LIMITING_DEVICE_TYPE)
        if device_type is None:
            continue
            
        if device_type in rt_beam_limiting_device_dict:
            logger.warning(
                f"Duplicate beam limiting device type found for beam #{beam_number}: "
                f"{device_type}. Skipping it."
            )
            continue

        rt_beam_limiting_device_dict[device_type] = {
            "source_to_beam_limiting_device_distance": get_dict_tag_values(
                device_item, RTPDicomTags.SOURCE_TO_BEAM_LIMITING_DEVICE_DISTANCE
            ),
            "number_of_leaf_or_jaw_pairs": get_dict_tag_values(
                device_item, RTPDicomTags.NUMBER_OF_LEAF_JAW_PAIRS
            ),
            "leaf_position_boundaries": get_dict_tag_values(
                device_item, RTPDicomTags.LEAF_POSITION_BOUNDARIES
            ),
        }
    
    return rt_beam_limiting_device_dict


def _extract_wedge_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[Any, Dict[str, Any]]:
    """
    Extract wedge information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping wedge numbers to their configuration data
    """
    wedge_dict: Dict[Any, Dict[str, Any]] = {}
    wedge_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.WEDGE_SEQUENCE) or []
    
    for wedge_item in wedge_sequence:
        wedge_number = get_dict_tag_values(wedge_item, "300A00D2")  # Wedge Number
        if wedge_number is None:
            continue
            
        if wedge_number in wedge_dict:
            logger.warning(
                f"Duplicate wedge number found for beam #{beam_number}: "
                f"{wedge_number}. Skipping it."
            )
            continue
        
        wedge_dict[wedge_number] = {
            "wedge_type": get_dict_tag_values(wedge_item, "300A00D3"),  # STATIC, DYNAMIC, or MOTORIZED
            "wedge_id": get_dict_tag_values(wedge_item, "300A00D4"),    # User-supplied identifier
            "wedge_angle": get_dict_tag_values(wedge_item, "300A00D5"), # In degrees
            "wedge_factor": get_dict_tag_values(wedge_item, "300A00D6"),
            "wedge_orientation": get_dict_tag_values(wedge_item, "300A00D8"),
            "source_to_wedge_tray_distance": get_dict_tag_values(wedge_item, "300A00DA"),
            "effective_wedge_angle": get_dict_tag_values(wedge_item, "300A00DE"), # In degrees
            "accessory_code": get_dict_tag_values(wedge_item, "300A00F9"),
        }
    
    return wedge_dict


def _extract_compensator_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[Any, Dict[str, Any]]:
    """
    Extract compensator information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping compensator numbers to their configuration data
    """
    compensator_dict: Dict[Any, Dict[str, Any]] = {}
    compensator_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.COMPENSATOR_SEQUENCE) or []
    
    for compensator_item in compensator_sequence:
        compensator_number = get_dict_tag_values(compensator_item, "300A00E4")  # Compensator Number
        if compensator_number is None:
            continue
            
        if compensator_number in compensator_dict:
            logger.warning(
                f"Duplicate compensator number found for beam #{beam_number}: "
                f"{compensator_number}. Skipping it."
            )
            continue
        
        compensator_dict[compensator_number] = {
            "material_id": get_dict_tag_values(compensator_item, "300A00E1"),
            "compensator_id": get_dict_tag_values(compensator_item, "300A00E5"),
            "source_to_compensator_tray_distance": get_dict_tag_values(compensator_item, "300A00E6"),
            "compensator_rows": get_dict_tag_values(compensator_item, "300A00E7"),
            "compensator_columns": get_dict_tag_values(compensator_item, "300A00E8"),
            "compensator_pixel_spacing": get_dict_tag_values(compensator_item, "300A00E9"),
            "compensator_position": get_dict_tag_values(compensator_item, "300A00EA"),
            "compensator_transmission_data": get_dict_tag_values(compensator_item, "300A00EB"),
            "compensator_thickness_data": get_dict_tag_values(compensator_item, "300A00EC"),
            "compensator_type": get_dict_tag_values(compensator_item, "300A00EE"),
            "compensator_tray_id": get_dict_tag_values(compensator_item, "300A00EF"),
            "accessory_code": get_dict_tag_values(compensator_item, "300A00F9"),
            "compensator_divergence": get_dict_tag_values(compensator_item, "300A02E0"),
            "compensator_mounting_position": get_dict_tag_values(compensator_item, "300A02E1"),
            "source_to_compensator_distance": get_dict_tag_values(compensator_item, "300A02E2"),
            "compensator_description": get_dict_tag_values(compensator_item, "300A02EB"),
            "tray_accessory_code": get_dict_tag_values(compensator_item, "300A0355"),
        }
    
    return compensator_dict


def _extract_block_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[Any, Dict[str, Any]]:
    """
    Extract block information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping block numbers to their configuration data
    """
    block_dict: Dict[Any, Dict[str, Any]] = {}
    block_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.BLOCK_SEQUENCE) or []
    
    for block_item in block_sequence:
        block_number = get_dict_tag_values(block_item, "300A00FC")  # Block Number
        if block_number is None:
            continue
            
        if block_number in block_dict:
            logger.warning(
                f"Duplicate block number found for beam #{beam_number}: "
                f"{block_number}. Skipping it."
            )
            continue
        
        block_dict[block_number] = {
            "material_id": get_dict_tag_values(block_item, "300A00E1"),
            "block_tray_id": get_dict_tag_values(block_item, "300A00F5"),
            "source_to_block_tray_distance": get_dict_tag_values(block_item, "300A00F6"),
            "block_type": get_dict_tag_values(block_item, "300A00F8"),
            "accessory_code": get_dict_tag_values(block_item, "300A00F9"),
            "block_divergence": get_dict_tag_values(block_item, "300A00FA"),
            "block_mounting_position": get_dict_tag_values(block_item, "300A00FB"),
            "block_name": get_dict_tag_values(block_item, "300A00FE"),
            "block_thickness": get_dict_tag_values(block_item, "300A0100"),
            "block_transmission": get_dict_tag_values(block_item, "300A0102"),
            "block_number_of_points": get_dict_tag_values(block_item, "300A0104"),
            "block_data": get_dict_tag_values(block_item, "300A0106"),
            "tray_accessory_code": get_dict_tag_values(block_item, "300A0355"),
        }
    
    return block_dict


def _extract_applicator_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[str, Dict[str, Any]]:
    """
    Extract applicator information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary containing applicator configuration data
    """
    applicator_dict: Dict[str, Dict[str, Any]] = {}
    applicator_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.APPLICATOR_SEQUENCE)
    
    if applicator_sequence:
        if len(applicator_sequence) != 1:
            logger.warning(
                f"Multiple applicators found in the sequence for beam #{beam_number}. "
                f"Using the first one."
            )
        
        applicator_geometry_sequence = get_dict_tag_values(applicator_sequence[0], "300A0431")
        if applicator_geometry_sequence and len(applicator_geometry_sequence) != 1:
            logger.warning(
                f"Multiple applicator geometries found in the sequence for beam #{beam_number}. "
                f"Using the first one."
            )
        
        applicator_dict["applicator"] = {
            "accessory_code": get_dict_tag_values(applicator_sequence[0], "300A00F9"),
            "applicator_id": get_dict_tag_values(applicator_sequence[0], "300A0108"),
            "applicator_type": get_dict_tag_values(applicator_sequence[0], "300A0109"),
            "applicator_description": get_dict_tag_values(applicator_sequence[0], "300A010A"),
            "applicator_aperture_shape": get_dict_tag_values(
                applicator_geometry_sequence[0], "300A0432"
            ) if applicator_geometry_sequence else None,
            "applicator_opening": get_dict_tag_values(
                applicator_geometry_sequence[0], "300A0433"
            ) if applicator_geometry_sequence else None,
            "applicator_opening_x": get_dict_tag_values(
                applicator_geometry_sequence[0], "300A0434"
            ) if applicator_geometry_sequence else None,
            "applicator_opening_y": get_dict_tag_values(
                applicator_geometry_sequence[0], "300A0435"
            ) if applicator_geometry_sequence else None,
            "source_to_applicator_mounting_position_distance": get_dict_tag_values(
                applicator_sequence[0], "300A010C"
            ),
        }
    
    return applicator_dict


def _extract_control_point_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[Any, Dict[str, Any]]:
    """
    Extract control point information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping control point indices to their configuration data
    """
    control_point_dict: Dict[Any, Dict[str, Any]] = {}
    control_point_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.CONTROL_POINT_SEQUENCE) or []
    
    for cp_item in control_point_sequence:
        cp_index = get_dict_tag_values(cp_item, RTPDicomTags.CONTROL_POINT_INDEX)
        if cp_index is None:
            continue
            
        if cp_index in control_point_dict:
            logger.warning(
                f"Duplicate control point index found for beam #{beam_number}: "
                f"{cp_index}. Skipping it."
            )
            continue
        
        # Extract wedge positions
        wedge_position_sequence = get_dict_tag_values(cp_item, RTPDicomTags.WEDGE_POSITION_SEQUENCE) or [{}]
        wedge_position_dict = {
            get_dict_tag_values(x, "300C00C0"): get_dict_tag_values(x, "300A0118")
            for x in wedge_position_sequence
            if get_dict_tag_values(x, "300C00C0") is not None
        }
        
        # Extract beam limiting device positions
        device_position_sequence = get_dict_tag_values(cp_item, RTPDicomTags.BEAM_LIMITING_DEVICE_POSITION_SEQUENCE) or [{}]
        beam_limiting_device_dict = {
            get_dict_tag_values(x, "300C00B8"): get_dict_tag_values(x, "300A011C")
            for x in device_position_sequence
            if get_dict_tag_values(x, "300C00B8") is not None
        }
        
        control_point_dict[cp_index] = {
            "nominal_beam_energy": get_dict_tag_values(cp_item, RTPDicomTags.NOMINAL_BEAM_ENERGY),
            "dose_rate_set": get_dict_tag_values(cp_item, RTPDicomTags.DOSE_RATE_SET),
            "wedge_position_dict": wedge_position_dict,
            "beam_limiting_device_dict": beam_limiting_device_dict,
            "gantry_angle": get_dict_tag_values(cp_item, RTPDicomTags.GANTRY_ANGLE),
            "gantry_rotation_direction": get_dict_tag_values(cp_item, RTPDicomTags.GANTRY_ROTATION_DIRECTION),
            "beam_limiting_device_angle": get_dict_tag_values(cp_item, RTPDicomTags.BEAM_LIMITING_DEVICE_ANGLE),
            "beam_limiting_device_rotation_direction": get_dict_tag_values(cp_item, "300A0121"),
            "patient_support_angle": get_dict_tag_values(cp_item, RTPDicomTags.PATIENT_SUPPORT_ANGLE),
            "patient_support_rotation_direction": get_dict_tag_values(cp_item, "300A0123"),
            "table_top_eccentric_axis_distance": get_dict_tag_values(cp_item, "300A0124"),
            "table_top_eccentric_angle": get_dict_tag_values(cp_item, "300A0125"),
            "table_top_eccentric_rotation_direction": get_dict_tag_values(cp_item, "300A0126"),
            "table_top_vertical_position": get_dict_tag_values(cp_item, "300A0128"),
            "table_top_longitudinal_position": get_dict_tag_values(cp_item, "300A0129"),
            "table_top_lateral_position": get_dict_tag_values(cp_item, "300A012A"),
            "isocenter_position": get_dict_tag_values(cp_item, "300A012C"),
            "surface_entry_point": get_dict_tag_values(cp_item, "300A012E"),
            "source_to_surface_distance": get_dict_tag_values(cp_item, "300A0130"),
            "source_to_external_contour_distance": get_dict_tag_values(cp_item, "300A0132"),
            "external_contour_entry_point": get_dict_tag_values(cp_item, "300A0133"),
            "cumulative_meterset_weight": get_dict_tag_values(cp_item, RTPDicomTags.CUMULATIVE_METERSET_WEIGHT),
            "table_top_pitch_angle": get_dict_tag_values(cp_item, "300A0140"),
            "table_top_pitch_rotation_direction": get_dict_tag_values(cp_item, "300A0142"),
            "table_top_roll_angle": get_dict_tag_values(cp_item, "300A0144"),
            "table_top_roll_rotation_direction": get_dict_tag_values(cp_item, "300A0146"),
            "gantry_pitch_angle": get_dict_tag_values(cp_item, "300A014A"),
            "gantry_pitch_rotation_direction": get_dict_tag_values(cp_item, "300A014C"),
        }
    
    return control_point_dict


def _extract_referenced_dose_data(beam_sequence_item: Dict[str, Any]) -> tuple[List[str], List[str]]:
    """
    Extract referenced dose information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        
    Returns:
        Tuple of (SOP Class UID list, SOP Instance UID list)
    """
    referenced_dose_SOPClassUID_list = []
    referenced_dose_SOPInstanceUID_list = []
    referenced_dose_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.REFERENCED_DOSE_SEQUENCE) or []
    
    for referenced_dose_sequence_item in referenced_dose_sequence:
        sop_class_uid = get_dict_tag_values(referenced_dose_sequence_item, RTPDicomTags.REFERENCED_SOP_CLASS_UID)
        if sop_class_uid is not None and sop_class_uid not in referenced_dose_SOPClassUID_list:
            referenced_dose_SOPClassUID_list.append(sop_class_uid)

        sop_instance_uid = get_dict_tag_values(referenced_dose_sequence_item, RTPDicomTags.REFERENCED_SOP_INSTANCE_UID)
        if sop_instance_uid is not None and sop_instance_uid not in referenced_dose_SOPInstanceUID_list:
            referenced_dose_SOPInstanceUID_list.append(sop_instance_uid)
    
    return referenced_dose_SOPClassUID_list, referenced_dose_SOPInstanceUID_list


def _extract_bolus_data(beam_sequence_item: Dict[str, Any], beam_number: int) -> Dict[Any, Dict[str, Any]]:
    """
    Extract bolus information from beam sequence item.
    
    Args:
        beam_sequence_item: DICOM beam sequence item dictionary
        beam_number: Beam number for logging purposes
        
    Returns:
        Dictionary mapping ROI numbers to their bolus configuration data
    """
    bolus_dict: Dict[Any, Dict[str, Any]] = {}
    referenced_bolus_sequence = get_dict_tag_values(beam_sequence_item, RTPDicomTags.REFERENCED_BOLUS_SEQUENCE) or []
    
    for referenced_bolus_sequence_item in referenced_bolus_sequence:
        referenced_roi_number = get_dict_tag_values(referenced_bolus_sequence_item, RTPDicomTags.REFERENCED_ROI_NUMBER)
        if referenced_roi_number is None:
            continue
            
        if referenced_roi_number in bolus_dict:
            logger.warning(
                f"Duplicate referenced ROI number found in bolus dict for beam #{beam_number}: "
                f"{referenced_roi_number}. Skipping it."
            )
            continue
        
        bolus_dict[referenced_roi_number] = {
            "bolus_id": get_dict_tag_values(referenced_bolus_sequence_item, "300A00DC"),
            "bolus_description": get_dict_tag_values(referenced_bolus_sequence_item, "300A00DD"),
            "accessory_code": get_dict_tag_values(referenced_bolus_sequence_item, "300A00F9"),
        }
    
    return bolus_dict


def process_single_beam(
    beam_sequence_item: Dict[str, Any],
    beam_number: int,
    treatment_delivery_type: str,
    beam_dose: Optional[float],
    beam_meterset: Optional[float],
    read_beam_cp_data: bool
) -> Dict[str, Any]:
    """
    Process a single beam from the RT Plan and extract its beam information.
    
    Args:
        beam_sequence_item: A single beam sequence item from the DICOM dataset containing
                          all beam-specific DICOM tags and nested sequences
        beam_number: The beam number for DICOM identification and logging purposes
        treatment_delivery_type: The type of treatment delivery (e.g., "TREATMENT", "SETUP")
        beam_dose: Dose delivered by the beam in cGy, can be None if not specified
        beam_meterset: Meterset value for the beam in monitor units, can be None
        read_beam_cp_data: Whether to read control point data (can be memory-intensive
                          for beams with many control points)
    
    Returns:
        A comprehensive dictionary containing all extracted beam information including:
        - Basic beam parameters (number, name, type, radiation type)
        - Equipment information (machine name, model, serial number)
        - Beam limiting devices (jaws, MLCs with leaf positions)
        - Beam modifiers (wedges, compensators, blocks, applicators)
        - Control point data (if requested) with gantry angles, dose rates, etc.
        - Referenced dose and bolus information
        - Primary fluence mode data
    
    Raises:
        Exception: Any exceptions during processing are logged but not re-raised
                  to allow continued processing of other beams
    """
    try:
        # Initialize beam info dictionary with basic parameters
        beam_info: Dict[str, Any] = {
            "beam_number": beam_number,
            "treatment_delivery_type": treatment_delivery_type,
            "beam_dose": beam_dose,
            "beam_meterset": beam_meterset,
            "manufacturers_model_name": get_dict_tag_values(beam_sequence_item, RTPDicomTags.MANUFACTURERS_MODEL_NAME),
            "device_serial_number": get_dict_tag_values(beam_sequence_item, RTPDicomTags.DEVICE_SERIAL_NUMBER),
            "treatment_machine_name": get_dict_tag_values(beam_sequence_item, RTPDicomTags.TREATMENT_MACHINE_NAME),
            "primary_dosimeter_unit": get_dict_tag_values(beam_sequence_item, RTPDicomTags.PRIMARY_DOSIMETER_UNIT),
            "source_axis_distance": get_dict_tag_values(beam_sequence_item, RTPDicomTags.SOURCE_AXIS_DISTANCE),
            "beam_name": get_dict_tag_values(beam_sequence_item, RTPDicomTags.BEAM_NAME),
            "beam_description": get_dict_tag_values(beam_sequence_item, RTPDicomTags.BEAM_DESCRIPTION),
            "beam_type": get_dict_tag_values(beam_sequence_item, RTPDicomTags.BEAM_TYPE),
            "radiation_type": get_dict_tag_values(beam_sequence_item, RTPDicomTags.RADIATION_TYPE),
            "number_of_wedges": get_dict_tag_values(beam_sequence_item, "300A00D0"),
            "number_of_compensators": get_dict_tag_values(beam_sequence_item, "300A00E0"),
            "total_compensator_tray_factor": get_dict_tag_values(beam_sequence_item, "300A00E2"),
            "number_of_boli": get_dict_tag_values(beam_sequence_item, "300A00ED"),
            "number_of_blocks": get_dict_tag_values(beam_sequence_item, "300A00F0"),
            "total_block_tray_factor": get_dict_tag_values(beam_sequence_item, "300A00F2"),
            "final_cumulative_meterset_weight": get_dict_tag_values(beam_sequence_item, "300A010E"),
            "number_of_control_points": get_dict_tag_values(beam_sequence_item, "300A0110"),
            "referenced_patient_setup_number": get_dict_tag_values(beam_sequence_item, "300C006A"),
        }
        
        # Extract primary fluence mode data for IMRT/VMAT beams
        primary_fluence_mode, primary_fluence_mode_id = _extract_fluence_mode_data(beam_sequence_item, beam_number)
        beam_info["primary_fluence_mode"] = primary_fluence_mode
        beam_info["primary_fluence_mode_id"] = primary_fluence_mode_id
        
        # Extract beam limiting devices (jaws, MLCs)
        beam_info["rt_beam_limiting_device_dict"] = _extract_beam_limiting_devices(beam_sequence_item, beam_number)
        
        # Extract beam modifiers
        beam_info["wedge_dict"] = _extract_wedge_data(beam_sequence_item, beam_number)
        beam_info["compensator_dict"] = _extract_compensator_data(beam_sequence_item, beam_number)
        beam_info["block_dict"] = _extract_block_data(beam_sequence_item, beam_number)
        beam_info["applicator_dict"] = _extract_applicator_data(beam_sequence_item, beam_number)
        
        # Extract control points if requested
        if read_beam_cp_data:
            beam_info["control_point_dict"] = _extract_control_point_data(beam_sequence_item, beam_number)
        else:
            beam_info["control_point_dict"] = {}
        
        # Extract referenced dose information
        referenced_dose_SOPClassUID_list, referenced_dose_SOPInstanceUID_list = _extract_referenced_dose_data(beam_sequence_item)
        beam_info["referenced_dose_SOPClassUID_list"] = referenced_dose_SOPClassUID_list
        beam_info["referenced_dose_SOPInstanceUID_list"] = referenced_dose_SOPInstanceUID_list
        
        # Extract referenced bolus information
        beam_info["bolus_dict"] = _extract_bolus_data(beam_sequence_item, beam_number)
        
        return beam_info
        
    except Exception as e:
        logger.exception(f"Error processing beam #{beam_number}!")
        # Return minimal beam info to allow processing to continue
        return {
            "beam_number": beam_number,
            "treatment_delivery_type": treatment_delivery_type,
            "beam_dose": beam_dose,
            "beam_meterset": beam_meterset,
            "error": f"Processing failed: {str(e)}"
        }


class RTPlanBuilder:
    """
    DICOM RT Plan Builder.
    
    Attributes:
        file_path: Absolute path to the RT Plan DICOM file
        ss_mgr: Shared state manager for resource coordination and threading
        read_beam_cp_data: Flag to control extraction of control point data
        rt_plan_info_dict: Dictionary containing all extracted plan information
        ds_dict: DICOM dataset converted to dictionary format
    
    Example:
        ```python
        # Initialize the builder
        builder = RTPlanBuilder(
            file_path="/path/to/rtplan.dcm",
            ss_mgr=shared_state_manager,
            read_beam_cp_data=True
        )
        
        # Extract RT Plan information
        plan_info = builder.build_rtplan_info_dict()
        
        if plan_info:
            print(f"Plan: {plan_info['rt_plan_name']}")
            print(f"Beams: {plan_info['number_of_treatment_beams']}")
            print(f"Fractions: {plan_info['number_of_fractions_planned']}")
        ```
    """
    
    def __init__(
        self, 
        file_path: str, 
        ss_mgr: SharedStateManager, 
        read_beam_cp_data: bool = True
    ) -> None:
        """
        Initialize the RT Plan Builder with file path and configuration options.
        
        Args:
            file_path: Absolute path to the RT Plan DICOM file to be processed.
                      Must be a valid file path to an existing DICOM file.
            ss_mgr: Shared state manager instance for coordinating resources,
                   thread pools, and shutdown events across the application.
            read_beam_cp_data: Whether to extract detailed control point data
                             for each beam. Set to False for faster processing
                             when control point details are not needed, as this
                             data can be memory-intensive for complex plans.
        
        Raises:
            TypeError: If file_path is not a string or ss_mgr is invalid
            ValueError: If read_beam_cp_data is not a boolean
        """
        self.file_path: str = file_path
        self.ss_mgr: SharedStateManager = ss_mgr
        self.read_beam_cp_data: bool = read_beam_cp_data
        self.rt_plan_info_dict: Dict[str, Any] = {}
        self.ds_dict: Optional[Dict[str, Any]] = None
        
    def _validate_inputs(self) -> bool:
        """
        Validate all input parameters and prerequisites for RT Plan processing.
        
        Returns:
            True if all inputs are valid and processing can proceed,
            False if any validation fails.
        """
        if not isinstance(self.file_path, str):
            logger.error(
                f"File path must be a string. Received type '{type(self.file_path)}' "
                f"with value '{self.file_path}'."
            )
            return False
        
        if not exists(self.file_path):
            logger.error(f"RT Plan file '{self.file_path}' does not exist.")
            return False
        
        if not self.ss_mgr:
            logger.error("Shared state manager not provided to RT Plan Builder.")
            return False
        
        if not isinstance(self.read_beam_cp_data, bool):
            logger.error(
                f"read_beam_cp_data must be a boolean. Received type "
                f"'{type(self.read_beam_cp_data)}' with value '{self.read_beam_cp_data}'."
            )
            return False
        
        logger.debug(f"Input validation successful for RT Plan: {self.file_path}")
        return True
    
    def _read_and_validate_dataset(self) -> bool:
        """
        Loads the DICOM file into memory and converts it to a dictionary format.
        Validates that the file is readable and contains the expected DICOM structure.
        
        Returns:
            True if the dataset is successfully loaded and valid,
            False if reading fails or the dataset is invalid.
        """
        try:
            self.ds_dict = read_dcm_file(self.file_path, to_json_dict=True)
            if not self.ds_dict:
                logger.error(f"Failed to read DICOM file '{self.file_path}'. File may be corrupted.")
                return False
            
            logger.debug(f"Successfully loaded DICOM dataset from {self.file_path}")
            return True
            
        except Exception as e:
            logger.exception(f"Exception while reading DICOM file '{self.file_path}'!")
            return False
    
    def _extract_plan_info(self) -> None:
        """
        Extract high-level RT Plan identification and metadata information, including:
        - Plan label, name, and description
        - Plan creation date and time  
        - Treatment intent and protocol information
        - Plan approval status
        
        Updates:
            rt_plan_info_dict with plan-level metadata using standardized key names
        """
        plan_level_tags = [
            RTPDicomTags.RT_PLAN_LABEL,
            RTPDicomTags.RT_PLAN_NAME, 
            RTPDicomTags.RT_PLAN_DESCRIPTION,
            RTPDicomTags.RT_PLAN_DATE,
            RTPDicomTags.RT_PLAN_TIME,
            RTPDicomTags.APPROVAL_STATUS,
            RTPDicomTags.REVIEW_DATE,
            RTPDicomTags.REVIEW_TIME,
            RTPDicomTags.REVIEWER_NAME,
        ]
        
        for tag in plan_level_tags:
            safe_key = safe_keyword_for_tag(tag)
            self.rt_plan_info_dict[safe_key] = get_dict_tag_values(self.ds_dict, tag)
        
        logger.debug("Extracted high-level plan information")
    
    def _extract_dose_reference_info(self) -> None:
        """
        Processes the Dose Reference Sequence to determine the highest target
        prescription dose, with fallback to delivery maximum dose if
        target prescription dose is not specified.
        
        Updates:
            rt_plan_info_dict with 'target_prescription_dose_cgy' representing
            the highest target prescription dose in cGy.
        """
        target_prescription_dose_cgy: Optional[int] = None
        dose_reference_sequence = get_dict_tag_values(self.ds_dict, RTPDicomTags.DOSE_REFERENCE_SEQUENCE) or []
        
        for dose_reference_item in dose_reference_sequence:
            # Process target prescription dose (typical field)
            target_rx_dose_gy = get_dict_tag_values(dose_reference_item, RTPDicomTags.TARGET_PRESCRIPTION_DOSE)
            if target_rx_dose_gy is not None:
                dose_cgy = round(target_rx_dose_gy * RTConstants.GY_TO_CGY_FACTOR)
                if target_prescription_dose_cgy is None or dose_cgy > target_prescription_dose_cgy:
                    target_prescription_dose_cgy = dose_cgy
            
            # Process delivery maximum dose (alternative field)
            delivery_max_dose_gy = get_dict_tag_values(dose_reference_item, RTPDicomTags.DELIVERY_MAXIMUM_DOSE)
            if delivery_max_dose_gy is not None:
                dose_cgy = round(delivery_max_dose_gy * RTConstants.GY_TO_CGY_FACTOR)
                if target_prescription_dose_cgy is None or dose_cgy > target_prescription_dose_cgy:
                    target_prescription_dose_cgy = dose_cgy
        
        self.rt_plan_info_dict["target_prescription_dose_cgy"] = target_prescription_dose_cgy
        logger.debug(f"Extracted target prescription dose: {target_prescription_dose_cgy} cGy")
    
    def _extract_fraction_group_info(self) -> None:
        """
        Processes fraction group data to determine number of fractions planned
        and number of treatment beams. If multiple fraction groups exist, the
        maximum value is selected.
        
        Updates:
            rt_plan_info_dict with 'number_of_fractions_planned' and 'number_of_beams'
        """
        number_of_fractions_planned: Optional[int] = None
        number_of_beams: Optional[int] = None
        fraction_group_sequence = get_dict_tag_values(self.ds_dict, RTPDicomTags.FRACTION_GROUP_SEQUENCE) or []
        
        for fraction_group_item in fraction_group_sequence:
            # Extract number of fractions planned
            num_fractions = get_dict_tag_values(fraction_group_item, RTPDicomTags.NUMBER_OF_FRACTIONS_PLANNED)
            if num_fractions is not None:
                if number_of_fractions_planned is None or num_fractions > number_of_fractions_planned:
                    number_of_fractions_planned = num_fractions
            
            # Extract number of beams in this fraction group
            num_beams = get_dict_tag_values(fraction_group_item, RTPDicomTags.NUMBER_OF_BEAMS)
            if num_beams is not None:
                if number_of_beams is None or num_beams > number_of_beams:
                    number_of_beams = num_beams
        
        self.rt_plan_info_dict["number_of_fractions_planned"] = number_of_fractions_planned
        self.rt_plan_info_dict["number_of_beams"] = number_of_beams
        
        logger.debug(
            f"Extracted fraction info: {number_of_fractions_planned} fractions, "
            f"{number_of_beams} beams"
        )
    
    def _extract_patient_setup_info(self) -> None:
        """
        Extracts patient position (e.g., HFS, FFS, HFP, FFP) and setup technique
        from the Patient Setup Sequence. Inconsistencies are logged as warnings.
        
        Updates:
            rt_plan_info_dict with 'patient_position' and 'setup_technique'
        """
        patient_position: Optional[str] = None
        setup_technique: Optional[str] = None
        patient_setup_sequence = get_dict_tag_values(self.ds_dict, RTPDicomTags.PATIENT_SETUP_SEQUENCE) or []
        
        for patient_setup_item in patient_setup_sequence:
            setup_number = get_dict_tag_values(patient_setup_item, RTPDicomTags.PATIENT_SETUP_NUMBER)
            if setup_number is None:
                continue
            
            # Extract patient position
            pt_position = get_dict_tag_values(patient_setup_item, RTPDicomTags.PATIENT_POSITION)
            if pt_position is not None:
                if patient_position is None:
                    patient_position = pt_position
                elif patient_position != pt_position:
                    logger.warning(
                        f"Multiple patient positions found: {patient_position}, {pt_position}. "
                        f"Using the first one."
                    )
            
            # Extract setup technique
            setup_tech = get_dict_tag_values(patient_setup_item, RTPDicomTags.SETUP_TECHNIQUE)
            if setup_tech is not None:
                if setup_technique is None:
                    setup_technique = setup_tech
                elif setup_technique != setup_tech:
                    logger.warning(
                        f"Multiple setup techniques found: {setup_technique}, {setup_tech}. "
                        f"Using the first one."
                    )
        
        self.rt_plan_info_dict["patient_position"] = patient_position
        self.rt_plan_info_dict["setup_technique"] = setup_technique
        
        logger.debug(f"Extracted patient setup: position={patient_position}, technique={setup_technique}")
    
    def _extract_beam_dose_info(self) -> Dict[Any, Dict[str, Any]]:
        """
        Determine the planned dose and meterset values for individual beams.
        
        Returns:
            Dictionary mapping beam numbers to dictionaries containing:
            - 'beam_dose': Planned dose for the beam in cGy
            - 'beam_meterset': Planned meterset value in MU
        """
        beam_dose_info: Dict[Any, Dict[str, Any]] = {}
        fraction_group_sequence = get_dict_tag_values(self.ds_dict, RTPDicomTags.FRACTION_GROUP_SEQUENCE) or []
        
        for fraction_group_item in fraction_group_sequence:
            referenced_beam_sequence = get_dict_tag_values(fraction_group_item, RTPDicomTags.REFERENCED_BEAM_SEQUENCE) or []
            
            for ref_beam_item in referenced_beam_sequence:
                beam_number = get_dict_tag_values(ref_beam_item, RTPDicomTags.REFERENCED_BEAM_NUMBER)
                if beam_number is not None:
                    beam_dose = get_dict_tag_values(ref_beam_item, RTPDicomTags.BEAM_DOSE)
                    beam_meterset = get_dict_tag_values(ref_beam_item, RTPDicomTags.BEAM_METERSET_VALUE)
                    
                    beam_dose_info[beam_number] = {
                        'beam_dose': beam_dose,
                        'beam_meterset': beam_meterset
                    }
        
        logger.debug(f"Extracted dose information for {len(beam_dose_info)} beams")
        return beam_dose_info
    
    def _extract_beam_info(self) -> None:
        """
        Extract comprehensive information for all treatment beams using parallel processing.
        Only processes beams with treatment delivery type "TREATMENT".
        
        Updates:
            rt_plan_info_dict with:
            - 'beam_dict': Dictionary of all processed beam information
            - 'number_of_treatment_beams': Count of successfully processed beams
        """
        beam_sequence = get_dict_tag_values(self.ds_dict, RTPDicomTags.BEAM_SEQUENCE) or []
        if not beam_sequence:
            logger.warning(f"No beam sequence found in RT Plan file {self.file_path}")
            self.rt_plan_info_dict["number_of_treatment_beams"] = 0
            self.rt_plan_info_dict["beam_dict"] = {}
            return
        
        logger.info(f"Processing {len(beam_sequence)} beams from RT Plan")
        
        # Get dose information for all beams
        beam_dose_info = self._extract_beam_dose_info()
        beam_dict: Dict[Any, Dict[str, Any]] = {}
        futures: List[Future] = []
        
        # Initialize executor for parallel beam processing
        self.ss_mgr.startup_executor(use_process_pool=True)
        
        try:
            # Submit beam processing tasks
            for beam_sequence_item in beam_sequence:
                if should_exit(self.ss_mgr, msg="Beam processing cancelled by user."):
                    break
                
                beam_number = get_dict_tag_values(beam_sequence_item, RTPDicomTags.BEAM_NUMBER)
                if beam_number is None:
                    logger.warning("Beam found without beam number, skipping")
                    continue
                
                # Only process treatment beams, skip setup/port film beams
                treatment_delivery_type = get_dict_tag_values(beam_sequence_item, RTPDicomTags.TREATMENT_DELIVERY_TYPE)
                if treatment_delivery_type != RTConstants.TREATMENT_DELIVERY_TYPE:
                    logger.debug(f"Skipping non-treatment beam #{beam_number} (type: {treatment_delivery_type})")
                    continue
                
                # Get beam dose and meterset values
                beam_dose = beam_dose_info.get(beam_number, {}).get('beam_dose')
                beam_meterset = beam_dose_info.get(beam_number, {}).get('beam_meterset')
                
                # Submit beam processing to executor
                future = self.ss_mgr.submit_executor_action(
                    process_single_beam,
                    beam_sequence_item,
                    beam_number, 
                    treatment_delivery_type,
                    beam_dose,
                    beam_meterset,
                    self.read_beam_cp_data
                )
                
                if future is not None:
                    futures.append(future)
                    logger.debug(f"Submitted beam #{beam_number} for processing")
            
            # Collect results from parallel processing
            completed_beams = 0
            for future in as_completed(futures):
                if should_exit(self.ss_mgr, msg="Cancelling remaining beam processing at user request."):
                    break
                
                try:
                    beam_info = future.result()
                    if beam_info and "beam_number" in beam_info:
                        beam_number = beam_info["beam_number"]
                        beam_dict[beam_number] = beam_info
                        completed_beams += 1
                        
                        if completed_beams % 10 == 0:  # Log progress every 10 beams
                            logger.info(f"Processed {completed_beams} beams...")
                    else:
                        logger.warning("Received invalid beam info from processing")
                        
                except Exception as e:
                    logger.exception(f"Failed to process beam information!")
                finally:
                    # Ensure future is properly cleaned up
                    if isinstance(future, Future) and not future.done():
                        future.cancel()
            
            logger.info(f"Successfully processed {completed_beams} treatment beams")
            
        except Exception as e:
            logger.exception(f"Error during beam information extraction!")

        finally:
            # Always shutdown executor to free resources
            self.ss_mgr.shutdown_executor()
        
        # Check for shutdown before finalizing results
        if should_exit(self.ss_mgr, msg="Beam processing cancelled by user."):
            return
        
        self.rt_plan_info_dict["beam_dict"] = beam_dict
        self.rt_plan_info_dict["number_of_treatment_beams"] = len(beam_dict)
    
    def build_rtplan_info_dict(self) -> Optional[Dict[str, Any]]:
        """
        The method builds a dictionary following a structured approach:
        1. Validate inputs and read DICOM dataset
        2. Extract high-level plan information
        3. Process dose reference and fractionation data  
        4. Extract patient setup parameters
        5. Process all treatment beams in parallel
        
        Returns:
            RT Plan information dictionary, or None if processing fails or is aborted.
            
        Example of returned dictionary structure:
        ```python
        {
            'rt_plan_name': 'PLAN_001',
            'target_prescription_dose_cgy': 6000,
            'number_of_fractions_planned': 30,
            'number_of_treatment_beams': 7,
            'patient_position': 'HFS',
            'beam_dict': {
                1: {beam_info...},
                2: {beam_info...},
                ...
            }
        }
        ```
        """
        logger.info(f"Starting RT Plan processing for file: {self.file_path}")
        
        # Validate inputs and read dataset
        if should_exit(self.ss_mgr, msg="RT Plan processing cancelled by user."):
            return None
        if not self._validate_inputs():
            logger.error("RT Plan processing aborted due to input validation failure")
            return None

        if should_exit(self.ss_mgr, msg="RT Plan processing cancelled by user."):
            return None
        if not self._read_and_validate_dataset():
            logger.error("RT Plan processing aborted due to dataset reading failure")
            return None
        
        # Extract plan components with shutdown checking
        processing_steps = [
            ("plan information", self._extract_plan_info),
            ("dose reference information", self._extract_dose_reference_info), 
            ("fraction group information", self._extract_fraction_group_info),
            ("patient setup information", self._extract_patient_setup_info),
            ("beam information", self._extract_beam_info),
        ]
        
        for step_name, step_method in processing_steps:
            if should_exit(self.ss_mgr, msg=f"RT Plan processing cancelled during {step_name} extraction"):
                return None
                
            try:
                step_method()
                logger.debug(f"Completed {step_name} extraction")
            except Exception as e:
                logger.exception(f"Error extracting {step_name}!")
                return None
        
        # Final validation and logging
        if should_exit(self.ss_mgr, msg="RT Plan processing cancelled before completion"):
            return None
        
        plan_name = self.rt_plan_info_dict.get('rt_plan_name', 'Unknown')
        num_beams = self.rt_plan_info_dict.get('number_of_treatment_beams', 0)
        num_fractions = self.rt_plan_info_dict.get('number_of_fractions_planned', 0)
        
        logger.info(
            f"Successfully processed RT Plan '{plan_name}' with {num_beams} beams "
            f"and {num_fractions} fractions"
        )
        
        return self.rt_plan_info_dict
