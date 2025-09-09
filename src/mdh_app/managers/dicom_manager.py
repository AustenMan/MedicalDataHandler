from __future__ import annotations


import os
import logging
from json import dumps
from datetime import datetime
from concurrent.futures import as_completed, Future
from typing import TYPE_CHECKING, Callable, Optional, Dict, List, Any, Sequence, Tuple


import pydicom
from pydicom.tag import Tag
from sqlalchemy import select, or_, delete
from sqlalchemy.exc import IntegrityError


from mdh_app.database.db_session import get_session
from mdh_app.database.models import Patient, File, FileMetadata, FileMetadataOverride
from mdh_app.utils.dicom_utils import get_ds_tag_value, get_first_available_tag
from mdh_app.utils.general_utils import get_traceback, chunked_iterable


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# DICOM Tag Constants
# -----------------------------------------------------------------------------


# General tags
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


# Label tags
TAG_RT_PLAN_LABEL = Tag(0x300A, 0x0002)
TAG_STRUCTURE_SET_LABEL = Tag(0x3006, 0x0002)
TAG_RT_IMAGE_LABEL = Tag(0x3002, 0x0002)
LABEL_DICOM_TAGS = [TAG_RT_PLAN_LABEL, TAG_STRUCTURE_SET_LABEL, TAG_RT_IMAGE_LABEL]


# Name tags
TAG_RT_PLAN_NAME = Tag(0x300A, 0x0003)
TAG_STRUCTURE_SET_NAME = Tag(0x3006, 0x0004)
TAG_RT_IMAGE_NAME = Tag(0x3002, 0x0003)
NAME_DICOM_TAGS = [TAG_RT_PLAN_NAME, TAG_STRUCTURE_SET_NAME, TAG_RT_IMAGE_NAME]

# Description tags
TAG_RT_DOSE_COMMENT = Tag(0x3004, 0x0006)
TAG_IMAGE_COMMENTS = Tag(0x0020, 0x4000)
TAG_RT_PLAN_DESCRIPTION = Tag(0x300A, 0x0004)
TAG_STRUCTURE_SET_DESCRIPTION = Tag(0x3006, 0x0006)
TAG_SERIES_DESCRIPTION = Tag(0x0008, 0x103E)
TAG_RT_IMAGE_DESCRIPTION = Tag(0x3002, 0x0004)
TAG_STUDY_DESCRIPTION = Tag(0x0008, 0x1030)
DESCRIPTION_DICOM_TAGS = [
    TAG_RT_DOSE_COMMENT, TAG_IMAGE_COMMENTS, TAG_RT_PLAN_DESCRIPTION, TAG_STRUCTURE_SET_DESCRIPTION,
    TAG_SERIES_DESCRIPTION, TAG_RT_IMAGE_DESCRIPTION, TAG_STUDY_DESCRIPTION
]


# Date tags
TAG_RT_PLAN_DATE = Tag(0x300A, 0x0006)
TAG_STRUCTURE_SET_DATE = Tag(0x3006, 0x0008)
TAG_CONTENT_DATE = Tag(0x0008, 0x0023)
TAG_SERIES_DATE = Tag(0x0008, 0x0021)
TAG_STUDY_DATE = Tag(0x0008, 0x0020)
DATE_DICOM_TAGS = [
    TAG_RT_PLAN_DATE, TAG_STRUCTURE_SET_DATE, TAG_CONTENT_DATE, TAG_SERIES_DATE, TAG_STUDY_DATE
]


# Time tags
TAG_RT_PLAN_TIME = Tag(0x300A, 0x0007)
TAG_STRUCTURE_SET_TIME = Tag(0x3006, 0x0009)
TAG_CONTENT_TIME = Tag(0x0008, 0x0033)
TAG_SERIES_TIME = Tag(0x0008, 0x0031)
TAG_STUDY_TIME = Tag(0x0008, 0x0030)
TIME_DICOM_TAGS = [
    TAG_RT_PLAN_TIME, TAG_STRUCTURE_SET_TIME, TAG_CONTENT_TIME, TAG_SERIES_TIME, TAG_STUDY_TIME
]


# All tags that the worker should read
LINK_WORKER_DICOM_TAGS = [
    TAG_PATIENT_ID, TAG_PATIENTS_NAME, TAG_FRAME_OF_REFERENCE_UID, TAG_MODALITY, TAG_DOSE_SUMMATION_TYPE,
    TAG_SERIES_INSTANCE_UID, TAG_SOP_CLASS_UID, TAG_SOP_INSTANCE_UID, TAG_REFERENCED_SOP_CLASS_UID,
    TAG_REFERENCED_SOP_INSTANCE_UID, TAG_REFERENCED_RT_PLAN_SEQUENCE, TAG_REFERENCED_STRUCTURE_SET_SEQUENCE,
    TAG_REFERENCED_DOSE_SEQUENCE, TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE, TAG_RT_REFERENCED_STUDY_SEQUENCE,
    TAG_RT_REFERENCED_SERIES_SEQUENCE,
] + LABEL_DICOM_TAGS + NAME_DICOM_TAGS + DESCRIPTION_DICOM_TAGS + DATE_DICOM_TAGS + TIME_DICOM_TAGS


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def collect_independent_subdirs(base_dir: str, min_paths: int) -> List[str]:
    """Collect subdirectories under base_dir, preferring shallow directories first."""
    if not os.path.isdir(base_dir):
        return []
    
    dirs = [subdir for d in os.listdir(base_dir) if (subdir := os.path.join(base_dir, d)) and os.path.isdir(subdir)]
    
    if any(f.lower().endswith(".dcm") and os.path.isfile(os.path.join(base_dir, f)) for f in os.listdir(base_dir)):
        # If there are DICOM files in the base directory, add it as a candidate
        dirs.append(base_dir)
    
    i = 0
    while len(dirs) < min_paths and i < len(dirs):
        current = dirs[i]
        try:
            children = [child_dir for d in os.listdir(current) if (child_dir := os.path.join(current, d)) and os.path.isdir(child_dir)]
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


def read_dicom_metadata(file_path: str) -> Dict[str, Any]:
    """Read essential metadata from a DICOM file."""
    try:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True, force=True, specific_tags=LINK_WORKER_DICOM_TAGS)
    except Exception as e:
        logger.error(f"Failed to read DICOM file {file_path}." + get_traceback(e))
        return {}

    # Basic tags
    patient_id          = get_ds_tag_value(ds, TAG_PATIENT_ID,          reformat_str=True)
    patient_name        = get_ds_tag_value(ds, TAG_PATIENTS_NAME,       reformat_str=True)
    frame_of_reference_uid = get_ds_tag_value(ds, TAG_FRAME_OF_REFERENCE_UID)
    modality            = get_ds_tag_value(ds, TAG_MODALITY)
    sop_instance_uid    = get_ds_tag_value(ds, TAG_SOP_INSTANCE_UID)
    sop_class_uid       = get_ds_tag_value(ds, TAG_SOP_CLASS_UID)
    dose_summation_type = get_ds_tag_value(ds, TAG_DOSE_SUMMATION_TYPE)
    series_instance_uid = get_ds_tag_value(ds, TAG_SERIES_INSTANCE_UID)
    
    # Multi-option tags
    label       = get_first_available_tag(ds, LABEL_DICOM_TAGS, reformat_str=True)
    name        = get_first_available_tag(ds, NAME_DICOM_TAGS, reformat_str=True)
    description = get_first_available_tag(ds, DESCRIPTION_DICOM_TAGS, reformat_str=True)
    date        = get_first_available_tag(ds, DATE_DICOM_TAGS)
    time        = get_first_available_tag(ds, TIME_DICOM_TAGS)
    
    # Fallback to referenced Frame of Reference UIDs if Frame of Reference UID is not found
    if not frame_of_reference_uid:
        ref_seq = ds.get(TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE)
        if ref_seq:
            referenced_uids = {
                uid for item in ref_seq 
                if (uid := get_ds_tag_value(item, TAG_FRAME_OF_REFERENCE_UID)) is not None
            }
            if referenced_uids:
                sorted_uids = sorted(referenced_uids)
                if len(sorted_uids) > 1:
                    logger.warning(f"Multiple Referenced Frame of Reference UIDs found for {sop_instance_uid} in {file_path}. Using first one: {sorted_uids}")
                frame_of_reference_uid = sorted_uids[0]

    required = (patient_id, patient_name, frame_of_reference_uid, modality, sop_instance_uid)
    if None in required:
        logger.warning(
            f"Incomplete DICOM header in file: {file_path} ... Found PatientID={patient_id}, PatientName={patient_name}, FrameOfReferenceUID={frame_of_reference_uid}, "
            f"Modality={modality}, SOPInstanceUID={sop_instance_uid}"
        )
        return {}
    
    metadata: Dict[str, Any] = {
        "file_path": file_path,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "frame_of_reference_uid": frame_of_reference_uid,
        "modality": modality,
        "sop_instance_uid": sop_instance_uid,
        "sop_class_uid": sop_class_uid,
        "dose_summation_type": dose_summation_type,
        "series_instance_uid": series_instance_uid,
        "label": label,
        "name": name,
        "description": description,
        "date": date,
        "time": time,
        "referenced_sop_class_uid_seq": [],
        "referenced_sop_instance_uid_seq": [],
        "referenced_frame_of_reference_uid_seq": [],
        "referenced_series_instance_uid_seq": [],
        "referenced_rt_plan_sopi_seq": [],
        "referenced_rt_plan_sopc_seq": [],
        "referenced_structure_set_sopi_seq": [],
        "referenced_structure_set_sopc_seq": [],
        "referenced_dose_sopi_seq": [],
        "referenced_dose_sopc_seq": [],
    }
    
    # Direct referenced tags
    referenced_sop_class_uid = get_ds_tag_value(ds, TAG_REFERENCED_SOP_CLASS_UID)
    if referenced_sop_class_uid and referenced_sop_class_uid not in metadata["referenced_sop_class_uid_seq"]:
        metadata["referenced_sop_class_uid_seq"].append(referenced_sop_class_uid)
    
    referenced_sop_instance_uid = get_ds_tag_value(ds, TAG_REFERENCED_SOP_INSTANCE_UID)
    if referenced_sop_instance_uid and referenced_sop_instance_uid not in metadata["referenced_sop_instance_uid_seq"]:
        metadata["referenced_sop_instance_uid_seq"].append(referenced_sop_instance_uid)
    
    # Process Referenced Frame of Reference Sequence
    ref_for_seq = ds.get(TAG_REFERENCED_FRAME_OF_REFERENCE_SEQUENCE)
    if ref_for_seq:
        for item in ref_for_seq:
            item_for_uid = get_ds_tag_value(item, TAG_FRAME_OF_REFERENCE_UID)
            if item_for_uid and item_for_uid not in metadata["referenced_frame_of_reference_uid_seq"]:
                metadata["referenced_frame_of_reference_uid_seq"].append(item_for_uid)
            
            # Use proper constant for RT Referenced Study Sequence
            rt_ref_study_seq = item.get(TAG_RT_REFERENCED_STUDY_SEQUENCE)
            if rt_ref_study_seq:
                for study_item in rt_ref_study_seq:
                    item_sopc = get_ds_tag_value(study_item, TAG_REFERENCED_SOP_CLASS_UID)
                    if item_sopc and item_sopc not in metadata["referenced_sop_class_uid_seq"]:
                        metadata["referenced_sop_class_uid_seq"].append(item_sopc)
                    item_sopi = get_ds_tag_value(study_item, TAG_REFERENCED_SOP_INSTANCE_UID)
                    if item_sopi and item_sopi not in metadata["referenced_sop_instance_uid_seq"]:
                        metadata["referenced_sop_instance_uid_seq"].append(item_sopi)

                    rt_ref_series_seq = study_item.get(TAG_RT_REFERENCED_SERIES_SEQUENCE)
                    if rt_ref_series_seq:
                        for series_item in rt_ref_series_seq:
                            series_uid = get_ds_tag_value(series_item, TAG_SERIES_INSTANCE_UID)
                            if series_uid and series_uid not in metadata["referenced_series_instance_uid_seq"]:
                                metadata["referenced_series_instance_uid_seq"].append(series_uid)

    # Process additional sequences: RT Plan, Structure Set, and Dose
    for sopc_key, sopi_key, seq_tag in [
        ("referenced_rt_plan_sopc_seq", "referenced_rt_plan_sopi_seq", TAG_REFERENCED_RT_PLAN_SEQUENCE),
        ("referenced_structure_set_sopc_seq", "referenced_structure_set_sopi_seq", TAG_REFERENCED_STRUCTURE_SET_SEQUENCE),
        ("referenced_dose_sopc_seq", "referenced_dose_sopi_seq", TAG_REFERENCED_DOSE_SEQUENCE),
    ]:
        seq = ds.get(seq_tag)
        if not seq:
            continue
        for item in seq:
            sopc = get_ds_tag_value(item, TAG_REFERENCED_SOP_CLASS_UID)
            if sopc and sopc not in metadata[sopc_key]:
                metadata[sopc_key].append(sopc)
            sopi = get_ds_tag_value(item, TAG_REFERENCED_SOP_INSTANCE_UID)
            if sopi and sopi not in metadata[sopi_key]:
                metadata[sopi_key].append(sopi)
                    
    return metadata


# -----------------------------------------------------------------------------
# DicomManager Class
# -----------------------------------------------------------------------------


class DicomManager():
    """Manages DICOM file processing and database operations."""
    def __init__(self, conf_mgr: ConfigManager, ss_mgr: SharedStateManager) -> None:
        """Initialize DICOM manager with configuration and state managers."""
        self.conf_mgr = conf_mgr
        self.ss_mgr = ss_mgr
        self.anonymize = False # Disabled for now
        
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
    
    def get_exit_status(self) -> bool:
        """Check if a cleanup or shutdown event has been triggered."""
        return self.cleanup_check() or self.shutdown_check()
        
    def process_dicom_directory(self, dicom_dir: str, chunk_size: int = 10_000) -> None:
        """Process DICOM directory with parallel discovery and metadata extraction."""
        if self.get_exit_status():
            return

        db_path = self.conf_mgr.get_database_path()
        if not self._validate_can_process(dicom_dir, chunk_size, db_path):
            return

        self.ss_mgr.startup_executor(use_process_pool=False)

        try:
            files = self._discover_dicoms(dicom_dir, chunk_size)
            self._parse_dicom_headers(files, chunk_size)
        except Exception as e:
            self.progress_callback(100, 100, "Failure in processing DICOM files!" + get_traceback(e), True)
        finally:
            self.ss_mgr.shutdown_executor()
    
    def _validate_can_process(self, dicom_dir: str, chunk_size: int, db_path: Optional[str]) -> bool:
        """Validate the DICOM directory and chunk size."""
        if not dicom_dir or not os.path.isdir(dicom_dir):
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid DICOM directory: {dicom_dir}")
            return False
        
        if not chunk_size or not isinstance(chunk_size, int) or chunk_size <= 0:
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid chunk size: {chunk_size}")
            return False
        
        if not db_path:
            self.progress_callback(100, 100, f"Aborted DICOM processing task; invalid database path: {db_path}")
            return False
        
        if self.get_exit_status():
            self.progress_callback(100, 100, "Aborted DICOM processing task at user request!", terminated=True)
            return False
        
        return True
    
    def _discover_dicoms(self, dicom_dir: str, chunk_size: int) -> List[str]:
        """Search for DICOM files in parallel."""
        if self.get_exit_status():
            return []
        
        start_text = "(Step 1/2) Searching for DICOM files..."
        self.progress_callback(0, 0, start_text)
        
        futures = [
            fu for found_dir in collect_independent_subdirs(dicom_dir, min_paths=chunk_size)
            if (
                not self.get_exit_status() and
                (fu := self.ss_mgr.submit_executor_action(scan_folder_for_dicom, found_dir)) is not None
            )
        ] if not self.get_exit_status() else []
        
        dicom_files = []
        for fu in as_completed(futures):
            if self.get_exit_status():
                break
            try:
                result = fu.result()
                if isinstance(result, list):
                    dicom_files.extend(result)
            except Exception as e:
                logger.error(f"Failed to scan a folder for DICOM files." + get_traceback(e))
            finally:
                if isinstance(fu, Future) and not fu.done():
                    fu.cancel()
                self.progress_callback(0, len(dicom_files), start_text)
        
        if self.get_exit_status():
            return []
        
        if not dicom_files:
            self.progress_callback(100, 100, f"(Step 1/2) No DICOM files found in: {dicom_dir}", True)
        else:
            self.progress_callback(0, len(dicom_files), f"(Step 1/2) Found {len(dicom_files)} DICOM files in '{dicom_dir}'")
        
        return sorted(dicom_files, key=os.path.dirname)
    
    def _parse_dicom_headers(self, dicom_files: Sequence[str], chunk_size: int) -> None:
        """Read DICOM metadata and update DB in parallel."""
        if not dicom_files or self.get_exit_status():
            return
        
        num_dcm_files = len(dicom_files)
        start_text = "(Step 2/2) Reading DICOM metadata and inserting to DB..."
        self.progress_callback(0, num_dcm_files, start_text)
        
        analyzed = 0
        committed = 0
        with get_session() as ses:
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
                
                inserted = 0
                for fu in as_completed(futures):
                    if self.get_exit_status():
                        break
                    try:
                        meta = fu.result()
                        inserted += self._upsert(ses, meta)
                    except Exception as e:
                        logger.error(f"Failed to process DICOM metadata." + get_traceback(e))
                    finally:
                        if isinstance(fu, Future) and not fu.done():
                            fu.cancel()
                        analyzed += 1
                        if analyzed % 100 == 0:
                            self.progress_callback(min(analyzed, num_dcm_files - 1), num_dcm_files, start_text)
                
                ses.commit()  # commit changes after each chunk
                committed += inserted
        
        if self.get_exit_status():
            return
        
        if analyzed == 0:
            self.progress_callback(100, 100, f"(Step 2/2) No DICOM metadata could be analyzed from these files: {dicom_files}", True)
        elif committed == 0:
            self.progress_callback(100, 100, f"(Step 2/2) No DICOM metadata was committed to the database.", True)
        else:
            self.progress_callback(analyzed, analyzed, f"(Step 2/2) Finished analyzing metadata from {analyzed} DICOM files. Committed {committed} records to the database.")

    def _upsert(self, ses: Session, meta: Dict[str, str]) -> int:
        """Insert/update Patient, File, FileMetadata with conflict handling."""
        if not meta or self.get_exit_status():
            return 0
        
        try:
            # --- Patient ------------------------------------------------
            mrn  = meta["patient_id"]
            name = meta["patient_name"]
            # if self.anonymize:
            #     mrn  = _pseudo(mrn,  self._salt)
            #     name = _pseudo(name, self._salt)
            
            patient = (
                ses.query(Patient)
                .filter_by(mrn=mrn, name=name)
                .one_or_none()
            )
            if patient is None:
                patient = Patient(
                    mrn=mrn,
                    name=name,
                    is_anonymized=self.anonymize,
                    created_at=datetime.now(),
                )
                ses.add(patient)
                ses.flush()  # gets PK

            # --- File ---------------------------------------------------
            file_row = ses.query(File).filter_by(path=meta["file_path"]).one_or_none()
            if file_row is None:
                file_row = File(
                    patient_id=patient.id,
                    path=meta["file_path"],
                    created_at=datetime.now(),
                )
                ses.add(file_row)
                ses.flush()

            # --- FileMetadata ------------------------------------------
            md = ses.query(FileMetadata).filter_by(file_id=file_row.id).one_or_none()
            new_values = {
                "frame_of_reference_uid":           meta["frame_of_reference_uid"],
                "modality":                         meta["modality"],
                "sop_instance_uid":                 meta["sop_instance_uid"],
                "sop_class_uid":                    meta.get("sop_class_uid"),
                "dose_summation_type":              meta.get("dose_summation_type"),
                "series_instance_uid":              meta.get("series_instance_uid"),
                "label":                            meta.get("label"),
                "name":                             meta.get("name"),
                "description":                      meta.get("description"),
                "date":                             meta.get("date"),
                "time":                             meta.get("time"),
                "referenced_sop_class_uid_seq":             dumps(meta["referenced_sop_class_uid_seq"]),
                "referenced_sop_instance_uid_seq":          dumps(meta["referenced_sop_instance_uid_seq"]),
                "referenced_frame_of_reference_uid_seq":    dumps(meta["referenced_frame_of_reference_uid_seq"]),
                "referenced_series_instance_uid_seq":       dumps(meta["referenced_series_instance_uid_seq"]),
                "referenced_rt_plan_sopi_seq":              dumps(meta["referenced_rt_plan_sopi_seq"]),
                "referenced_rt_plan_sopc_seq":              dumps(meta["referenced_rt_plan_sopc_seq"]),
                "referenced_structure_set_sopi_seq":        dumps(meta["referenced_structure_set_sopi_seq"]),
                "referenced_structure_set_sopc_seq":        dumps(meta["referenced_structure_set_sopc_seq"]),
                "referenced_dose_sopi_seq":                 dumps(meta["referenced_dose_sopi_seq"]),
                "referenced_dose_sopc_seq":                 dumps(meta["referenced_dose_sopc_seq"]),
            }
            
            if md is None:
                md = FileMetadata(
                    file_id=file_row.id,
                    patient_id=patient.id,
                    **new_values,
                )
                ses.add(md)
                return 1 # Successfully inserted new metadata
            
            # compare – update only if something changed
            updated = False
            for k, v in new_values.items():
                if getattr(md, k) != v and v is not None:
                    setattr(md, k, v)
                    updated = True
            return 1 if updated else 0
        
        except IntegrityError as exc:
            logger.warning(f"DB integrity error on {meta['file_path']}: {exc}")
            ses.rollback()
            return 0
        except Exception as e:
            logger.error(f"Failed to upsert metadata for {meta['file_path']}." + get_traceback(e))
            ses.rollback()
            return 0

    def load_patient_data_from_db(
        self,
        subset_size: Optional[int] = None,
        subset_idx: Optional[int] = None,
        never_processed: Optional[bool] = None,
        filter_mrns: Optional[str] = None,
        filter_names: Optional[str] = None,
    ) -> Dict[Tuple[str, str], Patient]:
        """Load patient data from database with filtering options."""
        if self.get_exit_status():
            return {}
        
        self.progress_callback(0, 0, "Loading patient data from database…")
        
        results: Dict[Tuple[str, str], Patient] = {}
        try:
            with get_session() as ses:
                # Build base query
                stmt = select(Patient)

                # Filter by MRN/Name
                filters = []
                if filter_mrns:
                    filters.append(Patient.mrn.ilike(f"%{filter_mrns.strip()}%"))
                if filter_names:
                    filters.append(Patient.name.ilike(f"%{filter_names.strip()}%"))
                if filters:
                    stmt = stmt.where(or_(*filters))

                # never_processed filtering: no filtering if None
                if never_processed is True:
                    stmt = stmt.where(Patient.processed_at.is_(None))
                elif never_processed is False:
                    stmt = stmt.where(Patient.processed_at.is_not(None))

                # Apply pagination
                if isinstance(subset_size, int) and isinstance(subset_idx, int):
                    if subset_size <= 0 or subset_idx < 0:
                        logger.error(f"Invalid subset size/index: {subset_size}/{subset_idx}")
                        return {}
                    stmt = stmt.limit(subset_size).offset(subset_idx * subset_size)

                # execute
                all_patients = list(ses.scalars(stmt).all())
                
                total = len(all_patients)
                for idx, p in enumerate(all_patients, start=1):
                    if self.get_exit_status():
                        return {}
                    results[(p.mrn, p.name)] = p
                    self.progress_callback(idx, total, "Loading patient data from database…")

                self.progress_callback(total, total, f"Loaded {len(results)} patients from database.")
        except Exception as e:
            logger.error("Failed to load patient data from database." + get_traceback(e))
            return {}

        return results
    
    def delete_patient_from_db(self, mrn: str, name: str) -> bool:
        """Delete patient and related data using MRN and Name."""
        logger.info(f"Attempting to delete patient: MRN={mrn}, Name={name}")
        with get_session() as ses:
            try:
                # Find patient by MRN and Name
                patient = ses.query(Patient).filter_by(mrn=mrn, name=name).one_or_none()
                if not patient:
                    logger.warning(f"No patient found with MRN={mrn} and Name={name}.")
                    return False

                # Find all Files for this patient
                file_ids = [f.id for f in patient.files]
                if file_ids:
                    # Delete FileMetadataOverride first (if present)
                    ses.execute(delete(FileMetadataOverride).where(FileMetadataOverride.file_id.in_(file_ids)))
                    # Delete FileMetadata
                    ses.execute(delete(FileMetadata).where(FileMetadata.file_id.in_(file_ids)))
                    # Delete Files
                    ses.execute(delete(File).where(File.id.in_(file_ids)))

                # Delete the Patient
                ses.delete(patient)
                ses.commit()
                logger.info(f"✅ Deleted patient MRN={mrn}, Name={name} and all associated data.")
                return True
            except Exception as e:
                ses.rollback()
                logger.error("❌ Failed to delete patient: " + get_traceback(e))
                return False
    
    def purge_all_patient_data_from_db(self) -> None:
        """Delete all patient data from database (irreversible)."""
        logger.warning("Purging ALL patient data from database…")
        with get_session() as ses:
            try:
                # Order matters due to foreign keys
                ses.execute(delete(FileMetadataOverride))
                ses.execute(delete(FileMetadata))
                ses.execute(delete(File))
                ses.execute(delete(Patient))
                ses.commit()
                logger.info("✅ All patient data deleted from database.")
            except Exception as e:
                ses.rollback()
                logger.error("❌ Failed to purge patient data: " + get_traceback(e))

