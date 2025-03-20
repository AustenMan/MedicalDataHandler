import os
import json
import pydicom
from pydicom.tag import Tag
from concurrent.futures import as_completed, Future
from utils.dicom_objects import PatientData
from utils.general_utils import get_traceback

def get_dicom_tag_value(dicom_data, tag, reformat_str=False):
    """
    Retrieve the value of a DICOM tag safely.
    
    Args:
        dicom_data (pydicom.dataset.FileDataset): The DICOM dataset to read the tag from.
        tag (pydicom.tag.Tag): The tag to retrieve.
        reformat_str (bool, optional): If True, reformats strings by replacing "^" and spaces with "_". Defaults to False.
    
    Returns:
        str or None: The value of the tag if it exists, otherwise None.
    """
    element = dicom_data.get(tag)
    if element and element.value:
        value = str(element.value).strip()
        if reformat_str:
            value = value.replace("^", "_").replace(" ", "_")
        return value
    return None

def worker_read_dcm_core(filepath):
    """
    Read essential metadata from a DICOM file.
    
    Args:
        filepath (str): Path to the DICOM file.
    
    Returns:
        tuple: A tuple containing the following information:
            - filepath (str): The path to the DICOM file.
            - PatientID (str or None): Reformatted Patient ID.
            - PatientsName (str or None): Reformatted Patient's Name.
            - FrameOfReferenceUID (str or None): Frame of Reference UID.
            - Modality (str or None): The modality of the DICOM file (e.g., RTSTRUCT, RTPLAN).
            - SOPInstanceUID (str or None): SOP Instance UID of the DICOM file.
    """
    tag_PatientID = Tag(0x0010, 0x0020)
    tag_PatientsName = Tag(0x0010, 0x0010)
    tag_FrameOfReferenceUID = Tag(0x0020, 0x0052)
    tag_Modality = Tag(0x0008, 0x0060)
    tag_SOPInstanceUID = Tag(0x0008, 0x0018)
    tag_ReferencedFrameOfReferenceSequence = Tag(0x3006, 0x0010)
    
    dicom_data = pydicom.dcmread(
        filepath, 
        defer_size="100 KB", 
        stop_before_pixels=True, 
        force=True, 
        specific_tags=[
            tag_PatientsName,
            tag_PatientID,
            tag_FrameOfReferenceUID, 
            tag_Modality, 
            tag_SOPInstanceUID, 
            tag_ReferencedFrameOfReferenceSequence
        ]
    )
    
    # Retrieve tag values
    PatientID = get_dicom_tag_value(dicom_data, tag_PatientID, reformat_str=True)
    PatientsName = get_dicom_tag_value(dicom_data, tag_PatientsName, reformat_str=True)
    FrameOfReferenceUID = get_dicom_tag_value(dicom_data, tag_FrameOfReferenceUID)
    Modality = get_dicom_tag_value(dicom_data, tag_Modality)
    SOPInstanceUID = get_dicom_tag_value(dicom_data, tag_SOPInstanceUID)
    
    if not FrameOfReferenceUID:
        ReferencedFrameOfReferenceSequence = dicom_data.get(tag_ReferencedFrameOfReferenceSequence)
        if ReferencedFrameOfReferenceSequence:
            set_FrameOfReferenceUIDs = {
                get_dicom_tag_value(item, tag_FrameOfReferenceUID)
                for item in ReferencedFrameOfReferenceSequence
                if get_dicom_tag_value(item, tag_FrameOfReferenceUID)
            }
            if set_FrameOfReferenceUIDs:
                sorted_uids = sorted(set_FrameOfReferenceUIDs)
                if len(sorted_uids) > 1:
                    print(
                        f"Warning: Multiple Frame of Reference UIDs found for {SOPInstanceUID} in {filepath}. "
                        f"Using the first one: {sorted_uids}"
                    )
                FrameOfReferenceUID = sorted_uids.pop()
    
    # print(f"Read DICOM file: {filepath}, found Patient ID: {PatientID}, Patient's Name: {PatientsName}, Frame of Reference UID: {FrameOfReferenceUID}, Modality: {Modality}, SOP Instance UID: {SOPInstanceUID}")
    result = (filepath, PatientID, PatientsName, FrameOfReferenceUID, Modality, SOPInstanceUID)
    
    return result

def add_dicom_to_dict(patient_obj_dict, filepath, PatientID, PatientsName, FrameOfReferenceUID, Modality, SOPInstanceUID):
    """
    Add a DICOM file's metadata to the internal object dictionary.
    
    Args:
        patient_obj_dict (dict): Dictionary containing PatientData objects.
        filepath (str): File path of the DICOM file.
        PatientID (str): Patient ID extracted from the file.
        PatientsName (str): Patient's Name extracted from the file.
        FrameOfReferenceUID (str): Frame of Reference UID from the file.
        Modality (str): Modality type (e.g., RTSTRUCT, RTDOSE).
        SOPInstanceUID (str): SOP Instance UID from the file.
    """
    if PatientID is None or PatientsName is None or FrameOfReferenceUID is None or Modality is None or SOPInstanceUID is None:
        print(
            f"Warning: Incomplete DICOM data found for filepath: {filepath} with "
            f"PatientID: {PatientID}, PatientsName: {PatientsName}, FrameOfReferenceUID: {FrameOfReferenceUID}, "
            F"Modality: {Modality}, SOPInstanceUID: {SOPInstanceUID}"
        )
        return
    
    obj_key = (PatientID, PatientsName)
    if obj_key not in patient_obj_dict:
        patient_obj_dict[obj_key] = PatientData(PatientID, PatientsName)
    
    patientdata_class = patient_obj_dict[obj_key]
    patientdata_class.add_to_dicom_dict(FrameOfReferenceUID, Modality, SOPInstanceUID, filepath)

def monitor_dicom_read_progress(dicom_dir_string, obj_dir, progbar_fn, shared_state_manager=None):
    """ 
    Reads all DICOM files in the list and saves their objects to JSON files. 
    
    Args:
        dicom_dir_string (str): Directory to scan for DICOM files.
        obj_dir (str): Directory to save the JSON objects.
        progbar_fn (callable): Progress bar callback function.
        shared_state_manager: Instance of SharedStateManager for handling threading and task execution.
    """
    def exit_task_status(edit_pbar=True):
        should_exit = shared_state_manager is not None and (shared_state_manager.cleanup_event.is_set() or shared_state_manager.shutdown_event.is_set())
        if should_exit and edit_pbar:
            progbar_fn(0, 0, "Aborting DICOM file processing...")
        return should_exit
    
    # Gather all DICOM file paths.
    progbar_fn(0, 0, f"Searching for DICOM files in '{dicom_dir_string}', this may take some time if the directory is large...")
    dicom_files = get_dicom_files(dicom_dir_string, exit_task_status)
    if not dicom_files:
        progbar_fn(0, 0, f"No DICOM files found in the specified directory: {dicom_dir_string}")
        return
    
    if exit_task_status():
        return
    
    ini_num_files = len(dicom_files)
    progbar_fn(0, ini_num_files, "Found DICOM files. Processing them, please wait...")
    
    # Load any existing patient data.
    patient_obj_dict = {}
    for obj_filepath in [os.path.join(obj_dir, f) for f in os.listdir(obj_dir) if f.endswith('.json')]:
        if exit_task_status():
            return
        try:
            with open(obj_filepath, 'rt') as obj_file:
                obj_data = json.load(obj_file)
            patient_data = PatientData.from_dict(obj_data)
            patient_data.update_object_path(obj_filepath)
            patient_obj_dict[(patient_data.MRN, patient_data.Name)] = patient_data
            known_filepaths = set(patient_data.return_filepaths())
            dicom_files.difference_update(known_filepaths)
        except Exception as e:
            print(f"Error reading JSON file '{obj_filepath}': {get_traceback(e)}")     
    
    if not dicom_files:
        progbar_fn(ini_num_files, ini_num_files, "No new DICOM files to process.")
        return
    
    if exit_task_status():
        return
    
    # Submit tasks to read DICOM files
    futures = [future for filepath in dicom_files if (future := shared_state_manager.add_executor_action(worker_read_dcm_core, filepath)) is not None]
    
    if exit_task_status():
        return
    
    # Process the results of the DICOM file reads
    total_tasks = len(futures)
    completed = 0
    try:
        for future in as_completed(futures):
            if exit_task_status(edit_pbar=False):
                break
            try:
                add_dicom_to_dict(patient_obj_dict, *future.result())
            except Exception as e:
                print(f"Error processing future result: {get_traceback(e)}")
            finally:
                completed += 1
                if completed % 100 == 0:
                    progbar_fn(completed, total_tasks, "Processing DICOM files...")
    except Exception as e:
        print(f"Error processing DICOM futures: {get_traceback(e)}")
    finally:
        for future in futures:
            if isinstance(future, Future) and not future.done():
                future.cancel()
    
    if exit_task_status():
        return
    
    # Finalization: save each patient object to its corresponding JSON file.
    for obj_key, patientdata_class in patient_obj_dict.items():
        if exit_task_status():
            return
        obj_filepath = os.path.join(obj_dir, f"{obj_key[0]}_{obj_key[1]}.json")
        patientdata_class.update_object_path(obj_filepath)
    
    progbar_fn(total_tasks, total_tasks, f"Completed reading and saving DICOM objects for {completed} out of {total_tasks} files.")

def worker_link_dicoms(filepath):
    """
    Read a DICOM file and identify its links to other DICOM files.
    
    Args:
        filepath (str): Path to the DICOM file.
    
    Returns:
        dict: A dictionary containing file metadata and linked references:
            - "PatientID" (str): Reformatted Patient ID.
            - "PatientsName" (str): Reformatted Patient's Name.
            - "Modality" (str): Modality of the DICOM file.
            - "DoseSummationType" (str): Type of dose summation if applicable.
            - "SOPClassUID" (str): SOP Class UID.
            - "SOPInstanceUID" (str): SOP Instance UID.
            - "FrameOfReferenceUID" (str): Frame of Reference UID.
            - "SeriesInstanceUID" (str): Series Instance UID.
            - "ReferencedSOPClassUID" (list): List of referenced SOP Class UIDs.
            - "ReferencedSOPInstanceUID" (list): List of referenced SOP Instance UIDs.
            - "ReferencedFrameOfReferenceUID" (list): List of referenced Frame of Reference UIDs.
            - "ReferencedSeriesInstanceUID" (list): List of referenced Series Instance UIDs.
    """
    tag_PatientID = Tag(0x0010, 0x0020)
    tag_PatientsName = Tag(0x0010, 0x0010)
    tag_FrameOfReferenceUID = Tag(0x0020, 0x0052)
    tag_Modality = Tag(0x0008, 0x0060)
    tag_DoseSummationType = Tag(0x3004, 0x000A)
    tag_SeriesInstanceUID = Tag(0x0020, 0x000E)
    tag_SOPClassUID = Tag(0x0008, 0x0016)
    tag_SOPInstanceUID = Tag(0x0008, 0x0018)
    tag_ReferencedSOPClassUID = Tag(0x0008, 0x1150)
    tag_ReferencedSOPInstanceUID = Tag(0x0008, 0x1155)
    tag_ReferencedRTPlanSequence = Tag(0x300C, 0x0002)
    tag_ReferencedStructureSetSequence = Tag(0x300C, 0x0060)
    tag_ReferencedDoseSequence = Tag(0x300C, 0x0080)
    tag_ReferencedFrameOfReferenceSequence = Tag(0x3006, 0x0010)
    tag_RTReferencedStudySequence = Tag(0x3006, 0x0012)
    tag_RTReferencedSeriesSequence = Tag(0x3006, 0x0014)
    
    dicom_data = pydicom.dcmread(
        filepath, 
        defer_size="100 KB", 
        stop_before_pixels=True, 
        force=True, 
        specific_tags=[
            tag_PatientID,
            tag_PatientsName,
            tag_FrameOfReferenceUID,
            tag_Modality,
            tag_DoseSummationType,
            tag_SOPClassUID,
            tag_SOPInstanceUID,
            tag_ReferencedSOPClassUID,
            tag_ReferencedSOPInstanceUID,
            tag_ReferencedRTPlanSequence,
            tag_ReferencedStructureSetSequence,
            tag_ReferencedDoseSequence,
            tag_ReferencedFrameOfReferenceSequence,
            tag_RTReferencedStudySequence,
            tag_RTReferencedSeriesSequence,
            tag_SeriesInstanceUID
        ]
    )
    
    # Retrieve tag values
    PatientID = get_dicom_tag_value(dicom_data, tag_PatientID, reformat_str=True)
    PatientsName = get_dicom_tag_value(dicom_data, tag_PatientsName, reformat_str=True)
    Modality = get_dicom_tag_value(dicom_data, tag_Modality)
    DoseSummationType = get_dicom_tag_value(dicom_data, tag_DoseSummationType)
    SeriesInstanceUID = get_dicom_tag_value(dicom_data, tag_SeriesInstanceUID)
    SOPClassUID = get_dicom_tag_value(dicom_data, tag_SOPClassUID)
    SOPInstanceUID = get_dicom_tag_value(dicom_data, tag_SOPInstanceUID)
    FrameOfReferenceUID = get_dicom_tag_value(dicom_data, tag_FrameOfReferenceUID)
    
    file_links_dict = {
        "PatientID": PatientID, "PatientsName": PatientsName, "Modality": Modality, "DoseSummationType": DoseSummationType,
        "SOPClassUID": SOPClassUID, "SOPInstanceUID": SOPInstanceUID, "FrameOfReferenceUID": FrameOfReferenceUID, "SeriesInstanceUID": SeriesInstanceUID,
        "ReferencedSOPClassUID": [], "ReferencedSOPInstanceUID": [], "ReferencedFrameOfReferenceUID": [], "ReferencedSeriesInstanceUID": []
    }
    
    ReferencedSOPClassUID = get_dicom_tag_value(dicom_data, tag_ReferencedSOPClassUID)
    if ReferencedSOPClassUID and ReferencedSOPClassUID not in file_links_dict["ReferencedSOPClassUID"]:
        file_links_dict["ReferencedSOPClassUID"].append(ReferencedSOPClassUID)
    
    ReferencedSOPInstanceUID = get_dicom_tag_value(dicom_data, tag_ReferencedSOPInstanceUID)
    if ReferencedSOPInstanceUID and ReferencedSOPInstanceUID not in file_links_dict["ReferencedSOPInstanceUID"]:
        file_links_dict["ReferencedSOPInstanceUID"].append(ReferencedSOPInstanceUID)
    
    ReferencedFrameOfReferenceSequence = dicom_data.get(tag_ReferencedFrameOfReferenceSequence)
    if ReferencedFrameOfReferenceSequence:
        for item in ReferencedFrameOfReferenceSequence:
            item_value_FORUID = get_dicom_tag_value(item, tag_FrameOfReferenceUID)
            if item_value_FORUID and item_value_FORUID not in file_links_dict["ReferencedFrameOfReferenceUID"]:
                file_links_dict["ReferencedFrameOfReferenceUID"].append(item_value_FORUID)
            
            RTReferencedStudySequence = item.get(tag_RTReferencedStudySequence)
            if RTReferencedStudySequence:
                for item2 in RTReferencedStudySequence:
                    item_value_SOPC = get_dicom_tag_value(item2, tag_ReferencedSOPClassUID)
                    if item_value_SOPC and item_value_SOPC not in file_links_dict["ReferencedSOPClassUID"]:
                        file_links_dict["ReferencedSOPClassUID"].append(item_value_SOPC)
                    item_value_SOPI = get_dicom_tag_value(item2, tag_ReferencedSOPInstanceUID)
                    if item_value_SOPI and item_value_SOPI not in file_links_dict["ReferencedSOPInstanceUID"]:
                        file_links_dict["ReferencedSOPInstanceUID"].append(item_value_SOPI)
                    
                    RTReferencedSeriesSequence = item2.get(tag_RTReferencedSeriesSequence)
                    if RTReferencedSeriesSequence:
                        for item3 in RTReferencedSeriesSequence:
                            item_value_SIUID = get_dicom_tag_value(item3, tag_SeriesInstanceUID)
                            if item_value_SIUID and item_value_SIUID not in file_links_dict["ReferencedSeriesInstanceUID"]:
                                file_links_dict["ReferencedSeriesInstanceUID"].append(item_value_SIUID)
    
    plan_structset_dose_refs = []
    ReferencedRTPlanSequence = dicom_data.get(tag_ReferencedRTPlanSequence)
    if ReferencedRTPlanSequence:
        plan_structset_dose_refs.extend(ReferencedRTPlanSequence)
    
    ReferencedStructureSetSequence = dicom_data.get(tag_ReferencedStructureSetSequence)
    if ReferencedStructureSetSequence:
        plan_structset_dose_refs.extend(ReferencedStructureSetSequence)
    
    ReferencedDoseSequence = dicom_data.get(tag_ReferencedDoseSequence)
    if ReferencedDoseSequence:
        plan_structset_dose_refs.extend(ReferencedDoseSequence)
    
    for item in plan_structset_dose_refs:
        item_value_SOPC = get_dicom_tag_value(item, tag_ReferencedSOPClassUID)
        if item_value_SOPC and item_value_SOPC not in file_links_dict["ReferencedSOPClassUID"]:
            file_links_dict["ReferencedSOPClassUID"].append(item_value_SOPC)
        item_value_SOPI = get_dicom_tag_value(item, tag_ReferencedSOPInstanceUID)
        if item_value_SOPI and item_value_SOPI not in file_links_dict["ReferencedSOPInstanceUID"]:
            file_links_dict["ReferencedSOPInstanceUID"].append(item_value_SOPI)
    
    return {filepath: file_links_dict}

def monitor_link_dicom_progress(obj_dir, object_dict, progbar_fn, shared_state_manager=None):
    """
    Build references for all DICOM objects stored in the manager and save them to JSON files.
    
    Args:
        obj_dir (str): Directory to save the JSON objects.
        object_dict (dict): Dictionary containing PatientData objects.
        progbar_fn (callable): Progress bar callback function.
        shared_state_manager: Instance of SharedStateManager for handling threading and task execution.
    """
    def exit_task_status(edit_pbar=True):
        should_exit = shared_state_manager is not None and (shared_state_manager.cleanup_event.is_set() or shared_state_manager.shutdown_event.is_set())
        if should_exit and edit_pbar:
            progbar_fn(0, 0, "Aborting DICOM linking...")
        return should_exit
    
    futures_length = len(object_dict)
    progbar_fn(0, futures_length, "Starting to build DICOM references for all objects...")
    
    if exit_task_status():
        return
    
    # Process each PatientData object
    futures_completed = 0
    for key in object_dict:
        try:
            if exit_task_status():
                return
            
            results = {}
            files_to_read = [filepath for modality_dict in object_dict[key].DicomDict.values() for sopi_dict in modality_dict.values() for filepath in sopi_dict.values()]
            futures = [future for filepath in files_to_read if (future := shared_state_manager.add_executor_action(worker_link_dicoms, filepath)) is not None]
            
            try:
                for future in as_completed(futures):
                    if exit_task_status(edit_pbar=False):
                        break
                    results.update(future.result())
            except Exception as e:
                print(f"Error processing DICOM futures: {get_traceback(e)}")
            finally:
                for future in futures:
                    if isinstance(future, Future) and not future.done():
                        future.cancel()
            
            if exit_task_status():
                return
            
            # Update the PatientData object with the DICOM references
            object_dict[key].update_dicom_file_references_dict(results)
            
            # Save the updated object to a JSON file
            obj_filepath = os.path.join(obj_dir, f"{key[0]}_{key[1]}.json")
            patientdata_class = object_dict[key]
            with open(obj_filepath, 'w') as obj_file:
                json.dump(patientdata_class.to_dict(), obj_file)
        except Exception as e:
            print(f"Error processing future result: {get_traceback(e)}")
        finally:
            futures_completed += 1
            progbar_fn(futures_completed, futures_length, "Building DICOM references ...")
    
    # Finalization
    progbar_fn(futures_length, futures_length, f"Completed building DICOM references for {futures_completed} out of {futures_length} class objects.")

def get_dicom_files(dicom_dir_string, exit_task_status):
    """Efficiently finds all .dcm files in the given directory."""
    dicom_files = set()

    def scan_dir(directory):
        """Recursively scan directories using os.scandir()."""
        with os.scandir(directory) as entries:
            for entry in entries:
                if exit_task_status():
                    break
                if entry.is_file() and entry.name.lower().endswith(".dcm"):
                    dicom_files.add(entry.path)
                elif entry.is_dir():  # Recurse into subdirectories
                    scan_dir(entry.path)

    scan_dir(dicom_dir_string)
    return dicom_files

class DicomManager():
    """ Manages DICOM files processing: reads metadata, builds references, stores/retrieves structured DICOM objects. """
    
    def __init__(self, config_manager, shared_state_manager):
        """
        Initialize the DicomManager.
        
        Args:
            config_manager: Instance of ConfigManager, which handles configuration settings.
            shared_state_manager: Instance of SharedStateManager for handling threading and task execution.
        """
        self.config_manager = config_manager
        self.shared_state_manager = shared_state_manager
        
        self.progbar_fn = lambda val, max_val, text: print(text) # Defaults progress bar callback function to only print text
        self.object_dict = {} # Dictionary to store PatientData objects
    
    def set_pbar_callback(self, pbar_fn):
        """
        Set a callback function for progress bar updates.
        
        Args:
            pbar_fn (callable): A function to update the progress bar. It should accept three parameters:
                - The current progress count (int).
                - The total progress count (int).
                - A description string (str).
        """
        if not callable(pbar_fn):
            print("Invalid progress bar callback function provided.")
            return
        self.progbar_fn = pbar_fn
    
    def start_processing_dicom_directory(self, dicom_dir_string):
        """ Scans a selected directory recursively for '.dcm' files, reads their metadata, and saves them as JSON objects. """
        # Ask user to select a directory
        self.progbar_fn(0, 0, description="Ready to find DICOM files. Select a directory that contains DICOM files using the button below.")
        
        if dicom_dir_string is None:
            print("Invalid directory provided. Please select again.")
            return
        
        if not os.path.exists(dicom_dir_string) or not os.path.isdir(dicom_dir_string):
            print(f"Invalid DICOM directory provided: {dicom_dir_string}")
            return
        
        objects_dir = self.config_manager.get_patient_objects_dir()
        if not os.path.isdir(objects_dir):
            print(f"Invalid object directory path provided, cannot process directory: {objects_dir}")
            return
        
        monitor_dicom_read_progress(dicom_dir_string, objects_dir, self.progbar_fn, self.shared_state_manager)
    
    def load_dicom_objects(self, return_object_dict=False):
        """
        Load `PatientData` objects from JSON files in the object directory.
        
        This method reads all JSON files in the structured directory, deserializes them into
            `PatientData` objects, and populates `self.object_dict`.
        
        Args:
            return_object_dict (bool): If True, returns the populated `self.object_dict`.
        
        Returns:
            dict: The populated `self.object_dict` if `return_object_dict` is True, otherwise None.
        """
        patient_objs_dir = self.config_manager.get_patient_objects_dir()
        for obj_filepath in [os.path.join(patient_objs_dir, f) for f in os.listdir(patient_objs_dir) if f.endswith('.json')]:
            with open(obj_filepath, 'rt') as obj_file:
                try:
                    obj_data = json.load(obj_file)
                except Exception as e:
                    print(f"Error reading JSON file '{obj_filepath}': {get_traceback(e)}")
                    continue
                patient_data = PatientData.from_dict(obj_data)
                patient_data.update_object_path(obj_filepath)
                self.object_dict[(patient_data.MRN, patient_data.Name)] = patient_data
        
        if return_object_dict:
            return self.object_dict
    
    def start_linking_all_dicoms(self):
        """ Start the process of linking all DICOM objects in the `object_dict`. """
        patient_objs_dir = self.config_manager.get_patient_objects_dir()
        if not os.path.isdir(patient_objs_dir):
            print(f"Invalid object directory path provided, cannot link DICOMs: {patient_objs_dir}")
            return
        
        self.load_dicom_objects()
        
        if not self.object_dict:
            print("Cannot link DICOMs as there are no patient objects to link. Try finding DICOMs first.")
            return
        
        monitor_link_dicom_progress(patient_objs_dir, self.object_dict, self.progbar_fn, self.shared_state_manager)

