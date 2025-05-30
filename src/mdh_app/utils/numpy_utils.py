import logging
import numpy as np
import cv2
from scipy.interpolate import interp1d
from typing import Callable, List, Tuple, Union

logger = logging.getLogger(__name__)

def numpy_roi_mask_generation(
    cols: int,
    rows: int,
    mask: np.ndarray,
    matrix_points: np.ndarray,
    geometric_type: str
) -> np.ndarray:
    """
    CREDIT FOR ORIGINAL FUNCTION: http://www.github.com/brianmanderson
    
    Updated for vectorized interpolation.
    
    Generates a 3D ROI mask based on provided geometric type and matrix points.
    
    Args:
        cols (int): Number of columns in the mask.
        rows (int): Number of rows in the mask.
        mask (np.array): The 3D mask boolean array to modify.
        matrix_points (np.array): Array containing points defining the ROI.
        geometric_type (str): The type of geometry ("OPEN_NONPLANAR" or other types).
    
    Returns:
        np.array: The updated 3D mask with the ROI applied.
    """
    if geometric_type != "OPEN_NONPLANAR":
        col_val = matrix_points[:, 0]
        row_val = matrix_points[:, 1]
        z_vals  = matrix_points[:, 2]
        
        temp_mask = poly2mask(row_val, col_val, (rows, cols))
        mask[z_vals[0], temp_mask] = True
    else:
        # Compute interpolated values for each of col, row, z using np.linspace
        interp_arrays = [
            np.linspace(
                matrix_points[i], 
                matrix_points[i-1], 
                int(abs(matrix_points[i-1, 2] - matrix_points[i, 2])) + 1, # Determine number of interpolation steps (ensuring at least 2 points)
                dtype=int
            ) for i in range(1, len(matrix_points)) if matrix_points[i, 2] != matrix_points[i-1, 2] # Skip segments where no change in z occurs
        ]
        
        if interp_arrays:
            # Concatenate all interpolated points into one array. all_points has shape (N, 3) in the order [col, row, z]
            all_points = np.concatenate(interp_arrays, axis=0, dtype=int)
            # Reorder columns to match mask indexing ([z, row, col])
            all_points = all_points[:, [2, 1, 0]]
            # Clip indices to ensure they're within mask bounds.
            all_points[:, 0] = np.clip(all_points[:, 0], 0, mask.shape[0]-1) # z
            all_points[:, 1] = np.clip(all_points[:, 1], 0, mask.shape[1]-1) # row
            all_points[:, 2] = np.clip(all_points[:, 2], 0, mask.shape[2]-1) # col
            # Update the mask
            mask[all_points[:, 0], all_points[:, 1], all_points[:, 2]] = True
    
    return mask

def poly2mask(
    vertex_row_coords: np.ndarray,
    vertex_col_coords: np.ndarray,
    shape: Tuple[int, int]
) -> np.ndarray:
    """
    CREDIT: http://www.github.com/brianmanderson
    
    Converts polygon coordinates to a filled boolean mask.
    
    Args:
        vertex_row_coords (np.array): Row coordinates of the polygon vertices.
        vertex_col_coords (np.array): Column coordinates of the polygon vertices.
        shape (tuple): Dimensions of the output mask.
    
    Returns:
        np.array: A boolean mask with the polygon filled in.
    """
    xy_coords = np.array([vertex_col_coords, vertex_row_coords])
    coords = np.expand_dims(xy_coords.T, 0)
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, coords, 1)
    return mask.astype(bool)

def create_HU_to_RED_map(
    hu_values: Union[List[float], Tuple[float, ...]],
    red_values: Union[List[float], Tuple[float, ...]]
) -> Callable[[np.ndarray], np.ndarray]:
    """
    Creates a linear mapping function from Hounsfield Units (HU) to Relative Electron Density (RED).

    Args:
        hu_values: HU values for calibration.
        red_values: Corresponding RED values.

    Returns:
        Interpolation function that maps HU to RED.
    """
    if not hu_values or not red_values:
        logger.warning("HU/RED values not provided. Using default calibration.")
        hu_values = _get_backup_hu_values()
        red_values = _get_backup_red_values()
    elif not isinstance(hu_values, (list, tuple)) or not isinstance(red_values, (list, tuple)):
        logger.warning("HU/RED values must be lists or tuples. Using default calibration.")
        hu_values = _get_backup_hu_values()
        red_values = _get_backup_red_values()
    elif len(hu_values) != len(red_values):
        logger.warning("HU and RED lists must be of equal length. Using default calibration.")
        hu_values = _get_backup_hu_values()
        red_values = _get_backup_red_values()

    return interp1d(
        np.array(hu_values),
        np.array(red_values),
        kind="linear",
        bounds_error=False,
        fill_value="extrapolate"
    )

def _get_backup_hu_values() -> List[int]:
    """Returns default HU values for RED mapping."""
    return [
        -1050, -1000, -950, -900, -850, -800, -750, -700, -650, -600, -550, -500, -450, -400, -350, -300,
        -250, -200, -150, -100, -50, 0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650,
        700, 750, 800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350, 1400, 1450, 1500,
        1550, 1600, 1650, 1700, 1750, 1800, 1850, 1900, 1950, 2000, 2050, 2100, 2150, 2200, 2250, 2300,
        2350, 2400, 2450, 2500, 2550, 2600, 2650, 2700, 2750, 2800, 2850, 2900, 2950, 3000, 3050, 3100,
        3150, 3200, 3250, 3300, 3350, 3400, 3450, 3500, 3550, 3600, 3650, 3700, 3750, 3800, 3850, 3900,
        3950, 4000, 4050, 4100, 4150, 4200, 4250, 4300, 4350, 4400, 4450, 4500, 4550, 4600, 4650, 4700,
        4750, 4800, 4850, 4900, 4950, 5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500,
        5550, 5600, 5650, 5700, 5750, 5800, 5850, 5900, 5950, 6000, 6050, 6100, 6150, 6200, 6250, 6300,
        6350, 6400, 6450, 6500, 6550, 6600, 6650, 6700, 6750, 6800, 6850, 6900, 6950, 7000, 7050, 7100,
        7150, 7200, 7250, 7300, 7350, 7400, 7450, 7500, 7550, 7600, 7650, 7700, 7750, 7800, 7850, 7900,
        7950, 8000, 8050, 8100, 8150, 8200, 8250, 8300, 8350, 8400, 8450, 8500, 8550, 8600, 8650, 8700,
        8750, 8800, 8850, 8900, 8950, 9000, 9050, 9100, 9150, 9200, 9250, 9300, 9350, 9400, 9450, 9500,
        9550, 9600, 9650, 9700, 9750, 9800, 9850, 9900, 9950, 10000, 10050, 10100, 10150, 10200, 10250,
        10300, 10350, 10400, 10450, 10500, 10550, 10600, 10650, 10700, 10750, 10800, 10850, 10900, 10950,
        11000, 11050, 11100, 11150, 11200, 11250, 11300, 11350, 11400, 11450, 11500, 11550, 11600, 11650,
        11700, 11750, 11800, 11850, 11900, 11950, 12000, 12050, 12100, 12150, 12200, 12250, 12300, 12350,
        12400, 12450, 12500, 12550, 12600, 12650, 12700, 12750, 12800, 12850, 12900, 12950, 13000, 13050,
        13100, 13150, 13200, 13250, 13300, 13350, 13400, 13450, 13500, 13550, 13600, 13650, 13700, 13750,
        13800, 13850, 13900, 13950, 14000, 14050, 14100, 14150, 14200, 14250, 14300, 14350, 14400, 14450,
        14500, 14550, 14600, 14650, 14700, 14750, 14800, 14850, 14900, 14950, 15000, 15050, 15100, 15150,
        15200, 15250, 15300, 15350, 15400, 15450, 15500, 15550, 15600, 15650, 15700, 15750, 15800, 15850,
        15900, 15950, 16000, 16050, 16100, 16150, 16200, 16250, 16300, 16350, 16400, 16450, 16500, 16550,
        16600, 16650, 16700, 16750, 16800, 16850, 16900, 16950, 17000, 17050, 17100, 17150, 17200, 17250,
        17300, 17350, 17400, 17450, 17500, 17550, 17600, 17650, 17700, 17750, 17800, 17850, 17900, 17950,
        18000, 18050, 18100, 18150, 18200, 18250, 18300, 18350, 18400, 18450, 18500, 18550, 18600, 18650,
        18700, 18750, 18800, 18850, 18900, 18950, 19000, 19050, 19100, 19150, 19200, 19250, 19300, 19350,
        19400, 19450, 19500, 19550, 19600, 19650, 19700, 19750, 19800, 19850, 19900, 19950, 20000
    ]

def _get_backup_red_values() -> List[float]:
    """Returns default RED values corresponding to backup HU values."""
    return [
        0.0, 0.001, 0.05, 0.096, 0.145, 0.193, 0.237, 0.28, 0.321, 0.352, 0.398, 0.448, 0.498, 0.557,
        0.613, 0.67, 0.726, 0.784, 0.839, 0.906, 0.965, 1.0, 1.064, 1.067, 1.075, 1.088, 1.131, 1.164,
        1.204, 1.241, 1.282, 1.302, 1.327, 1.359, 1.387, 1.414, 1.442, 1.474, 1.503, 1.528, 1.56, 1.59,
        1.621, 1.649, 1.676, 1.704, 1.726, 1.748, 1.772, 1.795, 1.817, 1.84, 1.863, 1.886, 1.908, 1.931,
        1.954, 1.976, 2.0, 2.022, 2.044, 2.067, 2.09, 2.113, 2.135, 2.158, 2.18, 2.202, 2.225, 2.248,
        2.271, 2.295, 2.317, 2.34, 2.363, 2.385, 2.408, 2.431, 2.454, 2.477, 2.5, 2.517, 2.528, 2.544,
        2.56, 2.575, 2.589, 2.605, 2.621, 2.636, 2.65, 2.666, 2.681, 2.695, 2.711, 2.726, 2.741, 2.756,
        2.771, 2.786, 2.801, 2.816, 2.832, 2.848, 2.863, 2.878, 2.893, 2.908, 2.923, 2.939, 2.953, 2.968,
        2.984, 2.999, 3.013, 3.029, 3.045, 3.059, 3.074, 3.089, 3.105, 3.12, 3.134, 3.15, 3.166, 3.18,
        3.195, 3.211, 3.227, 3.241, 3.255, 3.27, 3.287, 3.302, 3.316, 3.331, 3.347, 3.363, 3.378, 3.392,
        3.407, 3.423, 3.439, 3.453, 3.468, 3.484, 3.5, 3.514, 3.529, 3.544, 3.559, 3.574, 3.589, 3.604,
        3.62, 3.635, 3.649, 3.665, 3.68, 3.696, 3.709, 3.73, 3.774, 3.82, 3.873, 3.922, 3.973, 4.022,
        4.073, 4.123, 4.173, 4.222, 4.272, 4.323, 4.373, 4.423, 4.473, 4.523, 4.573, 4.623, 4.674, 4.724,
        4.773, 4.823, 4.874, 4.925, 4.975, 5.024, 5.073, 5.124, 5.175, 5.225, 5.275, 5.324, 5.374, 5.424,
        5.475, 5.526, 5.575, 5.624, 5.675, 5.725, 5.776, 5.825, 5.875, 5.925, 5.975, 6.026, 6.076, 6.126,
        6.175, 6.226, 6.276, 6.326, 6.376, 6.426, 6.476, 6.526, 6.577, 6.627, 6.7, 6.74, 6.745, 6.747,
        6.749, 6.753, 6.756, 6.763, 6.769, 6.772, 6.777, 6.785, 6.787, 6.789, 6.796, 6.802, 6.804, 6.809,
        6.817, 6.819, 6.82, 6.83, 6.852, 6.877, 6.905, 6.932, 6.96, 6.988, 7.014, 7.04, 7.069, 7.096,
        7.123, 7.149, 7.176, 7.202, 7.229, 7.258, 7.286, 7.313, 7.341, 7.37, 7.401, 7.435, 7.472, 7.507,
        7.543, 7.579, 7.616, 7.651, 7.688, 7.724, 7.76, 7.795, 7.831, 7.868, 7.904, 7.94, 7.975, 8.012,
        8.044, 8.09, 8.132, 8.178, 8.229, 8.277, 8.328, 8.377, 8.426, 8.475, 8.524, 8.573, 8.623, 8.673,
        8.722, 8.771, 8.82, 8.869, 8.92, 8.969, 9.017, 9.067, 9.117, 9.167, 9.216, 9.265, 9.314, 9.362,
        9.413, 9.463, 9.511, 9.561, 9.609, 9.659, 9.709, 9.759, 9.808, 9.857, 9.906, 9.956, 10.005, 10.054,
        10.104, 10.153, 10.203, 10.252, 10.302, 10.351, 10.399, 10.448, 10.498, 10.548, 10.597, 10.647,
        10.696, 10.745, 10.794, 10.844, 10.893, 10.943, 10.992, 11.042, 11.091, 11.14, 11.19, 11.239,
        11.288, 11.338, 11.387, 11.437, 11.487, 11.535, 11.584, 11.634, 11.683, 11.732, 11.781, 11.831,
        11.881, 11.93, 11.98, 12.028, 12.077, 12.127, 12.177, 12.226, 12.276, 12.325, 12.373, 12.423,
        12.473, 12.522, 12.572, 12.621, 12.67, 12.72, 12.77, 12.818, 12.868, 12.917, 12.966, 13.016,
        13.065, 13.115, 13.163, 13.213, 13.262, 13.312, 13.362, 13.41, 13.459, 13.509, 13.559, 13.608,
        13.658, 13.707, 13.756, 13.805, 13.855, 13.904, 13.953, 14.004, 14.052, 14.101, 14.151, 14.201,
        14.25, 14.3, 14.348, 14.397, 14.447, 14.497, 14.546, 14.595, 14.645, 14.694, 14.743, 14.793,
        14.841, 14.89, 14.947, 15.0
    ]
