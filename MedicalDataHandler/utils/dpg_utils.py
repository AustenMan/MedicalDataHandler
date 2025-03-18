import os
import dearpygui.dearpygui as dpg
from typing import Any, Optional, Callable, Tuple
from pydicom.dataset import Dataset
from pydicom.dataelem import DataElement
from pydicom.sequence import Sequence
from utils.general_utils import validate_directory
from utils.dicom_utils import convert_VR_string_to_python_type

def safe_delete(item, children_only=False):
    """
    Safely delete a Dear PyGUI item or items if they exist.
    
    Args:
        item (str, int, list, tuple, or set): The DPG item(s) to delete.
        children_only (bool): If True, only delete the children of the item without deleting the item itself.
    
    Raises:
        ValueError: If `children_only` is not a boolean or `item` is not a valid type.
    """
    if not isinstance(children_only, bool):
        raise ValueError("'children_only' must be a boolean.")
    if isinstance(item, (list, tuple, set)):
        for i in item:
            safe_delete(i, children_only)
    elif isinstance(item, (str, int)):
        if dpg.does_item_exist(item):
            dpg.delete_item(item, children_only=children_only)
    else:
        raise ValueError("Item must be a string, integer, or a list/tuple/set of strings and integers.")

def get_popup_params(width_ratio=0.75, height_ratio=0.75, client_width=None, client_height=None):
    """
    Calculate the size and position of a popup window based on viewport dimensions and given ratios.
    
    Args:
        width_ratio (float): Width ratio relative to the viewport width (0.1 to 1).
        height_ratio (float): Height ratio relative to the viewport height (0.1 to 1).
        client_width (int, optional): Width of the viewport client area. Defaults to the current viewport width.
        client_height (int, optional): Height of the viewport client area. Defaults to the current viewport height.
    
    Returns:
        Tuple[int, int, Tuple[int, int]]: The popup width, height, and position.
    
    Raises:
        ValueError: If arguments are of invalid types or if viewport dimensions cannot be determined.
    """
    if not isinstance(width_ratio, (int, float)) or not isinstance(height_ratio, (int, float)):
        raise ValueError("Width and height ratios must be integers or floats.")
    if not isinstance(client_width, (int, type(None))) or not isinstance(client_height, (int, type(None))):
        raise ValueError("Client width and height must be integers or None.")
    if (isinstance(client_width, type(None)) or isinstance(client_height, type(None))) and not dpg.is_dearpygui_running():
        raise ValueError("Dear PyGUI must be running to automatically retrieve the viewport client width and height.")
    
    width_ratio = max(0.1, min(1, width_ratio))
    height_ratio = max(0.1, min(1, height_ratio))
    
    if client_width is None:
        client_width = dpg.get_viewport_client_width()
    if client_height is None:
        client_height = dpg.get_viewport_client_height()
    
    popup_width = round(client_width * width_ratio)
    popup_height = round(client_height * height_ratio)
    
    popup_x_pos = (client_width - popup_width) // 2
    popup_y_pos = (client_height - popup_height) // 2
    
    popup_pos = (popup_x_pos, popup_y_pos)
    
    return popup_width, popup_height, popup_pos

def verify_input_directory(directory, input_tag, error_tag):
    """
    Verifies if the directory specified in an input field is valid.
    
    Args:
        directory (str): The directory to validate.
        input_tag (int, str): The tag for the Dear PyGUI input text item.
        error_tag (int, str, None): The tag for the error message text item.
    
    Returns:
        bool: True if the directory is valid, False otherwise.
    
    Raises:
        ValueError: If tags are invalid or if input directory validation fails.
    """
    if not isinstance(input_tag, (int, str)) or not dpg.does_item_exist(input_tag) or not dpg.get_item_type(input_tag) == "mvAppItemType::mvInputText":
        print(f"DPG Item Type: {dpg.get_item_type(input_tag)}")
        raise ValueError(f"Input tag must be a valid string or integer tag for an existing DearPyGui input text item. Received input_tag: {input_tag}")
    if (not isinstance(error_tag, (int, str)) or not dpg.does_item_exist(error_tag) or not dpg.get_item_type(error_tag) == "mvAppItemType::mvText") and error_tag is not None:
        print(f"DPG Item Type: {dpg.get_item_type(error_tag)}")
        raise ValueError(f"Error tag must be None, or a valid string or integer tag for an existing DearPyGui text item. Received error_tag: {error_tag}")
    
    input_filename = dpg.get_value(input_tag)
    filepath = os.path.join(directory, input_filename)
    is_valid, abs_path, message = validate_directory(filepath)
    if not is_valid:
        dpg.configure_item(error_tag, default_value=f"\t\t{message}", color=(192, 57, 43))  # Red color for errors
        return False
    else:
        if dpg.does_item_exist(input_tag):
            dpg.set_value(input_tag, input_filename)
            dpg.configure_item(error_tag, default_value=f"\t\t{message}", color=(39, 174, 96))  # Green color for success
        return True

def add_data_to_tree(
    data: Any,
    label: str = "",
    parent: Optional[int] = None,
    text_wrap_width: int = -1,
    text_color_one: Tuple[int, int, int] = (30, 200, 120),
    text_color_two: Tuple[int, int, int] = (140, 220, 250),
    dcm_viewing_callback: Optional[Callable] = None,
    return_callback: Optional[Callable] = None,
    max_depth: int = 10,
    current_depth: int = 0
    ) -> None:
    
    """
    Recursively adds data to a Dear PyGUI tree structure.
    
    Args:
        data (Any): The data to display. Can be a dict, list, object, or base data type.
        label (str): Label for the current data node.
        parent (int, optional): The parent node in the GUI.
        text_wrap_width (int): Width for text wrapping. Defaults to -1 (no wrapping).
        text_color_one (Tuple[int, int, int]): RGB color for the labels.
        text_color_two (Tuple[int, int, int]): RGB color for the values.
        dcm_viewing_callback (Callable, optional): Callback function when a `.dcm` file is clicked.
        return_callback (Callable, optional): Callback for processing `.dcm` file data.
        max_depth (int): Maximum recursion depth. Defaults to 10.
        current_depth (int): Current recursion depth. Defaults to 0.
    """
    
    if current_depth > max_depth:
        dpg.add_text(default_value=f"{label}: (Max recursion depth reached)", parent=parent)
        return
    
    def add_empty_value(parent, key_or_label):
        with dpg.group(parent=parent):
            dpg.add_text(default_value=f"{key_or_label}:", wrap=text_wrap_width, bullet=True, color=text_color_one)
            dpg.add_text(default_value="\tN/A", wrap=text_wrap_width, color=text_color_two)
    
    if isinstance(data, dict):
        dpg.add_tree_node(label=label if label else "dict", parent=parent)
        new_parent = dpg.last_item()
        for key, value in data.items():
            if value:
                add_data_to_tree(
                    data=value, label=str(key), parent=new_parent, text_wrap_width=text_wrap_width, 
                    text_color_one=text_color_one, text_color_two=text_color_two, 
                    dcm_viewing_callback=dcm_viewing_callback, return_callback=return_callback,
                    max_depth=max_depth, current_depth=current_depth+1
                )
            else:
                add_empty_value(new_parent, key)
    elif isinstance(data, list):
        dpg.add_tree_node(label=label if label else "list", parent=parent)
        new_parent = dpg.last_item()
        if all([isinstance(item, (str, int, float, bool, type(None))) for item in data]):
            dpg.add_text(default_value=str(data), parent=new_parent, wrap=text_wrap_width, color=text_color_two)
        else:
            for idx, item in enumerate(data):
                item_label = f"Item #{str(idx)}"
                if item:
                    add_data_to_tree(
                        data=item, label=item_label, parent=new_parent, text_wrap_width=text_wrap_width, 
                        text_color_one=text_color_one, text_color_two=text_color_two, 
                        dcm_viewing_callback=dcm_viewing_callback, return_callback=return_callback,
                        max_depth=max_depth, current_depth=current_depth+1
                    )
                else:
                    add_empty_value(new_parent, item_label)
    elif hasattr(data, "__dict__"):
        # Object with attributes
        for key, value in vars(data).items():
            if value:
                add_data_to_tree(
                    data=value, label=str(key), parent=parent, text_wrap_width=text_wrap_width, 
                    text_color_one=text_color_one, text_color_two=text_color_two, 
                    dcm_viewing_callback=dcm_viewing_callback, return_callback=return_callback,
                    max_depth=max_depth, current_depth=current_depth+1
                )
            else:
                add_empty_value(parent, key)
    else:
        with dpg.group(parent=parent):
            dpg.add_text(default_value=f"{label}:", wrap=text_wrap_width, bullet=True, color=text_color_one)
            if data:
                data_str = str(data)
                if data_str.endswith(".dcm") and callable(dcm_viewing_callback):
                    dpg.add_button(label=data_str, height=25, indent=8, callback=dcm_viewing_callback, user_data=return_callback if callable(return_callback) else None)
                else:
                    dpg.add_text(default_value=f"\t{data_str}", wrap=text_wrap_width, color=text_color_two)
            else:
                dpg.add_text(default_value="\tN/A", wrap=text_wrap_width, color=text_color_two)

def build_userdata(key: Any = "", VR: Any = None, value: Any = None) -> dict:
    """Helper to create a uniform user_data dictionary."""
    return {"key": key, "VR": VR, "value": value}

def add_dicom_dataset_to_tree(
    data: Any,
    label: str = "",
    parent: Optional[int] = None,
    text_wrap_width: int = -1,
    text_color_one: Tuple[int, int, int] = (30, 200, 120),
    text_color_two: Tuple[int, int, int] = (140, 220, 250),
    max_depth: int = 10,
    current_depth: int = 0
) -> None:
    """
    Recursively adds DICOM data to a Dear PyGUI tree structure.
    
    Args:
        data (Any): The DICOM data to display. Can be a Dataset, DataElement, or base data type.
        label (str): Label for the current data node.
        parent (Optional[int]): Parent node in the GUI.
        text_wrap_width (int): Width for text wrapping.
        text_color_one (Tuple[int, int, int]): RGB color for the labels.
        text_color_two (Tuple[int, int, int]): RGB color for the values.
        max_depth (int): Maximum recursion depth.
        current_depth (int): Current recursion depth.
    
    Notes for future modification:
        v-ein — 03/20/2024 2:21 AM
            Yes, the implementation of add_filter_set looks as if it only hides immediate children, without passing the filter down the tree.
            So to filter the tree, you need to add add_filter_set on every level, and then somehow pass the value to all those filters... Like keeping their IDs in a list and then going through that list, or going directly through the tree (e.g. you can store the ID in user_data). Might still be faster than implementing your own filter (because for your own, you'll have to iterate through the entire tree anyway). However, with your own filter you can implement your own filtering rules, so it depends. 
        v-ein — 03/20/2024 2:29 AM
            The code you posted creates the entire tree at the start, with tree nodes in the closed state. I'd suggest that you only create children when a tree node is expanded - see add_item_toggled_open_handler. You can attach the list or dict of supposed child values to the tree node via user_data, and when it gets expanded, just pick up user_data and build children from there.
            Note: the user_data argument in add_item_toggled_open_handler receives user data for the handler itself, not for the tree node. Use get_item_user_data to retrieve it from the tree node.
    """
    
    if current_depth > max_depth:
        dpg.add_text(
            default_value=f"{label}: (Max recursion depth reached)",
            parent=parent,
            user_data=build_userdata(key=label, VR=None, value="(Max recursion depth reached)")
        )
        return
    
    def add_empty_value(parent, key_or_label):
        with dpg.group(parent=parent):
            dpg.add_text(
                default_value=f"{key_or_label}:",
                wrap=text_wrap_width,
                bullet=True,
                color=text_color_one,
                user_data=build_userdata(key=key_or_label, VR=None, value="")  # No value provided
            )
            dpg.add_text(
                default_value="\tN/A",
                wrap=text_wrap_width,
                color=text_color_two,
                user_data=build_userdata(key=key_or_label, VR=None, value="N/A")
            )
    
    # Handle pydicom Dataset
    if isinstance(data, Dataset):
        if label:
            new_parent = dpg.add_tree_node(
                label=label,
                parent=parent,
                user_data=build_userdata(key=label, VR=None, value=None)
            )
        else:
            new_parent = parent
        for elem in data:
            tag = elem.tag
            tag_name = elem.name if elem.name != "Unknown" else f"Private Tag {tag}"
            tag_label = f"{tag_name} ({tag})"
            add_dicom_dataset_to_tree(
                data=elem,
                label=tag_label,
                parent=new_parent,
                text_wrap_width=text_wrap_width,
                text_color_one=text_color_one,
                text_color_two=text_color_two,
                max_depth=max_depth,
                current_depth=current_depth + 1
            )
    # Handle pydicom DataElement
    elif isinstance(data, DataElement):
        new_parent = dpg.add_tree_node(
            label=label if label else "DataElement",
            parent=parent,
            user_data=build_userdata(key=data.tag, VR=data.VR, value=data.value)
        )
        if data.value is not None:
            tag = data.tag
            tag_name = data.name if data.name != "Unknown" else f"Private Tag {tag}"
            value = data.value
            tag_VR = data.VR
            tag_VR_type = convert_VR_string_to_python_type(str(data.VR))
            if isinstance(value, Dataset):
                add_dicom_dataset_to_tree(
                    data=value,
                    label="Value",
                    parent=new_parent,
                    text_wrap_width=text_wrap_width,
                    text_color_one=text_color_one,
                    text_color_two=text_color_two,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )
            elif isinstance(value, Sequence):
                for idx, item in enumerate(value):
                    item_label = f"Item #{idx}"
                    add_dicom_dataset_to_tree(
                        data=item,
                        label=item_label,
                        parent=new_parent,
                        text_wrap_width=text_wrap_width,
                        text_color_one=text_color_one,
                        text_color_two=text_color_two,
                        max_depth=max_depth,
                        current_depth=current_depth + 1
                    )
            elif isinstance(value, (list, tuple)):
                dpg.add_text(
                    default_value=f"Value: {value}",
                    parent=new_parent,
                    wrap=text_wrap_width,
                    color=text_color_two,
                    user_data=build_userdata(key=tag, VR=tag_VR, value=value)
                )
                with dpg.tooltip(parent=dpg.last_item()):
                    dpg.add_text(
                        default_value=f"VR: {tag_VR} ---> Value Representation: {tag_VR_type}",
                        wrap=text_wrap_width,
                        color=text_color_two,
                        user_data=build_userdata(key="VR Info", VR=tag_VR, value=tag_VR_type)
                    )
            else:
                dpg.add_text(
                    default_value=f"Value: {value}",
                    parent=new_parent,
                    wrap=text_wrap_width,
                    color=text_color_two,
                    user_data=build_userdata(key=tag, VR=tag_VR, value=value)
                )
                with dpg.tooltip(parent=dpg.last_item()):
                    dpg.add_text(
                        default_value=f"VR: {tag_VR} ---> Value Representation: {tag_VR_type}",
                        wrap=text_wrap_width,
                        color=text_color_two,
                        user_data=build_userdata(key="VR Info", VR=tag_VR, value=tag_VR_type)
                    )
        else:
            add_empty_value(new_parent, "Value")
    # Handle pydicom Sequence
    elif isinstance(data, Sequence):
        new_parent = dpg.add_tree_node(
            label=label if label else "Sequence",
            parent=parent,
            user_data=build_userdata(key=label if label else "Sequence", VR=None, value=None)
        )
        for idx, item in enumerate(data):
            item_label = f"Item #{idx}"
            add_dicom_dataset_to_tree(
                data=item,
                label=item_label,
                parent=new_parent,
                text_wrap_width=text_wrap_width,
                text_color_one=text_color_one,
                text_color_two=text_color_two,
                max_depth=max_depth,
                current_depth=current_depth + 1
            )
    # Handle dictionary
    elif isinstance(data, dict):
        new_parent = dpg.add_tree_node(
            label=label if label else "dict",
            parent=parent,
            user_data=build_userdata(key=label if label else "dict", VR=None, value=None)
        )
        for key, value in data.items():
            if value:
                add_dicom_dataset_to_tree(
                    data=value,
                    label=str(key),
                    parent=new_parent,
                    text_wrap_width=text_wrap_width,
                    text_color_one=text_color_one,
                    text_color_two=text_color_two,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )
            else:
                add_empty_value(new_parent, key)
    # Handle list
    elif isinstance(data, list):
        new_parent = dpg.add_tree_node(
            label=label if label else "list",
            parent=parent,
            user_data=build_userdata(key=label if label else "list", VR=None, value=None)
        )
        for idx, item in enumerate(data):
            item_label = f"Item #{idx}"
            if item:
                add_dicom_dataset_to_tree(
                    data=item,
                    label=item_label,
                    parent=new_parent,
                    text_wrap_width=text_wrap_width,
                    text_color_one=text_color_one,
                    text_color_two=text_color_two,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )
            else:
                add_empty_value(new_parent, item_label)
    # Fallback for base types
    else:
        with dpg.group(parent=parent):
            dpg.add_text(
                default_value=f"{label}:",
                wrap=text_wrap_width,
                bullet=True,
                color=text_color_one,
                user_data=build_userdata(key=label, VR=None, value=str(data))
            )
            dpg.add_text(
                default_value=f"\t{str(data)}",
                wrap=text_wrap_width,
                color=text_color_two,
                user_data=build_userdata(key=label, VR=None, value=str(data))
            )

def modify_table_rows(table_tag, delete=False, show=None):
    """
    Modifies existing rows in a Dear PyGUI table.
    
    Args:
        table_tag (str, int): The tag of the table to modify.
        delete (bool): If True, deletes the rows. Defaults to False.
        show (bool): If specified, shows or hides the rows.
    
    Raises:
        ValueError: If `delete` and `show` are both None or if invalid types are provided.
        ValueError: If the table tag does not exist.
    """
    if not isinstance(delete, (bool, type(None))) or not isinstance(show, (bool, type(None))):
        raise ValueError("Cannot modify the table rows, 'delete' and 'show' must be booleans or None.")
    elif not delete and show is None:
        raise ValueError("Cannot modify the table rows, either 'delete' or 'show' must be specified.")
    
    if not isinstance(table_tag, (str, int)) or not dpg.does_item_exist(table_tag):
        print(f"Cannot modify table rows, table tag '{table_tag}' does not exist, but user requested modification with delete={delete} and show={show}.")
        return
    
    table_tags = dpg.get_item_children(table_tag)
    if table_tags and len(table_tags) > 1:
        for row_tag in table_tags[1]:
            if delete:
                dpg.delete_item(row_tag)
            elif show:
                dpg.configure_item(row_tag, show=show)

def modify_table_cols(table_tag, delete=False, show=None):
    """
    Modifies existing columns in a Dear PyGUI table.
    
    Args:
        table_tag (str, int): The tag of the table to modify.
        delete (bool): If True, deletes the columns. Defaults to False.
        show (bool): If specified, shows or hides the columns.
    
    Raises:
        ValueError: If `delete` and `show` are both None or if invalid types are provided.
        ValueError: If the table tag does not exist.
    """
    if not isinstance(delete, (bool, type(None))) or not isinstance(show, (bool, type(None))):
        raise ValueError("Cannot modify the table columns, 'delete' and 'show' must be booleans or None.")
    elif not delete and show is None:
        raise ValueError("Cannot modify the table columns, either 'delete' or 'show' must be specified.")
    
    if not isinstance(table_tag, (str, int)) or not dpg.does_item_exist(table_tag):
        print(f"Cannot modify table columns, table tag '{table_tag}' does not exist, but user requested modification with delete={delete} and show={show}.")
        return
    
    table_tags = dpg.get_item_children(table_tag)
    if table_tags and len(table_tags[0]) > 2:
        for col_tag in table_tags[0][2:]:
            if delete:
                dpg.delete_item(col_tag)
            elif show:
                dpg.configure_item(col_tag, show=show)

def match_child_tags(parent_tag, match_criteria=None):
    """
    Find all child tags of a given parent item that match the specified criteria, including all levels of nested children.
    
    Args:
        parent_tag (str, int): The tag of the parent item.
        match_criteria (str or Callable, optional): 
            A string to match child tags containing the substring.
            A callable function to match tags.
    
    Returns:
        list: A list of tags that match the criteria.
    """
    def get_children_recursively(tag):
        """
        Recursively get all child tags for a given tag.
        """
        children_ids = dpg.get_item_children(tag)
        all_children_ids = sum(children_ids.values(), [])
        
        children_tags = []
        for child_id in all_children_ids:
            children_tags.append(child_id)
            children_tags.extend(get_children_recursively(child_id))
        return children_tags
    
    if not dpg.does_item_exist(parent_tag):
        return []
    
    # Retrieve all child tags recursively and flatten the list
    flattened_children_tags = get_children_recursively(parent_tag)
    
    if not match_criteria:
        return flattened_children_tags
    
    if isinstance(match_criteria, str):
        matching_tags = [tag if tag and isinstance(tag, str) else dpg.get_item_alias(tag) for tag in flattened_children_tags if (isinstance(tag, str) and match_criteria.lower() in tag.lower()) or (isinstance(tag, int) and match_criteria.lower() in dpg.get_item_alias(tag).lower())]
    elif callable(match_criteria):
        matching_tags = [tag for tag in flattened_children_tags if match_criteria(tag)]
    else:
        matching_tags = []
    
    return matching_tags


