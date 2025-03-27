import os
import json
import logging
import pydicom
from pydicom.tag import Tag
from concurrent.futures import as_completed, Future
from typing import Callable, Optional, Set, Dict, List, Tuple, Any

from mdh_app.managers.config_manager import ConfigManager
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.patient_data_object import PatientData
from mdh_app.utils.dicom_utils import get_ds_tag_value
from mdh_app.utils.general_utils import get_traceback, chunked_iterable, atomic_save

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# DICOM Tag Constants
# -----------------------------------------------------------------------------
TAG_PATIENT_ID = Tag(0x0010, 0x0020)
TAG_PATIENTS_NAME = Tag(0x0010, 0x0010)
TAG_FRAME_OF_REFERENCE_UID = Tag(0x0020, 0x0052)
TAG_MODALITY = Tag(0x0008, 0x0060)
TAG_DOSE_SUMMATION_TYPE = Tag(0x3004, 0x000A)
TAG_SERIES_INSTANCE_UID = Tag(0x0020, 0x000E)
TAG_SOP_CLASS_UID = Tag(0x0008, 0x0016)
TAG_SOP_INSTANCE_UID = Tag(0x0008, 0x0018)
TAG_REFERENCED_SOP_CLASS_UID = Tag(0x0008, 0x1150)
TAG_REFERENCED_SOP_INSTANCE_UID = Tag(0x0008, 0x1155)
TAG_REFERENCED_RT_PLAN_SEQUENCE = Tag(0x300C, 0x0002)
TAG_REFERENCED_STRUCTURE_SET_SEQUENCE = Tag(0x300C, 0x0060)
TAG_REFERENCED_DOSE_SEQUENCE = Tag(0x300C, 0x0080)
TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE = Tag(0x3006, 0x0010)
TAG_RT_REFERENCED_STUDY_SEQUENCE = Tag(0x3006, 0x0012)
TAG_RT_REFERENCED_SERIES_SEQUENCE = Tag(0x3006, 0x0014)

# Tags used for reading minimal metadata
READ_WORKER_DICOM_TAGS = [
    TAG_PATIENT_ID, TAG_PATIENTS_NAME, TAG_FRAME_OF_REFERENCE_UID, TAG_MODALITY, TAG_SOP_INSTANCE_UID, 
    TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE
]

# Tags used for linking DICOM references
LINK_WORKER_DICOM_TAGS = [
    TAG_PATIENT_ID, TAG_PATIENTS_NAME, TAG_FRAME_OF_REFERENCE_UID, TAG_MODALITY, TAG_DOSE_SUMMATION_TYPE,
    TAG_SERIES_INSTANCE_UID, TAG_SOP_CLASS_UID, TAG_SOP_INSTANCE_UID, TAG_REFERENCED_SOP_CLASS_UID,
    TAG_REFERENCED_SOP_INSTANCE_UID, TAG_REFERENCED_RT_PLAN_SEQUENCE, TAG_REFERENCED_STRUCTURE_SET_SEQUENCE,
    TAG_REFERENCED_DOSE_SEQUENCE, TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE, TAG_RT_REFERENCED_STUDY_SEQUENCE,
    TAG_RT_REFERENCED_SERIES_SEQUENCE,
]

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def collect_independent_subdirs(base_dir: str, min_paths: int) -> List[str]:
    """
    Try to collect at least `min_paths` subdirectories under `base_dir`, 
    preferring shallowest directories first.
    
    Args:
        base_dir (str): The root directory to search.
        min_paths (int): The ideal minimum number of independent subdirectories to return.

    Returns:
        List[str]: A list of directories under `base_dir` with size >= min_paths.
    """
    if not os.path.isdir(base_dir):
        return []
    
    dirs = [subdir for d in os.listdir(base_dir) if (subdir := os.path.join(base_dir, d)) and os.path.isdir(subdir)]
    
    i = 0
    while len(dirs) < min_paths and i < len(dirs):
        current = dirs[i]
        try:
            children = [os.path.join(current, d) for d in os.listdir(current)
                        if os.path.isdir(os.path.join(current, d))]
            if children:
                # Replace parent with children
                dirs = dirs[:i] + children + dirs[i+1:]
                # Do not increment i, stay at same position to check new children
                continue
        except Exception:
            pass
        i += 1

    return dirs

def scan_folder_for_dicom(folder: str) -> List[str]:
    """Recursively scan a folder for DICOM files."""
    dicom_files = []
    for root, _, files in os.walk(folder):
        dicom_files.extend(os.path.join(root, f) for f in files if f.lower().endswith(".dcm"))
    return dicom_files

def read_dicom_metadata(filepath: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    Read essential metadata from a DICOM file.

    Returns:
        A tuple (filepath, PatientID, PatientName, FrameOfReferenceUID, Modality, SOPInstanceUID)
        or None if any required tag is missing.
    """
    try:
        ds = pydicom.dcmread(filepath, stop_before_pixels=True, force=True, specific_tags=READ_WORKER_DICOM_TAGS)
    except Exception as e:
        logger.error(f"Failed to read DICOM file {filepath}." + get_traceback(e))
        return None

    patient_id = get_ds_tag_value(ds, TAG_PATIENT_ID, reformat_str=True)
    patient_name = get_ds_tag_value(ds, TAG_PATIENTS_NAME, reformat_str=True)
    for_uid = get_ds_tag_value(ds, TAG_FRAME_OF_REFERENCE_UID)
    modality = get_ds_tag_value(ds, TAG_MODALITY)
    sop_instance_uid = get_ds_tag_value(ds, TAG_SOP_INSTANCE_UID)
    
    # Fallback to referenced Frame of Reference UIDs if Frame of Reference UID is not found
    if not for_uid:
        ref_seq = ds.get(TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE)
        if ref_seq:
            referenced_uids = {
                uid for item in ref_seq 
                if (uid := get_ds_tag_value(item, TAG_FRAME_OF_REFERENCE_UID)) is not None
            }
            if referenced_uids:
                sorted_uids = sorted(referenced_uids)
                if len(sorted_uids) > 1:
                    logger.warning(f"Multiple Referenced Frame of Reference UIDs found for {sop_instance_uid} in {filepath}. Using first one: {sorted_uids}")
                for_uid = sorted_uids[0]
    
    if any(val is None for val in (patient_id, patient_name, for_uid, modality, sop_instance_uid)):
        logger.warning(
            f"Incomplete DICOM data in {filepath}: "
            f"(PatientID: {patient_id}, PatientName: {patient_name}, FrameOfReferenceUID: {for_uid}, Modality: {modality}, SOPInstanceUID: {sop_instance_uid})"
        )
        return None
    
    return (filepath, patient_id, patient_name, for_uid, modality, sop_instance_uid)

def add_dicom_to_patient_data(
    patient_dict: Dict[Tuple[str, str], PatientData],
    filepath: str,
    patient_id: str,
    patient_name: str,
    for_uid: str,
    modality: str,
    sop_instance_uid: str
) -> None:
    """Add a DICOM file's metadata to the corresponding PatientData object."""
    key = (patient_id, patient_name)
    if key not in patient_dict:
        patient_dict[key] = PatientData(patient_id, patient_name)
    patient_dict[key].add_to_dicom_dict(for_uid, modality, sop_instance_uid, filepath, update_obj=False)

def link_dicom_references(filepath: str) -> Dict[str, Any]:
    """
    Read a DICOM file and extract its linked references.

    Returns:
        A dict mapping the filepath to its extracted references.
    """
    try:
        ds = pydicom.dcmread(filepath, stop_before_pixels=True, force=True, specific_tags=LINK_WORKER_DICOM_TAGS)
    except Exception as e:
        logger.error(f"Failed to read DICOM file {filepath}." + get_traceback(e))
        return {filepath: {}}
    
    patient_id = get_ds_tag_value(ds, TAG_PATIENT_ID, reformat_str=True)
    patient_name = get_ds_tag_value(ds, TAG_PATIENTS_NAME, reformat_str=True)
    modality = get_ds_tag_value(ds, TAG_MODALITY)
    dose_summation_type = get_ds_tag_value(ds, TAG_DOSE_SUMMATION_TYPE)
    series_instance_uid = get_ds_tag_value(ds, TAG_SERIES_INSTANCE_UID)
    sop_class_uid = get_ds_tag_value(ds, TAG_SOP_CLASS_UID)
    sop_instance_uid = get_ds_tag_value(ds, TAG_SOP_INSTANCE_UID)
    for_uid = get_ds_tag_value(ds, TAG_FRAME_OF_REFERENCE_UID)
    
    links: Dict[str, Any] = {
        "PatientID": patient_id,
        "PatientsName": patient_name,
        "Modality": modality,
        "DoseSummationType": dose_summation_type,
        "SOPClassUID": sop_class_uid,
        "SOPInstanceUID": sop_instance_uid,
        "FrameOfReferenceUID": for_uid,
        "SeriesInstanceUID": series_instance_uid,
        "ReferencedSOPClassUID": [],
        "ReferencedSOPInstanceUID": [],
        "ReferencedFrameOfReferenceUID": [],
        "ReferencedSeriesInstanceUID": [],
    }
    
    # Direct referenced tags
    referenced_sop_class_uid = get_ds_tag_value(ds, TAG_REFERENCED_SOP_CLASS_UID)
    if referenced_sop_class_uid and referenced_sop_class_uid not in links["ReferencedSOPClassUID"]:
        links["ReferencedSOPClassUID"].append(referenced_sop_class_uid)
    
    referenced_sop_instance_uid = get_ds_tag_value(ds, TAG_REFERENCED_SOP_INSTANCE_UID)
    if referenced_sop_instance_uid and referenced_sop_instance_uid not in links["ReferencedSOPInstanceUID"]:
        links["ReferencedSOPInstanceUID"].append(referenced_sop_instance_uid)
    
    # Process Referenced Frame of Reference Sequence
    ref_for_seq = ds.get(TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE)
    if ref_for_seq:
        for item in ref_for_seq:
            item_for_uid = get_ds_tag_value(item, TAG_FRAME_OF_REFERENCE_UID)
            if item_for_uid and item_for_uid not in links["ReferencedFrameOfReferenceUID"]:
                links["ReferencedFrameOfReferenceUID"].append(item_for_uid)
            
            # Use proper constant for RT Referenced Study Sequence
            rt_ref_study_seq = item.get(TAG_RT_REFERENCED_STUDY_SEQUENCE)
            if rt_ref_study_seq:
                for study_item in rt_ref_study_seq:
                    item_sopc = get_ds_tag_value(study_item, TAG_REFERENCED_SOP_CLASS_UID)
                    if item_sopc and item_sopc not in links["ReferencedSOPClassUID"]:
                        links["ReferencedSOPClassUID"].append(item_sopc)
                    item_sopi = get_ds_tag_value(study_item, TAG_REFERENCED_SOP_INSTANCE_UID)
                    if item_sopi and item_sopi not in links["ReferencedSOPInstanceUID"]:
                        links["ReferencedSOPInstanceUID"].append(item_sopi)
                    
                    rt_ref_series_seq = study_item.get(TAG_RT_REFERENCED_SERIES_SEQUENCE)
                    if rt_ref_series_seq:
                        for series_item in rt_ref_series_seq:
                            series_uid = get_ds_tag_value(series_item, TAG_SERIES_INSTANCE_UID)
                            if series_uid and series_uid not in links["ReferencedSeriesInstanceUID"]:
                                links["ReferencedSeriesInstanceUID"].append(series_uid)
    
    # Process additional sequences: RT Plan, Structure Set, and Dose
    plan_struct_dose_refs: List[Any] = []
    for seq_tag in (TAG_REFERENCED_RT_PLAN_SEQUENCE, TAG_REFERENCED_STRUCTURE_SET_SEQUENCE, TAG_REFERENCED_DOSE_SEQUENCE):
        seq = ds.get(seq_tag)
        if seq:
            plan_struct_dose_refs.extend(seq)
    
    for item in plan_struct_dose_refs:
        item_sopc = get_ds_tag_value(item, TAG_REFERENCED_SOP_CLASS_UID)
        if item_sopc and item_sopc not in links["ReferencedSOPClassUID"]:
            links["ReferencedSOPClassUID"].append(item_sopc)
        item_sopi = get_ds_tag_value(item, TAG_REFERENCED_SOP_INSTANCE_UID)
        if item_sopi and item_sopi not in links["ReferencedSOPInstanceUID"]:
            links["ReferencedSOPInstanceUID"].append(item_sopi)
    
    return {filepath: links}

def get_matched_pdata_file(filepath: str, never_processed: bool) -> Optional[str]:
    """Return the path of a matching PatientData file based its JSON values."""
    try:
        with open(filepath, "r") as file:
            data = json.load(file)
        
        if never_processed == (data.get("DateLastProcessed", None) is None):
            return filepath
        
        return None
    except Exception as e:
        logger.error(f"Failed to read file '{filepath}'." + get_traceback(e))
        return None

def load_pdata_object(file_path: str,) -> Optional[PatientData]:
    """Load a PatientData object from a JSON file."""
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
        patient_data = PatientData.from_dict(data)
        patient_data.update_object_path(file_path)
        return patient_data
    except Exception as e:
        logger.error(f"Failed to read file '{file_path}'." + get_traceback(e))
        return None

def save_pdata_object(patient_data: PatientData, directory: str) -> None:
    """Save a PatientData object to a JSON file in the specified directory."""
    if not isinstance(patient_data, PatientData):
        logger.error(f"Invalid patient data, expected type 'PatientData': {type(patient_data)}")
        return
    
    if not directory or not os.path.isdir(directory):
        logger.error(f"Invalid patient data directory provided: {directory}")
        return
    
    filename = f"{patient_data.MRN}_{patient_data.Name}.json"
    filepath = os.path.join(directory, filename)
    patient_data.update_object_path(filepath)
    
    # Merge with existing data if the file already exists
    if os.path.isfile(filepath):
        prev_data = load_pdata_object(filepath)
        if prev_data:
            patient_data._internal_merge(prev_data)
    
    atomic_save(
        filepath=filepath, 
        write_func=lambda file: json.dump(patient_data.to_dict(), file),
    )

def remove_pdata_object(patient_data: PatientData, directory: str) -> bool:
    """Delete a specific PatientData JSON file by MRN and Name."""
    if not isinstance(patient_data, PatientData):
        logger.error(f"Invalid patient data object provided, expected 'PatientData': {type(patient_data)}")
        return False
    
    if not directory or not os.path.isdir(directory):
        logger.error(f"Invalid or missing patient data directory: {directory}")
        return False

    filename = f"{patient_data.MRN}_{patient_data.Name}.json"
    filepath = os.path.join(directory, filename)
    
    if not os.path.isfile(filepath):
        logger.error(f"Patient data file does not exist, so it cannot be deleted: {filepath}")
        return False
    
    try:
        os.remove(filepath)
        logger.info(f"Deleted patient data file: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete patient data file: {filepath}" + get_traceback(e))
        return False

def remove_all_pdata(directory: str) -> None:
    """Delete all PatientData JSON files in the specified directory."""
    if not directory or not os.path.isdir(directory):
        logger.error(f"Invalid or missing patient data directory: {directory}")
        return
    
    try:
        json_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".json")]
    except Exception as e:
        logger.error(f"Failed to list directory {directory}." + get_traceback(e))
        return
    
    for filepath in json_files:
        try:
            os.remove(filepath)
            logger.info(f"Deleted patient data file: {filepath}")
        except Exception as e:
            logger.error(f"Failed to delete patient data file: {filepath}" + get_traceback(e))

# -----------------------------------------------------------------------------
# DicomManager Class
# -----------------------------------------------------------------------------
class DicomManager():
    """
    Manages DICOM file processing: reading metadata, linking references,
    and storing/retrieving structured PatientData objects.
    """
    def __init__(self, conf_mgr: ConfigManager, ss_mgr: SharedStateManager) -> None:
        """
        Initialize the DicomManager.

        Args:
            conf_mgr: Handles configuration settings.
            ss_mgr: Manages threading and task execution.
        """
        self.conf_mgr = conf_mgr
        self.ss_mgr = ss_mgr
        
        # Default progress callback simply logs the description.
        self.progress_callback: Callable[[int, int, str, bool], None] = (
            lambda current, total, desc, terminated=False: logger.info(desc)
        )
        
        # Event-check callbacks
        self.cleanup_check: Callable[[], bool] = (
            self.ss_mgr.cleanup_event.is_set
            if self.ss_mgr and hasattr(self.ss_mgr, "cleanup_event")
            else lambda: False
        )
        self.shutdown_check: Callable[[], bool] = (
            self.ss_mgr.shutdown_event.is_set
            if self.ss_mgr and hasattr(self.ss_mgr, "shutdown_event")
            else lambda: False
        )
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]) -> None:
        """Set a callback function for progress updates."""
        if not callable(callback):
            logger.error("Invalid progress callback provided.")
            return
        self.progress_callback = callback
    
    def get_patient_data_directory(self) -> Optional[str]:
        """Get the directory path where PatientData objects are stored."""
        if not self.conf_mgr:
            logger.error("No ConfigManager provided. Cannot update PatientData directory.")
            return None
        
        dir_path = self.conf_mgr.get_patient_objects_dir()
        if not dir_path or not os.path.isdir(dir_path):
            logger.error(f"Invalid PatientData directory: {dir_path}")
            return None
        
        return dir_path
    
    def get_num_patient_data_objects(self) -> int:
        """Get the number of PatientData objects in the patient data directory."""
        dir_path = self.get_patient_data_directory()
        if not dir_path:
            return 0
        
        try:
            json_files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.endswith(".json")]
        except Exception as e:
            logger.error(f"Failed to list directory {dir_path}." + get_traceback(e))
            return 0
        
        return len(json_files)
    
    def get_exit_status(self) -> bool:
        """Check if a cleanup or shutdown event has been triggered."""
        return self.cleanup_check() or self.shutdown_check()
    
    def delete_patient_data_object(self, pt_data_obj: PatientData) -> bool:
        """Delete a specific PatientData JSON file."""
        if not pt_data_obj or not isinstance(pt_data_obj, PatientData):
            logger.error(f"Invalid patient data object provided, expected 'PatientData': {type(pt_data_obj)}")
            return False
        
        dir_path = self.get_patient_data_directory()
        if not dir_path:
            return False
        
        return remove_pdata_object(pt_data_obj, dir_path)
    
    def delete_all_patient_data_objects(self) -> None:
        """Delete all PatientData JSON files in the patient data directory."""
        return remove_all_pdata(self.get_patient_data_directory())
    
    def _parallelized_collect_filtered_jsons(
        self,
        dir_path: str,
        subset_size: Optional[int],
        subset_idx: Optional[int],
        never_processed: Optional[bool],
        filter_names: Optional[str],
        filter_mrns: Optional[str]
    ) -> List[str]:
        """
        Dynamically scan directory and filter PatientData JSONs based on metadata,
        stopping early if subset_size is reached.
        
        File names are expected to be formatted as one of:
            "{MRN}_{LASTNAME}_{MIDDLENAME}_{FIRSTNAME}.json"
            "{MRN}_{LASTNAME}_{FIRSTNAME}.json"
        """
        try:
            json_files = [entry.path for entry in os.scandir(dir_path) if entry.is_file() and entry.name.endswith(".json")]
            
            if all(x is None for x in (subset_size, subset_idx, never_processed, filter_names, filter_mrns)):
                return json_files
            
            if filter_names:
                filter_names = filter_names.upper()
                json_files = [fp for fp in json_files if filter_names in "_".join(os.path.splitext(os.path.basename(fp))[0].split("_")[1:])]
            
            if filter_mrns:
                filter_mrns = filter_mrns.upper()
                json_files = [fp for fp in json_files if filter_mrns in os.path.splitext(os.path.basename(fp))[0].split("_")[0]]
            
            get_subset = isinstance(subset_size, int) and isinstance(subset_idx, int)
            
            if never_processed is not None:
                futures = [
                    fu for fp in json_files 
                    if (
                        not self.get_exit_status() and
                        (fu := self.ss_mgr.submit_executor_action(get_matched_pdata_file, fp, never_processed)) is not None
                    )
                ] if not self.get_exit_status() else []
                
                matched_files = []
                
                try:
                    for future in as_completed(futures):
                        if self.get_exit_status():
                            matched_files = []
                            break
                        
                        if get_subset and len(matched_files) >= (subset_idx + 1) * subset_size:
                            break
                        
                        try:
                            result = future.result()
                            if result is not None:
                                matched_files.append(result)
                        except Exception as e:
                            logger.error(f"Failed to match patient data file." + get_traceback(e))
                        finally:
                            if isinstance(future, Future) and not future.done():
                                future.cancel()
                except Exception as e:
                    logger.error(f"Failed to process futures for matching patient data files." + get_traceback(e))
                finally:
                    for future in futures:
                        if isinstance(future, Future) and not future.done():
                            future.cancel()
                
                json_files = matched_files
            
            if get_subset:
                json_files = json_files[subset_idx * subset_size : (subset_idx + 1) * subset_size]
            
            return json_files
        except Exception as e:
            logger.error(f"Failed to list directory {dir_path}." + get_traceback(e))
            return []
    
    def _parallelized_load_patient_data_objects(
        self,
        dir_path: str,
        subset_size: Optional[int] = None,
        subset_idx: Optional[int] = None,
        use_pbar: bool = True,
        never_processed: Optional[bool] = None,
        filter_names: Optional[str] = None,
        filter_mrns: Optional[str] = None
    ) -> Dict[Tuple[str, str], PatientData]:
        """Helper function to load PatientData objects in parallel. Must already have started the executor."""
        start_info = f"Loading patient data from '{dir_path}'..."
        self.progress_callback(0, 0, start_info) if use_pbar else logger.info(start_info)
        
        json_files = self._parallelized_collect_filtered_jsons(
            dir_path=dir_path,
            subset_size=subset_size,
            subset_idx=subset_idx,
            never_processed=never_processed,
            filter_names=filter_names,
            filter_mrns=filter_mrns
        )
        
        if not json_files:
            exit_info = f"No patient data found in this directory: {dir_path}"
            self.progress_callback(100, 100, exit_info, True) if use_pbar else logger.info(exit_info)
            return {}
        
        files_read = 0
        num_files = len(json_files)
        patient_data_dict: Dict[Tuple[str, str], PatientData] = {}
        futures = [
            fu for fp in json_files 
            if (
                not self.get_exit_status() and
                (fu := self.ss_mgr.submit_executor_action(load_pdata_object, fp)) is not None
            )
        ] if not self.get_exit_status() else []
        
        for future in as_completed(futures):
            if self.get_exit_status():
                break
            
            try:
                pdata_result: Optional[PatientData] = future.result()
                if pdata_result:
                    patient_data_dict[(pdata_result.MRN, pdata_result.Name)] = pdata_result
            except Exception as e:
                logger.error(f"Failed to load a patient's data." + get_traceback(e))
            finally:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
                files_read += 1
                self.progress_callback(0, files_read, start_info) if use_pbar else logger.info(start_info + f" {files_read}/{num_files}")
        
        if self.get_exit_status():
            exit_info = "Aborted loading patient data at user request!"
            self.progress_callback(100, 100, exit_info, True) if use_pbar else logger.info(exit_info)
            return {}
        
        num_patients = len(patient_data_dict)
        completed_info = f"Loaded data for {num_patients} patient(s) from {num_files} file(s)."
        self.progress_callback(0, num_patients, completed_info) if use_pbar else logger.info(completed_info)
        return patient_data_dict
    
    def _validate_can_load_data(
        self,
        dir_path: str,
        subset_size: Optional[int] = None,
        subset_idx: Optional[int] = None,
        never_processed: Optional[bool] = None,
        filter_names: Optional[str] = None,
        filter_mrns: Optional[str] = None
    ) -> bool:
        """Validate the parameters for loading patient data."""
        if not dir_path:
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid directory: {dir_path}", True)
            return False
        
        if subset_size is not None and (not isinstance(subset_size, int) or subset_size <= 0):
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid subset size: {subset_size}", True)
            return False
        
        if subset_idx is not None and (not isinstance(subset_idx, int) or subset_idx < 0):
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid subset index: {subset_idx}", True)
            return False
        
        if never_processed is not None and not isinstance(never_processed, bool):
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid never_processed value: {never_processed}", True)
            return False
        
        if filter_names is not None and not isinstance(filter_names, str):
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid filter_names value: {filter_names}", True)
            return False
        
        if filter_mrns is not None and not isinstance(filter_mrns, str):
            self.progress_callback(100, 100, f"Aborted loading patient data; invalid filter_mrns value: {filter_mrns}", True)
            return False
        
        return True
    
    def load_patient_data_objects(
        self,
        subset_size: Optional[int] = None,
        subset_idx: Optional[int] = None,
        never_processed: Optional[bool] = None,
        filter_names: Optional[str] = None,
        filter_mrns: Optional[str] = None
    ) -> Dict[Tuple[str, str], PatientData]:
        """Load PatientData objects from the patient data directory."""
        dir_path = self.get_patient_data_directory()
        if not self._validate_can_load_data(dir_path, subset_size, subset_idx, never_processed, filter_names, filter_mrns):
            return {}
        
        patient_data_dict: Dict[Tuple[str, str], PatientData] = {}
        
        # Start the executor for parallel processing
        self.ss_mgr.startup_executor(use_process_pool=False)
        try:
            patient_data_dict = self._parallelized_load_patient_data_objects(
                dir_path=dir_path,
                subset_size=subset_size,
                subset_idx=subset_idx,
                use_pbar=False,
                never_processed=never_processed,
                filter_names=filter_names,
                filter_mrns=filter_mrns
            )
        except Exception as e:
            self.progress_callback(100, 100, f"Failure in loading patient data!" + get_traceback(e), True)
        finally:
            self.ss_mgr.shutdown_executor()
        
        return patient_data_dict
    
    def _validate_can_process(self, dicom_dir: str, chunk_size: int, patient_data_dir: Optional[str]) -> bool:
        """Validate the DICOM directory and chunk size."""
        if not dicom_dir or not os.path.isdir(dicom_dir):
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid DICOM directory: {dicom_dir}")
            return False
        
        if not chunk_size or not isinstance(chunk_size, int) or chunk_size <= 0:
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid chunk size: {chunk_size}")
            return False
        
        if not patient_data_dir:
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid patient data directory: {patient_data_dir}")
            return False
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted DICOM processing task at user request!", terminated=True)
            return False
        
        return True
    
    def _parallelized_dicom_search(self, dicom_dir: str, chunk_size: int) -> List[str]:
        """Helper function to search for DICOM files in parallel. Must already have started the executor."""
        if self.get_exit_status():
            return []
        
        start_text = "(Step 1/3) Searching for DICOM files..."
        self.progress_callback(0, 0, start_text)
        
        dicom_files = []
        futures = [
            fu for subdir in collect_independent_subdirs(dicom_dir, min_paths=chunk_size)
            if (
                not self.get_exit_status() and
                (fu := self.ss_mgr.submit_executor_action(scan_folder_for_dicom, subdir)) is not None
            )
        ] if not self.get_exit_status() else []
        for future in as_completed(futures):
            if self.get_exit_status():
                break
            
            try:
                result = future.result()
                if isinstance(result, list):
                    dicom_files.extend(result)
            except Exception as e:
                logger.error(f"Failed to scan a folder for DICOM files." + get_traceback(e))
            finally:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
                self.progress_callback(0, len(dicom_files), start_text)
        
        if self.get_exit_status():
            return []
        
        if not dicom_files:
            self.progress_callback(100, 100, f"(Step 1/3) No DICOM files found in: {dicom_dir}", True)
        else:
            self.progress_callback(0, len(dicom_files), f"(Step 1/3) Found {len(dicom_files)} DICOM files in '{dicom_dir}'")
        
        return sorted(dicom_files, key=os.path.dirname)
    
    def _parallelized_dicom_short_read(self, dicom_files: List[str], chunk_size: int) -> Dict[Tuple[str, str], PatientData]:
        """Helper function to read DICOM metadata in parallel. Must already have started the executor."""
        if not dicom_files or self.get_exit_status():
            return {}
        
        num_dcm_files = len(dicom_files)
        start_text = "(Step 2/3) Reading DICOM metadata..."
        self.progress_callback(0, num_dcm_files, start_text)
        
        processed_count = 0
        patient_data_dict: Dict[Tuple[str, str], PatientData] = {}
        
        for chunk in chunked_iterable(iter(dicom_files), chunk_size):
            if not chunk or self.get_exit_status():
                break
            
            futures = [
                fu for fp in chunk 
                if (
                    not self.get_exit_status() and
                    (fu := self.ss_mgr.submit_executor_action(read_dicom_metadata, fp)) is not None
                )
            ] if not self.get_exit_status() else []
            
            chunk_item_count = 0
            for future in as_completed(futures):
                if self.get_exit_status():
                    break
                
                try:
                    result = future.result()
                    if result:
                        add_dicom_to_patient_data(patient_data_dict, *result)
                except Exception as e:
                    logger.error(f"Failed to process DICOM metadata." + get_traceback(e))
                finally:
                    if isinstance(future, Future) and not future.done():
                        future.cancel()
                    chunk_item_count += 1
                    processed_count += 1
                    if processed_count % 100 == 0:
                        self.progress_callback(min(processed_count, num_dcm_files - 1), num_dcm_files, start_text)
        
        if self.get_exit_status():
            return {}
        
        if not patient_data_dict:
            self.progress_callback(100, 100, f"(Step 2/3) No DICOM metadata found in: {dicom_files}", True)
        else:
            self.progress_callback(0, len(patient_data_dict), f"(Step 2/3) Found {len(patient_data_dict)} patients in the {num_dcm_files} DICOM files.")
        
        return patient_data_dict
    
    def _parallelized_patient_data_save(self, patient_data_dict: Dict[Tuple[str, str], PatientData], patient_data_dir: str) -> None:
        """Helper function to save PatientData objects in parallel."""
        if not patient_data_dict:
            self.progress_callback(100, 100, f"Aborted saving patient data; no patients found.", True)
            return
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted saving patient data at user request!", True)
            return
        
        num_patients = len(patient_data_dict)
        start_text = "(Step 3/3) Saving patient data..."
        self.progress_callback(0, num_patients, start_text)
        
        futures = [
                fu for patient in patient_data_dict.values() 
                if (
                    not self.get_exit_status() and
                    (fu := self.ss_mgr.submit_executor_action(save_pdata_object, patient, patient_data_dir)) is not None
                )
            ] if not self.get_exit_status() else []
        
        processed_count = 0
        for future in as_completed(futures):
            if self.get_exit_status():
                break
            
            try:
                future.result()
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to save patient data." + get_traceback(e))
            finally:
                if isinstance(future, Future) and not future.done():
                    future.cancel()
                self.progress_callback(min(processed_count, num_patients - 1), num_patients, start_text)
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted saving patient data at user request!", True)
            return
        
        if processed_count > 0 and processed_count == num_patients:
            self.progress_callback(num_patients, num_patients, f"Completed saving data for {num_patients} patients.")
        else:
            self.progress_callback(processed_count, num_patients, f"Completed saving patient data, but encountered issue(s). See log.", True)
    
    def process_dicom_directory(self, dicom_dir: str, chunk_size: int = 10000) -> None:
        """Search for DICOM files in a directory, read their metadata, and save them as PatientData objects."""
        patient_data_dir = self.get_patient_data_directory()
        if not self._validate_can_process(dicom_dir, chunk_size, patient_data_dir):
            return
        
        # Start the executor for parallel processing
        self.ss_mgr.startup_executor(use_process_pool=False)
        
        try:
            # Step 1: Parallelize DICOM file search
            dicom_files = self._parallelized_dicom_search(dicom_dir, chunk_size)
            
            # Step 2: Parallelize DICOM metadata reading
            patient_data_dict = self._parallelized_dicom_short_read(dicom_files, chunk_size)
            
            # Step 3: Parallelize saving PatientData objects & provide final feedback
            self._parallelized_patient_data_save(patient_data_dict, patient_data_dir)
        except Exception as e:
            self.progress_callback(100, 100, "Failure in processing DICOM files!" + get_traceback(e), True)
        finally:
            self.ss_mgr.shutdown_executor()
    
    def _parallelized_linking(self, patient_objects: Dict[Tuple[str, str], PatientData], patient_data_dir: str) -> None:
        """Helper function to link DICOM references in parallel."""
        if not patient_objects: 
            self.progress_callback(100, 100, f"Aborted linking DICOMs; no patients found.", True)
            return
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted linking DICOMs at user request!", True)
            return
        
        num_patients = len(patient_objects)
        start_text = "Building DICOM references for each patient..."
        self.progress_callback(0, num_patients, start_text)
        
        completed_patients = 0
        for patient in patient_objects.values():
            if self.get_exit_status():
                break

            references: Dict[str, Any] = {}
            try:
                futures = [
                    fu for fp in patient.return_filepaths() 
                    if 
                    (
                        not self.get_exit_status() and
                        (fu := self.ss_mgr.submit_executor_action(link_dicom_references, fp)) is not None
                    )
                ] if not self.get_exit_status() else []
                
                for future in as_completed(futures):
                    if self.get_exit_status():
                        break
                    try:
                        ref_result = future.result()
                        references.update(ref_result)
                    except Exception as e:
                        logger.error(f"Failed to process DICOM references." + get_traceback(e))
                    finally:
                        if isinstance(future, Future) and not future.done():
                            future.cancel()
                
                if references:
                    patient.update_dicom_file_references_dict(references)
                    save_pdata_object(patient, patient_data_dir)
                else:
                    logger.warning(f"No DICOM references found for patient {patient.MRN} ({patient.Name})")
                
                completed_patients += 1
            except Exception as e:
                logger.error(f"Failed to process a patient's DICOM references." + get_traceback(e))
            finally:
                self.progress_callback(min(completed_patients, num_patients - 1), num_patients, "Building DICOM references...")
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted linking DICOMs at user request!", True)
            return
        
        if completed_patients > 0 and completed_patients == num_patients:
            self.progress_callback(num_patients, num_patients, f"Completed linking DICOM references for {num_patients} patient(s).")
        else:
            self.progress_callback(completed_patients, num_patients, f"Completed linking DICOM references, but encountered issue(s). See log.", True)
    
    def link_all_dicoms(self) -> None:
        """Build references for all PatientData objects and update their JSON files."""
        patient_data_dir = self.get_patient_data_directory()
        if not patient_data_dir:
            self.progress_callback(100, 100, f"Aborted linking DICOMs; invalid patient data directory: {patient_data_dir}", True)
            return
        
        # Start the executor for parallel processing
        self.ss_mgr.startup_executor(use_process_pool=False)
        try:
            # Step 1: Parallelize loading PatientData objects
            patient_objects = self._parallelized_load_patient_data_objects(patient_data_dir)
            
            # Step 2: Parallelize the linking of DICOM references & provide final feedback
            self._parallelized_linking(patient_objects, patient_data_dir)
        except Exception as e:
            self.progress_callback(100, 100, "Failure in linking DICOM references!" + get_traceback(e), True)
        finally:
            self.ss_mgr.shutdown_executor()
