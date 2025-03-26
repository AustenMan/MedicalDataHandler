import logging
import dearpygui.dearpygui as dpg
from typing import Dict, List, Tuple, Union, Optional

logger = logging.getLogger(__name__)

def get_global_theme() -> int:
    """
    Create and return a custom global theme for the DearPyGUI interface.

    This theme adjusts text, background, buttons, and other UI elements.

    Returns:
        The theme ID.
    """
    desired_theme: Dict[str, Tuple[int, ...]] = _build_modern_theme_dict()
    with dpg.theme() as custom_theme:
        with dpg.theme_component(dpg.mvAll):
            for component, color in desired_theme.items():
                dpg.add_theme_color(getattr(dpg, f"{component}"), color, category=dpg.mvThemeCat_Core)
    return custom_theme

def get_colored_button_theme(
    color_button: Union[Tuple[int, int, int], List[int]],
    color_text: Optional[Union[Tuple[int, int, int], List[int]]] = None
) -> int:
    """
    Create and return a theme for a button with custom colors.

    Args:
        color_button: A tuple or list of three integers (RGB) for the button color.
        color_text: Optional tuple or list of three integers (RGB) for the text color.

    Returns:
        The theme ID.

    Raises:
        ValueError: If the provided colors are not in the correct format.
    """
    if not isinstance(color_button, (list, tuple)) or len(color_button) != 3:
        raise ValueError(f"The button color must be a tuple or list of length 3 (RGB); received: {color_button}")
    if color_text is not None and (not isinstance(color_text, (list, tuple)) or len(color_text) != 3):
        raise ValueError(f"The text color must be None, or a tuple/list of length 3 (RGB); received: {color_text}")

    general_color: List[int] = list(color_button) + [255]
    hover_color: List[int] = [c + 20 for c in color_button] + [255]
    active_color: List[int] = [c + 40 for c in color_button] + [255]

    with dpg.theme() as generic_button_theme:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, general_color, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover_color, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active_color, category=dpg.mvThemeCat_Core)
            if color_text is not None:
                dpg.add_theme_color(dpg.mvThemeCol_Text, color_text, category=dpg.mvThemeCat_Core)
    return generic_button_theme

def get_hidden_button_theme(
    color_text: Optional[Union[Tuple[int, int, int], List[int]]] = None
) -> int:
    """
    Create and return a theme for a hidden button that blends with the background.

    Args:
        color_text: Optional RGB color for the text as a tuple or list of three integers.

    Returns:
        The theme ID.

    Raises:
        ValueError: If color_text is provided but is not a tuple/list of length 3.
    """
    if color_text is not None and (not isinstance(color_text, (list, tuple)) or len(color_text) != 3):
        raise ValueError(f"The text color must be a tuple or list of length 3 (RGB); received: {color_text}")

    bg_color: Tuple[int, ...] = _build_modern_theme_dict().get("mvThemeCol_WindowBg", (60, 60, 60))[:3]
    color_button: Tuple[int, int, int, int] = (bg_color[0], bg_color[1], bg_color[2], 255)
    with dpg.theme() as hidden_button_theme:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, color_button, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, color_button, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, color_button, category=dpg.mvThemeCat_Core)
    return hidden_button_theme

def get_pbar_theme(complete: bool = False, terminated_early: bool = False) -> int:
    """
    Create and return a theme for a progress bar with a custom color based on its state.

    Args:
        complete: If True, progress is complete and a "complete" color is used.
        terminated_early: If True, a "terminated early" color is used.

    Returns:
        The theme ID.
    """
    # Terminated early (red), completed (green), or in progress (blue)
    if terminated_early:
        color = (178, 34, 34, 255)
    elif complete:
        color = (39, 139, 34, 255)
    else:
        color = (100, 149, 237, 255)

    with dpg.theme() as progressbar_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, color, category=dpg.mvThemeCat_Core)
    return progressbar_theme

def get_table_cell_spacing_theme(x: int, y: int) -> int:
    """
    Create and return a theme that configures cell spacing for a table.

    Args:
        x: Horizontal spacing value.
        y: Vertical spacing value.

    Returns:
        The theme ID.

    Raises:
        ValueError: If x or y are not integers or are negative.
    """
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError(f"Spacing values must be integers; received: x={x}, y={y}")
    if x < 0 or y < 0:
        raise ValueError(f"Spacing values cannot be negative; received: x={x}, y={y}")
    with dpg.theme() as table_cell_theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, x=x, y=y, category=dpg.mvThemeCat_Core)
    return table_cell_theme

def _build_modern_theme_dict() -> Dict[str, Tuple[int, ...]]:
    """
    Build and return a dictionary of modern theme colors for the DearPyGUI interface.

    Returns:
        A dictionary mapping theme color identifiers to their RGB(A) values.
    """
    return {
    "mvThemeCol_Text": (240, 240, 240),
    "mvThemeCol_TextDisabled": (128, 128, 128),
    "mvThemeCol_WindowBg": (60, 60, 60),
    "mvThemeCol_ChildBg": (60, 60, 60),
    "mvThemeCol_PopupBg": (60, 60, 60),
    "mvThemeCol_Border": (110, 110, 110),
    "mvThemeCol_BorderShadow": (0, 0, 0, 0),
    "mvThemeCol_FrameBg": (100, 100, 100),
    "mvThemeCol_FrameBgHovered": (105, 105, 105),
    "mvThemeCol_FrameBgActive": (130, 130, 130),
    "mvThemeCol_TitleBg": (39, 70, 116),
    "mvThemeCol_TitleBgActive": (59, 103, 173),
    "mvThemeCol_TitleBgCollapsed": (53, 59, 69),
    "mvThemeCol_MenuBarBg": (53, 59, 69),
    "mvThemeCol_ScrollbarBg": (53, 59, 69),
    "mvThemeCol_ScrollbarGrab": (76, 82, 92),
    "mvThemeCol_ScrollbarGrabHovered": (92, 99, 110),
    "mvThemeCol_ScrollbarGrabActive": (112, 120, 130),
    "mvThemeCol_CheckMark": (84, 158, 255),
    "mvThemeCol_SliderGrab": (84, 158, 255),
    "mvThemeCol_SliderGrabActive": (97, 171, 255),
    "mvThemeCol_Button": (39, 70, 116),
    "mvThemeCol_ButtonHovered": (59, 103, 173),
    "mvThemeCol_ButtonActive": (22, 40, 65),
    "mvThemeCol_Header": (39, 70, 116),
    "mvThemeCol_HeaderHovered": (59, 103, 173),
    "mvThemeCol_HeaderActive": (84, 158, 255),
    "mvThemeCol_Separator": (110, 120, 130),
    "mvThemeCol_SeparatorHovered": (130, 136, 146),
    "mvThemeCol_SeparatorActive": (150, 155, 165),
    "mvThemeCol_ResizeGrip": (255, 255, 255, 26),
    "mvThemeCol_ResizeGripHovered": (255, 255, 255, 67),
    "mvThemeCol_ResizeGripActive": (255, 255, 255, 112),
    "mvThemeCol_Tab": (39, 70, 116),
    "mvThemeCol_TabHovered": (59, 103, 173),
    "mvThemeCol_TabActive": (84, 158, 255),
    "mvThemeCol_TabUnfocused": (33, 37, 43),
    "mvThemeCol_TabUnfocusedActive": (53, 59, 69),
    "mvThemeCol_DockingPreview": (84, 158, 255, 70),
    "mvThemeCol_DockingEmptyBg": (39, 70, 116),
    "mvThemeCol_PlotLines": (255, 255, 255),
    "mvThemeCol_PlotLinesHovered": (255, 255, 255, 110),
    "mvThemeCol_PlotHistogram": (255, 255, 255),
    "mvThemeCol_PlotHistogramHovered": (255, 255, 255, 110),
    "mvThemeCol_TableHeaderBg": (39, 70, 116),
    "mvThemeCol_TableBorderStrong": (110, 120, 130),
    "mvThemeCol_TableBorderLight": (78, 84, 95),
    "mvThemeCol_TableRowBg": (60, 60, 60),
    "mvThemeCol_TableRowBgAlt": (70, 70, 70),
    "mvThemeCol_TextSelectedBg": (84, 158, 255),
    "mvThemeCol_DragDropTarget": (255, 255, 255),
    "mvThemeCol_NavHighlight": (84, 158, 255),
    "mvThemeCol_NavWindowingHighlight": (255, 255, 255, 80),
    "mvThemeCol_NavWindowingDimBg": (255, 255, 255, 20),
    "mvThemeCol_ModalWindowDimBg": (0, 0, 0, 35)
    }

