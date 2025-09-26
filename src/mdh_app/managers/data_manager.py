from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union, Optional, Set, Literal
import gc
from json import load, dump, dumps
from os.path import exists
from copy import deepcopy


import cv2
import numpy as np
import SimpleITK as sitk


from mdh_app.data_builders.ImageBuilder import construct_image
from mdh_app.data_builders.RTStructBuilder import extract_rtstruct_and_roi_datasets
from mdh_app.data_builders.RTDoseBuilder import construct_dose
from mdh_app.utils.dicom_utils import (
    read_dcm_file, get_first_ref_beam_number, get_first_num_fxns_planned, 
    get_first_ref_series_uid, get_first_ref_struct_sop_uid, 
)
from mdh_app.utils.general_utils import (
    get_json_list, struct_name_priority_key, regex_find_dose_and_fractions,
    clean_dicom_string, find_reformatted_mask_name, find_disease_site,
    validate_rgb_color, atomic_save
)
from mdh_app.utils.numpy_utils import numpy_roi_mask_generation, create_HU_to_RED_map
from mdh_app.utils.sitk_utils import (
    sitk_resample_to_reference, resample_sitk_data_with_params, get_orientation_labels, 
    copy_all_metadata
)


if TYPE_CHECKING:
    from pydicom import Dataset
    from mdh_app.database.models import Patient, File, FileMetadata
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


def build_single_mask(roi_ds_dict: Dict[str, Dataset], sitk_image_params: Dict[str, Any]) -> Optional[sitk.Image]:
    """Build binary mask from ROI contour data with TG-263 naming."""
    roi_name = roi_ds_dict.get("StructureSetROI", {}).get("ROIName", "N/A")
    roi_number = roi_ds_dict.get("StructureSetROI", {}).get("ROINumber", None)

    if roi_number is None:
        logger.error(f"ROI number is missing for ROI with name '{roi_name}'. Cannot build mask.")
        return None

    # Initialize mask with (slices, rows, cols) shape
    mask_shape = (sitk_image_params["slices"], sitk_image_params["rows"], sitk_image_params["cols"])
    mask_np = np.zeros(mask_shape, dtype=np.uint8)
    
    # Precompute transformation matrix components
    origin_array = np.array(sitk_image_params["origin"], dtype=np.float32)
    spacing_array = np.array(sitk_image_params["spacing"], dtype=np.float32)
    direction_array = np.array(sitk_image_params["direction"], dtype=np.float32).reshape(3, 3)
    A_inv_T = np.linalg.inv(direction_array @ np.diag(spacing_array)).T
    
    has_valid_contour_data = False
    contour_seq = roi_ds_dict.get("ROIContour", {}).get("ContourSequence", [])
    
    for contour_ds in contour_seq:
        try:
            contour_num = contour_ds.get("ContourNumber", None)
            contour_geom_type = contour_ds.get("ContourGeometricType", None)
            if contour_geom_type is None:
                logger.warning(
                    f"Skipping invalid ContourGeometricType for contour number {contour_num} "
                    f"in ROI '{roi_name}' (number: {roi_number}). Found: {contour_geom_type}."
                )
                continue
            
            # Extract and reshape contour points from flat array to (N, 3) array
            contour_points_flat = contour_ds.get("ContourData", [])
            if not contour_points_flat or len(contour_points_flat) % 3 != 0:
                logger.warning(
                    f"Skipping invalid or missing ContourData for contour number {contour_num} "
                    f"in ROI '{roi_name}' (number: {roi_number}). Found: {contour_points_flat}"
                )
                continue
            
            # Transform physical coordinates to image matrix indices
            contour_points_3d = np.array(contour_points_flat, dtype=np.float32).reshape(-1, 3)
            matrix_points = np.rint((contour_points_3d - origin_array) @ A_inv_T).astype(np.int32)
            
            # Add points to mask
            numpy_roi_mask_generation(mask=mask_np, matrix_points=matrix_points, geometric_type=contour_geom_type)
            has_valid_contour_data = True
        except Exception as e:
            logger.error(
                f"Failed to process contour number {contour_num} for ROI '{roi_name}' (number: {roi_number})", 
                exc_info=True, stack_info=True
            )
            continue
    
    # Check if any valid contour data was processed
    if not has_valid_contour_data:
        logger.warning(f"No valid contour data processed for ROI '{roi_name}' (number: {roi_number}).")
        return None
    
    # Create SimpleITK image from numpy array
    mask_sitk: sitk.Image = sitk.GetImageFromArray(mask_np)
    mask_sitk.SetSpacing(sitk_image_params["spacing"])
    mask_sitk.SetDirection(sitk_image_params["direction"])
    mask_sitk.SetOrigin(sitk_image_params["origin"])

    return mask_sitk


class DataManager:
    """Manages RT data loading and processing using SimpleITK."""

    def __init__(self, conf_mgr: ConfigManager, ss_mgr: SharedStateManager) -> None:
        """Initialize data manager with configuration and state managers."""
        self.conf_mgr = conf_mgr
        self.ss_mgr = ss_mgr
        
        self.keys_roi_ds_dict: Set[str] = {"StructureSetROI", "ROIContour", "RTROIObservations"}
        
        # Define the dose colormap in BGR order and normalize to [0, 1]
        self._dose_colors = np.clip(
            np.array([
                [0, 0, 90],     # Deep Blue (0%)  
                [0, 15, 180],   # Blue (~10%)  
                [0, 60, 255],   # Bright Blue (~20%)  
                [0, 120, 255],  # Blue-Cyan (~30%)  
                [0, 200, 255],  # Cyan (~40%)  
                [0, 255, 200],  # Cyan-Green (~50%)  
                [50, 255, 100], # Greenish (~55%)  
                [120, 255, 0],  # Green (~60%)  
                [200, 255, 0],  # Yellow-Green (~70%)  
                [255, 255, 0],  # Yellow (~80%)  
                [255, 180, 0],  # Yellow-Orange (~85%)  
                [255, 120, 0],  # Orange (~90%)  
                [255, 50, 0],   # Deep Orange (~95%)  
                [255, 0, 0]     # Red (100%)  
            ], dtype=np.float32) / 255.0, 
            a_min=0.0, a_max=1.0
        )
        self._num_dose_colors = len(self._dose_colors)
        
        self.HU_to_RED_map = create_HU_to_RED_map(
            hu_values=conf_mgr.get_ct_HU_map_vals(), 
            red_values=conf_mgr.get_ct_RED_map_vals()
        )
        
        self.initialize_data()
        self._update_raw_data_params()
    
    def initialize_data(self) -> None:
        """Initialize data structures and cache."""
        self.images: Dict[str, sitk.Image] = {}
        self.image_fpaths: Dict[str, List[str]] = {}
        self.images_params: Dict[str, Dict[str, Any]] = {}
        self.rtstruct_datasets: Dict[str, Dataset] = {}
        self.rtstruct_fpaths: Dict[str, str] = {}
        self.rtstruct_roi_metadata: Dict[str, Dict[int, Dict[str, Any]]] = {}
        self.rtstruct_roi_ds_dicts: Dict[str, Dict[int, Dict[str, Dataset]]] = {}
        self.rois: Dict[Tuple[str, int], sitk.Image] = {}
        self.rtplan_datasets: Dict[str, Dataset] = {}
        self.rtplan_fpaths: Dict[str, str] = {}
        self.rtdoses: Dict[str, sitk.Image] = {}
        self.rtdose_fpaths: Dict[str, str] = {}
        self._patient_objectives_dict: Dict[str, Any] = {}
        self.initialize_texture_cache()
    
    def initialize_texture_cache(self) -> None:
        """Initialize temporary texture cache."""
        self._cached_sitk_reference: Optional[sitk.Image] = None
        self._cached_texture_param_dict: Dict[str, Any] = {}
        self._cached_sitk_objects: Dict[Union[str, Tuple[str, int]], sitk.Image] = {}
        self._cached_dose_sum: Optional[sitk.Image] = None
    
    def clear_data(self) -> None:
        """Clear all loaded data and trigger garbage collection."""
        self.images.clear()
        self.image_fpaths.clear()
        self.images_params.clear()
        self.rtstruct_datasets.clear()
        self.rtstruct_fpaths.clear()
        self.rtstruct_roi_metadata.clear()
        self.rtstruct_roi_ds_dicts.clear()
        self.rois.clear()
        self.rtplan_datasets.clear()
        self.rtplan_fpaths.clear()
        self.rtdoses.clear()
        self.rtdose_fpaths.clear()
        self._patient_objectives_dict.clear()
        self._clear_cache()
        gc.collect()
    
    def _clear_cache(self) -> None:
        """Clear all cached temporary data."""
        self._cached_sitk_reference = None
        self._cached_texture_param_dict.clear()
        self._cached_sitk_objects.clear()
        self._cached_dose_sum = None
    
    @property
    def is_any_data_loaded(self) -> bool:
        """True if any modality data is loaded."""
        return bool(self.images or self.rtstruct_datasets or self.rtplan_datasets or self.rtdoses)

    @property
    def is_all_data_loaded(self) -> bool:
        """True if all modalities are loaded."""
        return bool(self.images and self.rtstruct_datasets and self.rtplan_datasets and self.rtdoses)

    @property
    def is_image_data_loaded(self) -> bool:
        """True if image data is loaded."""
        return bool(self.images)

    @property
    def is_rtstruct_data_loaded(self) -> bool:
        """True if RTSTRUCT data is loaded."""
        return bool(self.rtstruct_datasets)

    @property
    def is_rtplan_data_loaded(self) -> bool:
        """True if RTPLAN data is loaded."""
        return bool(self.rtplan_datasets)

    @property
    def is_rtdose_data_loaded(self) -> bool:
        """True if RTDOSE data is loaded."""
        return bool(self.rtdoses)
    
    def load_all_dicom_data(self, patient: Patient, selected_files: Set[str]) -> None:
        """Loads selected DICOM data."""
        self._clear_cache()
        modalities: Dict[str, Set[str]] = self.conf_mgr.get_dicom_modalities()
        
        img_data: Dict[str, List[File]] = {}
        rtstruct_files: List[File] = []
        rtplan_files: List[File] = []
        rtdose_data: Dict[str, List[File]] = {"plan_dose": [], "beam_dose": []}
        seen_sopi = set()
        
        for file_obj in patient.files:
            file_obj: File
            
            file_path = file_obj.path
            if not file_path:
                logger.error(f"Skipping file '{file_obj.filepath}' due to missing path.")
                continue
            if not exists(file_path):
                logger.error(f"Skipping file '{file_obj.filepath}' because the file does not exist at path '{file_path}'.")
                continue
            if file_path not in selected_files:
                continue # No message needed; user intentionally deselected
            
            file_md: FileMetadata = file_obj.file_metadata
            if not file_md:
                logger.error(f"Skipping file '{file_obj.filepath}' due to missing metadata.")
                continue
            
            file_modality = (file_md.modality or "").strip().upper()
            if not file_modality:
                logger.error(f"Skipping file '{file_obj.filepath}' due to missing Modality in metadata.")
                continue

            file_sopi = (file_md.sop_instance_uid or "").strip()
            if not file_sopi:
                logger.error(f"Skipping file '{file_obj.filepath}' due to missing SOPInstanceUID in metadata.")
                continue
            if file_sopi in seen_sopi:
                logger.error(f"Skipping file '{file_obj.filepath}' due to duplicate SOPInstanceUID '{file_sopi}', which was already identified.")
                continue
            seen_sopi.add(file_sopi)

            # Image Series Handling
            if file_modality in modalities["image"]:
                file_series_uid = (file_md.series_instance_uid or "").strip()
                if not file_series_uid:
                    logger.error(f"Skipping IMAGE file '{file_obj.filepath}' due to missing SeriesInstanceUID.")
                    continue
                img_data.setdefault(file_series_uid, []).append(file_obj)
            
            # RT Structure Set Handling
            elif file_modality in modalities["rtstruct"]:
                rtstruct_files.append(file_obj)
            
            # RT Plan Handling
            elif file_modality in modalities["rtplan"]:
                rtplan_files.append(file_obj)
            
            # RT Dose Handling
            elif file_modality in modalities["rtdose"]:
                dose_summation_type = (file_md.dose_summation_type or "").strip().upper()
                if dose_summation_type == "PLAN":
                    rtdose_data["plan_dose"].append(file_obj)
                elif dose_summation_type == "BEAM":
                    rtdose_data["beam_dose"].append(file_obj)
                else:
                    logger.error(f"Skipping RTDOSE file '{file_obj.filepath}' due to unsupported or missing DoseSummationType '{dose_summation_type}'.")
                    continue
            
            # Unsupported Modality Handling
            else:
                logger.error(f"Skipping file '{file_obj.filepath}' due to unsupported Modality '{file_modality}'.")
                continue
        
        # set class patient to use in other functions ###
        self.load_images(img_data)
        self.load_rtstructs(rtstruct_files)
        self.load_rtplans(rtplan_files)
        self.load_rtdoses(rtdose_data)

        # Review from here
        self._clear_cache()
        if not self.is_any_data_loaded:
            logger.error("No valid data was selected or loaded, please try again.")
            return
        self.load_rtstruct_goals(patient.mrn)
        logger.info("Loaded SITK data")
    
    ### Internal Data Retrieval Methods ###
    def _get_data(self, data_type: Literal["image", "roi", "dose"], key: Union[str, Tuple[str, int]], use_cached: bool = False) -> Optional[sitk.Image]:
        """Retrieve SITK image by type and key, optionally using cached version."""
        if use_cached:
            cache_key = (data_type, *key) if isinstance(key, tuple) else (data_type, key)
            self.update_cached_data(True, cache_key)  # builds ROI and adds to cache if needed
            return self._cached_sitk_objects.get(cache_key, None)
        
        if data_type == "image":
            return self.images.get(key, None)
        elif data_type == "roi":
            self.build_rtstruct_roi(*key)  # ensure ROI is built first
            return self.rois.get(key, None)
        elif data_type == "dose":
            return self.rtdoses.get(key, None)
        return None

    def _update_raw_data_params(self) -> None:
        """Update original image parameters based on the first loaded image."""
        if self._cached_sitk_objects:
            cached_img_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "image"]
            if cached_img_keys and cached_img_keys[0][1] in self.images:
                image = self.images[cached_img_keys[0][1]]
                self.original_size = image.GetSize()
                self.original_spacing = image.GetSpacing()
                self.original_origin = image.GetOrigin()
                self.original_direction = image.GetDirection()
                return

            cached_roi_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "roi"]
            if cached_roi_keys and cached_roi_keys[0][1:] in self.rois:
                roi = self.rois[cached_roi_keys[0][1:]]
                self.original_size = roi.GetSize()
                self.original_spacing = roi.GetSpacing()
                self.original_origin = roi.GetOrigin()
                self.original_direction = roi.GetDirection()
                return
            
            cached_dose_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "dose"]
            if cached_dose_keys and cached_dose_keys[0][1] in self.rtdoses:
                dose = self.rtdoses[cached_dose_keys[0][1]]
                self.original_size = dose.GetSize()
                self.original_spacing = dose.GetSpacing()
                self.original_origin = dose.GetOrigin()
                self.original_direction = dose.GetDirection()
                return
            
            logger.warning(f"Cannot update original image params, none of the cached objects are valid: {self._cached_sitk_objects.keys()}")
            
        elif self.images:
            first_image = next(iter(self.images.values()))
            self.original_size = first_image.GetSize()
            self.original_spacing = first_image.GetSpacing()
            self.original_origin = first_image.GetOrigin()
            self.original_direction = first_image.GetDirection()
        
        elif self.rois:
            first_roi = next(iter(self.rois.values()))
            self.original_size = first_roi.GetSize()
            self.original_spacing = first_roi.GetSpacing()
            self.original_origin = first_roi.GetOrigin()
            self.original_direction = first_roi.GetDirection()
        
        elif self.rtdoses:
            first_dose = next(iter(self.rtdoses.values()))
            self.original_size = first_dose.GetSize()
            self.original_spacing = first_dose.GetSpacing()
            self.original_origin = first_dose.GetOrigin()
            self.original_direction = first_dose.GetDirection()
        
        else:
            self.original_size = (600, 600, 600)
            self.original_spacing = (3.0, 3.0, 3.0)
            self.original_origin = (0.0, 0.0, 0.0)
            self.original_direction = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    
    ### Image Data Methods ###
    def load_images(self, img_data: Dict[str, List[File]]) -> Dict[str, Any]:
        """Load IMAGEs and update internal data dictionary."""
        if not img_data:
            return
        
        for series_instance_uid, files in img_data.items():
            if self.ss_mgr.cleanup_event.is_set() or self.ss_mgr.shutdown_event.is_set():
                return
            
            # Skip if already loaded
            if series_instance_uid in self.images:
                logger.error(f"Skipping IMAGE SeriesInstanceUID '{series_instance_uid}' due to duplicate series already loaded.")
                continue
            
            # Get info for files
            file_paths = [f.path for f in files]
            modality = (files[0].file_metadata.modality or "").strip().upper()
            logger.debug(f"Loading {modality} series {series_instance_uid} from {len(file_paths)} files")
            
            # Construct image
            sitk_image = construct_image(file_paths, self.ss_mgr, series_instance_uid)
            if sitk_image is None:
                logger.error(f"Failed to load {modality} with SeriesInstanceUID '{series_instance_uid}'.")
                continue
            
            # Validate SeriesInstanceUID
            validate_series_uid = str(sitk_image.GetMetaData("SeriesInstanceUID")).strip()
            if validate_series_uid != series_instance_uid:
                logger.error(f"Mismatch in SeriesInstanceUID for IMAGE files '{file_paths}': metadata has '{series_instance_uid}' but DICOM has '{validate_series_uid}'. Skipping.")
                continue
            
            # Add to dictionaries
            self.images[series_instance_uid] = sitk_image
            self.image_fpaths[series_instance_uid] = file_paths
        
        self.images_params = {
            k: {
                "origin": sitk_image.GetOrigin(),
                "spacing": sitk_image.GetSpacing(),
                "direction": sitk_image.GetDirection(),
                "cols": sitk_image.GetSize()[0],
                "rows": sitk_image.GetSize()[1],
                "slices": sitk_image.GetSize()[2],
            } 
            for k, sitk_image in self.images.items()
        }
    
    def get_image_series_uids(self) -> List[str]:
        """Return list of available image SeriesInstanceUIDs."""
        return list(self.images.keys())
    
    def get_image_filepaths_by_series_uid(self, series_uid: str) -> List[str]:
        """Get file paths for image using SeriesInstanceUID."""
        return self.image_fpaths.get(series_uid, [])
    
    def get_image_metadata_by_series_uid_and_key(self, series_uid: str, metadata_key: Optional[str] = None, default: Any = None) -> Any:
        """Get metadata from image using SeriesInstanceUID.
        
        Args:
            series_uid: Image SeriesInstanceUID.
            metadata_key: The metadata key to retrieve.
            default: Default value if key doesn't exist.
            
        Returns:
            The metadata value or default.
        """
        if series_uid not in self.images:
            return default
        sitk_obj = self.images[series_uid]
        if not isinstance(sitk_obj, sitk.Image):
            return default
        if sitk_obj.HasMetaDataKey(metadata_key):
            return sitk_obj.GetMetaData(metadata_key)
        return default

    def get_image_metadata_dict_by_series_uid(self, series_uid: str, default: Any = None) -> Any:
        """
        Return a dict of metadata key->value for the SITK image identified by series_uid.
        Keys with empty values are omitted. If series_uid is not found or not a SITK image
        the provided `default` is returned.
        """
        if series_uid not in self.images:
            return default
        sitk_obj = self.images[series_uid]
        if not isinstance(sitk_obj, sitk.Image):
            return default

        try:
            keys = list(sitk_obj.GetMetaDataKeys())
        except Exception as exc:
            logger.error(f"Failed to enumerate metadata keys for series {series_uid}.", exc_info=True, stack_info=True)
            return default

        return {k: sitk_obj.GetMetaData(k) for k in keys}
    
    
    ### RTSTRUCT Data Methods ###
    def load_rtstructs(self, rtstruct_files: List[File]) -> None:
        """Load RTSTRUCTs and update internal data dictionary."""
        if not rtstruct_files:
            return
        
        if not self.images:
            logger.error("No IMAGE data loaded; cannot load RTSTRUCT data without corresponding IMAGE.")
            return
        
        if not self.images_params:
            logger.error("No valid IMAGE parameters found; cannot load RTSTRUCT data.")
            return
        
        for rtstruct_file in rtstruct_files:
            if self.ss_mgr.cleanup_event.is_set() or self.ss_mgr.shutdown_event.is_set():
                return
            
            # Get file info
            file_path = rtstruct_file.path
            modality = (rtstruct_file.file_metadata.modality or "").strip().upper()
            sop_instance_uid = (rtstruct_file.file_metadata.sop_instance_uid or "").strip()
            
            # Skip if already loaded
            if sop_instance_uid in self.rtstruct_datasets:
                logger.error(f"Skipping RTSTRUCT file '{file_path}' due to duplicate SOPInstanceUID '{sop_instance_uid}' already loaded.")
                continue
            
            # Get a referenced SeriesInstanceUID that matches a loaded IMAGE, so we can use its params for display
            ref_series_uid_seq = get_json_list(rtstruct_file.file_metadata.referenced_series_instance_uid_seq)
            if not ref_series_uid_seq:
                logger.error(f"Skipping RTSTRUCT file '{file_path}' due to missing ReferencedSeriesInstanceUIDs.")
                continue
            matched_ref_series_uids = [uid for uid in ref_series_uid_seq if uid in self.images_params]
            if not matched_ref_series_uids:
                logger.error(f"Skipping RTSTRUCT file '{file_path}' as none of its ReferencedSeriesInstanceUIDs {ref_series_uid_seq} match loaded IMAGE SeriesInstanceUIDs.")
                continue
            if len(set(matched_ref_series_uids)) > 1:
                logger.warning(f"RTSTRUCT file '{file_path}' has multiple matched ReferencedSeriesInstanceUIDs: {matched_ref_series_uids}, only the first will be used.")
            matched_ref_series_uid = matched_ref_series_uids[0]
            image_params = self.images_params[matched_ref_series_uid]

            # Extract RTSTRUCT and ROI datasets
            logger.debug(f"Loading {modality} {sop_instance_uid}: {file_path}")
            result = extract_rtstruct_and_roi_datasets(file_path, image_params, self.ss_mgr)
            if result is None:
                logger.error(f"Failed to extract RTSTRUCT data from file '{file_path}'.")
                continue
            rtstruct_ds: Dataset = result[0]
            roi_ds_dict: Dict[int, Dict[str, Dataset]] = result[1] # ROI Number -> {"StructureSetROI": ds, "ROIContour": ds, "RTROIObservations": ds}
            
            # Validate SOPInstanceUID
            validate_sopiuid = str(rtstruct_ds.SOPInstanceUID).strip()
            if validate_sopiuid != sop_instance_uid:
                logger.error(f"Mismatch in SOPInstanceUID for RTSTRUCT file '{file_path}': metadata has '{sop_instance_uid}' but DICOM has '{validate_sopiuid}'. Skipping.")
                continue
            
            # Add to dictionaries
            self.rtstruct_datasets[sop_instance_uid] = rtstruct_ds
            self.rtstruct_fpaths[sop_instance_uid] = file_path
            self.rtstruct_roi_ds_dicts[sop_instance_uid] = roi_ds_dict
            
            # Add metadata for each ROI
            for roi_number in roi_ds_dict.keys():
                self.init_roi_gui_metadata_by_uid(sop_instance_uid, roi_number)
    
    def get_rtstruct_uids(self) -> List[str]:
        """Return list of available RTSTRUCT SOPInstanceUIDs."""
        return list(self.rtstruct_datasets.keys())
    
    def get_rtstruct_ds_value_by_uid_and_key(self, struct_uid: str, metadata_key: str, default: Any = None, return_deepcopy: bool = True) -> Any:
        """Get metadata from RTSTRUCT using SOPInstanceUID.
        
        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            metadata_key: The metadata key to retrieve.
            default: Default value if key doesn't exist.
            
        Returns:
            The metadata value or default.
        """
        if struct_uid not in self.rtstruct_datasets:
            return default
        ds: Dataset = self.rtstruct_datasets[struct_uid]
        value = ds.get(metadata_key, default)
        return deepcopy(value) if return_deepcopy else value


    ### RTSTRUCT ROI Data Methods ###
    def load_rtstruct_goals(self, patient_mrn: str) -> None:
        """Load and apply RTSTRUCT goals from JSON file."""
        if not patient_mrn or not self.rtstruct_datasets:
            return

        if not patient_mrn:
            logger.error("No patient MRN provided; cannot update RTSTRUCT with goals.")
            return

        objectives_fpath = self.conf_mgr.get_objectives_filepath()
        if not objectives_fpath or not objectives_fpath.endswith(".json") or not exists(objectives_fpath):
            logger.error(f"Objectives JSON file not found at location: {objectives_fpath}. Cannot update RTSTRUCT with goals.")
            return

        with open(objectives_fpath, 'rt') as file:
            patient_objectives = load(file).get(patient_mrn, {})
        if not patient_objectives:
            logger.error(f"No objectives found for patient MRN '{patient_mrn}' in the JSON file.")
            return
        
        self._patient_objectives_dict.update(patient_objectives)
        
        # Find relevant objectives for the patient's RTSTRUCTs
        matched_objectives: Dict[str, Any] = {}
        for rtstruct_ds in self.rtstruct_datasets.values():
            ss_sopi = (rtstruct_ds.get("SOPInstanceUID", "") or "").strip()
            ss_label = (rtstruct_ds.get("StructureSetLabel", "") or "").strip()
            if not ss_label:
                continue
            logger.info(f"Checking objectives for RTSTRUCT: {ss_label}")
            structure_set_objectives = self._patient_objectives_dict.get("StructureSetId", {}).get(ss_label, {})
            if structure_set_objectives:
                matched_objectives.setdefault(ss_sopi, {}).update(structure_set_objectives)
        
        # Find relevant objectives for the patient's RTPLAN(s) that reference RTSTRUCTs
        for rtplan_ds in self.rtplan_datasets.values():
            rtp_label = (rtplan_ds.get("RTPlanLabel", "") or "").strip()
            if not rtp_label:
                continue
            logger.info(f"Checking objectives for RTPLAN: {rtp_label}")
            
            plan_objectives = self._patient_objectives_dict.get("PlanId", {}).get(rtp_label, {})
            if not plan_objectives:
                continue
            
            for ref_rtstruct_ds in rtplan_ds.get("ReferencedStructureSetSequence", []):
                ref_ss_sopi = (ref_rtstruct_ds.get("ReferencedSOPInstanceUID", "") or "").strip()
                if not ref_ss_sopi:
                    continue
                matched_objectives.setdefault(ref_ss_sopi, {}).update(plan_objectives)
        
        if not matched_objectives:
            logger.error("No objectives found for the patient in the JSON file; cannot update RTSTRUCT with goals.")
            return
        
        # Add ROI goals as SITK metadata
        for ss_sopi, objectives in matched_objectives.items():
            if ss_sopi not in self.rtstruct_datasets:
                continue
            roi_ds_dict = self.rtstruct_roi_ds_dicts.get(ss_sopi, {})
            for roi_number, roi_ds_dict in roi_ds_dict.items():
                structure_set_roi_ds = roi_ds_dict.get("StructureSetROI")
                roi_name = (structure_set_roi_ds.get("ROIName", "") or "").strip()
                
                # First pass to match by ROIName
                found_roi_goals = objectives.get(roi_name, {}).get("Goals")
                # Second pass to match by ManualStructNames if not found
                if not found_roi_goals:
                    for obj_struct, obj_dict in objectives.items():
                        if obj_struct == roi_name or roi_name in obj_dict.get("ManualStructNames", []):
                            found_roi_goals = obj_dict.get("Goals")
                            break
                if not found_roi_goals:
                    continue
                
                if ss_sopi not in self.rtstruct_roi_metadata or roi_number not in self.rtstruct_roi_metadata[ss_sopi]:
                    self.init_roi_gui_metadata_by_uid(ss_sopi, roi_number)
                self.rtstruct_roi_metadata[ss_sopi][roi_number]["roi_goals"] = found_roi_goals

                logger.info(f"Updated goals for ROI '{roi_name}' in RTSTRUCT (SOPInstanceUID: {ss_sopi}): {found_roi_goals}")
    
    def build_rtstruct_roi(self, struct_uid: str, roi_number: int) -> None:
        """ Build and cache ROI mask as a SimpleITK image. Returns None if failed. """
        if (struct_uid, roi_number) in self.rois:
            return  # Already built
        
        if struct_uid not in self.rtstruct_roi_ds_dicts:
            logger.error(f"RTSTRUCT with UID {struct_uid} not found. Cannot build ROI.")
            return
        roi_ds_dict = self.rtstruct_roi_ds_dicts[struct_uid].get(roi_number)
        if not roi_ds_dict:
            logger.error(f"ROI {roi_number} not found in RTSTRUCT {struct_uid}. Cannot build ROI.")
            return
        
        ref_series_uid = get_first_ref_series_uid(self.rtstruct_datasets[struct_uid])
        if not ref_series_uid or ref_series_uid not in self.images:
            logger.error(f"RTSTRUCT {struct_uid} references missing image series {ref_series_uid}. Cannot build ROI.")
            return
        image_params = self.images_params.get(ref_series_uid)
        if not image_params:
            logger.error(f"Missing image parameters for series {ref_series_uid}. Cannot build ROI.")
            return
        
        # Check metadata to see if disabled
        if self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {}).get("disabled", True):
            return  # ROI is disabled, do not build
        
        # Build the mask
        mask_sitk = build_single_mask(roi_ds_dict, image_params)
        if mask_sitk is None:
            return
        self.rois[(struct_uid, roi_number)] = mask_sitk
    
    def get_rtstruct_roi_numbers_by_uid(
        self,
        struct_uid: str,
        sort_by_name: bool = False
    ) -> List[int]:
        """Get list of ROI numbers defined in RTSTRUCT using SOPInstanceUID.
        
        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            sort_by_name: If True, sort ROI numbers by the ROIName in StructureSetROI.
                        If False, sort numerically by ROI number (default).
            
        Returns:
            List of ROI numbers, possibly sorted by ROIName. Empty list if not found.
        """
        if struct_uid not in self.rtstruct_roi_ds_dicts:
            return []

        roi_dict = self.rtstruct_roi_ds_dicts[struct_uid]

        if not sort_by_name:
            return sorted(roi_dict.keys())

        # Collect (roi_number, roi_name) pairs
        roi_pairs = []
        for roi_number, roi_ds_dict in roi_dict.items():
            roi_name = roi_ds_dict.get("StructureSetROI", {}).get("ROIName", "") or ""
            roi_pairs.append((roi_number, roi_name))

        # Sort by struct_name_priority_key first, then by name, then roi_number
        roi_pairs.sort(key=lambda x: (*struct_name_priority_key(x[1]), x[0]))

        return [roi_number for roi_number, _ in roi_pairs]
    
    def get_rtstruct_roi_ds_value_by_uid(
        self,
        struct_uid: str,
        roi_number: int,
        metadata_key: str,
        default: Any = None,
        return_deepcopy: bool = True
    ) -> Any:
        """
        Get metadata from a specific ROI in an RTSTRUCT, using SOPInstanceUID and ROI number.

        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            roi_number: ROI number within the RTSTRUCT.
            metadata_key: The metadata key to retrieve from one of the ROI sub-datasets.
            default: Default value if key doesn't exist.
            return_deepcopy: Whether to return a deepcopy of the value (default: True).

        Returns:
            The metadata value or default.
        """
        # Check struct existence
        if struct_uid not in self.rtstruct_roi_ds_dicts:
            return default
        
        # Check ROI existence
        roi_ds_dict = self.rtstruct_roi_ds_dicts[struct_uid].get(roi_number)
        if not roi_ds_dict:
            return default

        # Iterate over sub-datasets for this ROI (StructureSetROI, ROIContour, ROIObservation)
        for sub_ds in roi_ds_dict.values():
            value = sub_ds.get(metadata_key, default)
            if value is not default:
                return deepcopy(value) if return_deepcopy else value
        
        return default
    
    def get_rtstruct_filepath_by_uid(self, struct_uid: str) -> Optional[str]:
        """Get file path for RTSTRUCT using SOPInstanceUID."""
        return self.rtstruct_fpaths.get(struct_uid, None)
    
    def init_roi_gui_metadata_by_uid(self, struct_uid: str, roi_number: int) -> None:
        """
        Ensure that the GUI metadata for an ROI is initialized in the metadata dict.
        This includes keys like 'name', 'color', 'type', 'disabled', etc...
        If the ROI or RTSTRUCT does not exist, or if the metadata already exists, this is a no-op.

        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            roi_number: ROI number within the RTSTRUCT.
        """
        # Check struct existence
        if struct_uid not in self.rtstruct_roi_ds_dicts:
            return
        
        # Check ROI existence
        roi_ds_dict = self.rtstruct_roi_ds_dicts[struct_uid].get(roi_number)
        if not roi_ds_dict:
            return
        
        # Only initialize metadata dict if not present
        if self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, None) is not None:
            return  # Already initialized
        
        # Get defaults from config
        unmatched_organ_name = self.conf_mgr.get_unmatched_organ_name()
        tg_263_oar_names_list = self.conf_mgr.get_tg_263_names(ready_for_dpg=True)
        organ_name_matching_dict = self.conf_mgr.get_organ_matching_dict()

        # Get ROI info
        roi_name = clean_dicom_string(roi_ds_dict.get("StructureSetROI", {}).get("ROIName", unmatched_organ_name))
        roi_display_color = validate_rgb_color(roi_ds_dict.get("ROIContour", {}).get("ROIDisplayColor", None))
        rt_roi_interpreted_type = roi_ds_dict.get("RTROIObservations", {}).get("RTROIInterpretedType", "CONTROL")
        
        # Get ROI Physical Properties (REL_ELEC_DENSITY overrides)
        roi_phys_prop_value = None
        roi_phys_prop_seq = roi_ds_dict.get("RTROIObservations", {}).get("ROIPhysicalPropertiesSequence", [])
        for roi_phys_prop_ds in roi_phys_prop_seq:
            phys_prop = roi_phys_prop_ds.get("ROIPhysicalProperty", "").strip().upper()
            if not phys_prop or phys_prop not in ("REL_ELEC_DENSITY", "RELELECDENSITY", "RED"):
                continue
            prop_value = roi_phys_prop_ds.get("ROIPhysicalPropertyValue", None)
            if prop_value is None or not isinstance(prop_value, (float, int)):
                continue
            roi_phys_prop_value = float(prop_value)
            break  # Use first valid REL_ELEC_DENSITY value found
        
        # Try to match a TG-263 name, or a default match
        templated_roi_name = find_reformatted_mask_name(roi_name, rt_roi_interpreted_type, tg_263_oar_names_list, organ_name_matching_dict, unmatched_organ_name)
        display_name = templated_roi_name
        
        # Defaults
        roi_rx_dose = None
        roi_rx_fractions = None
        roi_rx_site = None
        
        # If PTV, try to extract data
        if rt_roi_interpreted_type == "PTV" or templated_roi_name.upper().startswith("PTV"):
            orig_dose_fx_dict = regex_find_dose_and_fractions(roi_name)
            logger.info(f"Extracted dose/fractions for PTV '{roi_name}': {orig_dose_fx_dict}")
            roi_rx_dose = orig_dose_fx_dict.get("dose", None)
            roi_rx_fractions = orig_dose_fx_dict.get("fractions", None)
            
            # Try to find an RT Plan that uses this structure set
            plan_label = None
            plan_name = None
            for rtp_sop_uid, rtp_ds in self.rtplan_datasets.items():
                ref_rts_sop_uid = get_first_ref_struct_sop_uid(rtp_ds)
                if ref_rts_sop_uid == struct_uid:
                    plan_label = rtp_ds.get("PlanLabel", None)
                    plan_name = rtp_ds.get("PlanName", None)
                    break
            
            # Try to find disease site from plan or structure names
            roi_rx_site = find_disease_site(plan_label, plan_name, [roi_name, templated_roi_name])

            display_name += f"_{roi_rx_site}" if roi_rx_site is not None else "_NoSite"
            display_name += f"_{roi_rx_dose}" if roi_rx_dose is not None and roi_rx_dose > 0 else "_NoDose"
            display_name += f"_{roi_rx_fractions}" if roi_rx_fractions is not None and roi_rx_fractions > 0 else "_NoFxn"

        if struct_uid not in self.rtstruct_roi_metadata:
            self.rtstruct_roi_metadata[struct_uid] = {}
        
        self.rtstruct_roi_metadata[struct_uid][roi_number] = {
            "ROIName": roi_name,
            "ROIDisplayColor": roi_display_color,
            "RTROIInterpretedType": rt_roi_interpreted_type,
            "ROIPhysicalPropertyValue": roi_phys_prop_value,
            "display_name": display_name,
            "base_template_name": templated_roi_name,
            "is_template_based": True,
            "custom_suffix": "",
            "roi_goals": {},
            "roi_rx_dose": roi_rx_dose,
            "roi_rx_fractions": roi_rx_fractions,
            "roi_rx_site": roi_rx_site,
            "disabled": False,
        }
    
    def set_roi_gui_metadata_value_by_uid_and_key(self, struct_uid: str, roi_number: int, key: str, value: Any) -> None:
        """
        Set a specific key in the GUI metadata dict for an ROI, initializing it if necessary.

        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            roi_number: ROI number within the RTSTRUCT.
            key: The metadata key to set.
            value: The value to set.

        Returns:
            True if the key was set successfully, False if ROI or RTSTRUCT does not exist.
        """
        # Ensure metadata is initialized
        self.init_roi_gui_metadata_by_uid(struct_uid, roi_number)

        # Set the key if possible
        metadata_dict = self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {})
        if key not in metadata_dict:
            logger.error(f"Attempted to set unknown ROI metadata key '{key}' for struct ({struct_uid}, ROI {roi_number}).")
            return

        metadata_dict[key] = value
        logger.info(f"Set ROI metadata key '{key}' for struct ({struct_uid}, ROI {roi_number}) to {value}.")

    def get_roi_gui_metadata_by_uid(self, struct_uid: str, roi_number: int, return_deepcopy: bool = True) -> Dict[str, Any]:
        """
        Get the GUI metadata dict for an ROI, initializing it if necessary.

        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            roi_number: ROI number within the RTSTRUCT.
            return_deepcopy: Whether to return a deepcopy of the dict (default: True).

        Returns:
            The metadata dict, or empty dict if ROI or RTSTRUCT does not exist.
        """
        # Ensure metadata is initialized
        self.init_roi_gui_metadata_by_uid(struct_uid, roi_number)

        # Retrieve metadata dict
        md_dict = self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {})
        
        return deepcopy(md_dict) if return_deepcopy else md_dict

    def get_roi_gui_metadata_value_by_uid_and_key(self, struct_uid: str, roi_number: int, key: str, default: Any = None, return_deepcopy: bool = True) -> Any:
        """
        Get a specific key from the GUI metadata dict for an ROI, initializing it if necessary.

        Args:
            struct_uid: RTSTRUCT SOPInstanceUID.
            roi_number: ROI number within the RTSTRUCT.
            key: The metadata key to retrieve.
            default: Default value if key doesn't exist.
            return_deepcopy: Whether to return a deepcopy of the value (default: True).

        Returns:
            The metadata value or default.
        """
        # Ensure metadata is initialized
        self.init_roi_gui_metadata_by_uid(struct_uid, roi_number)

        # Retrieve the key if possible
        metadata_dict = self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {})
        if key not in metadata_dict:
            logger.warning(f"Requested unknown ROI metadata key '{key}' for struct ({struct_uid}, ROI {roi_number}). Returning default.")
        value = metadata_dict.get(key, default)
        return deepcopy(value) if return_deepcopy else value

    def get_orig_roi_names(self, ss_sopi: str, match_criteria: Optional[str] = None) -> List[str]:
        """
        Retrieve a list of all original (unmodified) ROI names, optionally filtered by criteria.

        Args:
            match_criteria: Optional substring to filter ROI names.

        Returns:
            A list of matching ROI names.
        """
        if not ss_sopi or ss_sopi not in self.rtstruct_datasets:
            logger.error(f"Invalid or missing RTSTRUCT SOPInstanceUID provided: {ss_sopi}.")
            return []
        if not (isinstance(match_criteria, str) or match_criteria is None):
            logger.error(f"Invalid match criteria provided: {match_criteria}. Expected a string or None.")
            return []
        
        # Find all original ROI names
        roi_names: List[str] = []
        for roi_number, roi_ds_dict in self.rtstruct_roi_ds_dicts.get(ss_sopi, {}).items():
            roi_name = (roi_ds_dict.get("StructureSetROI").get("ROIName", "") or "").strip()
            # Add the ROI name if there are no match criteria, or if the criteria is found in the ROI name
            if roi_name and (not match_criteria or match_criteria.lower() in roi_name.lower()):
                roi_names.append(roi_name)
        
        return roi_names
    
    def get_roi_center_of_mass_by_uid(self, struct_uid: str, roi_number: int) -> Optional[Tuple[int, int, int]]:
        """ Return center of mass for an ROI. Returns center of mass as (x, y, z) tuple or None if no data. """
        self.update_cached_data(True, ("roi", struct_uid, roi_number))  # ensure ROI is built and cached
        sitk_roi: sitk.Image = self._cached_sitk_objects.get(("roi", struct_uid, roi_number), self.rois.get((struct_uid, roi_number), None))
        if sitk_roi is None:
            logger.error(f"ROI {roi_number} in RTSTRUCT {struct_uid} could not be created; cannot compute center of mass.")
            return None
        
        stats = sitk.LabelShapeStatisticsImageFilter()
        stats.Execute(sitk_roi)
        
        if not stats.HasLabel(1):
            view = sitk.GetArrayViewFromImage(sitk_roi)
            coords = np.argwhere(view > 0)
            if coords.size == 0:  # No points
                logger.error(f"ROI {roi_number} in RTSTRUCT {struct_uid} has no voxels in its mask; cannot compute center of mass.")
                return None
            elif coords.shape[0] == 1:  # Single point
                return tuple(coords[0][::-1])  # (x, y, z)
            else:  # Multiple points - return rounded mean
                mean_idx = np.rint(coords.mean(axis=0)).astype(int)
                return tuple(mean_idx[::-1])  # (x, y, z)
        
        # GetCentroid returns (x, y, z) in physical coordinates
        centroid_phys = stats.GetCentroid(1)
        
        # Convert to voxel indices (integer tuple)
        centroid_index = sitk_roi.TransformPhysicalPointToIndex(centroid_phys)
        
        return centroid_index  # (x, y, z)
    
    def get_roi_extent_ranges_by_uid(self, struct_uid: str, roi_number: int) -> Optional[Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]]:
        """Return (x_range, y_range, z_range) index extents of an ROI."""
        self.update_cached_data(True, ("roi", struct_uid, roi_number))  # ensure ROI is built and cached
        sitk_roi: sitk.Image = self._cached_sitk_objects.get(("roi", struct_uid, roi_number), self.rois.get((struct_uid, roi_number), None))
        if sitk_roi is None:
            logger.error(f"ROI {roi_number} in RTSTRUCT {struct_uid} could not be created; cannot compute center of mass.")
            return None
        
        stats = sitk.LabelShapeStatisticsImageFilter()
        stats.Execute(sitk_roi)

        if not stats.HasLabel(1):
            view = sitk.GetArrayViewFromImage(sitk_roi)
            coords = np.argwhere(view > 0)
            if coords.size == 0:  # No points
                logger.error(f"ROI {roi_number} in RTSTRUCT {struct_uid} has no voxels in its mask; cannot compute extent ranges.")
                return None
            elif coords.shape[0] == 1:  # Single point
                return ((coords[0][2], coords[0][2]), (coords[0][1], coords[0][1]), (coords[0][0], coords[0][0]))  # (x_range, y_range, z_range)
            else:  # Multiple points - return min/max
                x_min, y_min, z_min = coords.min(axis=0)
                x_max, y_max, z_max = coords.max(axis=0)
                return ((x_max, x_min), (y_max, y_min), (z_max, z_min))

        # BoundingBox -> (x_min, y_min, z_min, size_x, size_y, size_z)
        bb = stats.GetBoundingBox(1)

        x_range = (bb[0], bb[0] + bb[3] - 1)
        y_range = (bb[1], bb[1] + bb[4] - 1)
        z_range = (bb[2], bb[2] + bb[5] - 1)

        return (x_range, y_range, z_range)
    
    def remove_roi_from_rtstruct(self, ss_sopi: str, roi_number: int) -> None:
        """ Remove an ROI from the specified RTSTRUCT. """
        ss_roi_ds_dicts = self.rtstruct_roi_ds_dicts.get(ss_sopi, {})
        roi_ds_dict = ss_roi_ds_dicts.get(roi_number)
        if not roi_ds_dict:
            logger.error(f"Cannot remove ROI number {roi_number} from RTSTRUCT with SOPInstanceUID '{ss_sopi}': ROI not found.")
            return
        if ss_sopi in self.rtstruct_roi_metadata and roi_number in self.rtstruct_roi_metadata[ss_sopi]:
            self.rtstruct_roi_metadata[ss_sopi][roi_number]["disabled"] = True
        if (ss_sopi, roi_number) in self.rois:
            logger.info(f"Removing ROI number {roi_number} from RTSTRUCT with SOPInstanceUID '{ss_sopi}'.")
            del self.rois[(ss_sopi, roi_number)]
        if ("roi", ss_sopi, roi_number) in self._cached_sitk_objects:
            del self._cached_sitk_objects[("roi", ss_sopi, roi_number)]
        # Update texture?
    
    ### RTPLAN Data Methods ###
    def load_rtplans(self, rtplan_files: List[File]) -> None:
        """Load RTPLANs and update internal data dictionary."""
        if not rtplan_files:
            return
        
        for rtplan_file in rtplan_files:
            if self.ss_mgr.cleanup_event.is_set() or self.ss_mgr.shutdown_event.is_set():
                return

            # Get file info
            file_path = rtplan_file.path
            modality = (rtplan_file.file_metadata.modality or "").strip().upper()
            sop_instance_uid = (rtplan_file.file_metadata.sop_instance_uid or "").strip()
            logger.debug(f"Loading {modality} {sop_instance_uid}: {file_path}")
            
            # Skip if already loaded
            if sop_instance_uid in self.rtplan_datasets:
                logger.error(f"Skipping RTPLAN file '{file_path}' due to duplicate SOPInstanceUID '{sop_instance_uid}' already loaded.")
                continue
            
            # Read RTPLAN dataset
            rtplan_ds = read_dcm_file(file_path)
            if rtplan_ds is None:
                logger.error(f"Failed to read RTPLAN file '{file_path}'.")
                continue
            
            # Validate SOPInstanceUID
            validate_sop_instance_uid = str(rtplan_ds.SOPInstanceUID)
            if validate_sop_instance_uid != sop_instance_uid:
                logger.error(f"Mismatch in SOPInstanceUID for RTPLAN file '{file_path}': metadata has '{sop_instance_uid}' but DICOM has '{validate_sop_instance_uid}'. Skipping.")
                continue
            
            # Add to dictionaries
            self.rtplan_datasets[sop_instance_uid] = rtplan_ds
            self.rtplan_fpaths[sop_instance_uid] = file_path
            logger.info(f"Loaded {modality} with SOPInstanceUID '{sop_instance_uid}'.")
    
    def get_rtplan_uids(self) -> List[str]:
        """Return list of available RTPLAN SOPInstanceUIDs."""
        return list(self.rtplan_datasets.keys())

    def get_rtplan_ds_value_by_uid(self, rtplan_uid: str, metadata_key: str, default: Any = None, return_deepcopy: bool = True) -> Any:
        """
        Get data from an RTPLAN DICOM dataset using SOPInstanceUID.

        Args:
            rtplan_uid: RTPLAN SOPInstanceUID.
            metadata_key: The metadata key to retrieve from the RTPLAN dataset.
            default: Default value if key doesn't exist.
            return_deepcopy: Whether to return a deepcopy of the value (default: True).

        Returns:
            The metadata value or default.
        """
        # Check RTPLAN existence
        if rtplan_uid not in self.rtplan_datasets:
            return default

        # Get the RTPLAN dataset
        rtplan_ds = self.rtplan_datasets[rtplan_uid]
        
        if metadata_key == "NumberOfFractionsPlanned":
            value = get_first_num_fxns_planned(rtplan_ds) or default
        else:
            value = rtplan_ds.get(metadata_key, default)
        
        if value is not default:
            return deepcopy(value) if return_deepcopy else value
        return default
    
    def get_rtplan_filepath_by_uid(self, rtplan_uid: str) -> Optional[str]:
        """Get file path for RTPLAN using SOPInstanceUID."""
        return self.rtplan_fpaths.get(rtplan_uid, None)
    
    def get_rtplan_ds_beam_summary_by_uid(self, rtplan_uid: str, return_deepcopy: bool = True) -> List[Dict[str, Any]]:
        """
        Get a summary of beams from an RTPLAN DICOM dataset using SOPInstanceUID.

        Args:
            rtplan_uid: RTPLAN SOPInstanceUID.
            return_deepcopy: Whether to return a deepcopy of the list (default: True).

        Returns:
            A list of dictionaries summarizing each beam.
        """
        # Check RTPLAN existence
        if rtplan_uid not in self.rtplan_datasets:
            return []

        # Get the RTPLAN dataset
        rtplan_ds = self.rtplan_datasets[rtplan_uid]
        
        # Get per-beam dose/meterset from FractionGroupSequence
        beams_doses_metersets = {}
        for fraction_grp_ds in rtplan_ds.get("FractionGroupSequence", []):
            for ref_beam_ds in fraction_grp_ds.get("ReferencedBeamSequence", []):
                ref_beam_number = ref_beam_ds.get("ReferencedBeamNumber", None)
                if ref_beam_number is None:
                    continue
                beam_dose = ref_beam_ds.get("BeamDose", None)
                beam_meterset = ref_beam_ds.get("BeamMeterset", None)
                if beam_dose is None and beam_meterset is None:
                    continue
                beams_doses_metersets[ref_beam_number] = {
                    "BeamDose": beam_dose,
                    "BeamMeterset": beam_meterset,
                }
        
        # Summarize per-beam info with TreatmentDeliveryType == "TREATMENT"
        beam_summaries = []
        
        for beam_ds in rtplan_ds.get("BeamSequence", []):
            beam_number = beam_ds.get("BeamNumber", None)
            if beam_number is None:
                continue
            
            treatment_delivery_type = beam_ds.get("TreatmentDeliveryType", "").strip().upper()
            if treatment_delivery_type != "TREATMENT":
                continue
            
            beam_dose_meterset = beams_doses_metersets.get(beam_number, {})
            if not beam_dose_meterset:
                continue
            
            beam_dose = beam_dose_meterset.get("BeamDose", None)
            beam_meterset = beam_dose_meterset.get("BeamMeterset", None)
            
            treatment_machine_name = beam_ds.get("TreatmentMachineName", "")
            primary_dosimeter_unit = beam_ds.get("PrimaryDosimeterUnit", "")
            source_axis_distance = beam_ds.get("SourceAxisDistance", None)
            beam_name = beam_ds.get("BeamName", "")
            beam_description = beam_ds.get("BeamDescription", "")
            beam_type = beam_ds.get("BeamType", "") # STATIC or DYNAMIC
            radiation_type = beam_ds.get("RadiationType", "")  # PHOTON, ELECTRON, PROTON, NEUTRON
            num_wedges = beam_ds.get("NumberOfWedges", 0)
            num_compensators = beam_ds.get("NumberOfCompensators", 0)
            num_boli = beam_ds.get("NumberOfBoli", 0)
            num_blocks = beam_ds.get("NumberOfBlocks", 0)
            num_control_points = beam_ds.get("NumberOfControlPoints", 0)
            
            fluence_mode = ""
            fluence_mode_id = ""
            for pfm_ds in beam_ds.get("PrimaryFluenceModeSequence", []):
                fluence_mode = pfm_ds.get("FluenceMode", "")
                fluence_mode_id = pfm_ds.get("FluenceModeID", "")
            
            energies = set()
            dose_rates = set()
            gantry_angles = set()
            collimator_angles = set()
            couch_angles = set()
            isocenters = set()
            for cp_ds in beam_ds.get("ControlPointSequence", []):
                energy = cp_ds.get("NominalBeamEnergy", None)
                if energy is not None:
                    energies.add(energy)
                dose_rate = cp_ds.get("DoseRateSet", None)
                if dose_rate is not None:
                    dose_rates.add(dose_rate)
                gantry_angle = cp_ds.get("GantryAngle", None)
                if gantry_angle is not None:
                    gantry_angles.add(gantry_angle)
                collimator_angle = cp_ds.get("BeamLimitingDeviceAngle", None)
                if collimator_angle is not None:
                    collimator_angles.add(collimator_angle)
                couch_angle = cp_ds.get("PatientSupportAngle", None)
                if couch_angle is not None:
                    couch_angles.add(couch_angle)
                isocenter = cp_ds.get("IsocenterPosition", None)
                if isocenter is not None:
                    isocenters.add(tuple(isocenter))

            beam_info = {
                "BeamNumber": beam_number,
                "TreatmentDeliveryType": treatment_delivery_type,
                "BeamDose": beam_dose,
                "BeamMeterset": beam_meterset,
                
                "TreatmentMachineName": treatment_machine_name,
                "PrimaryDosimeterUnit": primary_dosimeter_unit,
                "SourceAxisDistance": source_axis_distance,
                "BeamName": beam_name,
                "BeamDescription": beam_description,
                "BeamType": beam_type,
                "RadiationType": radiation_type,
                "NumberOfWedges": num_wedges,
                "NumberOfCompensators": num_compensators,
                "NumberOfBoli": num_boli,
                "NumberOfBlocks": num_blocks,
                "NumberOfControlPoints": num_control_points,
                
                "FluenceMode": fluence_mode,
                "FluenceModeID": fluence_mode_id,
                
                "Unique Energies": sorted(energies),
                "Unique Dose Rates": sorted(dose_rates),
                "Unique Gantry Angles": sorted(gantry_angles),
                "Unique Collimator Angles": sorted(collimator_angles),
                "Unique Couch Angles": sorted(couch_angles),
                "Number Of Unique Isocenters": len(isocenters),
            }
            beam_summaries.append(beam_info)
        
        return deepcopy(beam_summaries) if return_deepcopy else beam_summaries
    
    def get_rtplan_ds_overall_beam_summary_by_uid(self, rtplan_uid: str, beam_summaries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Get an overall summary of beams from an RTPLAN DICOM dataset using SOPInstanceUID.

        Args:
            rtplan_uid: RTPLAN SOPInstanceUID.

        Returns:
            A dictionary summarizing overall beam info, or None if RTPLAN not found.
        """
        # Get beam summaries if not provided
        if beam_summaries is None: 
            beam_summaries = self.get_rtplan_ds_beam_summary_by_uid(rtplan_uid)
        
        # If no beam summaries found, return empty dict
        if not beam_summaries: 
            return {}
        
        # Aggregate overall info
        primary_dosimeter_units = set(beam.get("PrimaryDosimeterUnit", "") for beam in beam_summaries if beam.get("PrimaryDosimeterUnit", ""))
        primary_dosimeter_units = f"({', '.join(primary_dosimeter_units)})" if primary_dosimeter_units else "(N/A)"
        return {
            "Number of Treatment Beams": len(beam_summaries),
            "Total Beam Dose (Gy)": sum(beam.get("BeamDose", 0) for beam in beam_summaries if isinstance(beam.get("BeamDose", None), (int, float))),
            f"Total Beam Meterset {primary_dosimeter_units}": sum(beam.get("BeamMeterset", 0) for beam in beam_summaries if isinstance(beam.get("BeamMeterset", None), (int, float))),
            "Unique Treatment Machines": sorted(set(beam.get("TreatmentMachineName", "") for beam in beam_summaries if beam.get("TreatmentMachineName", ""))),
            "Unique Source-Axis Distances (mm)": sorted(set(beam.get("SourceAxisDistance", 0) for beam in beam_summaries if isinstance(beam.get("SourceAxisDistance", None), (int, float)) and beam.get("SourceAxisDistance", 0) > 0)),
            "Unique Beam Types": sorted(set(beam.get("BeamType", "") for beam in beam_summaries if beam.get("BeamType", ""))),
            "Unique Beam Energies": sorted(set(val for beam in beam_summaries for val in beam.get("Unique Energies", []))),
            "Unique Radiation Types": sorted(set(beam.get("RadiationType", "") for beam in beam_summaries if beam.get("RadiationType", ""))),
            "Number of Beams with Wedges": sum(beam.get("NumberOfWedges", 0) > 0 for beam in beam_summaries if isinstance(beam.get("NumberOfWedges", None), int)),
            "Number of Beams with Compensators": sum(beam.get("NumberOfCompensators", 0) > 0 for beam in beam_summaries if isinstance(beam.get("NumberOfCompensators", None), int)),
            "Number of Beams with Bolus": sum(beam.get("NumberOfBoli", 0) > 0 for beam in beam_summaries if isinstance(beam.get("NumberOfBoli", None), int)),
            "Number of Beams with Blocks": sum(beam.get("NumberOfBlocks", 0) > 0 for beam in beam_summaries if isinstance(beam.get("NumberOfBlocks", None), int)),
            "Total Number of Control Points": sum(beam.get("NumberOfControlPoints", 0) for beam in beam_summaries if isinstance(beam.get("NumberOfControlPoints", None), int)),
            "Unique Fluence Modes": sorted(set(beam.get("FluenceMode", "") for beam in beam_summaries if beam.get("FluenceMode", ""))),
            "Unique Fluence Mode IDs": sorted(set(beam.get("FluenceModeID", "") for beam in beam_summaries if beam.get("FluenceModeID", ""))),
            "Unique Gantry Angles": sorted(set(val for beam in beam_summaries for val in beam.get("Unique Gantry Angles", []))),
            "Unique Collimator Angles": sorted(set(val for beam in beam_summaries for val in beam.get("Unique Collimator Angles", []))),
            "Unique Couch Angles": sorted(set(val for beam in beam_summaries for val in beam.get("Unique Couch Angles", []))),
            "Number Of Unique Isocenters": sum(beam.get("Number Of Unique Isocenters", 0) for beam in beam_summaries if isinstance(beam.get("Number Of Unique Isocenters", None), int))
        }
    
    ### RTDOSE Data Methods ###
    def load_rtdoses(self, rtdose_data: Dict[str, List[File]]) -> None:
        """Load RTDOSEs and update internal data dictionary."""
        if not rtdose_data:
            return
        
        for dose_type, dose_files in rtdose_data.items():
            for dose_file in dose_files:
                if self.ss_mgr.cleanup_event.is_set() or self.ss_mgr.shutdown_event.is_set():
                    return
                
                # Get file info
                file_path = dose_file.path
                modality = (dose_file.file_metadata.modality or "").strip().upper()
                sop_instance_uid = (dose_file.file_metadata.sop_instance_uid or "").strip()
                dose_summation_type = (dose_file.file_metadata.dose_summation_type or "").strip().upper()
                logger.debug(f"Loading {modality} {sop_instance_uid}: {file_path}")
                
                # Skip if already loaded
                if sop_instance_uid in self.rtdoses:
                    logger.error(f"Skipping RTDOSE file '{file_path}' due to duplicate SOPInstanceUID '{sop_instance_uid}' already loaded.")
                    continue
                
                # Construct SITK dose
                sitk_dose = construct_dose(file_path, self.ss_mgr)
                
                # Validate SOPInstanceUID
                validate_sop_instance_uid = str(sitk_dose.GetMetaData("SOPInstanceUID")).strip()
                if validate_sop_instance_uid != sop_instance_uid:
                    logger.error(f"Mismatch in SOPInstanceUID for RTDOSE file '{file_path}': metadata has '{sop_instance_uid}' but DICOM has '{validate_sop_instance_uid}'. Skipping.")
                    continue
                
                # If RTP is loaded, enhance the dose metadata
                ref_rtp_sopiuid = sitk_dose.GetMetaData("ReferencedRTPlanSOPInstanceUID")
                if self.rtplan_datasets and ref_rtp_sopiuid in self.rtplan_datasets:
                    ds_rtplan = self.rtplan_datasets[ref_rtp_sopiuid]
                    
                    num_fxns_planned = get_first_num_fxns_planned(ds_rtplan)
                    if num_fxns_planned is not None:
                        sitk_dose.SetMetaData("NumberOfFractionsPlanned", str(num_fxns_planned))
                    
                    dose_summation_type = sitk_dose.GetMetaData("DoseSummationType").strip().upper() # Re-read from SITK to ensure accuracy
                    if dose_summation_type.strip().upper() == "BEAM":
                        beam_number = get_first_ref_beam_number(ds_rtplan)
                        if beam_number is not None:
                            sitk_dose.SetMetaData("ReferencedRTPlanBeamNumber", str(beam_number))
                
                # Add the dose to the dictionaries
                self.rtdoses[sop_instance_uid] = sitk_dose
                self.rtdose_fpaths[sop_instance_uid] = file_path
    
    def get_rtdose_metadata_by_uid_and_key(self, rtdose_uid: str, metadata_key: str, default: Any = None, return_deepcopy: bool = True) -> Any:
        """
        Get data from an RTDOSE SimpleITK image using SOPInstanceUID.

        Args:
            rtdose_uid: RTDOSE SOPInstanceUID.
            metadata_key: The metadata key to retrieve from the RTDOSE SimpleITK image.
            default: Default value if key doesn't exist.
            return_deepcopy: Whether to return a deepcopy of the value (default: True).

        Returns:
            The metadata value or default.
        """
        # Check RTDOSE existence
        if rtdose_uid not in self.rtdoses:
            return default

        # Get the RTDOSE SimpleITK image
        sitk_dose = self.rtdoses[rtdose_uid]
        if not isinstance(sitk_dose, sitk.Image):
            logger.error(f"RT Dose with UID {rtdose_uid} is not a valid SITK Image.")
            return default
        
        # Get the metadata value
        if not sitk_dose.HasMetaDataKey(metadata_key):
            return default
        
        value = sitk_dose.GetMetaData(metadata_key)
        return deepcopy(value) if return_deepcopy else value
    
    def get_rtdose_metadata_dict_by_uid(self, rtdose_uid: str, return_deepcopy: bool = True) -> Dict[str, str]:
        """
        Get all metadata from an RTDOSE SimpleITK image using SOPInstanceUID.

        Args:
            rtdose_uid: RTDOSE SOPInstanceUID.
            return_deepcopy: Whether to return a deepcopy of the dict (default: True).

        Returns:
            The metadata dict or empty dict if RTDOSE not found.
        """
        # Check RTDOSE existence
        if rtdose_uid not in self.rtdoses:
            return {}

        # Get the RTDOSE SimpleITK image
        sitk_dose = self.rtdoses[rtdose_uid]
        if not isinstance(sitk_dose, sitk.Image):
            logger.error(f"RT Dose with UID {rtdose_uid} is not a valid SITK Image.")
            return {}
        
        # Get all metadata keys and values
        metadata_dict = {key: sitk_dose.GetMetaData(key) for key in sitk_dose.GetMetaDataKeys()}
        return deepcopy(metadata_dict) if return_deepcopy else metadata_dict
    
    def get_rtdose_filepath_by_uid(self, rtdose_uid: str) -> Optional[str]:
        """Get file path for RTDOSE using SOPInstanceUID."""
        return self.rtdose_fpaths.get(rtdose_uid, None)
    
    def set_rtdose_metadata_by_uid_and_key(self, rtdose_uid: str, metadata_key: str, metadata_value: str) -> bool:
        """
        Set metadata in an RTDOSE SimpleITK image using SOPInstanceUID.

        Args:
            rtdose_uid: RTDOSE SOPInstanceUID.
            metadata_key: The metadata key to set in the RTDOSE SimpleITK image.
            metadata_value: The value to set for the metadata key.

        Returns:
            True if the metadata was set successfully, False otherwise.
        """
        # Check RTDOSE existence
        if rtdose_uid not in self.rtdoses:
            logger.error(f"Cannot set metadata for RTDOSE with UID '{rtdose_uid}': RTDOSE not found.")
            return False

        # Get the RTDOSE SimpleITK image
        sitk_dose = self.rtdoses[rtdose_uid]
        if not isinstance(sitk_dose, sitk.Image):
            logger.error(f"RT Dose with UID {rtdose_uid} is not a valid SITK Image.")
            return False
        
        # Set the metadata key/value
        try:
            sitk_dose.SetMetaData(metadata_key, str(metadata_value))
            logger.info(f"Set metadata key '{metadata_key}' for RTDOSE with UID '{rtdose_uid}' to '{metadata_value}'.")
            return True
        except Exception as exc:
            logger.error(f"Failed to set metadata key '{metadata_key}' for RTDOSE with UID '{rtdose_uid}'.", exc_info=True, stack_info=True)
            return False
    
    ### RTPLAN/RTDOSE Mapping Methods ###
    def get_rtp_rtd_mappings(self) -> Dict[str, Union[List[str], Dict[str, List[str]]]]:
        """
        Returns dict with:
        - 'plan_to_doses': Dict[rtplan_uid, List[rtdose_uid]] of mapped doses
        - 'unmapped_doses': List[rtdose_uid] that are invalid or do not map to a loaded plan
        - 'unmapped_plans': List[rtplan_uid] that have no RTDOSE referencing them
        """
        plan_to_doses: Dict[str, List[str]] = {}
        unmapped_doses: List[str] = []

        for dose_uid, sitk_dose in self.rtdoses.items():
            if not isinstance(sitk_dose, sitk.Image):
                logger.error(f"RT Dose with UID {dose_uid} is not a valid SITK Image.")
                continue
            
            try:
                if not sitk_dose.HasMetaDataKey("ReferencedRTPlanSOPInstanceUID"):
                    logger.error(f"RT Dose with UID {dose_uid} is missing ReferencedRTPlanSOPInstanceUID metadata.")
                    unmapped_doses.append(dose_uid)
                    continue
                ref_plan = str(sitk_dose.GetMetaData("ReferencedRTPlanSOPInstanceUID")).strip()
            except Exception as exc:
                logger.error(f"Failed reading ReferencedRTPlanSOPInstanceUID for dose {dose_uid}.", exc_info=True, stack_info=True)
                unmapped_doses.append(dose_uid)
                continue

            if not ref_plan:
                logger.error(f"RT Dose with UID {dose_uid} has empty ReferencedRTPlanSOPInstanceUID metadata.")
                unmapped_doses.append(dose_uid)
                continue

            if ref_plan not in self.rtplan_datasets:
                logger.warning(f"RT Dose with UID {dose_uid} references RT Plan UID {ref_plan} which is not loaded.")
                unmapped_doses.append(dose_uid)
                continue

            plan_to_doses.setdefault(ref_plan, []).append(dose_uid)

        all_plans = set(self.rtplan_datasets.keys())
        mapped_plans = set(plan_to_doses.keys())
        unmapped_plans = sorted(list(all_plans - mapped_plans))

        return {
            "plan_to_doses": plan_to_doses,
            "unmapped_doses": sorted(unmapped_doses),
            "unmapped_plans": unmapped_plans,
        }
    
    ### Cached SITK Methods ###
    def get_raw_data_params(self) -> Dict[str, Any]:
        self._update_raw_data_params()
        return {
            "size": self.original_size,
            "spacing": self.original_spacing,
            "direction": self.original_direction,
            "origin": self.original_origin,
        }
    
    def get_current_data_params(self) -> Dict[str, Any]:
        
        if self._cached_sitk_reference is None:
            return self.get_raw_data_params()
        return {
            "size": self._cached_sitk_reference.GetSize(),
            "spacing": self._cached_sitk_reference.GetSpacing(),
            "direction": self._cached_sitk_reference.GetDirection(),
            "origin": self._cached_sitk_reference.GetOrigin(),
        }
    
    def _initialize_cached_sitk_reference(self, sitk_data: sitk.Image) -> sitk.Image:
        """
        Initialize the cached reference SimpleITK image if none exists.

        The reference is created by resampling `sitk_data` according to
        parameters stored in `_cached_texture_param_dict` (voxel spacing,
        rotation, flips). The resulting image is cached and augmented with
        metadata recording the original spacing, size, and direction.

        Args:
            sitk_data: Input SimpleITK image to serve as the basis for the reference.

        Returns:
            The cached reference image if it was created, otherwise the
            provided `sitk_data` unchanged.
        """
        if self._cached_sitk_reference is None:
            voxel_spacing = self._cached_texture_param_dict.get("voxel_spacing", sitk_data.GetSpacing())
            rotation = self._cached_texture_param_dict.get("rotation", None)
            flips = self._cached_texture_param_dict.get("flips", None)
            self._cached_sitk_reference = resample_sitk_data_with_params(
                sitk_data=sitk_data,
                set_spacing=voxel_spacing,
                set_rotation=rotation,
                set_flip=flips,
                interpolator=sitk.sitkLinear,
            )
            return self._cached_sitk_reference
        return sitk_data
    
    def _sitk_cache_process(self, sitk_data: sitk.Image) -> sitk.Image:
        """ Process and cache SITK data for given display keys."""
        sitk_data = self._initialize_cached_sitk_reference(sitk_data)
        
        ref = self._cached_sitk_reference
        if sitk_data is ref:
            return sitk_data  # Already the same object
        
        # Check if geometry already matches reference
        same_spacing = sitk_data.GetSpacing() == ref.GetSpacing()
        same_origin = sitk_data.GetOrigin() == ref.GetOrigin()
        same_direction = sitk_data.GetDirection() == ref.GetDirection()
        same_size = sitk_data.GetSize() == ref.GetSize()
        if all((same_spacing, same_origin, same_direction, same_size)):
            return sitk_data  # No resample needed
        
        # Otherwise, resample to match reference
        return sitk_resample_to_reference(
            sitk_data, 
            self._cached_sitk_reference, 
            interpolator=sitk.sitkLinear, 
            default_pixel_val_outside_image=0.0
        )
    
    def update_cached_data(self, load_data: bool, display_keys: Union[Tuple[str, str], Tuple[str, str, int]]) -> None:
        """
        Update active display data based on the specified keys.

        Args:
            load_data: True to load data; False to remove.
            display_keys: Sequence of keys specifying the data to update.
        """
        if display_keys is None or display_keys[0] not in ("image", "roi", "dose"):
            logger.error(f"Invalid display keys provided to updating active data: {display_keys}")
            return
        
        # Handle data removal
        if not load_data:
            if display_keys in self._cached_sitk_objects:
                del self._cached_sitk_objects[display_keys]
                if not self._cached_sitk_objects:
                    self._cached_sitk_reference = None
            self._update_dose_sum_cache()
            return
        
        # Check if already loaded
        if display_keys in self._cached_sitk_objects:
            return
        
        # Load the appropriate data
        if display_keys[0] == "image":
            series_uid = display_keys[1]
            if series_uid not in self.images:
                logger.error(f"Cannot update active image data: SeriesInstanceUID '{series_uid}' not found.")
                return
            sitk_data = self.images[series_uid]
        
        elif display_keys[0] == "roi":
            struct_uid, roi_number = display_keys[1:]
            self.build_rtstruct_roi(struct_uid, roi_number)  # Checks and only builds if needed
            if (struct_uid, roi_number) not in self.rois:
                logger.error(f"Cannot update active ROI data: ROI number {roi_number} in RTSTRUCT with SOPInstanceUID '{struct_uid}' not found or failed to build.")
                return
            sitk_data = self.rois[(struct_uid, roi_number)]
        
        elif display_keys[0] == "dose":
            dose_uid = display_keys[1]
            if dose_uid not in self.rtdoses:
                logger.error(f"Cannot update active dose data: RTDOSE with SOPInstanceUID '{dose_uid}' not found.")
                return
            sitk_data = self.rtdoses[dose_uid]

        self._cached_sitk_objects[display_keys] = self._sitk_cache_process(sitk_data)
        self._update_dose_sum_cache()
    
    def _update_dose_sum_cache(self) -> None:
        """Update the dose sum cache based on current active dose data."""
        dose_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "dose"]
        if dose_keys:
            dose_objects = [self._cached_sitk_objects[k] for k in dose_keys]
            dose_sum = dose_objects[0]
            for dose in dose_objects[1:]:
                dose_sum = sitk.Add(dose_sum, dose)
            # Normalize the sum so that max is 1.0
            stats = sitk.StatisticsImageFilter()
            stats.Execute(dose_sum)
            max_val = stats.GetMaximum()
            self._cached_dose_sum = sitk.Divide(dose_sum, max_val + 1e-4)
        else:
            self._cached_dose_sum = None
    
    ### Texture Methods ###
    def return_texture_from_active_data(self, texture_params: Dict[str, Any]) -> np.ndarray:
        """
        Generate and return a flattened texture slice from the cached data based on the given parameters.

        Args:
            texture_params: Dictionary of parameters defining texture properties.

        Returns:
            A 1D NumPy array representing the resized texture slice.
        """
        if not texture_params or not isinstance(texture_params, dict):
            logger.error(f"Texture generation failed: texture parameter dictionary is missing or invalid: {texture_params}")
            return np.zeros(1, dtype=np.float32)

        image_length = texture_params.get("image_length")
        if not image_length or not isinstance(image_length, int):
            logger.error(f"Texture generation failed: 'image_length' is missing or not an integer in {texture_params}")
            return np.zeros(1, dtype=np.float32)

        texture_RGB_size = image_length * image_length * 3

        slicer = texture_params.get("slicer") # (z, y, x) order
        if not slicer or not isinstance(slicer, tuple) or not all(isinstance(s, (slice, int)) for s in slicer):
            logger.error(f"Texture generation failed: 'slicer' is missing or invalid in {texture_params}")
            return np.zeros(texture_RGB_size, dtype=np.float32)

        view_type = texture_params.get("view_type")
        if not view_type or not isinstance(view_type, str) or view_type not in ["axial", "coronal", "sagittal"]:
            logger.error(f"Texture generation failed: 'view_type' is missing or invalid in {texture_params}")
            return np.zeros(texture_RGB_size, dtype=np.float32)
        
        try:
            # Rebuild cache if texture parameters have changed
            if self._check_for_texture_param_changes(texture_params, ignore_keys=["view_type", "slicer", "xyz_slices", "xyz_ranges"]):
                # Store current keys before clearing cache
                cached_keys = list(self._cached_sitk_objects.keys())
                
                self._clear_cache()
                self._cached_texture_param_dict = texture_params
                
                # Reload data using the stored keys
                for key in cached_keys:
                    self.update_cached_data(True, key)

            # Determine base layer shape based on slicer dimensions and create base layer
            shape_RGB = tuple(s.stop - s.start for s in slicer if isinstance(s, slice)) + (3,)
            base_layer = np.zeros(shape_RGB, dtype=np.float32)

            # Blend images, masks, and doses if display alphas are provided
            alphas = texture_params.get("display_alphas")
            if alphas and len(alphas) == 3:
                self._blend_images_RGB(base_layer, slicer, texture_params["image_window_level"], texture_params["image_window_width"], alphas[0])
                self._blend_masks_RGB(base_layer, slicer, texture_params["contour_thickness"], alphas[1])
                self._blend_doses_RGB(base_layer, slicer, texture_params["dose_thresholds"], alphas[2])
            else:
                logger.error(f"Data textures could not be blended: 'display_alphas' are missing or invalid: {alphas}")
            
            # Add crosshairs to the base layer
            self._draw_slice_crosshairs(
                base_layer, 
                texture_params.get("show_crosshairs", False), 
                view_type, 
                texture_params["xyz_slices"], 
                texture_params["xyz_ranges"]
            )
            
            # Adjust dimension order based on view type
            if view_type == "coronal":
                base_layer = base_layer[::-1, :, :]  # Flip z axis
            elif view_type == "sagittal":
                base_layer = base_layer[::-1, ::-1, :]  # Flip z and x axes
            
            # Normalize and clip to [0, 1]
            np.clip(base_layer, 0, 255, out=base_layer)
            base_layer /= 255.0
            
            # Resize to the desired image dimensions
            base_layer = cv2.resize(src=base_layer, dsize=(image_length, image_length), interpolation=cv2.INTER_LINEAR)
            
            # Add orientation labels after resizing to avoid text distortion
            self._draw_orientation_labels(
                base_layer, 
                texture_params["show_orientation_labels"], 
                view_type, 
                texture_params["rotation"], 
                texture_params["flips"]
            )
            
            # Resize to the desired image dimensions and flatten to a 1D texture
            return base_layer.ravel()
        except Exception as e:
            logger.exception("Failed to generate a texture.", exc_info=True, stack_info=True)
            return np.zeros(texture_RGB_size, dtype=np.float32)
    
    def _check_for_texture_param_changes(
        self, 
        texture_params: Dict[str, Any], 
        ignore_keys: Optional[List[str]] = None
    ) -> bool:
        """
        Determine if the provided texture parameters differ from the cached parameters.

        Args:
            texture_params: The current texture parameters.
            ignore_keys: List of parameter keys to ignore during comparison.

        Returns:
            True if differences are detected; otherwise, False.
        """
        if self._cached_texture_param_dict is None:
            return True
        
        for key, value in texture_params.items():
            if ignore_keys and key in ignore_keys:
                continue
            cached_value = self._cached_texture_param_dict.get(key)
            if isinstance(value, (list, tuple, set)):
                if any(v != cv for v, cv in zip(value, cached_value)):
                    return True
            elif value != cached_value:
                return True

        return False
    
    ### Texture Blending Methods ###
    def _blend_layers(self, base_layer: np.ndarray, overlay: np.ndarray, alpha: float) -> None:
        """
        Blend an overlay onto the base layer using the specified alpha value.

        This function modifies the base_layer in place.

        Args:
            base_layer: The base image layer.
            overlay: The overlay image layer.
            alpha: The blending alpha value (0-100).
        """
        overlay_indices = overlay.any(axis=-1)
        if not overlay_indices.any():  # Skip if no overlay pixels
            return
        
        alpha_ratio = alpha / 100.0
        inv_alpha = 1.0 - alpha_ratio
        
        base_layer[overlay_indices] *= inv_alpha
        base_layer[overlay_indices] += overlay[overlay_indices] * alpha_ratio
    
    def _get_valid_slicer_and_dest(self, slicer: Tuple[Union[slice, int], ...], data_shape: Tuple[int, ...]) -> Tuple[Tuple, Tuple[slice, ...]]:
        """
        Convert a slicer that may extend beyond data bounds into a valid slicer and destination slices.
        
        Args:
            slicer: Original slicer that may have negative indices or exceed bounds
            data_shape: Shape of the data being sliced
        
        Returns:
            Tuple of (valid_slicer, dest_slices) where:
            - valid_slicer: Slicer clipped to valid data bounds
            - dest_slices: Where to place the data in the destination array
        """
        assert len([s for s in slicer if isinstance(s, slice)]) == 2, f"Slicer must have two slice objects, but got: {slicer}"
        
        valid_slicer = []
        dest_slices = []
        
        for s, dim_size in zip(slicer, data_shape):
            if isinstance(s, slice):
                start = s.start if s.start is not None else 0
                stop = s.stop if s.stop is not None else dim_size
                
                # Clip to valid range
                valid_start = max(0, start)
                valid_stop = min(dim_size, stop)
                
                if valid_stop <= valid_start:  # no data along this axis
                    return None, None
                
                # Calculate destination position
                dest_start = max(0, -start) if start < 0 else 0
                dest_stop = dest_start + (valid_stop - valid_start)
                
                valid_slicer.append(slice(valid_start, valid_stop))
                dest_slices.append(slice(dest_start, dest_stop))
            else:
                # Single index
                if 0 <= s < dim_size:
                    valid_slicer.append(s)
                    # Single index doesn't need a destination slice
                else:
                    # Index out of bounds
                    return None, None
        
        # Use destination slices for 2D placement
        dest_2d = tuple(dest_slices[:2])
        
        return tuple(valid_slicer), dest_2d
    
    def _blend_images_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        image_window_level: float,
        image_window_width: float,
        alpha: float
    ) -> None:
        """
        Blend active image slices into the base layer using specified window level, window width, and blending alpha.

        Args:
            base_layer: The base layer for image blending.
            slicer: A tuple defining the slicing of the image.
            image_window_level: The window level value.
            image_window_width: The window width value.
            alpha: The blending alpha (0-100).
        """
        sitk_images = self.find_active_sitk_images()
        if not sitk_images:
            return

        if image_window_level is None or image_window_width is None or alpha is None:
            logger.error(f"Image blending failed: Missing parameters (level: {image_window_level}, width: {image_window_width}, alpha: {alpha}).")
            return

        lower_bound = image_window_level - (image_window_width / 2)
        upper_bound = image_window_level + (image_window_width / 2)
        scale_factor = 255.0 / (upper_bound - lower_bound + 1e-4)
        
        # Initialize image slice accumulator
        composite_image = np.zeros((*base_layer.shape[:2], 3), dtype=np.float32)
        
        for sitk_image in sitk_images:
            # Convert the needed slice to numpy
            view = sitk.GetArrayViewFromImage(sitk_image)
            
            valid_slicer, dest_2d = self._get_valid_slicer_and_dest(slicer, view.shape)
            if valid_slicer is None:
                continue  # Skip if slice is out of bounds
            
            image_slice = view[valid_slicer].astype(np.float32)  # 2D slice
            
            np.clip(image_slice, lower_bound, upper_bound, out=image_slice)
            image_slice -= lower_bound
            image_slice *= scale_factor
            
            # Add to RGB channels
            composite_image[dest_2d[0], dest_2d[1], 0] += image_slice
            composite_image[dest_2d[0], dest_2d[1], 1] += image_slice
            composite_image[dest_2d[0], dest_2d[1], 2] += image_slice

        composite_image /= len(sitk_images) # Average of images

        self._blend_layers(base_layer, composite_image, alpha)
    
    def _blend_masks_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        contour_thickness: int,
        alpha: float
    ) -> None:
        """
        Blend mask overlays into the base layer using specified contour thickness and blending alpha.

        Args:
            base_layer: The base image layer.
            slicer: A tuple defining the slice of the mask.
            contour_thickness: The thickness of the mask contour.
            alpha: The blending alpha (0-100).
        """
        roi_keys_list = [k for k in self._cached_sitk_objects.keys() if k[0] == "roi"]
        if not roi_keys_list:
            return

        if not contour_thickness or not alpha:
            logger.error(f"Mask blending failed: 'contour_thickness' ({contour_thickness}) or 'alpha' ({alpha}) is missing or invalid.")
            return

        # If contour_thickness is 0, fill the contour (0 has no utility)
        if contour_thickness == 0:
            contour_thickness = -1

        composite_masks_RGB = np.zeros_like(base_layer, dtype=np.uint8)
        
        for roi_keys in roi_keys_list:
            roi_sitk = self._cached_sitk_objects[roi_keys]
            roi_view = sitk.GetArrayViewFromImage(roi_sitk)
            
            valid_slicer, dest_2d = self._get_valid_slicer_and_dest(slicer, roi_view.shape)
            if valid_slicer is None:
                continue  # Skip if slice is out of bounds
            
            roi_slice = roi_view[valid_slicer]
            if not np.any(roi_slice):
                continue
            
            struct_uid, roi_number = roi_keys[1], roi_keys[2]
            roi_display_color = self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {}).get("ROIDisplayColor", (0, 255, 0))
            
            # Get offset from dest_2d
            y_offset = dest_2d[0].start if dest_2d[0].start else 0  # 'y' w.r.t. texture, not anatomy
            x_offset = dest_2d[1].start if dest_2d[1].start else 0  # 'x' w.r.t. texture, not anatomy
            
            roi_contour_input = np.ascontiguousarray(roi_slice, dtype=np.uint8)
            contours, _ = cv2.findContours(
                image=roi_contour_input,
                mode=cv2.RETR_EXTERNAL,
                method=cv2.CHAIN_APPROX_SIMPLE,
                offset=(x_offset, y_offset)  # Note: (x, y) order for OpenCV
            )
            cv2.drawContours(
                image=composite_masks_RGB,
                contours=contours,
                contourIdx=-1,
                color=roi_display_color,
                thickness=contour_thickness
            )
            
        composite_masks_RGB = composite_masks_RGB.astype(np.float32)
        self._blend_layers(base_layer, composite_masks_RGB, alpha)
    
    def _blend_doses_RGB(
        self,
        base_layer: np.ndarray,
        slicer: Tuple[Union[slice, int], ...],
        dose_thresholds: Union[Tuple[float, float], List[float]],
        alpha: float
    ) -> None:
        """
        Blend dose overlays into the base layer using specified dose thresholds and blending alpha.

        Args:
            base_layer: The base image layer.
            slicer: A tuple defining the slice of the dose data.
            dose_thresholds: A tuple or list with lower and upper dose thresholds.
            alpha: The blending alpha (0-100).
        """
        if self._cached_dose_sum is None:
            return

        if (
            not dose_thresholds or 
            not isinstance(dose_thresholds, (tuple, list)) or
            len(dose_thresholds) != 2 or 
            not alpha
        ):
            logger.error(f"Dose blending failed: 'dose_thresholds' ({dose_thresholds}) or 'alpha' ({alpha}) is missing or invalid.")
            return

        min_threshold_p, max_threshold_p = dose_thresholds
        min_thresh = min_threshold_p / 100
        max_thresh = max_threshold_p / 100
        
        total_dose_view = sitk.GetArrayViewFromImage(self._cached_dose_sum)
        
        valid_slicer, dest_2d = self._get_valid_slicer_and_dest(slicer, total_dose_view.shape)
        if valid_slicer is None:
            return  # Skip if slice is out of bounds
        
        total_dose_slice = total_dose_view[valid_slicer]
        dose_mask = (total_dose_slice > min_thresh) & (total_dose_slice < max_thresh)
        if not np.any(dose_mask):
            return  # No dose in range to display

        # Create a color map for the base layer size
        cmap_data = np.zeros((*base_layer.shape[:2], 3), dtype=np.float32)
        
        # Apply colormap only to the valid dose region at the correct position
        dose_colors = self._dosewash_colormap(total_dose_slice[dose_mask]) * 255.0  # Scale to [0, 255] for blending
        
        # Get indices where dose_mask is True
        y_indices, x_indices = np.where(dose_mask)
        
        # Offset indices to destination position
        y_offset = dest_2d[0].start if dest_2d[0].start else 0  # 'y' w.r.t. texture, not anatomy
        x_offset = dest_2d[1].start if dest_2d[1].start else 0  # 'x' w.r.t. texture, not anatomy
        
        # Place colors directly at offset positions
        cmap_data[y_indices + y_offset, x_indices + x_offset] = dose_colors
        
        self._blend_layers(base_layer, cmap_data, alpha)
    
    ### Texture Helper Methods ###
    def _dosewash_colormap(self, value_array: np.ndarray) -> np.ndarray:
        """
        Apply a DoseWash colormap to a normalized 2-D dose array.

        Args:
            value_array: A 2-D NumPy array with values normalized to [0, 1].

        Returns:
            A 2-D NumPy array of corresponding RGB values (each in [0, 1]).
        """
        # Compute interpolated RGB values
        color_idx = value_array * (self._num_dose_colors - 1)
        lower_idx = color_idx.astype(np.int32) # Floor index
        upper_idx = np.minimum(lower_idx + 1, self._num_dose_colors - 1) # Ceil index
        blend_factor = (color_idx - lower_idx)[..., None] # Fractional part for blending

        # Linear interpolation between lower and upper colors
        rgb = self._dose_colors[lower_idx] * (1 - blend_factor) + self._dose_colors[upper_idx] * blend_factor

        # Clip RGB values to [0, 1]
        np.clip(rgb, 0.0, 1.0, out=rgb)
        
        return rgb
      
    def _draw_slice_crosshairs(
        self,
        base_layer: np.ndarray,
        show_crosshairs: bool,
        view_type: str,
        xyz_slices: Union[Tuple[int, int, int], List[int]],
        xyz_ranges: Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]],
        crosshair_color: int = 150
    ) -> None:
        """
        Draw crosshairs on the base layer at specified slice locations.

        Args:
            base_layer: The image layer on which to draw crosshairs.
            show_crosshairs: Flag indicating whether to display crosshairs.
            view_type: The view type ('axial', 'coronal', or 'sagittal').
            xyz_slices: A tuple or list of three integer slice positions.
            xyz_ranges: A tuple of three (min, max) integer pairs defining the spatial ranges.
            crosshair_color: The intensity/color value to use for crosshairs.
        """
        if not show_crosshairs:
            return
        
        if not xyz_slices or not isinstance(xyz_slices, (list, tuple)) or len(xyz_slices) != 3:
            logger.error(f"Crosshair drawing failed: 'xyz_slices' is missing or invalid: {xyz_slices}")
            return
        
        if not xyz_ranges or not isinstance(xyz_ranges, (list, tuple)) or len(xyz_ranges) != 3:
            logger.error(f"Crosshair drawing failed: 'xyz_ranges' is missing or invalid: {xyz_ranges}")
            return
        
        # Convert absolute slice positions to relative positions within the given ranges
        xyz_slices = [s - r[0] for s, r in zip(xyz_slices, xyz_ranges)]

        def get_thickness(dim_size: int) -> int:
            """Calculate dynamic thickness: 1 plus an increment for every 500 pixels."""
            return max(1, 1 + (dim_size // 500) * 2)
        
        if view_type == "axial":
            # Base layer has shape (y, x, 3) and xyz_slices are in (x, y, z) order
            thickness_y = get_thickness(base_layer.shape[0])
            thickness_x = get_thickness(base_layer.shape[1])
            if 0 <= xyz_slices[1] < base_layer.shape[0]:  # Horizontal line = y location
                base_layer[max(0, xyz_slices[1] - thickness_y // 2) : min(base_layer.shape[0], xyz_slices[1] + thickness_y // 2 + 1), :, :] = crosshair_color
            if 0 <= xyz_slices[0] < base_layer.shape[1]:  # Vertical line = x location
                base_layer[:, max(0, xyz_slices[0] - thickness_x // 2) : min(base_layer.shape[1], xyz_slices[0] + thickness_x // 2 + 1), :] = crosshair_color
        elif view_type == "coronal":
            # Base layer has shape (z, x, 3) and xyz_slices are in (z, y, x) order
            thickness_z = get_thickness(base_layer.shape[0])
            thickness_x = get_thickness(base_layer.shape[1])
            if 0 <= xyz_slices[2] < base_layer.shape[0]:  # Horizontal line = z location
                base_layer[max(0, xyz_slices[2] - thickness_z // 2) : min(base_layer.shape[0], xyz_slices[2] + thickness_z // 2 + 1), :, :] = crosshair_color
            if 0 <= xyz_slices[0] < base_layer.shape[1]:  # Vertical line = x location
                base_layer[:, max(0, xyz_slices[0] - thickness_x // 2) : min(base_layer.shape[1], xyz_slices[0] + thickness_x // 2 + 1), :] = crosshair_color
        elif view_type == "sagittal":
            # Base layer has shape (z, y, 3) and xyz_slices are in (z, y, x) order.
            thickness_z = get_thickness(base_layer.shape[0])
            thickness_y = get_thickness(base_layer.shape[1])
            if 0 <= xyz_slices[2] < base_layer.shape[0]:  # Horizontal line = z location
                base_layer[max(0, xyz_slices[2] - thickness_z // 2) : min(base_layer.shape[0], xyz_slices[2] + thickness_z // 2 + 1), :, :] = crosshair_color
            if 0 <= xyz_slices[1] < base_layer.shape[1]:  # Vertical line = y location
                base_layer[:, max(0, xyz_slices[1] - thickness_y // 2) : min(base_layer.shape[1], xyz_slices[1] + thickness_y // 2 + 1), :] = crosshair_color

    def _draw_orientation_labels(
        self,
        base_layer: np.ndarray,
        show_orientation_labels: bool,
        view_type: str,
        rotation: int,
        flips: List[bool]
    ) -> None:
        """
        Draw orientation labels (L/R, A/P, S/I) on the base image and blend them onto it.

        Args:
            base_layer: The image layer on which to draw labels.
            show_orientation_labels: Whether orientation labels should be drawn.
            view_type: One of 'axial', 'coronal', or 'sagittal'.
            rotation: The rotation angle in degrees.
            flips: A list of booleans indicating flip status for each axis.
        """
        if not show_orientation_labels:
            return

        # Do not draw orientation labels if the image is too small
        h, w = base_layer.shape[:2]
        if h < 50 or w < 50:
            return
        
        dicom_direction = self.original_direction or tuple(np.eye(3).flatten().tolist())
        rotation_angle = int(rotation) or 0
        flips = flips or [False, False, False]
        
        orientation_labels = get_orientation_labels(dicom_direction, rotation_angle, flips)
        if not orientation_labels:
            logger.error(f"Orientation labels are invalid; cannot draw labels.")
            return
        
        # Define label properties
        font = cv2.FONT_HERSHEY_COMPLEX
        font_scale = min(w, h) * 2e-3
        font_thickness = max(1, round(min(w, h) * 1e-3))
        
        text_RGBA = self.conf_mgr.get_orientation_label_color()
        text_RGB = [min(max(round(i), 0), 255) for i in text_RGBA[:3]]
        alpha = min(max(text_RGBA[3] / 2.55, 0), 100)  # Convert 0-255 to 0-100
        
        # Create an overlay for text
        overlay = np.zeros_like(base_layer, dtype=np.uint8)
        
        # Define a small buffer based on image size (1% of width/height)
        buffer_x = max(1, int(0.01 * w))  # At least 1 pixel
        buffer_y = max(1, int(0.01 * h))
        
        # Draw labels on the overlay
        keys_labels = {
            k.lower().strip():str(v).strip() 
            for k, v in orientation_labels.items() 
            if k.lower().strip().startswith(view_type.lower())
        }
        for key_position, label_text in keys_labels.items():
            if not label_text:
                continue
            
            text_size = cv2.getTextSize(label_text, font, font_scale, font_thickness)[0]
            
            # Default center alignment
            text_x = round((w - text_size[0]) / 2)  # Center horizontally
            text_y = round((h + text_size[1]) / 2)  # Center vertically
            
            # Snap to the edges
            if key_position.endswith("left"):
                text_x = buffer_x  # Fully left
            elif key_position.endswith("right"):
                text_x = w - text_size[0] - buffer_x  # Fully right
            elif key_position.endswith("top"):
                text_y = text_size[1] + buffer_y  # Fully top
            elif key_position.endswith("bottom"):
                text_y = h - buffer_y  # Fully bottom

            cv2.putText(img=overlay, text=label_text, org=(text_x, text_y), fontFace=font, fontScale=font_scale, color=text_RGB, thickness=font_thickness, lineType=cv2.LINE_AA)
        
        overlay = overlay.astype(np.float32)
        self._blend_layers(base_layer, overlay, alpha)
    
    ### GUI Data Retrieval Methods ###
    def find_active_sitk_images(self) -> List[sitk.Image]:
        """
        Retrieve all active IMAGE SITK objects from the cache.

        Returns:
            A list of SITK images for active IMAGE data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_img_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "image"]
        return [sitk_data for key in cached_img_keys if (sitk_data := self._cached_sitk_objects.get(key)) is not None]
    
    def find_active_sitk_rois(self) -> List[sitk.Image]:
        """
        Retrieve all active RTSTRUCT SITK objects from the cache.

        Returns:
            A list of SITK images for active RTSTRUCT data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_rts_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "roi"]
        return [sitk_data for key in cached_rts_keys if (sitk_data := self._cached_sitk_objects.get(key)) is not None]
    
    def find_active_sitk_doses(self) -> List[sitk.Image]:
        """
        Retrieve all active RTDOSE SITK objects from the cache.

        Returns:
            A list of SITK images for active RTDOSE data.
        """
        # Copy the keys to avoid error due to dictionary change during iteration
        cached_rtd_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "dose"]
        return [sitk_data for key in cached_rtd_keys if (sitk_data := self._cached_sitk_objects.get(key)) is not None]
    
    def return_roi_info_list_at_slice(self, slicer: Tuple[int, int, int]) -> List[Tuple[str, str, Tuple[int, int, int]]]:
        """
        Retrieve ROI information at the specified slice.

        Args:
            slicer: A tuple of (z, y, x) indices defining the current view.

        Returns:
            A list of tuples containing (ROI number, current ROI name, display color).
        """
        # Get ROI information from active cached data
        result = []
        roi_keys = [k for k in self._cached_sitk_objects.keys() if k[0] == "roi"]
        for key in roi_keys:
            struct_uid, roi_number = key[1], key[2]
            
            # Check if ROI has data at this slice by getting the SITK object
            roi_sitk = self._cached_sitk_objects.get(key)
            if roi_sitk is None:
                continue
            
            # Skip if slicer is out of bounds
            if not all(0 <= idx < dim for idx, dim in zip(slicer, list(roi_sitk.GetSize())[::-1])):
                continue
            
            view = sitk.GetArrayViewFromImage(roi_sitk)
            if not np.any(view[slicer]):
                continue  # Skip if no ROI data at this slice
            
            # Get ROI display name
            display_name = self.get_roi_gui_metadata_value_by_uid_and_key(struct_uid, roi_number, "display_name", "Unknown")
            
            color = self.get_roi_gui_metadata_value_by_uid_and_key(struct_uid, roi_number, "ROIDisplayColor", [255, 255, 255])
            if color:
                result.append((str(roi_number), display_name, tuple(color)))
        return result
    
    def return_image_value_list_at_slice(self,  slicer: Tuple[int, int, int]) -> List[np.ndarray]:
        """
        Retrieve image slices from active IMAGE data for the specified view.

        Args:
            slicer: A tuple of (z, y, x) indices defining the current view.

        Returns:
            A list of image slices as NumPy arrays.
        """
        return [sitk.GetArrayViewFromImage(img)[slicer] for img in self.find_active_sitk_images() if all(0 <= idx < dim for idx, dim in zip(slicer, list(img.GetSize())[::-1]))]

    def return_dose_value_list_at_slice(self,  slicer: Tuple[int, int, int]) -> List[np.ndarray]:
        """
        Retrieve dose slices from active RTDOSE data for the specified view.

        Args:
            slicer: A tuple of (z, y, x) indices defining the current view.

        Returns:
            A list of dose slices as NumPy arrays.
        """
        return [sitk.GetArrayViewFromImage(dose)[slicer] for dose in self.find_active_sitk_doses() if all(0 <= idx < dim for idx, dim in zip(slicer, list(dose.GetSize())[::-1]))]
        
    def return_is_any_data_active(self) -> bool:
        """
        Determine if any active data exists in the cache.

        Returns:
            True if active data is present; otherwise, False.
        """
        return len(self._cached_sitk_objects) > 0

    def count_active_data_items(self) -> int:
        """
        Count the total number of active data items in the cache.

        Returns:
            The number of active data items.
        """
        return len(self._cached_sitk_objects)
    
    ### Save Methods ###
    def save_image(self, series_uid: str, roi_overrides: List[Tuple[Tuple[str, int], float]], output_path: str, convert_ct_hu_to_red: bool = False, use_cached_data: bool = False) -> None:
        """ Save image with optional HU→RED conversion and ROI overrides for CT. """
        try:
            ct_image: Optional[sitk.Image] = self._get_data("image", series_uid, use_cached=use_cached_data)
            if ct_image is None:
                logger.error(f"No CT image found for series UID: {series_uid}")
                return

            modality = str(self.get_image_metadata_by_series_uid_and_key(series_uid, "Modality", "")).strip().upper()
            if modality != "CT" or not convert_ct_hu_to_red:
                if roi_overrides:
                    logger.warning("An image is saving, but note that ROI overrides were ignored - only applied with HU→RED conversion")
                # Save the original image without modification
                sitk.WriteImage(ct_image, output_path)
                logger.info(f"An image was saved to: {output_path}")
                return
            
            # Get the CT image as a NumPy array
            ct_array = sitk.GetArrayFromImage(ct_image).astype(np.float32)
            
            # Convert HU to RED
            ct_red_array: np.ndarray = self.HU_to_RED_map(ct_array)

            # Apply ROI overrides
            for roi_key, red_value in roi_overrides:
                roi_image: Optional[sitk.Image] = self._get_data("roi", roi_key, use_cached=use_cached_data)
                if roi_image is None:
                    logger.warning(f"ROI not found for override: {roi_key}. Skipping this override.")
                    continue
                
                roi_array = sitk.GetArrayFromImage(roi_image) > 0  # Binary mask
                ct_red_array[roi_array] = red_value
            
            # Create a new SITK image from the RED array and copy metadata
            ct_red_image = sitk.GetImageFromArray(ct_red_array)
            ct_red_image.CopyInformation(ct_image)  # Copy origin, spacing, direction
            copy_all_metadata(src=self.images.get(series_uid), dst=ct_red_image, copy_spatial=False)  # Copy all metadata from original
            
            # Set filepath metadata
            ct_filepaths = self.get_image_filepaths_by_series_uid(series_uid)
            ct_red_image.SetMetaData("dcm_filepaths", dumps(ct_filepaths))
            
            # Save the modified CT image
            sitk.WriteImage(ct_red_image, output_path)
            logger.info(f"CT image converted to units of RED and saved to: {output_path}")
        except Exception as e:
            logger.exception(f"Failed to save image for series UID '{series_uid}' to: {output_path}", exc_info=True, stack_info=True)

    def save_roi(self, struct_uid: str, roi_numbers: Union[int, List[int]], output_path: str, use_cached_data: bool = False) -> None:
        """ Save ROI(s) as binary mask. Multiple ROI numbers will be merged. """
        roi_numbers = [roi_numbers] if isinstance(roi_numbers, int) else roi_numbers
        try:
            # Collect all ROI masks
            roi_arrays = []
            reference_roi = None
            
            for roi_num in roi_numbers:
                roi_image = self._get_data("roi", (struct_uid, roi_num), use_cached=use_cached_data)
                if roi_image is None:
                    logger.warning(f"ROI #{roi_num} not found in RTSTRUCT {struct_uid}, skipping saving it")
                    continue
                
                if reference_roi is None:
                    reference_roi = roi_image  # Keep first as reference for metadata/spacing
                
                roi_array = sitk.GetArrayFromImage(roi_image) > 0  # Binary mask
                roi_arrays.append(roi_array)
            
            if not roi_arrays:
                logger.error(f"No valid ROIs found for RTSTRUCT {struct_uid} with numbers {roi_numbers}")
                return
            
            # Merge masks
            merged_mask = np.logical_or.reduce(roi_arrays).astype(np.uint8)
            
            # Create new image from merged mask
            merged_roi = sitk.GetImageFromArray(merged_mask)
            merged_roi.CopyInformation(reference_roi)
            
            # Set RTSTRUCT metadata
            merged_roi.SetMetaData("SOPInstanceUID", str(struct_uid))
            merged_roi.SetMetaData("dcm_filepath", str(self.get_rtstruct_filepath_by_uid(struct_uid)))
            merged_roi.SetMetaData("StructureSetLabel", str(self.get_rtstruct_ds_value_by_uid_and_key(struct_uid, "StructureSetLabel", "N/A")))
            merged_roi.SetMetaData("StructureSetName", str(self.get_rtstruct_ds_value_by_uid_and_key(struct_uid, "StructureSetName", "N/A")))
            merged_roi.SetMetaData("StructureSetDate", str(self.get_rtstruct_ds_value_by_uid_and_key(struct_uid, "StructureSetDate", "N/A")))
            merged_roi.SetMetaData("StructureSetTime", str(self.get_rtstruct_ds_value_by_uid_and_key(struct_uid, "StructureSetTime", "N/A")))
            
            # Add the GUI ROI metadata and save
            if len(roi_numbers) == 1:
                roi_number = roi_numbers[0]
                merged_roi.SetMetaData("ROINumber", str(roi_number))
                for key, value in self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_number, {}).items():
                    if isinstance(value, (str, int, float)):
                        merged_roi.SetMetaData(str(key), str(value))
                    else:
                        merged_roi.SetMetaData(str(key), dumps(value))
                
                sitk.WriteImage(merged_roi, output_path)
                logger.info(f"ROI number {roi_number} from RTSTRUCT '{struct_uid}' saved to: {output_path}")
            
            # For multiple ROIs, store lists of values and save
            else:
                merged_roi.SetMetaData("ROINumbers", dumps(roi_numbers))
                collected_keyvals = {}
                for roi_num in roi_numbers:
                    for key, value in self.rtstruct_roi_metadata.get(struct_uid, {}).get(roi_num, {}).items():
                        if key not in collected_keyvals:
                            collected_keyvals[key] = []
                        collected_keyvals[key].append(value)
                for key, value in collected_keyvals.items():
                    merged_roi.SetMetaData(str(key), dumps(value))
                
                sitk.WriteImage(merged_roi, output_path)
                logger.info(f"ROIs numbers {roi_numbers} from RTSTRUCT '{struct_uid}' merged and saved to: {output_path}")
            
        except Exception as e:
            logger.exception(f"Failed to save ROI image for RTSTRUCT {struct_uid} with numbers {roi_numbers} to: {output_path}", exc_info=True, stack_info=True)
    
    def save_plan(self, plan_uid: str, output_path: str) -> None:
        """ Save RTPLAN as a JSON file. """
        try:
            plan_ds = self.rtplan_datasets.get(plan_uid)
            if plan_ds is None:
                logger.error(f"No RTPLAN found for SOP Instance UID: {plan_uid}")
                return
            
            plan_json = plan_ds.to_json_dict(suppress_invalid_tags=True)
            plan_json["dcm_filepath"] = self.get_rtplan_filepath_by_uid(plan_uid)
            
            atomic_save(
                filepath=output_path,
                write_func=lambda fp: dump(plan_json, fp),
                success_message=f"RTPLAN '{plan_uid}' saved to: {output_path}",
                error_message=f"Failed to save RTPLAN '{plan_uid}' to: {output_path}"
            )
        except Exception as e:
            logger.exception(f"Failed to save RTPLAN '{plan_uid}' to: {output_path}", exc_info=True, stack_info=True)

    def save_dose(self, dose_uids: Union[str, List[str]], output_paths: Union[str, List[str]], use_cached_data: bool = False) -> None:
        """ Save RTDOSE as NRRD file. Multiple UIDs will be merged by summation. """
        dose_uids = [dose_uids] if isinstance(dose_uids, str) else dose_uids
        output_paths = [output_paths] if isinstance(output_paths, str) else output_paths
        try:
            # Collect all dose arrays
            dose_arrays = []
            reference_dose = None
            
            for uid in dose_uids:
                dose_image = self._get_data("dose", uid, use_cached=use_cached_data)
                if dose_image is None:
                    logger.warning(f"RTDOSE not found for UID {uid}, skipping saving it")
                    continue
                
                if reference_dose is None:
                    reference_dose = dose_image  # Keep first as reference for metadata/spacing
                
                dose_array = sitk.GetArrayFromImage(dose_image).astype(np.float32)
                dose_arrays.append(dose_array)
            
            if not dose_arrays:
                logger.error(f"No valid RTDOSE found for UIDs: {dose_uids}")
                return
            
            # Merge doses by summation
            merged_dose_array = np.sum(dose_arrays, axis=0)
            
            # Get total fxns
            planned_fxns = [self.get_rtdose_metadata_by_uid_and_key(uid, "NumberOfFractionsPlanned", "N/A") for uid in dose_uids]
            total_planned_fxns = sum(int(fx) for fx in planned_fxns if fx.isdigit())
            dose_fxns = [self.get_rtdose_metadata_by_uid_and_key(uid, "NumberOfFractions", "N/A") for uid in dose_uids]
            total_fxns = sum(int(fx) for fx in dose_fxns if fx.isdigit())
            all_ref_rtplans = [self.get_rtdose_metadata_by_uid_and_key(uid, "ReferencedRTPlanSOPInstanceUID", "") for uid in dose_uids]
            all_ref_beam_num = [self.get_rtdose_metadata_by_uid_and_key(uid, "ReferencedRTPlanBeamNumber", "N/A") for uid in dose_uids]
            
            # Scale dose if total planned fxns differ from total fxns
            scaling_ratio = total_planned_fxns / total_fxns if (total_fxns > 0 and total_planned_fxns > 0 and total_planned_fxns != total_fxns) else 1.0
            if scaling_ratio != 1.0:
                merged_dose_array *= scaling_ratio
                logger.info(f"Scaling merged dose by ratio {scaling_ratio:.4f} (Total Planned Fxns: {total_planned_fxns}, Total Fxns: {total_fxns})")
            
            # Create new image from merged dose
            merged_dose = sitk.GetImageFromArray(merged_dose_array)
            merged_dose.CopyInformation(reference_dose)

            # Set RTDOSE metadata and save
            merged_dose.SetMetaData("SOPInstanceUID", str(dose_uids[0]))
            merged_dose.SetMetaData("DoseType", str(self.get_rtdose_metadata_by_uid_and_key(dose_uids[0], "DoseType", "N/A")))
            merged_dose.SetMetaData("DoseUnits", str(self.get_rtdose_metadata_by_uid_and_key(dose_uids[0], "DoseUnits", "N/A")))
            merged_dose.SetMetaData("DoseScalingRatio", str(scaling_ratio))  # Always store scaling ratio
            if len(dose_uids) == 1:
                merged_dose.SetMetaData("dcm_filepath", str(self.get_rtdose_filepath_by_uid(dose_uids[0])))
                merged_dose.SetMetaData("DoseSummationType", str(self.get_rtdose_metadata_by_uid_and_key(dose_uids[0], "DoseSummationType", "N/A")))
                merged_dose.SetMetaData("NumberOfFractionsPlanned", str(planned_fxns[0]))
                merged_dose.SetMetaData("NumberOfFractions", str(dose_fxns[0]))
                merged_dose.SetMetaData("ReferencedRTPlanSOPInstanceUID", str(all_ref_rtplans[0]))
                merged_dose.SetMetaData("ReferencedRTPlanBeamNumber", str(all_ref_beam_num[0]))
                
                for path in output_paths:
                    sitk.WriteImage(merged_dose, path)
                    logger.info(f"RTDOSE '{dose_uids[0]}' saved to: {path}")
            else:
                merged_dose.SetMetaData("dcm_filepaths", dumps([self.get_rtdose_filepath_by_uid(uid) for uid in dose_uids]))
                merged_dose.SetMetaData("DoseSummationType", "CustomDoseSum")
                merged_dose.SetMetaData("NumberOfFractionsPlanned", str(total_planned_fxns))
                merged_dose.SetMetaData("NumberOfFractions", str(total_fxns))
                merged_dose.SetMetaData("ReferencedRTPlanSOPInstanceUIDs", dumps(all_ref_rtplans))
                merged_dose.SetMetaData("ReferencedRTPlanBeamNumbers", dumps(all_ref_beam_num))
                
                for output_path in output_paths:
                    sitk.WriteImage(merged_dose, output_path)
                    logger.info(f"RTDOSE {', '.join(dose_uids)} merged and saved to: {output_path}")
        
        except Exception as e:
            logger.exception(f"Failed to save RTDOSE '{dose_uids}' to: {output_paths}", exc_info=True, stack_info=True)
