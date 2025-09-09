from __future__ import annotations


import logging
from typing import Dict, Tuple, TYPE_CHECKING


import dearpygui.dearpygui as dpg


if TYPE_CHECKING:
    pass

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
