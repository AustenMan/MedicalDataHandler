from __future__ import annotations


import logging
from typing import Union, Tuple, List, Optional, TYPE_CHECKING


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.themes.theme_manager import _build_modern_theme_dict


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


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
