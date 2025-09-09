from __future__ import annotations


import logging
from typing import Dict, Tuple, TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    pass


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

