from __future__ import annotations


import logging
from datetime import datetime
from typing import TYPE_CHECKING


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)
Base = declarative_base()


class Patient(Base):
    """Patient record with demographics and processing timestamps."""
    __tablename__ = 'patient'
    
    id = Column(Integer, primary_key=True)
    mrn = Column(String, nullable=False, doc="Medical Record Number")
    name = Column(String, nullable=False, doc="Patient name (may be anonymized)")
    is_anonymized = Column(Boolean, default=False, doc="Whether patient data has been anonymized")
    
    # Timestamps for tracking patient data lifecycle
    created_at = Column(DateTime, default=datetime.now, doc="When patient record was created")
    modified_at = Column(DateTime, doc="When patient record was last modified")
    accessed_at = Column(DateTime, doc="When patient data was last accessed")
    processed_at = Column(DateTime, doc="When patient data was last processed")
    
    # Relationships
    files = relationship(
        "File", 
        back_populates="patient", 
        lazy="selectin",
        doc="DICOM files associated with this patient"
    )
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('mrn', 'name', name='uq_patient_mrn_name'),
    )
    
    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, mrn='{self.mrn}', name='{self.name}')>"


class File(Base):
    """DICOM file record with path and metadata relationships."""
    __tablename__ = 'file'
    
    id = Column(Integer, primary_key=True)
    patient_id = Column(
        Integer, 
        ForeignKey('patient.id'), 
        nullable=False,
        doc="Foreign key to patient who owns this file"
    )
    
    path = Column(
        String, 
        unique=True, 
        nullable=False,
        doc="Absolute file system path to DICOM file"
    )
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now, doc="When file record was created")
    modified_at = Column(DateTime, doc="When file record was last modified")
    
    # Relationships
    patient = relationship("Patient", back_populates="files")
    file_metadata = relationship(
        "FileMetadata", 
        uselist=False, 
        back_populates="file",
        doc="DICOM metadata extracted from this file"
    )
    
    def __repr__(self) -> str:
        return f"<File(id={self.id}, path='{self.path}')>"


class FileMetadata(Base):
    """DICOM metadata with essential tags and cross-references."""
    __tablename__ = 'file_metadata'
    
    id = Column(Integer, primary_key=True)
    file_id = Column(
        Integer, 
        ForeignKey('file.id'), 
        nullable=False,
        doc="Foreign key to the DICOM file"
    )
    patient_id = Column(
        Integer, 
        ForeignKey('patient.id'), 
        nullable=False,
        doc="Foreign key to patient for denormalization"
    )
    
    # Basic DICOM information
    label = Column(String, doc="Human-readable label for the file")
    name = Column(String, doc="DICOM series or study name")
    description = Column(String, doc="Detailed description of the data")
    date = Column(String, doc="Study or series date (YYYYMMDD format)")
    time = Column(String, doc="Study or series time (HHMMSS format)")
    
    # Core DICOM UIDs
    frame_of_reference_uid = Column(String, doc="Frame of Reference UID for spatial alignment")
    modality = Column(String, doc="DICOM modality (CT, MR, RTPLAN, RTSTRUCT, RTDOSE, etc.)")
    sop_instance_uid = Column(String, doc="Unique identifier for this DICOM instance")
    sop_class_uid = Column(String, doc="DICOM SOP Class UID defining object type")
    series_instance_uid = Column(String, doc="Series Instance UID grouping related images")
    study_instance_uid = Column(String, doc="Study Instance UID grouping related series")
    
    # Radiotherapy-specific fields
    dose_summation_type = Column(String, doc="How dose distributions should be summed")
    
    # Referenced object sequences (for linking related DICOM objects)
    referenced_sop_class_uid_seq = Column(String, doc="Referenced SOP Class UIDs")
    referenced_sop_instance_uid_seq = Column(String, doc="Referenced SOP Instance UIDs")
    referenced_frame_of_reference_uid_seq = Column(String, doc="Referenced Frame of Reference UIDs")
    referenced_series_instance_uid_seq = Column(String, doc="Referenced Series Instance UIDs")
    
    # RT Plan references
    referenced_rt_plan_sopi_seq = Column(String, doc="Referenced RT Plan SOP Instance UIDs")
    referenced_rt_plan_sopc_seq = Column(String, doc="Referenced RT Plan SOP Class UIDs")
    
    # RT Structure Set references
    referenced_structure_set_sopi_seq = Column(String, doc="Referenced Structure Set SOP Instance UIDs")
    referenced_structure_set_sopc_seq = Column(String, doc="Referenced Structure Set SOP Class UIDs")
    
    # RT Dose references
    referenced_dose_sopi_seq = Column(String, doc="Referenced Dose SOP Instance UIDs")
    referenced_dose_sopc_seq = Column(String, doc="Referenced Dose SOP Class UIDs")
    
    # Relationships
    file = relationship("File", back_populates="file_metadata")
    
    def __repr__(self) -> str:
        return f"<FileMetadata(id={self.id}, modality='{self.modality}', sop_instance_uid='{self.sop_instance_uid}')>"


class FileMetadataOverride(Base):
    """User modifications to DICOM metadata with audit trail."""
    __tablename__ = 'file_metadata_override'
    
    id = Column(Integer, primary_key=True)
    file_id = Column(
        Integer, 
        ForeignKey('file.id'), 
        nullable=False,
        doc="Foreign key to the file being modified"
    )
    
    field_name = Column(
        String, 
        nullable=False,
        doc="Name of the metadata field being overridden"
    )
    old_value = Column(String, doc="Original value before modification")
    new_value = Column(String, doc="New value after modification")
    modified_by = Column(String, doc="User or system that made the modification")
    modified_at = Column(
        DateTime, 
        default=datetime.now,
        doc="When the modification was made"
    )
    
    def __repr__(self) -> str:
        return f"<FileMetadataOverride(id={self.id}, field='{self.field_name}', modified_by='{self.modified_by}')>"


# Example queries for common operations:
#
# Find all files for a specific SOP Instance UID:
#   SELECT f.path FROM file_metadata fm
#   JOIN file f ON fm.file_id = f.id
#   WHERE fm.sop_instance_uid = ?;
#
# Find all files in the same Frame of Reference:
#   SELECT f.path FROM file_metadata fm
#   JOIN file f ON fm.file_id = f.id
#   WHERE fm.frame_of_reference_uid = ?;
#
# Get patient processing statistics:
#   SELECT COUNT(*) as total_patients,
#          COUNT(processed_at) as processed_count
#   FROM patient;

