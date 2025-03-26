import os
import re
import json
import logging
from datetime import datetime
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union

from mdh_app.utils.general_utils import atomic_save

logger = logging.getLogger(__name__)

class PatientData:
    """
    Manages patient-related data including metadata, file references, and associated DICOM data.
    """

    def __init__(self, MRN: Any, Name: Any) -> None:
        """
        Initialize a PatientData instance.

        Args:
            MRN: The patient's Medical Record Number.
            Name: The patient's name.
        """
        self.ObjectPath: Optional[str] = None
        self.MRN: str = self._get_clean_string(MRN)
        self.Name: str = self._get_clean_string(Name)
        self.DateCreated: Optional[datetime] = None
        self.DateLastModified: Optional[datetime] = None
        self.DateLastAccessed: Optional[datetime] = None
        self.DateLastProcessed: Optional[datetime] = None
        self.DicomDict: Dict[str, Any] = {}
        self.DicomFileReferencesDict: Dict[str, Any] = {}
        self.DataDict: Dict[str, Any] = {}
        self.UniqueFilepaths: List[str] = []
    
    @staticmethod
    def _get_clean_string(item: Any) -> str:
        """Return a cleaned string of the input."""
        # Remove leading/trailing carets and whitespace
        item_str = str(item).strip().replace('^', '') 
        # Collapse multiple underscores
        item_str = re.sub(r'_+', '_', item_str)
        # Remove leading/trailing underscores
        return item_str.strip('_')
    
    def update_last_modified(self) -> None:
        """Set DateLastModified to the current datetime and save the object."""
        self.DateLastModified = datetime.now()
        self.save_object()

    def update_last_accessed(self) -> None:
        """Set DateLastAccessed to the current datetime and save the object."""
        self.DateLastAccessed = datetime.now()
        self.save_object()

    def update_last_processed(self) -> None:
        """Set DateLastProcessed to the current datetime and save the object."""
        self.DateLastProcessed = datetime.now()
        self.save_object()

    def update_object_path(self, object_path: str) -> None:
        """
        Update the object path if different and save the object.

        Args:
            object_path: The new object file path.
        """
        abs_path = os.path.abspath(object_path)
        if self.ObjectPath != abs_path:
            self.ObjectPath = abs_path
            self.save_object()

    def return_object_path(self) -> Optional[str]:
        """Return the current object file path."""
        return self.ObjectPath

    def return_patient_id(self) -> str:
        """Return the patient MRN."""
        return self.MRN

    def return_patient_name(self) -> str:
        """Return the patient name."""
        return self.Name

    def return_patient_info(self) -> Tuple[str, str]:
        """
        Return patient identification information.

        Returns:
            A tuple containing (MRN, Name).
        """
        return self.MRN, self.Name

    def return_dates_dict(self) -> Dict[str, Optional[datetime]]:
        """
        Return a dictionary of associated date fields.

        Returns:
            Dictionary with date fields.
        """
        return {
            'DateCreated': self.DateCreated,
            'DateLastModified': self.DateLastModified,
            'DateLastAccessed': self.DateLastAccessed,
            'DateLastProcessed': self.DateLastProcessed
        }
    
    def return_dicom_dict(self, keys_only: bool = False) -> Union[Dict[str, Any], List[str]]:
        """
        Return the DicomDict containing DICOM references.

        Args:
            keys_only: If True, only return the dictionary keys.

        Returns:
            The complete DicomDict or a list of its keys.
        """
        return list(self.DicomDict.keys()) if keys_only else self.DicomDict

    def return_dicom_frefs_dict(self) -> Dict[str, Any]:
        """
        Return the dictionary of DICOM file references.

        Returns:
            The DicomFileReferencesDict.
        """
        return self.DicomFileReferencesDict

    def return_filepaths(self) -> List[str]:
        """
        Return the list of all file paths associated with this patient.

        Returns:
            A list of file paths.
        """
        return self.UniqueFilepaths

    def add_to_dicom_dict(
        self,
        FrameOfReferenceUID: str,
        Modality: str,
        SOPInstanceUID: str,
        filepath: str,
        update_obj: bool = True
    ) -> None:
        """
        Add a DICOM file reference to the DicomDict.

        Args:
            FrameOfReferenceUID: The frame of reference UID.
            Modality: The modality type.
            SOPInstanceUID: The SOP instance UID.
            filepath: Absolute path to the DICOM file.
            update_obj: If True, update the last modified date.
        """
        if filepath not in self.UniqueFilepaths:
            self.UniqueFilepaths.append(filepath)
        self.DicomDict.setdefault(FrameOfReferenceUID, {}).setdefault(Modality, {})[SOPInstanceUID] = filepath
        if update_obj:
            self.update_last_modified()
    
    def update_dicom_file_references_dict(self, fpathrefdicts: Dict[str, Any]) -> None:
        """
        Update the DicomFileReferencesDict with new references.

        Args:
            fpathrefdicts: A dictionary of file path references.
        """
        self.DicomFileReferencesDict.update(fpathrefdicts)
        self.update_last_modified()

    def update_data_dict(self, key: str, filepaths: Union[str, List[str]]) -> None:
        """
        Update the DataDict with one or more absolute file paths.

        Args:
            key: The key to update in DataDict.
            filepaths: A single absolute filepath or a list of them.
        """
        key = str(key)
        if isinstance(filepaths, str):
            filepaths = [filepaths]
        elif not isinstance(filepaths, list):
            raise ValueError("filepaths must be a string or a list of strings.")

        valid_filepaths: List[str] = []
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
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the PatientData object into a dictionary.

        Returns:
            A dictionary representation suitable for JSON serialization.
        """
        return {
            'MRN': self.MRN,
            'Name': self.Name,
            'DateCreated': self.DateCreated.isoformat() if self.DateCreated else None,
            'DateLastAccessed': self.DateLastAccessed.isoformat() if self.DateLastAccessed else None,
            'DateLastModified': self.DateLastModified.isoformat() if self.DateLastModified else None,
            'DateLastProcessed': self.DateLastProcessed.isoformat() if self.DateLastProcessed else None,
            'DicomDict': self.DicomDict,
            'DicomFileReferencesDict': self.DicomFileReferencesDict,
            'DataDict': self.DataDict,
            'UniqueFilepaths': self.UniqueFilepaths
        }
    
    def save_object(self) -> None:
        """Save the PatientData object to a JSON file at ObjectPath."""
        if self.ObjectPath is None:
            return
        if not os.path.isabs(self.ObjectPath):
            raise ValueError("Patient object path must be an absolute path.")
        atomic_save(
            filepath=self.ObjectPath, 
            write_func=lambda file: json.dump(self.to_dict(), file),
            error_message=f"Failed to save PatientData object to {self.ObjectPath}."
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatientData":
        """
        Create a PatientData instance from a serialized dictionary.

        Args:
            data: A dictionary representation of PatientData.

        Returns:
            An initialized PatientData object.
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

    def _internal_merge(self, other: "PatientData") -> None:
        """
        Merge data from another PatientData object into this one.

        Args:
            other: Another PatientData instance to merge.
        """
        if not isinstance(other, PatientData):
            raise ValueError("Can only merge another PatientData instance.")

        if self.MRN != other.MRN or self.Name.lower() != other.Name.lower():
            logger.error(f"Merge aborted due to mismatch in MRN/Name: ({self.MRN}, {self.Name}) != ({other.MRN}, {other.Name})")
            return

        for frame, modalities in other.DicomDict.items():
            for modality, sops in modalities.items():
                for sop_uid, filepath in sops.items():
                    self.DicomDict.setdefault(frame, {}).setdefault(modality, {})[sop_uid] = filepath

        for path in other.UniqueFilepaths:
            if path not in self.UniqueFilepaths:
                self.UniqueFilepaths.append(path)

        self.DateLastModified = datetime.now()
    
    @staticmethod
    def manual_merge(patient1: "PatientData", patient2: "PatientData") -> "PatientData":
        """
        Merge two PatientData instances into one.

        Prompts the user to supply a new MRN and Name if the two differ.

        Args:
            patient1: The first PatientData instance.
            patient2: The second PatientData instance.

        Returns:
            A new merged PatientData object.
        """
        if not isinstance(patient1, PatientData) or not isinstance(patient2, PatientData):
            raise ValueError("Can only merge PatientData instances.")

        new_MRN = patient1.MRN if patient1.MRN == patient2.MRN else input(
            f"First MRN was {patient1.MRN}, second MRN was {patient2.MRN}. Enter new MRN: "
        ).strip().replace('^', '')
        new_Name = patient1.Name if patient1.Name == patient2.Name else input(
            f"First Name was {patient1.Name}, second Name was {patient2.Name}. Enter new Name: "
        ).strip().replace('^', '')

        merged_patient = PatientData(new_MRN, new_Name)
        merged_patient.DateCreated = min(filter(None, [patient1.DateCreated, patient2.DateCreated]))
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
                                logger.info(f"Overwriting existing entry for SOPInstanceUID {sop_uid} in FrameOfReference {frame}, Modality {modality}")
                            merged_patient.DicomDict[frame][modality][sop_uid] = patient2.DicomDict[frame][modality][sop_uid]

        merged_patient.DicomFileReferencesDict = deepcopy(patient1.DicomFileReferencesDict)
        for key in patient2.DicomFileReferencesDict:
            if key in merged_patient.DicomFileReferencesDict:
                logger.info(f"Updating entry for key {key} in DicomFileReferencesDict")
                merged_patient.DicomFileReferencesDict[key].update(patient2.DicomFileReferencesDict[key])
            else:
                merged_patient.DicomFileReferencesDict[key] = patient2.DicomFileReferencesDict[key]

        merged_patient.DataDict = deepcopy(patient1.DataDict)
        for key in patient2.DataDict:
            if key in merged_patient.DataDict:
                logger.info(f"Overwriting entry for key {key} in DataDict")
            merged_patient.DataDict[key] = patient2.DataDict[key]

        merged_patient.DateLastModified = datetime.now()
        merged_patient.UniqueFilepaths = list(set(patient1.UniqueFilepaths + patient2.UniqueFilepaths))
        return merged_patient
