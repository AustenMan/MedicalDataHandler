from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Optional, Tuple, Dict, Union, Any, List


import numpy as np
import SimpleITK as sitk


from mdh_app.utils.dicom_utils import safe_keyword_for_tag


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def sitk_transform_physical_point_to_index(
    physical_point: Union[Tuple[float, ...], List[float]],
    origin: Union[Tuple[float, ...], List[float]],
    spacing: Union[Tuple[float, ...], List[float]],
    direction: Union[Tuple[float, ...], List[float]]
) -> Tuple[int, int, int]:
    """Convert physical point to image index coordinates."""
    A = np.array(direction).reshape((3, 3)) @ np.diag(spacing)
    index = np.linalg.inv(A) @ (np.array(physical_point) - np.array(origin))
    return tuple(np.round(index).astype(int))


def sitk_to_array(
    sitk_image: sitk.Image,
    np_dtype: Optional[np.dtype] = None,
    flip_z_axis: bool = True
) -> np.ndarray:
    """Converts a SimpleITK image to a NumPy array with [Y, X, Z] layout."""
    array = sitk.GetArrayFromImage(sitk_image).transpose(1, 2, 0) # Transpose to [Y, X, Z] and flip Z axis
    if flip_z_axis:
        array = array[:, :, ::-1]
    return array.astype(np_dtype) if np_dtype else array


def array_to_sitk(
    numpy_array: np.ndarray,
    sitk_to_match: Optional[sitk.Image] = None,
    copy_metadata: bool = False,
    flip_z_axis: bool = True
) -> sitk.Image:
    """Converts a [Y, X, Z] NumPy array to a SimpleITK image and optionally copies metadata."""
    if flip_z_axis:
        numpy_array = numpy_array[:, :, ::-1]
    
    if numpy_array.dtype == bool:
        numpy_array = numpy_array.astype(np.uint8)
    
    sitk_image = sitk.GetImageFromArray(numpy_array.transpose(2, 0, 1))
    
    if isinstance(sitk_to_match, sitk.Image):
        sitk_image.CopyInformation(sitk_to_match)
        if copy_metadata:
            for key in sitk_to_match.GetMetaDataKeys():
                sitk_image.SetMetaData(key, sitk_to_match.GetMetaData(key))
    
    return sitk_image


def sitk_resample_to_reference(
    input_img: sitk.Image,
    reference_img: sitk.Image,
    interpolator: int = sitk.sitkLinear,
    default_pixel_val_outside_image: float = 0.0
) -> sitk.Image:
    """Resamples an image to match the geometry of a reference image."""
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference_img)
    resampler.SetInterpolator(interpolator)
    resampler.SetDefaultPixelValue(default_pixel_val_outside_image)
    resampler.SetTransform(sitk.AffineTransform(input_img.GetDimension()))
    resampler.SetOutputSpacing(reference_img.GetSpacing())
    resampler.SetSize(reference_img.GetSize())
    resampler.SetOutputOrigin(reference_img.GetOrigin())
    resampler.SetOutputDirection(reference_img.GetDirection())
    return resampler.Execute(input_img)


def resample_sitk_data_with_params(
    sitk_data: sitk.Image,
    set_spacing: Optional[Tuple[float, float, float]] = None,
    set_rotation: Optional[float] = None,
    set_flip: Optional[Tuple[bool, bool, bool]] = (False, False, False),
    interpolator: int = sitk.sitkLinear,
    numpy_output: bool = True,
    numpy_output_dtype: np.dtype = np.float32
) -> Union[np.ndarray, sitk.Image]:
    """Applies resampling to a 3D SimpleITK image with optional spacing, rotation, and flipping."""
    if not isinstance(sitk_data, sitk.Image):
        raise ValueError(f"Input must be a SimpleITK Image, but got {type(sitk_data)}.")
    if sitk_data.GetDimension() != 3:
        raise ValueError(f"Input must be a 3D SimpleITK Image, but got {sitk_data.GetDimension()}D.")
    
    original_spacing = sitk_data.GetSpacing()
    original_size = sitk_data.GetSize()
    original_direction = sitk_data.GetDirection()
    original_origin = sitk_data.GetOrigin()
    
    # Determine new spacing and size
    if set_spacing:
        new_spacing = set_spacing
        new_size = [round(osz * ospc / nspc) for osz, ospc, nspc in zip(original_size, original_spacing, new_spacing)]
    else:
        new_spacing = original_spacing
        new_size = original_size
    
    new_direction, transformation_matrix = transform_direction_cosines(
        original_direction, set_rotation, set_flip, return_transformation_matrix=True
    )
    
    # Update origin to account for transformation around the image center
    center = sitk_data.TransformContinuousIndexToPhysicalPoint((np.array(original_size) - 1) / 2.0)
    new_origin = center - transformation_matrix @ (center - np.array(original_origin))
    
    resampler = sitk.ResampleImageFilter()
    resampler.SetInterpolator(interpolator)
    resampler.SetOutputSpacing(set_spacing if set_spacing else original_spacing)
    resampler.SetSize(new_size if set_spacing else original_size)
    resampler.SetOutputDirection(tuple(new_direction))
    resampler.SetOutputOrigin(tuple(new_origin))
    resampled = resampler.Execute(sitk_data)
    
    return sitk_to_array(resampled, np_dtype=numpy_output_dtype) if numpy_output else resampled


def get_orientation_labels(
    dicom_direction: Union[list, tuple],
    rotation_angle: Union[int, float],
    flip_bools: Union[list, tuple],
    return_new_orientation: bool = False
) -> Union[Dict[str, str], Tuple[Dict[str, str], str]]:
    """Computes GUI orientation labels after applying rotation and flipping to DICOM direction cosines."""
    if not isinstance(dicom_direction, (list, tuple)) or len(dicom_direction) != 9:
        logger.error(f"The provided DICOM direction is not a list or tuple of length 9.")
        return None
    
    new_direction_list = transform_direction_cosines(dicom_direction, rotation_angle, flip_bools)
    new_orientation_str = sitk.DICOMOrientImageFilter().GetOrientationFromDirectionCosines(new_direction_list)
    
    # Define mapping of opposite orientations
    opposite = {"L": "R", "R": "L", "P": "A", "A": "P", "S": "I", "I": "S"}
    
    orientation_label_dict = {
        "coronal_gui_left": opposite[new_orientation_str[0]],
        "coronal_gui_right": new_orientation_str[0], 
        "coronal_gui_top": new_orientation_str[2],
        "coronal_gui_bottom": opposite[new_orientation_str[2]],
        "sagittal_gui_left": new_orientation_str[1],
        "sagittal_gui_right": opposite[new_orientation_str[1]],
        "sagittal_gui_top": new_orientation_str[2],
        "sagittal_gui_bottom": opposite[new_orientation_str[2]],
        "axial_gui_left": opposite[new_orientation_str[0]],
        "axial_gui_right": new_orientation_str[0], 
        "axial_gui_top": opposite[new_orientation_str[1]],
        "axial_gui_bottom": new_orientation_str[1],
    }

    return (orientation_label_dict, new_orientation_str) if return_new_orientation else orientation_label_dict


def transform_direction_cosines(
    dicom_direction: Union[list, tuple],
    rotation_angle: Optional[float],
    flip_bools: Optional[Tuple[bool, bool, bool]],
    return_transformation_matrix: bool = False
) -> Union[list, Tuple[list, np.ndarray]]:
    """Applies flipping and rotation to DICOM direction cosines."""
    # original_dicom_orientation = sitk.DICOMOrientImageFilter().GetOrientationFromDirectionCosines(dicom_direction)
    direction = np.array(dicom_direction).reshape(3, 3)
    flip_bools = list(flip_bools or (False, False, False))
    
    # If already rotated 90/270, then we need to swap flip index order to accurately reflect left/right flip and anterior/posterior flip
    if rotation_angle in [90, 270]:
        flip_bools[0], flip_bools[1] = flip_bools[1], flip_bools[0]
    
    flip_mat = np.diag([-1 if flip else 1 for flip in flip_bools])
    rot_mat = np.eye(3)
    
    if rotation_angle:
        theta = -np.deg2rad(rotation_angle) # Negative for clockwise rotation
        rot_mat = np.array([
            [np.cos(theta), -np.sin(theta), 0],
            [np.sin(theta),  np.cos(theta), 0],
            [0,              0,             1]
        ])
    
    # Combine transformations: flip then rotate
    trans_mat = rot_mat @ flip_mat
    new_direction = trans_mat @ direction
    
    return (new_direction.flatten().tolist(), trans_mat) if return_transformation_matrix else new_direction.flatten().tolist()


def merge_imagereader_metadata(
    reader: Union[sitk.ImageFileReader, sitk.ImageSeriesReader],
    image: Optional[sitk.Image] = None
) -> Union[Dict[str, Any], sitk.Image, None]:
    """Merges metadata from a SimpleITK image reader into a single dictionary or image."""
    if not isinstance(reader, (sitk.ImageFileReader, sitk.ImageSeriesReader)):
        logger.error("Object must be a SimpleITK reader.")
        return None

    if image is not None and not isinstance(image, sitk.Image):
        logger.error("Image must be a SimpleITK Image.")
        return None
    
    merged = {}
    
    if isinstance(reader, sitk.ImageFileReader):
        # Ensure that the reader has read the image information
        reader.ReadImageInformation()
        # Collect metadata from the single image
        merged = {key: reader.GetMetaData(key) for key in reader.GetMetaDataKeys()}
    
    elif isinstance(reader, sitk.ImageSeriesReader):
        filenames = reader.GetFileNames()
        if not filenames:
            logger.error("Series reader contains no files.")
            return None
        
        # Collect metadata dictionaries from each image in the series
        metadata_list = [{key: reader.GetMetaData(i, key) for key in reader.GetMetaDataKeys(i)} for i in range(len(filenames))]
        
        # Merge the metadata lists
        for meta in metadata_list:
            for key, value in meta.items():
                merged.setdefault(key, []).append(value)
        
        # Reduce lists to unique values if possible (i.e., if all values are the same)
        for key, values in merged.items():
            unique_vals = list(set(values))
            merged[key] = unique_vals[0] if len(unique_vals) == 1 else unique_vals
    
    if image is None:
        return merged
    
    # Assign the merged metadata to the image's MetaDataDictionary
    for key, value in merged.items():
        keyword = safe_keyword_for_tag(key)
        image.SetMetaData(keyword or key, str(value))
    
    return image


def log_image_metadata(image: sitk.Image) -> None:
    """Logs metadata, spacing, origin, direction, and size of a SimpleITK image."""
    logger.info("Logging image metadata:")
    for key in image.GetMetaDataKeys():
        logger.info(f"{key}: {image.GetMetaData(key)}")
    logger.info(f"Spacing: {image.GetSpacing()}, Origin: {image.GetOrigin()}, Direction: {image.GetDirection()}, Size: {image.GetSize()}")


def copy_structure_without_sitk_images(obj: Any) -> Any:
    """Recursively removes SimpleITK.Image objects from nested structures, replacing them with None."""
    if isinstance(obj, dict):
        return {k: copy_structure_without_sitk_images(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [copy_structure_without_sitk_images(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(copy_structure_without_sitk_images(v) for v in obj)
    elif isinstance(obj, set):
        return {copy_structure_without_sitk_images(v) for v in obj}
    elif isinstance(obj, sitk.Image):
        return None
    return obj


def get_sitk_roi_display_color(
    sitk_data: sitk.Image,
    default_return_color: Tuple[int, int, int] = (255, 255, 255)
) -> Tuple[int, int, int]:
    """Retrieves the 'roi_display_color' metadata value from an image."""
    if not isinstance(sitk_data, sitk.Image):
        logger.error("Object is not a SimpleITK Image.")
        return default_return_color
    
    try:
        color = sitk_data.GetMetaData("roi_display_color")
        return tuple(map(int, color.strip("[]").split(", ")))
    except:
        return default_return_color


def reduce_sitk_size(sitk_image: sitk.Image) -> sitk.Image:
    """Crops an image to the smallest bounding box containing all non-zero voxels."""
    array = sitk.GetArrayFromImage(sitk_image).transpose(2, 1, 0).astype(bool)
    non_zero = np.nonzero(array)
    bounds_min = [np.min(ax) for ax in non_zero]
    bounds_max = [np.max(ax) for ax in non_zero]
    return sitk_image[
        bounds_min[0]:bounds_max[0]+1,
        bounds_min[1]:bounds_max[1]+1,
        bounds_min[2]:bounds_max[2]+1
    ]

