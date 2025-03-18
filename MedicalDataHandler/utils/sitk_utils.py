import numpy as np
import SimpleITK as sitk
from typing import Optional, Tuple, Dict
from utils.dicom_utils import safe_keyword_for_tag

def sitk_transform_physical_point_to_index(physical_point, origin, spacing, direction):
    """
    Transforms a physical point to its corresponding voxel index in the image space.
    
    P = O + (D * S_diagonal) * I, where:
        P = physical space position vector
        O = physical space origin vector
        D = direction cosines matrix
        S_diagonal = physical spacing between voxels as a diagonal matrix
        I = voxel indices vector
    
    Args:
        physical_point (tuple or list): The physical coordinates to transform.
        origin (tuple or list): The origin of the image in physical space.
        spacing (tuple or list): The voxel spacing of the image.
        direction (tuple or list): The direction cosines of the image.
    
    Returns:
        tuple: The voxel index corresponding to the physical point.
    """
    # Convert inputs to numpy arrays
    physical_point = np.array(physical_point)
    origin = np.array(origin)
    spacing = np.array(spacing)
    direction = np.array(direction).reshape((3, 3))
    
    # Calculate the transformation matrix A
    A = direction @ np.diag(spacing)
    
    # Calculate the inverse of the transformation matrix A
    A_inv = np.linalg.inv(A)
    
    # Compute the index
    index = np.dot(A_inv, (physical_point - origin))
    
    # Round the index to the nearest integer
    index = np.round(index).astype(int)
    
    return tuple(index)

def sitk_to_array(sitk_image, np_dtype=None):
    """
    Converts a SimpleITK image (from [Z, Y, X] dim order) to a numpy array (to [Y, X, Z] dim order).
    
    Args:
        sitk_image (SimpleITK.Image): The input SimpleITK image.
        np_dtype (np.dtype, optional): Desired numpy data type for the output array.
    
    Returns:
        np.array: A numpy array representing the image, with dimensions [Y, X, Z].
    """
    if np_dtype:
        return sitk.GetArrayFromImage(sitk_image).astype(np_dtype).transpose(1, 2, 0)[:, :, ::-1] # Transpose to [Y, X, Z] and flip Z axis
    else:
        return sitk.GetArrayFromImage(sitk_image).transpose(1, 2, 0)[:, :, ::-1]

def array_to_sitk(numpy_array, sitk_to_match=None, copy_metadata=False):
    """
    Converts a numpy array (from [Y, X, Z] dim order) to a SimpleITK image (to [Z, Y, X] dim order).
    
    Args:
        numpy_array (np.array): The input numpy array, with dimensions [Y, X, Z].
        sitk_to_match (SimpleITK.Image, optional): Reference image for copying metadata.
        copy_metadata (bool, optional): Whether to copy metadata from the reference image.
    
    Returns:
        SimpleITK.Image: The converted SimpleITK image.
    """
    if numpy_array.dtype == bool:
        numpy_array = numpy_array.astype(np.uint8)
    
    sitk_image = sitk.GetImageFromArray(numpy_array[:, :, ::-1].transpose(2, 0, 1))
    
    if isinstance(sitk_to_match, sitk.Image):
        sitk_image.CopyInformation(sitk_to_match)
        
        if copy_metadata:
            for key in sitk_to_match.GetMetaDataKeys():
                sitk_image.SetMetaData(key, sitk_to_match.GetMetaData(key))
    
    return sitk_image

def sitk_resample_to_reference(input_img, reference_img, interpolator=sitk.sitkLinear, default_pixel_val_outside_image=0.0):
    """
    Resamples an input image to match the spatial characteristics of a reference image.
    
    Args:
        input_img (SimpleITK.Image): The image to be resampled.
        reference_img (SimpleITK.Image): The reference image.
        interpolator (int): Interpolation method for resampling (e.g., sitk.sitkLinear).
        default_pixel_val_outside_image (float): Default pixel value for regions outside the image.
    
    Returns:
        SimpleITK.Image: The resampled image.
    """
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference_img)
    resampler.SetInterpolator(interpolator)
    resampler.SetDefaultPixelValue(default_pixel_val_outside_image)
    resampler.SetTransform(sitk.AffineTransform(input_img.GetDimension()))
    resampler.SetOutputSpacing(reference_img.GetSpacing())
    resampler.SetSize(reference_img.GetSize())
    resampler.SetOutputOrigin(reference_img.GetOrigin())
    resampler.SetOutputDirection(reference_img.GetDirection())
    
    resampled_img = resampler.Execute(input_img)
    
    return resampled_img

def resample_sitk_data_with_params(
    sitk_data: sitk.Image, 
    set_spacing: Optional[Tuple[float, float, float]] = None, 
    set_rotation: Optional[float] = None, 
    set_flip: Optional[Tuple[bool, bool, bool]] = [False, False, False],
    interpolator: int = sitk.sitkLinear, 
    numpy_output: bool = True,
    numpy_output_dtype: np.dtype = np.float32) -> Tuple[sitk.Image, Optional[Dict[str, sitk.Image]]]:
    """
    Resamples a 3D SimpleITK image with specified parameters for spacing, rotation, and flipping.
    
    Args:
        sitk_data (SimpleITK.Image): The input 3D image.
        set_spacing (tuple, optional): Desired voxel spacing.
        set_rotation (float, optional): Rotation angle in degrees.
        set_flip (tuple, optional): Boolean flags for flipping along each axis.
        interpolator (int): Interpolation method for resampling.
        numpy_output (bool): Whether to return the result as a numpy array.
        numpy_output_dtype (np.dtype): Data type for the output numpy array.
    
    Returns:
        Tuple: The resampled image as SimpleITK.Image or numpy array.
    """
    
    assert isinstance(sitk_data, sitk.Image), "sitk_data must be a SimpleITK Image."
    assert sitk_data.GetDimension() == 3, "sitk_data must be a 3D SimpleITK Image."
    
    original_spacing = sitk_data.GetSpacing()
    original_size = sitk_data.GetSize()
    original_direction = sitk_data.GetDirection()
    original_origin = sitk_data.GetOrigin()
    
    resampler = sitk.ResampleImageFilter()
    resampler.SetInterpolator(interpolator)
    
    # Determine new spacing and size
    if set_spacing:
        new_spacing = set_spacing
        new_size = [round(osz * ospc / nspc) for osz, ospc, nspc in zip(original_size, original_spacing, new_spacing)]
    else:
        new_spacing = original_spacing
        new_size = original_size
    
    resampler.SetOutputSpacing(set_spacing if set_spacing else original_spacing)
    resampler.SetSize(new_size if set_spacing else original_size)
    
    new_direction, transformation_matrix = transform_direction_cosines(original_direction, set_rotation, set_flip, return_transformation_matrix=True)
    
    # Update origin to account for transformation around the image center
    center = sitk_data.TransformContinuousIndexToPhysicalPoint((np.array(original_size) - 1) / 2.0)
    new_origin = center - transformation_matrix @ (center - np.array(original_origin))
    
    resampler.SetOutputDirection(tuple(new_direction))
    resampler.SetOutputOrigin(tuple(new_origin))
    
    resampled_sitk_data = resampler.Execute(sitk_data)
    
    if numpy_output:
        return sitk_to_array(resampled_sitk_data, np_dtype=numpy_output_dtype)
    else:
        return resampled_sitk_data

def get_orientation_labels(dicom_direction, rotation_angle, flip_bools, return_new_orientation=False):
    """
    Derives orientation labels based on DICOM direction, rotation, and flipping.
    
    Args:
        dicom_direction (list, tuple): The DICOM direction cosines.
        rotation_angle (int, float): The rotation angle in degrees.
        flip_bools (list, tuple): List/tuple of booleans indicating flips along each axis.
        return_new_orientation (bool): Whether to return the new DICOM orientation string (after rotation and flipping).
    
    Returns:
        tuple: A dictionary of orientation labels for each view and the new DICOM orientation string.
    """
    if not isinstance(dicom_direction, (list, tuple)) or len(dicom_direction) != 9:
        print(f"Error: The provided DICOM direction is not a list or tuple of length 9.")
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

    if return_new_orientation:
        return orientation_label_dict, new_orientation_str
    else:
        return orientation_label_dict

def transform_direction_cosines(dicom_direction, rotation_angle, flip_bools, return_transformation_matrix=False):
    """
    Transforms DICOM direction cosines based on rotation and flipping.
    
    Args:
        dicom_direction (list, tuple): The DICOM direction cosines.
        rotation_angle (int, float): The rotation angle in degrees.
        flip_bool_list (list, tuple): List/tuple of booleans indicating flips along each axis
        return_transformation_matrix (bool): Whether to return the transformation matrix.
        
    Returns:
        list: The new flattened list of DICOM direction cosines.
        np.array (optional): The transformation matrix.
    """
        
    # original_dicom_orientation = sitk.DICOMOrientImageFilter().GetOrientationFromDirectionCosines(dicom_direction)
    original_direction = np.array(dicom_direction).reshape(3, 3)
    
    # Build flip matrix
    if flip_bools:
        # If already rotated 90/270, then we need to swap flip index order to accurately reflect left/right flip and anterior/posterior flip
        if rotation_angle in [90, 270]: 
            flip_bools = [flip_bools[1], flip_bools[0], flip_bools[2]]
        flip_matrix = np.diag([-1 if flip else 1 for flip in flip_bools])
    else:
        flip_matrix = np.eye(3)
    
    # Build rotation matrix
    if rotation_angle:
        angle_rad = -np.deg2rad(rotation_angle)  # Negative for clockwise rotation
        cos_theta = np.cos(angle_rad)
        sin_theta = np.sin(angle_rad)
        rotation_matrix = np.array([
            [cos_theta, -sin_theta, 0],
            [sin_theta,  cos_theta, 0],
            [0,          0,         1]
        ])
    else:
        rotation_matrix = np.eye(3)
    
    # Combine transformations: flip then rotate
    transformation_matrix = rotation_matrix @ flip_matrix
    
    # Update direction matrix
    new_direction = transformation_matrix @ np.array(original_direction).reshape(3, 3)
    
    if return_transformation_matrix:
        return new_direction.flatten().tolist(), transformation_matrix
    else:
        return new_direction.flatten().tolist()

def merge_imagereader_metadata(reader, image=None):
    """
    Merges the metadata dictionaries from all images in a SimpleITK ImageFileReader or ImageSeriesReader into a single dictionary.
    
    If a key has multiple different values across images (in the case of ImageSeriesReader), the value
        in the merged dictionary will be a list of unique values.
    
    Args:
        reader (SimpleITK.ImageFileReader or SimpleITK.ImageSeriesReader): The reader object.
        image (SimpleITK.Image, optional): The image to which metadata will be added.
    
    Returns:
        dict or SimpleITK.Image: Merged metadata dictionary or updated SimpleITK image.
    """
    if not isinstance(reader, (sitk.ImageFileReader, sitk.ImageSeriesReader)):
        print("Error: The provided object is not a SimpleITK ImageFileReader or ImageSeriesReader.")
        return None
    
    if image is not None and not isinstance(image, sitk.Image):
        print("Error: The provided image is not a SimpleITK Image.")
        return None
    
    merged_meta = {}
    
    if isinstance(reader, sitk.ImageFileReader):
        # Ensure that the reader has read the image information
        reader.ReadImageInformation()
        
        # Collect metadata from the single image
        metadata_dict = {key: reader.GetMetaData(key) for key in reader.GetMetaDataKeys()}
        merged_meta = metadata_dict
    
    elif isinstance(reader, sitk.ImageSeriesReader):
        num_files_in_reader = len(reader.GetFileNames())
        if not num_files_in_reader:
            print("Error: The reader contains no files.")
            return None
        
        # Collect metadata dictionaries from each image in the series
        metadata_dicts = [{key: reader.GetMetaData(i, key) for key in reader.GetMetaDataKeys(i)} for i in range(num_files_in_reader)]
        
        # Merge the metadata dictionaries
        merged_meta = {}
        for meta in metadata_dicts:
            for key, value in meta.items():
                if key not in merged_meta:
                    merged_meta[key] = [value]
                else:
                    merged_meta[key].append(value)
        
        # Reduce lists to unique values if possible (i.e., if all values are the same)
        for key, value in merged_meta.items():
            unique_values = list(set(value))
            if len(unique_values) == 1:
                merged_meta[key] = unique_values[0]
    
    if image is None:
        return merged_meta
    
    # Assign the merged metadata to the image's MetaDataDictionary
    for key, value in merged_meta.items():
        keyword = safe_keyword_for_tag(key)
        if keyword is not None:
            image.SetMetaData(keyword, str(value))
        else:
            image.SetMetaData(key, str(value))
    
    return image

def print_image_metadata(image):
    """
    Prints the metadata of a SimpleITK image.
    
    Args:
        image (SimpleITK.Image): The input image whose metadata will be printed.
    
    Returns:
        None
    """
    print(f"Starting to print metadata for an SITK image...")
    for key in image.GetMetaDataKeys():
        value = image.GetMetaData(key)
        print(f'Key: {key}, Value: "{value}"')
    print(f"Image spacing: {image.GetSpacing()}, Image origin: {image.GetOrigin()}, Image direction: {image.GetDirection()}, Image size: {image.GetSize()}")

def copy_structure_without_sitk_images(obj):
    """
    Recursively copies a data structure, replacing any SimpleITK.Image instances with None.
    
    Args:
        obj: The data structure to copy.
    
    Returns:
        The copied data structure with SimpleITK.Image instances replaced by None.
    """
    if isinstance(obj, dict):
        return {key: copy_structure_without_sitk_images(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [copy_structure_without_sitk_images(element) for element in obj]
    elif isinstance(obj, tuple):
        return tuple(copy_structure_without_sitk_images(element) for element in obj)
    elif isinstance(obj, set):
        return {copy_structure_without_sitk_images(element) for element in obj}
    elif isinstance(obj, sitk.Image):
        return None
    else:
        return obj

def get_sitk_roi_display_color(sitk_data, default_return_color=(255, 255, 255)):
    """
    Retrieves the ROI display color from a SimpleITK image's metadata.
    
    Args:
        sitk_data (SimpleITK.Image): The input image.
        default_return_color (tuple): The default color to return if no color is found.
    
    Returns:
        tuple: The ROI display color.
    """
    if not isinstance(sitk_data, sitk.Image):
        print("Error: The provided object is not a SimpleITK Image.")
        return default_return_color
    
    roi_display_color = sitk_data.GetMetaData("roi_display_color")
    if roi_display_color:
        return tuple(map(int, roi_display_color.strip('[]').split(', ')))
    else:
        return default_return_color

def reduce_sitk_size(sitk_image):
    """
    Reduces the size of a SimpleITK image by cropping non-zero regions.
    
    Args:
        sitk_image (SimpleITK.Image): The input image.
    
    Returns:
        SimpleITK.Image: The cropped image.
    """
    array_xyz = sitk.GetArrayFromImage(sitk_image).transpose(2, 1, 0).astype(bool)
    non_zero_indices = np.nonzero(array_xyz)
    min_bounds_xyz = [np.min(axis) for axis in non_zero_indices]
    max_bounds_xyz = [np.max(axis) for axis in non_zero_indices]
    sitk_image = sitk_image[min_bounds_xyz[0]:max_bounds_xyz[0]+1, min_bounds_xyz[1]:max_bounds_xyz[1]+1, min_bounds_xyz[2]:max_bounds_xyz[2]+1]
    return sitk_image
