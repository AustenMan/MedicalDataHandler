import os
import json
from datetime import datetime

class PatientData:
    """
    A class to manage patient-related data, including metadata, file references, and associated DICOM data.
    """
    
    def __init__(self, MRN, Name):
        """
        Initialize a PatientData object.
        
        Args:
            MRN (str): Medical Record Number of the patient.
            Name (str): Name of the patient.
        """
        self.ObjectPath = None
        self.MRN = str(MRN).strip().replace('^', '')
        self.Name = str(Name).strip().replace('^', '')
        self.DateCreated = None
        self.DateLastModified = None
        self.DateLastAccessed = None
        self.DateLastProcessed = None
        self.DicomDict = {}
        self.DicomFileReferencesDict = {}
        self.DataDict = {}
        self.UniqueFilepaths = []
    
    def update_last_modified(self):
        """Update the DateLastModified to the current datetime."""
        self.DateLastModified = datetime.now()
        self.save_object()
    
    def update_last_accessed(self):
        """Update the DateLastAccessed to the current datetime."""
        self.DateLastAccessed = datetime.now()
        self.save_object()
    
    def update_last_processed(self):
        """Update the DateLastProcessed to the current datetime."""
        self.DateLastProcessed = datetime.now()
        self.save_object()
    
    def update_object_path(self, object_path):
        """
        Update the object path for the PatientData object.
        """
        object_path = os.path.abspath(object_path)
        if self.ObjectPath != object_path:
            self.ObjectPath = object_path
            self.save_object()
    
    def return_object_path(self):
        """Return the object path for the PatientData object."""
        return self.ObjectPath
    
    def return_patient_id(self):
        """Return the Patient ID (MRN)."""
        return self.MRN
    
    def return_patient_name(self):
        """Return the Patient Name."""
        return self.Name
    
    def return_patient_info(self):
        """
        Return patient identification information.
        
        Returns:
            tuple: (MRN, Name)
        """
        return self.MRN, self.Name
    
    def return_dates_dict(self):
        """
        Return a dictionary of dates associated with the PatientData object.
        
        Returns:
            dict: Dictionary of date fields.
        """
        return {
            'DateCreated': self.DateCreated,
            'DateLastModified': self.DateLastModified,
            'DateLastAccessed': self.DateLastAccessed,
            'DateLastProcessed': self.DateLastProcessed
        }
    
    def return_dicom_dict(self, keys_only=False):
        """
        Return the DicomDict containing references to DICOM data.
        
        Args:
            keys_only (bool): Whether to return only the keys.
        
        Returns:
            dict or list: DicomDict or its keys.
        """
        if keys_only:
            return list(self.DicomDict.keys())
        return self.DicomDict
    
    def return_dicom_frefs_dict(self):
        """
        Return the DicomFileReferencesDict containing file references.
        
        Returns:
            dict: DicomFileReferencesDict
        """
        return self.DicomFileReferencesDict
    
    def return_filepaths(self):
        """
        Return a list of all file paths associated with the PatientData object.
        
        Returns:
            list: List of file paths.
        """
        return self.UniqueFilepaths
    
    def add_to_dicom_dict(self, FrameOfReferenceUID, Modality, SOPInstanceUID, filepath):
        """
        Add DICOM file information to the DicomDict.
        
        Args:
            FrameOfReferenceUID (str): Frame of reference UID.
            Modality (str): Modality type.
            SOPInstanceUID (str): SOP instance UID.
            filepath (str): Path to the DICOM file.
        """
        if filepath not in self.UniqueFilepaths:
            self.UniqueFilepaths.append(filepath)
        self.DicomDict.setdefault(FrameOfReferenceUID, {}).setdefault(Modality, {})[SOPInstanceUID] = filepath
        self.update_last_modified()
    
    def update_dicom_file_references_dict(self, fpathrefdicts):
        """
        Update the DicomFileReferencesDict with new file references.
        
        Args:
            fpathrefdicts (dict): Dictionary of file paths and references.
        """
        self.DicomFileReferencesDict.update(fpathrefdicts)
        self.update_last_modified()
    
    def update_data_dict(self, key, filepaths):
        """
        Update the DataDict with new file paths.
        
        Args:
            key (str): Key for the data.
            filepaths (str or list): File path(s) to associate with the key.
        """
        key = str(key)
        if isinstance(filepaths, str):
            filepaths = [filepaths]
        elif not isinstance(filepaths, list):
            raise ValueError("filepaths must be a string or a list of strings.")
        
        valid_filepaths = []
        for filepath in filepaths:
            if not isinstance(filepath, str):
                continue
            if not os.path.isabs(filepath):
                raise ValueError(f"Filepath {filepath} is not an absolute path.")
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File {filepath} does not exist.")
            if filepath not in self.UniqueFilepaths:
                self.UniqueFilepaths.append(filepath)
            valid_filepaths.append(filepath)
        
        if key not in self.DataDict:
            self.DataDict[key] = valid_filepaths
        else:
            self.DataDict[key].extend([fp for fp in valid_filepaths if fp not in self.DataDict[key]])
        self.update_last_modified()
    
    def to_dict(self):
        """
        Convert the PatientData object into a dictionary for JSON serialization.
        
        Returns:
            dict: Serialized representation of the object.
        """
        return {
            'MRN': self.MRN,
            'Name': self.Name,
            'DateCreated': self.DateCreated.isoformat() if self.DateCreated is not None else None,
            'DateLastAccessed': self.DateLastAccessed.isoformat() if self.DateLastAccessed is not None else None,
            'DateLastModified': self.DateLastModified.isoformat() if self.DateLastModified is not None else None,
            'DateLastProcessed': self.DateLastProcessed.isoformat() if self.DateLastProcessed is not None else None,
            'DicomDict': self.DicomDict,
            'DicomFileReferencesDict': self.DicomFileReferencesDict,
            'DataDict': self.DataDict,
            'UniqueFilepaths': self.UniqueFilepaths
        }
    
    def save_object(self):
        """
        Save the PatientData object to a JSON file.
        """
        if self.ObjectPath is None:
            return
        if not os.path.isabs(self.ObjectPath):
            raise ValueError("Patient object path must be an absolute path.")
        with open(self.ObjectPath, 'wt') as obj_file:
            json.dump(self.to_dict(), obj_file)
    
    @classmethod
    def from_dict(cls, data):
        """
        Create a PatientData object from a dictionary.
        
        Args:
            data (dict): Serialized PatientData dictionary.
        
        Returns:
            PatientData: An initialized PatientData object.
        """
        obj = cls(data['MRN'], data['Name'])
        obj.DateCreated = datetime.fromisoformat(data['DateCreated']) if data.get('DateCreated') else datetime.now()
        obj.DateLastAccessed = datetime.fromisoformat(data['DateLastAccessed']) if data.get('DateLastAccessed') else None
        obj.DateLastModified = datetime.fromisoformat(data['DateLastModified']) if data.get('DateLastModified') else None
        obj.DateLastProcessed = datetime.fromisoformat(data['DateLastProcessed']) if data.get('DateLastProcessed') else None
        obj.DicomDict = data.get('DicomDict', {})
        obj.DicomFileReferencesDict = data.get('DicomFileReferencesDict', {})
        obj.DataDict = data.get('DataDict', {})
        obj.UniqueFilepaths = data.get('UniqueFilepaths', [])
        return obj
    
    @staticmethod
    def merge_patient_data(patient1, patient2):
        """
        Merge two PatientData objects into a single object.
        
        Args:
            patient1 (PatientData): First PatientData object.
            patient2 (PatientData): Second PatientData object.
        
        Returns:
            PatientData: Merged PatientData object.
        """
        if not isinstance(patient1, PatientData) or not isinstance(patient2, PatientData):
            raise ValueError("Can only merge PatientData instances.")
        
        # Prompt for new MRN and Name
        if patient1.MRN == patient2.MRN:
            new_MRN = patient1.MRN
        else:
            new_MRN = input(f"First MRN was {patient1.MRN}, second MRN was {patient2.MRN}. Enter new MRN: ").strip().replace('^', '')
        
        if patient1.Name == patient2.Name:
            new_Name = patient1.Name
        else:
            new_Name = input(f"First Name was {patient1.Name}, second Name was {patient2.Name}. Enter new Name: ").strip().replace('^', '')
        
        # Create a new PatientData instance
        merged_patient = PatientData(new_MRN, new_Name)
        
        # Set DateCreated to the earliest date
        merged_patient.DateCreated = min(filter(None, [patient1.DateCreated, patient2.DateCreated]))
        
        # Merge DicomDict
        from copy import deepcopy
        merged_patient.DicomDict = deepcopy(patient1.DicomDict)
        for frame in patient2.DicomDict:
            if frame not in merged_patient.DicomDict:
                merged_patient.DicomDict[frame] = deepcopy(patient2.DicomDict[frame])
            else:
                for modality in patient2.DicomDict[frame]:
                    if modality not in merged_patient.DicomDict[frame]:
                        merged_patient.DicomDict[frame][modality] = deepcopy(patient2.DicomDict[frame][modality])
                    else:
                        for sop_uid in patient2.DicomDict[frame][modality]:
                            if sop_uid in merged_patient.DicomDict[frame][modality]:
                                print(f"Warning: Overwriting existing entry for SOPInstanceUID {sop_uid} in FrameOfReference {frame}, Modality {modality}")
                            merged_patient.DicomDict[frame][modality][sop_uid] = patient2.DicomDict[frame][modality][sop_uid]
        
        # Merge DicomFileReferencesDict
        merged_patient.DicomFileReferencesDict = deepcopy(patient1.DicomFileReferencesDict)
        for key in patient2.DicomFileReferencesDict:
            if key in merged_patient.DicomFileReferencesDict:
                print(f"Warning: Overwriting updating entry for key {key} in DicomFileReferencesDict")
                merged_patient.DicomFileReferencesDict[key].update(patient2.DicomFileReferencesDict[key])
            else:
                merged_patient.DicomFileReferencesDict[key] = patient2.DicomFileReferencesDict[key]
        
        # Merge DataDict
        merged_patient.DataDict = deepcopy(patient1.DataDict)
        for key in patient2.DataDict:
            if key in merged_patient.DataDict:
                print(f"Warning: Overwriting existing entry for key {key} in DataDict")
            merged_patient.DataDict[key] = patient2.DataDict[key]
        
        merged_patient.DateLastModified = datetime.now()
        
        # Merge UniqueFilepaths
        merged_patient.UniqueFilepaths = list(set(patient1.UniqueFilepaths + patient2.UniqueFilepaths))
        
        return merged_patient
