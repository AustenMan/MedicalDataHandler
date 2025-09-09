from __future__ import annotations


import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING


from sqlalchemy import func, select
from sqlalchemy.orm import selectinload


from mdh_app.database.db_session import get_session
from mdh_app.database.models import File, Patient


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def get_num_patients() -> int:
    """Get total number of patients in database."""
    with get_session() as session:
        return session.scalar(select(func.count(Patient.id))) or 0


def get_patient_full(patient_id: int) -> Optional[Patient]:
    """Retrieve patient with eagerly loaded files and metadata."""
    with get_session() as session:
        stmt = (
            select(Patient)
            .where(Patient.id == patient_id)
            .options(
                selectinload(Patient.files).selectinload(File.file_metadata)
            )
        )
        patient = session.scalars(stmt).first()
        
        if patient:
            # Ensure all relationships are fully loaded
            for file in patient.files:
                metadata = file.file_metadata
                if metadata:
                    # Access the file reference to ensure it's loaded
                    _ = metadata.file
                    
        return patient


def update_patient_accessed_at(patient: Patient, when: Optional[datetime] = None) -> None:
    """Update patient accessed_at timestamp."""
    timestamp = when or datetime.now()
    
    with get_session() as session:
        # Merge handles both attached and detached instances
        managed_patient = session.merge(patient)
        managed_patient.accessed_at = timestamp


def update_patient_processed_at(patient: Patient, when: Optional[datetime] = None) -> None:
    """Update patient processed_at timestamp."""
    timestamp = when or datetime.now()
    
    with get_session() as session:
        # Merge handles both attached and detached instances
        managed_patient = session.merge(patient)
        managed_patient.processed_at = timestamp
