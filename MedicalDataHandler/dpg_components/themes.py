import dearpygui.dearpygui as dpg

def get_global_theme():
    """
    Creates a custom global theme for the DearPyGUI interface.
    
    Notes:
        - The theme modifies text, background, buttons, and other UI elements.
        
    Returns:
        int: The theme ID.
    """
    # Get the theme
    desired_theme = _build_modern_theme_dict()
    
    # Modify a few theme colors
    with dpg.theme() as custom_theme:
        with dpg.theme_component(dpg.mvAll):
            for component, color in desired_theme.items():
                dpg.add_theme_color(getattr(dpg, f"{component}"), color, category=dpg.mvThemeCat_Core)
    return custom_theme

def get_colored_button_theme(color_button, color_text=None):
    """
    Creates a theme for a button with custom colors.
    
    Args:
        color_button (tuple): RGB color for the button.
        color_text (tuple, optional): RGB color for the text. Defaults to None.
    
    Returns:
        int: The theme ID.
    """
    if not isinstance(color_button, (list, tuple)) or len(color_button) != 3:
        raise ValueError("The button color must be a tuple or list of length 3 (RGB).")
    if color_text is not None and (not isinstance(color_text, (list, tuple)) or len(color_text) != 3):
        raise ValueError("The text color must be None, or a tuple or list of length 3 (RGB).")
    
    general_color = [c for c in color_button] + [255]
    hover_color = [c + 20 for c in color_button] + [255]
    active_color = [c + 40 for c in color_button] + [255]
    
    with dpg.theme() as generic_button_theme:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, general_color, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover_color, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active_color, category=dpg.mvThemeCat_Core)
            if color_text is not None:
                dpg.add_theme_color(dpg.mvThemeCol_Text, color_text, category=dpg.mvThemeCat_Core)
    return generic_button_theme

def get_hidden_button_theme(color_text=None):
    """
    Creates a theme for a hidden button (blends with the background).
    
    Args:
        color_text (tuple, optional): RGB color for the text. Defaults to None.
    
    Returns:
        int: The theme ID.
    """
    if color_text is not None and (not isinstance(color_text, (list, tuple)) or len(color_text) != 3):
        raise ValueError("The text color must be a tuple or list of length 3 (RGB).")
    
    bg_color = _build_modern_theme_dict().get("mvThemeCol_WindowBg", (60, 60, 60))[:3]
    color_button = (bg_color[0], bg_color[1], bg_color[2], 255)
    with dpg.theme() as hidden_button_theme:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, color_button, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, color_button, category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, color_button, category=dpg.mvThemeCat_Core)
    return hidden_button_theme

def get_pbar_theme(color=(39, 139, 34, 255)):
    """
    Creates a theme for a progress bar with custom color.
    
    Args:
        color (tuple): RGBA color for the progress bar. Defaults to green.
    
    Returns:
        int: The theme ID.
    """
    with dpg.theme() as progressbar_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, color, category=dpg.mvThemeCat_Core)
    return progressbar_theme

def get_table_cell_spacing_theme(x, y):
    """
    Configures cell spacing for a table.
    
    Args:
        x (int): Horizontal spacing value.
        y (int): Vertical spacing value.
    
    Returns:
        int: The theme ID.
    
    Raises:
        ValueError: If `x` or `y` are not integers or are negative.
    """
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("The spacing values must be integers.")
    if x < 0 or y < 0:
        raise ValueError("The spacing values cannot be negative.")
    with dpg.theme() as table_cell_theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, x=x, y=y, category=dpg.mvThemeCat_Core)
    return table_cell_theme

def _build_modern_theme_dict():
    """ Sets the DearPyGUI theme to a modern style. """
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
    "mvThemeCol_TitleBg": (39, 70, 116),  # Toned down blue
    "mvThemeCol_TitleBgActive": (59, 103, 173),  # Toned down blue
    "mvThemeCol_TitleBgCollapsed": (53, 59, 69),
    "mvThemeCol_MenuBarBg": (53, 59, 69),
    "mvThemeCol_ScrollbarBg": (53, 59, 69),
    "mvThemeCol_ScrollbarGrab": (76, 82, 92),
    "mvThemeCol_ScrollbarGrabHovered": (92, 99, 110),
    "mvThemeCol_ScrollbarGrabActive": (112, 120, 130),
    "mvThemeCol_CheckMark": (84, 158, 255),  # Toned down blue
    "mvThemeCol_SliderGrab": (84, 158, 255),  # Toned down blue
    "mvThemeCol_SliderGrabActive": (97, 171, 255),  # Toned down blue
    "mvThemeCol_Button": (39, 70, 116),  # Toned down blue
    "mvThemeCol_ButtonHovered": (59, 103, 173),  # Toned down blue
    "mvThemeCol_ButtonActive": (22, 40, 65),  # Toned down blue
    "mvThemeCol_Header": (39, 70, 116),  # Toned down blue
    "mvThemeCol_HeaderHovered": (59, 103, 173),  # Toned down blue
    "mvThemeCol_HeaderActive": (84, 158, 255),  # Toned down blue
    "mvThemeCol_Separator": (110, 120, 130),
    "mvThemeCol_SeparatorHovered": (130, 136, 146),
    "mvThemeCol_SeparatorActive": (150, 155, 165),
    "mvThemeCol_ResizeGrip": (255, 255, 255, 26),
    "mvThemeCol_ResizeGripHovered": (255, 255, 255, 67),
    "mvThemeCol_ResizeGripActive": (255, 255, 255, 112),
    "mvThemeCol_Tab": (39, 70, 116),  # Toned down blue
    "mvThemeCol_TabHovered": (59, 103, 173),  # Toned down blue
    "mvThemeCol_TabActive": (84, 158, 255),  # Toned down blue
    "mvThemeCol_TabUnfocused": (33, 37, 43),
    "mvThemeCol_TabUnfocusedActive": (53, 59, 69),
    "mvThemeCol_DockingPreview": (84, 158, 255, 70),  # Toned down blue
    "mvThemeCol_DockingEmptyBg": (39, 70, 116),  # Toned down blue
    "mvThemeCol_PlotLines": (255, 255, 255),
    "mvThemeCol_PlotLinesHovered": (255, 255, 255, 110),
    "mvThemeCol_PlotHistogram": (255, 255, 255),
    "mvThemeCol_PlotHistogramHovered": (255, 255, 255, 110),
    "mvThemeCol_TableHeaderBg": (39, 70, 116),  # Toned down blue
    "mvThemeCol_TableBorderStrong": (110, 120, 130),
    "mvThemeCol_TableBorderLight": (78, 84, 95),
    "mvThemeCol_TableRowBg": (60, 60, 60),
    "mvThemeCol_TableRowBgAlt": (70, 70, 70),
    "mvThemeCol_TextSelectedBg": (84, 158, 255),  # Toned down blue
    "mvThemeCol_DragDropTarget": (255, 255, 255),
    "mvThemeCol_NavHighlight": (84, 158, 255),  # Toned down blue
    "mvThemeCol_NavWindowingHighlight": (255, 255, 255, 80),
    "mvThemeCol_NavWindowingDimBg": (255, 255, 255, 20),
    "mvThemeCol_ModalWindowDimBg": (0, 0, 0, 35)
    }

