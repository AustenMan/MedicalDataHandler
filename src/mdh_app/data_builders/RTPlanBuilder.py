import logging
from os.path import exists
from typing import Any, Dict, Optional
from concurrent.futures import as_completed, Future

from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dicom_utils import read_dcm_file, get_dict_tag_values, safe_keyword_for_tag
from mdh_app.utils.general_utils import get_traceback

logger = logging.getLogger(__name__)

def process_single_beam(
    beam_sequence_item: dict,
    beam_number: int,
    treatment_delivery_type: str,
    beam_dose: Optional[float],
    beam_meterset: Optional[float],
    read_beam_cp_data: bool
) -> Dict[str, Any]:
    """
    Processes a single beam and extracts detailed beam information.

    Args:
        beam_sequence_item (dict): A single beam sequence item from the DICOM dataset.
        beam_number (int): The beam number.
        treatment_delivery_type (str): The type of treatment delivery (e.g., TREATMENT).
        beam_dose (float): Dose delivered by the beam in cGy.
        beam_meterset (float): Meterset of the beam.
        read_beam_cp_data (bool): Whether to read control point data (time-consuming and memory-intensive).

    Returns:
        dict: Detailed information about the beam.
    """
    # Initialize beam info dictionary
    beam_info: Dict[str, Any] = {
        "beam_number": beam_number,
        "treatment_delivery_type": treatment_delivery_type,
        "beam_dose": beam_dose,
        "beam_meterset": beam_meterset,
        "manufacturers_model_name": get_dict_tag_values(beam_sequence_item, "00081090"), # Vendor's model name (not the machine name)
        "device_serial_number": get_dict_tag_values(beam_sequence_item, "00181000"), # Vendor's serial number for the machine
        "treatment_machine_name": get_dict_tag_values(beam_sequence_item, "300A00B2"), # Machine name
        "primary_dosimeter_unit": get_dict_tag_values(beam_sequence_item, "300A00B3"), # Unit of the primary dosimeter, can be MU or minutes (generally MU)
        "source_axis_distance": get_dict_tag_values(beam_sequence_item, "300A00B4"), # Distance from the source to the isocenter (in mm)
        "beam_name": get_dict_tag_values(beam_sequence_item, "300A00C2"),
        "beam_description": get_dict_tag_values(beam_sequence_item, "300A00C3"),
        "beam_type": get_dict_tag_values(beam_sequence_item, "300A00C4"), # STATIC (All Control Point Sequence Attributes are unchanged between consecutive control points, but Cumulative Meterset Weight may change) or DYNAMIC
        "radiation_type": get_dict_tag_values(beam_sequence_item, "300A00C6"), # PHOTON, ELECTRON, NEUTRON, PROTON
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
    
    # Extract primary fluence mode/id
    primary_fluence_mode_sequence = get_dict_tag_values(beam_sequence_item, "30020050") or []
    primary_fluence_mode: Optional[str] = None
    primary_fluence_mode_id: Optional[str] = None
    for fluence_item in primary_fluence_mode_sequence:
        mode = get_dict_tag_values(fluence_item, "30020051")
        if mode and primary_fluence_mode is None:
            primary_fluence_mode = mode
        elif mode and primary_fluence_mode != mode:
            logger.warning(f"Multiple primary fluence modes found for beam #{beam_number}: {primary_fluence_mode}, {mode}. Using the first one.")

        mode_id = get_dict_tag_values(fluence_item, "30020052")
        if mode_id and primary_fluence_mode_id is None:
            primary_fluence_mode_id = mode_id
        elif mode_id and primary_fluence_mode_id != mode_id:
            logger.warning(f"Multiple primary fluence mode IDs found for beam #{beam_number}: {primary_fluence_mode_id}, {mode_id}. Using the first one.")

    beam_info["primary_fluence_mode"] = primary_fluence_mode
    beam_info["primary_fluence_mode_id"] = primary_fluence_mode_id
    
    # Extract beam limiting devices.
    rt_beam_limiting_device_dict: Dict[str, Any] = {}
    beam_limiting_device_sequence = get_dict_tag_values(beam_sequence_item, "300A00B6") or []
    for device_item in beam_limiting_device_sequence:
        device_type = get_dict_tag_values(device_item, "300A00B8") # X, Y, ASYMX, ASYMY, MLCX, MLCY
        if device_type is None:
            continue
        if device_type in rt_beam_limiting_device_dict:
            logger.warning(f"Duplicate beam limiting device type found for beam #{beam_number}: {device_type}. Skipping it.")
            continue

        rt_beam_limiting_device_dict[device_type] = {
            "source_to_beam_limiting_device_distance": get_dict_tag_values(device_item, "300A00BA"),
            "number_of_leaf_or_jaw_pairs": get_dict_tag_values(device_item, "300A00BC"),
            "leaf_position_boundaries": get_dict_tag_values(device_item, "300A00BE"),
        }
    beam_info["rt_beam_limiting_device_dict"] = rt_beam_limiting_device_dict
    
    # Extract wedges
    wedge_dict: Dict[Any, Any] = {}
    wedge_sequence = get_dict_tag_values(beam_sequence_item, "300A00D1") or []
    for wedge_item in wedge_sequence:
        wedge_number = get_dict_tag_values(wedge_item, "300A00D2") # For DICOM identification
        if wedge_number is None:
            continue
        if wedge_number in wedge_dict:
            logger.warning(f"Duplicate wedge number found for beam #{beam_number}: {wedge_number}. Skipping it.")
            continue
        
        wedge_dict[wedge_number] = {
            "wedge_type": get_dict_tag_values(wedge_item, "300A00D3"), # STATIC, DYNAMIC, or MOTORIZED
            "wedge_id": get_dict_tag_values(wedge_item, "300A00D4"), # User-supplied identifier
            "wedge_angle": get_dict_tag_values(wedge_item, "300A00D5"), # In degrees
            "wedge_factor": get_dict_tag_values(wedge_item, "300A00D6"),
            "wedge_orientation": get_dict_tag_values(wedge_item, "300A00D8"),
            "source_to_wedge_tray_distance": get_dict_tag_values(wedge_item, "300A00DA"),
            "effective_wedge_angle": get_dict_tag_values(wedge_item, "300A00DE"), # In degrees
            "accessory_code": get_dict_tag_values(wedge_item, "300A00F9"),
        }
    beam_info["wedge_dict"] = wedge_dict
    
    # Extract compensators
    compensator_dict: Dict[Any, Any] = {}
    compensator_sequence = get_dict_tag_values(beam_sequence_item, "300A00E3") or []
    for compensator_item in compensator_sequence:
        compensator_number = get_dict_tag_values(compensator_item, "300A00E4") # For DICOM identification
        if compensator_number is None:
            continue
        if compensator_number in compensator_dict:
            logger.warning(f"Duplicate compensator number found for beam #{beam_number}: {compensator_number}. Skipping it.")
            continue
        
        compensator_dict[compensator_number] = {
            "material_id": get_dict_tag_values(compensator_item, "300A00E1"),
            "compensator_id": get_dict_tag_values(compensator_item, "300A00E5"), # User-supplied identifier
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
    beam_info["compensator_dict"] = compensator_dict
    
    # Extract blocks
    block_dict: Dict[Any, Any] = {}
    block_sequence = get_dict_tag_values(beam_sequence_item, "300A00F4") or []
    for block_item in block_sequence:
        block_number = get_dict_tag_values(block_item, "300A00FC") # For DICOM identification
        if block_number is None:
            continue
        if block_number in block_dict:
            logger.warning(f"Duplicate block number found for beam #{beam_number}: {block_number}. Skipping it.")
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
    beam_info["block_dict"] = block_dict
    
    # Extract applicator
    applicator_dict: Dict[str, Any] = {}
    applicator_sequence = get_dict_tag_values(beam_sequence_item, "300A0107") # Only a single item is allowed in this sequence
    if applicator_sequence:
        if len(applicator_sequence) != 1:
            logger.warning(f"Multiple applicators found in the sequence for beam #{beam_number}. Using the first one.")
        
        applicator_geometry_sequence = get_dict_tag_values(applicator_sequence[0], "300A0431") # Only a single item is allowed in this sequence
        if applicator_sequence and len(applicator_geometry_sequence) != 1:
            logger.warning(f"Multiple applicator geometries found in the sequence for beam #{beam_number}. Using the first one.")
        
        applicator_dict["applicator"] = {
            "accessory_code": get_dict_tag_values(applicator_sequence[0], "300A00F9"),
            "applicator_id": get_dict_tag_values(applicator_sequence[0], "300A0108"),
            "applicator_type": get_dict_tag_values(applicator_sequence[0], "300A0109"),
            "applicator_description": get_dict_tag_values(applicator_sequence[0], "300A010A"),
            "applicator_aperture_shape": get_dict_tag_values(applicator_geometry_sequence[0], "300A0432") if applicator_geometry_sequence else None,
            "applicator_opening": get_dict_tag_values(applicator_geometry_sequence[0], "300A0433") if applicator_geometry_sequence else None,
            "applicator_opening_x": get_dict_tag_values(applicator_geometry_sequence[0], "300A0434") if applicator_geometry_sequence else None,
            "applicator_opening_y": get_dict_tag_values(applicator_geometry_sequence[0], "300A0435") if applicator_geometry_sequence else None,
            "source_to_applicator_mounting_position_distance": get_dict_tag_values(applicator_sequence[0], "300A010C"),
        }
    beam_info["applicator_dict"] = applicator_dict
    
    # Extract control points (if requested)
    control_point_dict: Dict[Any, Any] = {}
    if read_beam_cp_data:
        control_point_sequence = get_dict_tag_values(beam_sequence_item, "300A0111") or []
        for cp_item in control_point_sequence:
            cp_index = get_dict_tag_values(cp_item, "300A0112")
            if cp_index is None:
                continue
            if cp_index in control_point_dict:
                logger.warning(f"Duplicate control point index found for beam #{beam_number}: {cp_index}. Skipping it.")
                continue
            
            control_point_dict[cp_index] = {
                "nominal_beam_energy": get_dict_tag_values(cp_item, "300A0114"),
                "dose_rate_set": get_dict_tag_values(cp_item, "300A0115"),
                "wedge_position_dict": {get_dict_tag_values(x, "300C00C0"): get_dict_tag_values(x, "300A0118") for x in (get_dict_tag_values(cp_item, "300A0116") or [{}]) if get_dict_tag_values(x, "300C00C0")}, # Referenced wedge number to wedge position
                "beam_limiting_device_dict": {get_dict_tag_values(x, "300C00B8"): get_dict_tag_values(x, "300A011C") for x in (get_dict_tag_values(cp_item, "300A011A") or [{}]) if get_dict_tag_values(x, "300C00B8")}, # Referenced beam limiting device type to leaf/jaw positions
                "gantry_angle": get_dict_tag_values(cp_item, "300A011E"),
                "gantry_rotation_direction": get_dict_tag_values(cp_item, "300A011F"),
                "beam_limiting_device_angle": get_dict_tag_values(cp_item, "300A0120"),
                "beam_limiting_device_rotation_direction": get_dict_tag_values(cp_item, "300A0121"),
                "patient_support_angle": get_dict_tag_values(cp_item, "300A0122"),
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
                "cumulative_meterset_weight": get_dict_tag_values(cp_item, "300A0134"),
                "table_top_pitch_angle": get_dict_tag_values(cp_item, "300A0140"),
                "table_top_pitch_rotation_direction": get_dict_tag_values(cp_item, "300A0142"),
                "table_top_roll_angle": get_dict_tag_values(cp_item, "300A0144"),
                "table_top_roll_rotation_direction": get_dict_tag_values(cp_item, "300A0146"),
                "gantry_pitch_angle": get_dict_tag_values(cp_item, "300A014A"),
                "gantry_pitch_rotation_direction": get_dict_tag_values(cp_item, "300A014C"),
            }
    beam_info["control_point_dict"] = control_point_dict
    
    # Extract referenced dose information
    referenced_dose_SOPClassUID_list = []
    referenced_dose_SOPInstanceUID_list = []
    referenced_dose_sequence = get_dict_tag_values(beam_sequence_item, "300C0080") or []
    for referenced_dose_sequence_item in referenced_dose_sequence:
        referenced_dose_SOPClassUID = get_dict_tag_values(referenced_dose_sequence_item, "00081150")
        if referenced_dose_SOPClassUID is not None and referenced_dose_SOPClassUID not in referenced_dose_SOPClassUID_list:
            referenced_dose_SOPClassUID_list.append(referenced_dose_SOPClassUID)

        referenced_dose_SOPInstanceUID = get_dict_tag_values(referenced_dose_sequence_item, "00081155")
        if referenced_dose_SOPInstanceUID is not None and referenced_dose_SOPInstanceUID not in referenced_dose_SOPInstanceUID_list:
            referenced_dose_SOPInstanceUID_list.append(referenced_dose_SOPInstanceUID)
    beam_info["referenced_dose_SOPClassUID_list"] = referenced_dose_SOPClassUID_list
    beam_info["referenced_dose_SOPInstanceUID_list"] = referenced_dose_SOPInstanceUID_list
    
    # Extract referenced bolus information
    bolus_dict: Dict[Any, Any] = {}
    referenced_bolus_sequence = get_dict_tag_values(beam_sequence_item, "300C00B0") or []
    for referenced_bolus_sequence_item in referenced_bolus_sequence:
        referenced_roi_number = get_dict_tag_values(referenced_bolus_sequence_item, "30060084")
        if referenced_roi_number is None:
            continue
        if referenced_roi_number in bolus_dict:
            logger.warning(f"Duplicate referenced ROI number found in bolus dict for beam #{beam_number}: {referenced_roi_number}. Skipping it.")
            continue
        
        bolus_dict[referenced_roi_number] = {
            "bolus_id": get_dict_tag_values(referenced_bolus_sequence_item, "300A00DC"),
            "bolus_description": get_dict_tag_values(referenced_bolus_sequence_item, "300A00DD"),
            "accessory_code": get_dict_tag_values(referenced_bolus_sequence_item, "300A00F9"),
            }
    beam_info["bolus_dict"] = bolus_dict
    
    return beam_info

class RTPlanBuilder:
    """
    Constructs RT Plan information from a DICOM file.
    
    Attributes:
        file_path (str): Path to the RT Plan DICOM file.
        ss_mgr (SharedStateManager): Manager for shared resources.
        read_beam_cp_data (bool): Whether to read control point data for each beam.
        rt_plan_info_dict (dict): Extracted RT Plan information.
        ds_dict (dict): DICOM dataset as a dictionary.
    """
    
    def __init__(self, file_path: str, ss_mgr: SharedStateManager, read_beam_cp_data: bool = True) -> None:
        """
        Initialize the RTPlanBuilder.
        
        Args:
            file_path (str): Path to the RT Plan DICOM file.
            ss_mgr (SharedStateManager): Manager for shared resources.
            read_beam_cp_data (bool, optional): Whether to read control point data. Defaults to True.
        """
        self.file_path: str = file_path
        self.ss_mgr = ss_mgr
        self.read_beam_cp_data: bool = read_beam_cp_data
        self.rt_plan_info_dict: Dict[str, Any] = {}
        self.ds_dict: Optional[Dict[str, Any]] = None
    
    def _should_exit(self) -> bool:
        """
        Checks if the task should be aborted due to cleanup or shutdown events.
        
        Returns:
            bool: True if an exit condition is met, False otherwise.
        """
        if (self.ss_mgr is not None and 
            (self.ss_mgr.cleanup_event.is_set() or 
             self.ss_mgr.shutdown_event.is_set())):
            logger.info("Aborting RT Plan Builder task.")
            return True
        return False
    
    def _validate_inputs(self) -> bool:
        """
        Validates the input file path and parameters.
        
        Returns:
            bool: True if inputs are valid, False otherwise.
        """
        if not isinstance(self.file_path, str):
            logger.error(f"File path must be a string. Received type '{type(self.file_path)}' with value '{self.file_path}'.")
            return False
        
        if not exists(self.file_path):
            logger.error(f"File '{self.file_path}' does not exist.")
            return False
        
        if not self.ss_mgr:
            logger.error("Shared state manager not provided to RT Plan Builder.")
            return False
        
        if not isinstance(self.read_beam_cp_data, bool):
            logger.error(f"read_beam_cp_data must be a boolean. Received type '{type(self.read_beam_cp_data)}' with value '{self.read_beam_cp_data}'.")
            return False
        
        return True
    
    def _read_and_validate_dataset(self) -> bool:
        """
        Reads and validates the DICOM dataset.
        
        Returns:
            bool: True if dataset is successfully read, False otherwise.
        """
        self.ds_dict = read_dcm_file(self.file_path, to_json_dict=True)
        if not self.ds_dict:
            logger.error(f"Failed to read DICOM file '{self.file_path}'.")
            return False
        return True
    
    def _extract_plan_info(self) -> None:
        """
        Extracts high-level plan information from the dataset.
        """
        tags = [
            "300A0002", "300A0003", "300A0004", "300A0006", "300A0007", 
            "300E0002", "300E0004", "300E0005", "300E0008"
        ]
        for tag in tags:
            self.rt_plan_info_dict[safe_keyword_for_tag(tag)] = get_dict_tag_values(self.ds_dict, tag)
    
    def _extract_dose_reference(self) -> None:
        """
        Extracts the dose reference information, including the target prescription dose.
        
        Updates:
            rt_plan_info_dict: Adds 'target_prescription_dose_cgy', representing the highest
                target prescription dose or delivery maximum dose in cGy.
        """
        target_prescription_dose_cgy: Optional[int] = None
        dose_reference_sequence = get_dict_tag_values(self.ds_dict, "300A0010") or []
        
        for dose_reference_sequence_item in dose_reference_sequence:
            # Extract and calculate prescription dose in cGy
            target_rx_dose_gy = get_dict_tag_values(dose_reference_sequence_item, "300A0026")
            if target_rx_dose_gy is not None:
                dose_cgy = round(target_rx_dose_gy * 100)
                if target_prescription_dose_cgy is None or dose_cgy > target_prescription_dose_cgy:
                    target_prescription_dose_cgy = dose_cgy
            
            # Extract and calculate delivery maximum dose in cGy
            delivery_max_dose = get_dict_tag_values(dose_reference_sequence_item, "300A0023")
            if delivery_max_dose is not None:
                dose_cgy = round(delivery_max_dose * 100)
                if target_prescription_dose_cgy is None or dose_cgy > target_prescription_dose_cgy:
                    target_prescription_dose_cgy = dose_cgy
        
        self.rt_plan_info_dict["target_prescription_dose_cgy"] = target_prescription_dose_cgy
    
    def _extract_fraction_group_info(self) -> None:
        """
        Extracts fraction group information such as the number of fractions planned and the number of beams.
        
        Updates:
            rt_plan_info_dict: Adds 'number_of_fractions_planned' and 'number_of_beams'.
        """
        number_of_fractions_planned: Optional[int] = None
        number_of_beams: Optional[int] = None
        fraction_group_sequence = get_dict_tag_values(self.ds_dict, "300A0070") or []
        
        for fraction_group_sequence_item in fraction_group_sequence:
            # Get number of fractions planned
            num_fractions = get_dict_tag_values(fraction_group_sequence_item, "300A0078")
            if num_fractions is not None:
                if number_of_fractions_planned is None or num_fractions > number_of_fractions_planned:
                    number_of_fractions_planned = num_fractions
            
            # Get number of beams
            num_beams = get_dict_tag_values(fraction_group_sequence_item, "300A0080")
            if num_beams is not None:
                if number_of_beams is None or num_beams > number_of_beams:
                    number_of_beams = num_beams
        
        self.rt_plan_info_dict["number_of_fractions_planned"] = number_of_fractions_planned
        self.rt_plan_info_dict["number_of_beams"] = number_of_beams
    
    def _extract_patient_setup(self) -> None:
        """
        Extracts patient setup information, including patient position and setup technique.
        
        Updates:
            rt_plan_info_dict: Adds 'patient_position' and 'setup_technique'.
        """
        patient_position: Optional[str] = None
        setup_technique: Optional[str] = None
        patient_setup_sequence = get_dict_tag_values(self.ds_dict, "300A0180") or []
        
        for patient_setup_sequence_item in patient_setup_sequence:
            # Get patient setup number
            pt_setup_number = get_dict_tag_values(patient_setup_sequence_item, "300A0182")
            if pt_setup_number is None:
                continue
            
            # Get patient position
            pt_position = get_dict_tag_values(patient_setup_sequence_item, "00185100")
            if pt_position is not None:
                if patient_position is None:
                    patient_position = pt_position
                elif patient_position != pt_position:
                    logger.warning(f"Multiple patient positions found: {patient_position}, {pt_position}. Using the first one.")
            
            # Get setup technique
            setup_tech = get_dict_tag_values(patient_setup_sequence_item, "300A01B0")
            if setup_tech is not None:
                if setup_technique is None:
                    setup_technique = setup_tech
                elif setup_technique != setup_tech:
                    logger.warning(f"Multiple setup techniques found: {setup_technique}, {setup_tech}. Using the first one.")
        
        self.rt_plan_info_dict["patient_position"] = patient_position
        self.rt_plan_info_dict["setup_technique"] = setup_technique
    
    def _extract_beam_dose(self) -> Dict[Any, Any]:
        """
        Extracts dose information for each beam.
        
        Returns:
            dict: A mapping of beam numbers to dictionaries containing 'beam_dose' and 'beam_meterset'.
        """
        beam_dose_info: Dict[Any, Any] = {} # beam_number: {'beam_dose': value, 'beam_meterset': value}
        fraction_group_sequence = get_dict_tag_values(self.ds_dict, "300A0070") or []
        
        for fraction_group_sequence_item in fraction_group_sequence:
            referenced_beam_sequence = get_dict_tag_values(fraction_group_sequence_item, "300C0004") or []
            for ref_beam_item in referenced_beam_sequence:
                beam_number = get_dict_tag_values(ref_beam_item, "300C0006")
                if beam_number is not None:
                    beam_dose = get_dict_tag_values(ref_beam_item, "300A0084") # Dose in units of cGy
                    beam_meterset = get_dict_tag_values(ref_beam_item, "300A0086") # Based on primary dosimeter unit (generally MU)
                    beam_dose_info[beam_number] = {
                        'beam_dose': beam_dose,
                        'beam_meterset': beam_meterset
                    }
        
        return beam_dose_info
    
    def _extract_beam_info(self) -> None:
        """
        Extracts detailed information for each treatment beam using concurrent processing.
        
        Updates:
            rt_plan_info_dict: Adds 'beam_dict' and 'number_of_treatment_beams'.
        """
        beam_sequence = get_dict_tag_values(self.ds_dict, "300A00B0") or []
        if not beam_sequence:
            logger.warning(f"No beam sequence found in {self.file_path}.")
            self.rt_plan_info_dict["number_of_treatment_beams"] = 0
            return
        
        self.ss_mgr.startup_executor(use_process_pool=True)
        beam_dose_info = self._extract_beam_dose()
        futures = []
        
        for beam_sequence_item in beam_sequence:
            if self._should_exit():
                break
            
            # Backend beam number for linking in DICOM format
            beam_number = get_dict_tag_values(beam_sequence_item, "300A00C0") 
            if beam_number is None:
                continue
            
            # Type should be one of: TREATMENT, OPEN_PORTFILM, TRMT_PORTFILM, CONTINUATION, SETUP
            treatment_delivery_type = get_dict_tag_values(beam_sequence_item, "300A00CE") 
            if treatment_delivery_type != "TREATMENT":
                continue
            
            beam_dose = beam_dose_info.get(beam_number, {}).get('beam_dose')
            beam_meterset = beam_dose_info.get(beam_number, {}).get('beam_meterset')
            
            # Process each beam in a separate future
            future = self.ss_mgr.submit_executor_action(
                process_single_beam, beam_sequence_item, beam_number, treatment_delivery_type, beam_dose, beam_meterset, self.read_beam_cp_data,
            )
            if future is not None:
                futures.append(future)
        
        # Collect results from futures
        beam_dict: Dict[Any, Any] = {}
        for future in as_completed(futures):
            if self._should_exit():
                break
            try:
                beam_info = future.result()
                if beam_info:
                    beam_number = beam_info["beam_number"]
                    beam_dict[beam_number] = beam_info
            except Exception as e:
                logger.error("Failed to process beam information." + get_traceback(e))
            finally:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
        
        self.ss_mgr.shutdown_executor()
        if self._should_exit():
            return
        
        self.rt_plan_info_dict["beam_dict"] = beam_dict
        self.rt_plan_info_dict["number_of_treatment_beams"] = len(beam_dict)
    
    def build_rtplan_info_dict(self) -> Optional[Dict[str, Any]]:
        """
        Constructs the RT Plan information dictionary by extracting relevant details from the DICOM dataset.
        
        Returns:
            dict: The constructed RT Plan information dictionary, or None if the process fails.
        """
        if self._should_exit() or not self._validate_inputs():
            return None
        if self._should_exit() or not self._read_and_validate_dataset():
            return None
        
        if self._should_exit():
            return None
        self._extract_plan_info()
        
        if self._should_exit():
            return None
        self._extract_dose_reference()
        
        if self._should_exit():
            return None
        self._extract_fraction_group_info()
        
        if self._should_exit():
            return None
        self._extract_patient_setup()
        
        if self._should_exit():
            return None
        self._extract_beam_info()
        
        return self.rt_plan_info_dict
