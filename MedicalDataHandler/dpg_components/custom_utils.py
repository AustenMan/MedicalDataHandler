import dearpygui.dearpygui as dpg

def get_tag(key):
    """ Get the tag from the tag dictionary. """
    if not isinstance(key, str):
        raise ValueError("The key must be a string.")
    return dpg.get_item_user_data("tag_dict").get(key)

def get_user_data(td_key=None, tag=None):
    """ 
    Get user data from a key in the tag dictionary, or from a provided tag.
    
    Args:
        td_key (str, optional): The key in the tag dictionary to retrieve user data from. Defaults to None.
        tag (str or int, optional): The tag of the item to retrieve user data from. Defaults to None.
    """
    valid_key = isinstance(td_key, str)
    valid_tag = isinstance(tag, (str, int))
    
    if not valid_key and not valid_tag:
        raise ValueError("Either a key in the tag dictionary or a tag must be provided.")
    if valid_key and valid_tag:
        raise ValueError("Only one of key or tag should be provided.")
    
    if valid_key:
        tag = get_tag(td_key)
        valid_tag = isinstance(tag, (str, int))
        if not valid_tag:
            raise ValueError(f"Invalid tag retrieved from tag dictionary key '{td_key}'.")
    
    if valid_tag:
        return dpg.get_item_user_data(tag) if dpg.does_item_exist(tag) else None
    
    raise ValueError(f"Invalid input. Tag dictionary key must be a string, and tag must be a string or integer: td_key={td_key}, tag={tag}")

def update_viewport_and_popups(new_screen_size, current_screen_size=None):
    """
    Updates the viewport and adjusts any open popups to the new screen size.
    
    Args:
        new_screen_size (tuple): New screen dimensions (width, height).
        current_screen_size (tuple, optional): Current screen dimensions (width, height). Defaults to None.
    
    Returns:
        tuple: Width and height ratios between the new and current screen sizes.
    """
    # Update the viewport size
    dpg.configure_viewport(
        item=0,
        width=new_screen_size[0], height=new_screen_size[1],
        min_width=new_screen_size[0], min_height=new_screen_size[1],
        max_width=new_screen_size[0], max_height=new_screen_size[1]
    )
    
    # Get the width and height ratios between the new and current screen sizes
    if isinstance(current_screen_size, (tuple, list)) and len(current_screen_size) == 2:
        width_ratio = new_screen_size[0] / current_screen_size[0]
        height_ratio = new_screen_size[1] / current_screen_size[1]
        WH_ratios = (width_ratio, height_ratio)
    else:
        WH_ratios = (1.0, 1.0)
    
    # Update any open windows if the screen size has changed
    if WH_ratios != (1.0, 1.0):
        tag_dict = get_user_data(td_key="tag_dict")
        for tag in list(tag_dict.values()):
            if isinstance(tag, (int, str)) and dpg.does_item_exist(tag) and dpg.get_item_type(tag) == "mvAppItemType::mvWindowAppItem":
                prev_pos = dpg.get_item_pos(tag)
                prev_pos_percent = (prev_pos[0] / current_screen_size[0], prev_pos[1] / current_screen_size[1])
                new_pos = (round(new_screen_size[0] * prev_pos_percent[0]), round(new_screen_size[1] * prev_pos_percent[1]))
                
                prev_W, prev_H = dpg.get_item_rect_size(tag)
                new_W, new_H = min(round(prev_W * WH_ratios[0]), new_screen_size[0]), min(round(prev_H * WH_ratios[1]), new_screen_size[1])
                
                dpg.configure_item(tag, width=new_W, height=new_H, pos=new_pos)
    
    # Return the width and height ratios
    return WH_ratios

def update_font_scale(new_font_scale):
    """ 
    Updates the global font scale in Dear PyGUI. 
    
    Args:
        new_font_scale (float): New font scale value.
    
    """
    current_font_scale = dpg.get_global_font_scale()
    if current_font_scale != new_font_scale:
        dpg.set_global_font_scale(new_font_scale)

def add_custom_separator(parent_tag=None):
    """
    Adds a custom separator with spacing before and after.
    
    Args:
        parent (str or int, optional): The tag of the parent item to which the separator will be added. Defaults to None.
    """
    size_dict = get_user_data(td_key="size_dict")
    
    if parent_tag:
        dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        dpg.add_separator(parent=parent_tag)
        dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
    else:
        dpg.add_spacer(height=size_dict["spacer_height"])
        dpg.add_separator()
        dpg.add_spacer(height=size_dict["spacer_height"])

def add_custom_button(
    tag=None, label="", height=None, width=None, parent_tag=None, theme_tag=None, 
    callback=None, user_data=None, visible=True, 
    add_spacer_before=False, add_spacer_after=False, 
    add_separator_before=False, add_separator_after=False, 
    tooltip_tag=None, tooltip_text="",
):
    """
    Adds a customizable button with optional spacers, separators, tooltips, and themes.

    Args:
        tag (str or int, optional): Unique identifier for the button. Defaults to an auto-generated UUID.
        label (str, optional): Text displayed on the button. Defaults to an empty string.
        height (int, optional): Button height. Defaults to a predefined value.
        width (int, optional): Button width. Defaults to a predefined value.
        parent_tag (str or int, optional): Parent container's tag. Defaults to None.
        theme_tag (int or str, optional): Theme tag for the button. Defaults to None.
        callback (callable, optional): Function to call when the button is clicked. Defaults to None.
        user_data (any, optional): Extra data to pass to the callback. Defaults to None.
        visible (bool, optional): Whether the button is initially visible. Defaults to True.
        
        add_spacer_before (bool, optional): Insert a spacer before the button. Defaults to False.
        add_spacer_after (bool, optional): Insert a spacer after the button. Defaults to False.
        add_separator_before (bool, optional): Insert a separator before the button. Defaults to False.
        add_separator_after (bool, optional): Insert a separator after the button. Defaults to False.

        tooltip_tag (str or int, optional): Tag for tooltip text. Defaults to None.
        tooltip_text (str, optional): Text to display when hovering over the button. Defaults to an empty string.

    Returns:
        str or int: The tag of the created button.
    """
    size_dict = get_user_data(td_key="size_dict")
    
    tag = tag or dpg.generate_uuid()
    height = height or size_dict["button_height"]
    width = width or size_dict["button_width"]

    # Pre-button spacing/separators
    if add_separator_before:
        add_custom_separator(parent_tag)
    elif add_spacer_before:
        if parent_tag:
            dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        else:
            dpg.add_spacer(height=size_dict["spacer_height"])

    # Create button
    if parent_tag:
        dpg.add_button(
            tag=tag, label=label, width=width, height=height,
            callback=callback, user_data=user_data, show=visible, parent=parent_tag
        )
    else:
        dpg.add_button(
            tag=tag, label=label, width=width, height=height,
            callback=callback, user_data=user_data, show=visible
        )

    # Apply theme if provided
    if theme_tag:
        dpg.bind_item_theme(tag, theme_tag)

    # Post-button spacing/separators
    if add_separator_after:
        add_custom_separator(parent_tag)
    elif add_spacer_after:
        if parent_tag:
            dpg.add_spacer(parent=parent_tag, height=size_dict["spacer_height"])
        else:
            dpg.add_spacer(height=size_dict["spacer_height"])

    # Add tooltip if needed
    if tooltip_text or tooltip_tag:
        tooltip_tag = tooltip_tag or dpg.generate_uuid()
        with dpg.tooltip(parent=tag):
            dpg.add_text(str(tooltip_text), tag=tooltip_tag, wrap=size_dict["tooltip_width"])

    return tag

def add_custom_checkbox(
    default_value, tag=None, checkbox_label="", tooltip_text="", add_spacer_after=False):
    """
    Adds a custom checkbox with optional tooltip and spacer.
    
    Args:
        default_value (bool): The initial value of the checkbox.
        tag (str or int, optional): The unique identifier for the checkbox. Defaults to a generated UUID.
        checkbox_label (str, optional): The label displayed next to the checkbox. Defaults to an empty string.
        tooltip_text (str, optional): The tooltip text to display when hovering over the checkbox. Defaults to an empty string.
        add_spacer_after (bool, optional): Add a spacer after the checkbox. Defaults to False.
    
    Returns:
        str or int: The tag of the created checkbox.
    """
    size_dict = get_user_data(td_key="size_dict")
    tag = tag or dpg.generate_uuid()
    dpg.add_checkbox(tag=tag, default_value=bool(default_value), label=checkbox_label)
    if tooltip_text:
        with dpg.tooltip(parent=tag):
            dpg.add_text(str(tooltip_text), wrap=size_dict["tooltip_width"])
    if add_spacer_after:
        dpg.add_spacer(height=size_dict["spacer_height"])
    return tag

    
    