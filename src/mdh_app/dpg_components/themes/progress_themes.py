from __future__ import annotations


import logging
from typing import TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


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
