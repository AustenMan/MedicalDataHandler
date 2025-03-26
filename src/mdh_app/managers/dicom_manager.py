import os
import json
import logging
import pydicom
from pydicom.tag import Tag
from time import time
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
def find_dicom_files(
    directory: str,
    check_exit: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Set[str]:
    """Recursively find all DICOM (.dcm) files in the specified directory."""
    check_exit = check_exit or (lambda: False)
    progress_callback = progress_callback or (lambda current, total, text, terminated: logger.info(text))
    
    dicom_files: Set[str] = set()
    dcm_suffix = ".dcm"
    
    # Speed up by avoiding repeated function lookups
    join_fn = os.path.join
    lower_fn = str.lower
    endswith_fn = str.endswith
    dcm_add_fn = dicom_files.add
    
    # Walk through the directory to find all DICOM files
    for dirpath, _, filenames in os.walk(directory):
        progress_callback(0, len(dicom_files), f"Searching for DICOMs: {dirpath}")
        for filename in filenames:
            if check_exit():
                return set()
            if endswith_fn(lower_fn(filename), dcm_suffix):
                dcm_add_fn(join_fn(dirpath, filename))
    
    return dicom_files

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

def read_dicom_metadata_worker(filepath: str) -> Optional[Tuple[str, str, str, str, str, str]]:
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

def link_dicom_references_worker(filepath: str) -> Dict[str, Any]:
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

def return_patient_data_objects_count(directory: str) -> int:
    """Returns the number of patient data objects in the directory."""
    if not directory or not os.path.isdir(directory):
        logger.error(f"Invalid patient data directory provided: {directory}")
        return 0
    
    try:
        json_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".json")]
    except Exception as e:
        logger.error(f"Failed to list directory {directory}." + get_traceback(e))
        return 0
    
    return len(json_files)

def load_patient_data_objects(
    directory: str,
    check_exit: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    subset_size: Optional[int] = None,
    subset_idx: Optional[int] = None
) -> Dict[Tuple[str, str], PatientData]:
    """Load all PatientData objects from JSON files in the given directory."""
    if not directory or not os.path.isdir(directory):
        logger.error(f"Invalid patient data directory provided: {directory}")
        return {}
    
    check_exit = check_exit or (lambda: False)
    patient_data_dict: Dict[Tuple[str, str], PatientData] = {}
    
    try:
        json_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".json")]
    except Exception as e:
        logger.error(f"Failed to list directory {directory}." + get_traceback(e))
        return {}
    
    if isinstance(subset_size, int) and isinstance(subset_idx, int):
        if subset_size <= 0 or subset_idx < 0:
            logger.error(f"Invalid subset size or index: {subset_size}, {subset_idx}")
            return {}
        json_files = json_files[subset_idx * subset_size : (subset_idx + 1) * subset_size]
    
    if progress_callback is not None:
        progress_callback(0, 0, "Loading patient data from found files...")
    
    files_read = 0
    for filepath in json_files:
        if check_exit():
            return {}
        try:
            with open(filepath, "r") as file:
                data = json.load(file)
            patient_data = PatientData.from_dict(data)
            patient_data.update_object_path(filepath)
            patient_data_dict[(patient_data.MRN, patient_data.Name)] = patient_data
        except Exception as e:
            logger.error(f"Failed to read file '{filepath}'." + get_traceback(e))
        finally:
            files_read += 1
            if progress_callback is not None:
                progress_callback(0, files_read, "Loading patient data from found files...")
    
    return patient_data_dict

def save_patient_data_object(patient_data: PatientData, directory: str) -> None:
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
    
    atomic_save(
        filepath=filepath, 
        write_func=lambda file: json.dump(patient_data.to_dict(), file),
    )

def remove_patient_data(patient_data: PatientData, directory: str) -> bool:
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

def remove_all_patient_data(directory: str) -> None:
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
        self.progress_callback: Callable[[int, int, str], None] = lambda current, total, desc, terminated: logger.info(desc)
        
        # Use is_set() to check events.
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
        
        self.patient_data_dir: Optional[str] = None
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]) -> None:
        """Set a callback function for progress updates."""
        if not callable(callback):
            logger.error("Invalid progress callback provided.")
            return
        self.progress_callback = callback
    
    def update_patient_data_directory(self) -> None:
        """Update the directory path where PatientData objects are stored."""
        if not self.conf_mgr:
            logger.error("No ConfigManager provided. Cannot update PatientData directory.")
            self.patient_data_dir = None
            return
        
        dir_path = self.conf_mgr.get_patient_objects_dir()
        if not dir_path or not os.path.isdir(dir_path):
            logger.error(f"Invalid PatientData directory: {dir_path}")
            self.patient_data_dir = None
            return
        
        self.patient_data_dir = dir_path
    
    def get_patient_data_directory(self) -> Optional[str]:
        """Get the directory path where PatientData objects are stored."""
        self.update_patient_data_directory()
        return self.patient_data_dir
    
    def get_patient_data_objects(self, subset_size: Optional[int], subset_idx: Optional[int]) -> Optional[Dict[Tuple[str, str], PatientData]]:
        """Load PatientData objects from JSON files in the patient data directory."""
        dir_path = self.get_patient_data_directory()
        return load_patient_data_objects(dir_path, self.get_exit_status, None, subset_size, subset_idx)
    
    def get_num_patient_data_objects(self) -> int:
        """Get the number of PatientData objects in the patient data directory."""
        dir_path = self.get_patient_data_directory()
        return return_patient_data_objects_count(dir_path)
    
    def get_exit_status(self, update_progress: bool = True) -> bool:
        """Check if a cleanup or shutdown event has been triggered."""
        should_exit = self.cleanup_check() or self.shutdown_check()
        if should_exit and update_progress:
            self.progress_callback(0, 0, "Aborting the current task...", terminated=True)
        return should_exit
    
    def delete_patient_data_object(self, pt_data_obj: PatientData) -> bool:
        """Delete a specific PatientData JSON file."""
        if not pt_data_obj or not isinstance(pt_data_obj, PatientData):
            logger.error(f"Invalid patient data object provided, expected 'PatientData': {type(pt_data_obj)}")
            return False
        
        return remove_patient_data(pt_data_obj, self.get_patient_data_directory())
    
    def delete_all_patient_data_objects(self) -> None:
        """Delete all PatientData JSON files in the patient data directory."""
        return remove_all_patient_data(self.get_patient_data_directory())
    
    def process_dicom_directory(self, dicom_dir: str) -> None:
        """Search for DICOM files in a directory, read their metadata, and save them as PatientData objects."""
        self.progress_callback(0, 0, "Ready to find DICOM files. Please select a valid directory.")
        
        if not dicom_dir or not os.path.isdir(dicom_dir):
            self.progress_callback(0, 0, f"Invalid DICOM directory: {dicom_dir}")
            return
        
        patient_data_dir = self.get_patient_data_directory()
        if not patient_data_dir:
            self.progress_callback(0, 0, f"Task aborted. The patient data directory is invalid: {patient_data_dir}")
            return
        
        if self.get_exit_status():
            return
        
        self.progress_callback(0, 0, f"Searching for DICOM files in '{dicom_dir}'...")
        dicom_files = find_dicom_files(dicom_dir, self.get_exit_status, self.progress_callback)
        
        if not dicom_files:
            self.progress_callback(0, 0, f"No DICOM files found in: {dicom_dir}")
            return
        
        if self.get_exit_status():
            return
        
        total_found = len(dicom_files)
        self.progress_callback(0, total_found, f"Found {total_found} files. Validating against known files...")
        existing_data = load_patient_data_objects(patient_data_dir, self.get_exit_status, None)
        # Exclude already processed files.
        dicom_files.difference_update({fp for patient in existing_data.values() for fp in patient.return_filepaths()})
        remaining_files = len(dicom_files)
        
        if remaining_files == 0:
            self.progress_callback(total_found, total_found, "No new DICOM files to process.")
            return
        
        dicom_files = sorted(dicom_files, key=lambda x: os.path.dirname(x))
        self.ss_mgr.startup_executor(use_process_pool=False)
        chunk_size = 10000
        processed_count = 0
        
        self.progress_callback(0, remaining_files, f"Processing {remaining_files} new DICOM files...")
        
        for chunk in chunked_iterable(iter(dicom_files), chunk_size):
            if not chunk or self.get_exit_status(update_progress=False):
                break
            
            submit_start = time()
            
            futures = [fu for fp in chunk if (fu := self.ss_mgr.submit_executor_action(read_dicom_metadata_worker, fp)) is not None]
            for future in as_completed(futures):
                if self.get_exit_status(update_progress=False):
                    break
                try:
                    result = future.result()
                    if result:
                        add_dicom_to_patient_data(existing_data, *result)
                except Exception as e:
                    logger.error(f"Falied to process DICOM metadata." + get_traceback(e))
                finally:
                    if isinstance(future, Future) and not future.done():
                        future.cancel()
                    processed_count += 1
                    if processed_count % 100 == 0:
                        self.progress_callback(min(processed_count, remaining_files - 1), remaining_files, "Processing DICOM files...")
            
            submit_end = time()
            logger.info(f"Processed {len(chunk)} files in {submit_end - submit_start:.3f} seconds")
        
        self.ss_mgr.shutdown_executor()
        
        if self.get_exit_status(update_progress=False):
            self.progress_callback(processed_count, remaining_files, f"Task aborted early! Didn't save any of the files.", True)
            return
        
        for ii, patient in enumerate(existing_data.values()):
            if self.get_exit_status(update_progress=False):
                self.progress_callback(processed_count, remaining_files, f"Task aborted early! Only saved {ii} out of {len(existing_data)} patients.", True)
                return
            save_patient_data_object(patient, patient_data_dir)
        
        self.progress_callback(remaining_files, remaining_files, f"Completed processing {processed_count} out of {remaining_files} files.")
    
    def link_all_dicoms(self) -> None:
        """Build references for all PatientData objects and update their JSON files."""
        patient_data_dir = self.get_patient_data_directory()
        if not patient_data_dir:
            self.progress_callback(0, 0, f"Task aborted. The patient data directory is invalid: {patient_data_dir}")
            return
        
        patient_objects = load_patient_data_objects(patient_data_dir, self.get_exit_status, self.progress_callback)
        if not patient_objects:
            self.progress_callback(0, 0, f"No patient data found for linking in this directory: {patient_data_dir}") 
            return
        
        total_objects = len(patient_objects)
        completed_objects = 0
        self.progress_callback(0, total_objects, "Starting to read DICOM files and find their references...")
        self.ss_mgr.startup_executor(use_process_pool=False)
        
        for patient in patient_objects.values():
            if not isinstance(patient, PatientData):
                self.progress_callback(completed_objects, total_objects, f"Invalid patient data object, expected 'PatientData': {type(patient)}")
                continue
            
            if self.get_exit_status(update_progress=False):
                break

            references: Dict[str, Any] = {}
            try:
                futures = [fu for fp in patient.return_filepaths() if (fu := self.ss_mgr.submit_executor_action(link_dicom_references_worker, fp)) is not None]
                for future in as_completed(futures):
                    if self.get_exit_status(update_progress=False):
                        break
                    try:
                        ref_result = future.result()
                        references.update(ref_result)
                    except Exception as e:
                        logger.error(f"Falied to process DICOM references." + get_traceback(e))
                    finally:
                        if isinstance(future, Future) and not future.done():
                            future.cancel()
                
                if self.get_exit_status(update_progress=False):
                    break
                
                patient.update_dicom_file_references_dict(references)
                save_patient_data_object(patient, patient_data_dir)
            except Exception as e:
                logger.error(f"Falied to process patient DICOM references." + get_traceback(e))
            finally:
                completed_objects += 1
                self.progress_callback(min(completed_objects, total_objects - 1), total_objects, "Building DICOM references...")
        
        self.ss_mgr.shutdown_executor()
        
        if completed_objects == total_objects:
            self.progress_callback(total_objects, total_objects, f"Completed linking references for {completed_objects} out of {total_objects} patients.")
        else:
            prepend_text = "Task aborted early! Only saved" if self.get_exit_status(update_progress=False) else "Finished processing, could only save"
            self.progress_callback(completed_objects, total_objects, prepend_text + f"{completed_objects} out of {total_objects} patients.", True)

