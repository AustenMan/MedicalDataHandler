from __future__ import annotations


import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING


from sqlalchemy import func, select, delete
from sqlalchemy.orm import selectinload


from mdh_app.database.db_session import get_session
from mdh_app.database.models import Patient, File, FileMetadata, FileMetadataOverride


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def get_num_patients() -> int:
    """Get total number of patients in database."""
    with get_session(expire_all=True) as session:
        return session.scalar(select(func.count(Patient.id))) or 0


def get_patient_full(patient_id: int) -> Optional[Patient]:
    """Retrieve patient with eagerly loaded files and metadata."""
    with get_session(expire_all=True) as session:
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


def delete_all_data() -> bool:
    """Delete ALL data from database tables (preserves schema)."""
    logger.info("Deleting database data")
    
    try:
        with get_session() as session:
            # Order matters due to foreign key constraints
            tables_to_clear = [
                FileMetadataOverride,
                FileMetadata,
                File,
                Patient
            ]
            
            for table in tables_to_clear:
                count = session.scalar(select(func.count()).select_from(table)) or 0
                if count > 0:
                    session.execute(delete(table))
                    logger.info(f"Deleted {count} records from {table.__tablename__}")
            
            # Context manager will commit
            logger.info("All data deleted")
            return True
            
    except Exception as e:
        logger.exception("Failed to delete all data.", exc_info=True, stack_info=True)
        return False

