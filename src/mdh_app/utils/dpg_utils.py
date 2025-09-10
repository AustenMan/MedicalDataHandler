from __future__ import annotations


import logging
from os.path import join
from typing import TYPE_CHECKING, Any, Optional, Callable, Tuple, Union, List, Set


import dearpygui.dearpygui as dpg
from pydicom.dataset import Dataset
from pydicom.dataelem import DataElement
from pydicom.sequence import Sequence
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm.exc import DetachedInstanceError, UnmappedInstanceError


from mdh_app.utils.general_utils import validate_directory
from mdh_app.utils.dicom_utils import convert_VR_string_to_python_type


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def safe_delete(
    item: Union[str, int, List[Any], Tuple[Any, ...], Set[Any]],
    children_only: bool = False
) -> None:
    """Safely delete Dear PyGUI item(s) if they exist."""
    if not isinstance(children_only, bool):
        raise ValueError(f"'children_only' must be a boolean. Received: {children_only}")
    if isinstance(item, (list, tuple, set)):
        for i in item:
            safe_delete(i, children_only)
    elif isinstance(item, (str, int)):
        if dpg.does_item_exist(item):
            dpg.delete_item(item, children_only=children_only)
    else:
        raise ValueError("Item must be a string, integer, or a list/tuple/set of strings and integers.")


def get_popup_params(
    width_ratio: float = 0.75,
    height_ratio: float = 0.75,
    client_width: Optional[int] = None,
    client_height: Optional[int] = None
) -> Tuple[int, int, Tuple[int, int]]:
    """Calculate popup window size and position based on viewport dimensions."""
    if not isinstance(width_ratio, (int, float)) or not isinstance(height_ratio, (int, float)):
        raise ValueError(f"Width and height ratios must be numeric. Received: width_ratio={width_ratio}, height_ratio={height_ratio}")
    if not isinstance(client_width, (int, type(None))) or not isinstance(client_height, (int, type(None))):
        raise ValueError("Client width and height must be integers or None.")
    if (client_width is None or client_height is None) and not dpg.is_dearpygui_running():
        raise ValueError("Dear PyGUI must be running to automatically retrieve viewport dimensions.")

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
    return popup_width, popup_height, (popup_x_pos, popup_y_pos)


def verify_input_directory(
    directory: str,
    input_tag: Union[str, int],
    error_tag: Optional[Union[str, int]]
) -> bool:
    """Verify if directory specified in input field is valid."""
    if not isinstance(input_tag, (str, int)) or not dpg.does_item_exist(input_tag) or dpg.get_item_type(input_tag) != "mvAppItemType::mvInputText":
        logger.info(f"DPG Item Type: {dpg.get_item_type(input_tag)}")
        raise ValueError(f"Input tag must be a valid tag for an existing DearPyGUI input text item. Received: {input_tag}")
    if error_tag is not None and (not isinstance(error_tag, (str, int)) or not dpg.does_item_exist(error_tag) or dpg.get_item_type(error_tag) != "mvAppItemType::mvText"):
        logger.info(f"DPG Item Type: {dpg.get_item_type(error_tag)}")
        raise ValueError(f"Error tag must be None or a valid tag for an existing DearPyGUI text item. Received: {error_tag}")

    input_filename = dpg.get_value(input_tag)
    filepath = join(directory, input_filename)
    is_valid, abs_path, message = validate_directory(filepath)
    if not is_valid:
        dpg.configure_item(error_tag, default_value=message, color=(192, 57, 43)) # Red color
        return False
    else:
        if dpg.does_item_exist(input_tag):
            dpg.set_value(input_tag, input_filename)
            dpg.configure_item(error_tag, default_value=message, color=(39, 174, 96)) # Green color
        return True


def add_data_to_tree(
    data: Any,
    label: str = "",
    user_data: Any = None,
    parent: Optional[int] = None,
    text_wrap_width: int = -1,
    text_color_one: Tuple[int, int, int] = (30, 200, 120),
    text_color_two: Tuple[int, int, int] = (140, 220, 250),
    dcm_viewing_callback: Optional[Callable] = None,
    max_depth: int = 10,
    current_depth: int = 0
) -> None:
    """
    Recursively add data to a Dear PyGUI tree structure.

    Args:
        data: The data to display (can be SQLAlchemy mapped instance, dict, list, or basic type).
        label: Label for the current data node.
        parent: Parent node tag in the GUI.
        text_wrap_width: Width for text wrapping.
        text_color_one: RGB color for labels.
        text_color_two: RGB color for values.
        dcm_viewing_callback: Callback function when a ".dcm" file is clicked.
        max_depth: Maximum recursion depth.
        current_depth: Current recursion depth.
    """
    if current_depth > max_depth:
        dpg.add_text(default_value=f"{label}: (Max recursion depth reached)", parent=parent)
        return
    
    def add_kv(parent_id: int, key: str, value: Any) -> None:
        """Render a simple key/value line, with .dcm button support."""
        
        val_text = str(value) if value is not None and value != "" else "N/A"
        
        with dpg.group(parent=parent_id, horizontal=True):
            dpg.add_text(default_value=f"{key}:", wrap=text_wrap_width, bullet=True, color=text_color_one)
            if val_text.endswith(".dcm") and callable(dcm_viewing_callback):
                # Clickable .dcm line
                dpg.add_button(
                    label=val_text, # Maybe change this to a descriptor later
                    user_data=val_text,
                    callback=dcm_viewing_callback,
                )
            else:
                dpg.add_text(default_value=f"\t{val_text}", wrap=text_wrap_width, color=text_color_two)
    
    def add_empty_value(parent_id: int, key_or_label: str) -> None:
        with dpg.group(parent=parent_id):
            dpg.add_text(default_value=f"{key_or_label}:", wrap=text_wrap_width, bullet=True, color=text_color_one)
            dpg.add_text(default_value="\tN/A", wrap=text_wrap_width, color=text_color_two)
    
    # Determining if data is a SQLAlchemy mapped instance
    is_sqla = False
    mapper = None
    try:
        mapper = sa_inspect(data)  # works for mapped instances; raises otherwise
        is_sqla = True  # If this didn't raise, we’ve got a SQLAlchemy-mapped instance
    except (UnmappedInstanceError, TypeError):
        is_sqla = False
    
    # SQLAlchemy mapped instance handling
    if is_sqla and mapper is not None and hasattr(mapper, "mapper"):
        # Render an expandable node titled with either provided label or ClassName
        node_label = label or mapper.mapper.class_.__name__
        new_parent = dpg.add_tree_node(label=node_label, parent=parent, default_open=(current_depth==0))

        # First, columns
        for col in mapper.mapper.columns:
            key = col.key
            try:
                val = getattr(data, key, None)
            except DetachedInstanceError:
                val = "<unloaded attribute>"
            add_kv(new_parent, key, val)

        # Next, attributes
        for rel in mapper.mapper.relationships:
            rel_label = rel.key
            if current_depth + 1 > max_depth:
                add_empty_value(new_parent, rel_label)
                continue

            # Try accessing relationship; do not show if not loaded & session closed
            try:
                rel_val = getattr(data, rel.key)
            except DetachedInstanceError:
                continue
            
            # Render relationship node
            if rel.uselist:  # one-to-many / many-to-many
                rel_parent = dpg.add_tree_node(label=f"{rel_label} [{len(rel_val) if rel_val is not None else 0}]", parent=new_parent)
                if not rel_val:
                    add_empty_value(rel_parent, rel_label)
                else:
                    # Each item under its own subtree
                    for idx, item in enumerate(rel_val):
                        file_path = (" - " + str(getattr(item, 'path', ''))) if hasattr(item, 'path') else ''
                        add_data_to_tree(
                            data=item,
                            label=f"{item.__class__.__name__} #{idx+1}{file_path}",
                            user_data=user_data,
                            parent=rel_parent,
                            text_wrap_width=text_wrap_width,
                            text_color_one=text_color_one,
                            text_color_two=text_color_two,
                            dcm_viewing_callback=dcm_viewing_callback,
                            max_depth=max_depth,
                            current_depth=current_depth + 1,
                        )
            else:  # many-to-one / one-to-one
                rel_parent = dpg.add_tree_node(label=rel_label, parent=new_parent)
                if rel_val is None:
                    add_empty_value(rel_parent, rel_label)
                else:
                    add_data_to_tree(
                        data=rel_val,
                        label="",
                        user_data=user_data,
                        parent=rel_parent,
                        text_wrap_width=text_wrap_width,
                        text_color_one=text_color_one,
                        text_color_two=text_color_two,
                        dcm_viewing_callback=dcm_viewing_callback,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                    )
        return
    
    # Dictionary handling
    if isinstance(data, dict):
        new_parent = dpg.add_tree_node(label=label if label else "dict", parent=parent)
        for key, value in data.items():
            if value is not None and value != "":
                add_data_to_tree(
                    data=value, 
                    label=str(key), 
                    user_data=user_data,
                    parent=new_parent, 
                    text_wrap_width=text_wrap_width, 
                    text_color_one=text_color_one, 
                    text_color_two=text_color_two, 
                    dcm_viewing_callback=dcm_viewing_callback, 
                    max_depth=max_depth, 
                    current_depth=current_depth + 1,
                )
            else:
                add_empty_value(new_parent, str(key))
        return
    
    # List handling
    if isinstance(data, (list, tuple)):
        new_parent = dpg.add_tree_node(label=label if label else "list", parent=parent)
        simple = all(isinstance(item, (str, int, float, bool, type(None))) for item in data)
        if simple:
            dpg.add_text(default_value=str(list(data)), parent=new_parent, wrap=text_wrap_width, color=text_color_two)
        else:
            for idx, item in enumerate(data):
                item_label = f"Item #{str(idx)}"
                if item is not None and item != "":
                    add_data_to_tree(
                        data=item, 
                        label=item_label, 
                        user_data=user_data,
                        parent=new_parent, 
                        text_wrap_width=text_wrap_width, 
                        text_color_one=text_color_one, 
                        text_color_two=text_color_two, 
                        dcm_viewing_callback=dcm_viewing_callback, 
                        max_depth=max_depth, 
                        current_depth=current_depth + 1,
                    )
                else:
                    add_empty_value(new_parent, item_label)
        return
    
    # Generic Python object handling
    if hasattr(data, "__dict__"):
        new_parent = dpg.add_tree_node(label=label if label else data.__class__.__name__, parent=parent)
        for key, value in vars(data).items():
            if key.startswith("_"):
                continue # Skip private attributes
            if value is not None and value != "":
                add_data_to_tree(
                    data=value,
                    label=str(key),
                    user_data=user_data,
                    parent=new_parent,
                    text_wrap_width=text_wrap_width,
                    text_color_one=text_color_one,
                    text_color_two=text_color_two,
                    dcm_viewing_callback=dcm_viewing_callback,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                )
            else:
                add_empty_value(new_parent, key)
        return
    
    # Unhandled data types (e.g., scalars)
    add_kv(parent, label or "value", data)


def normalize_dcm_string(s: Any) -> str:
    """
    Normalize a DICOM string for consistent matching (e.g., case-insensitive, whitespace-trimmed).

    Args:
        s: The string to normalize.

    Returns:
        A lowercase, trimmed string.
    """
    return str(s).strip().lower() if s is not None else ""


def build_userdata(tag: Any = "", VR: Any = None, value: Any = None) -> dict:
    """
    Create a standardized user_data dictionary with normalized string fields
    for consistent future matching (e.g., case-insensitive, whitespace-trimmed).

    Args:
        tag: DICOM tag or key name.
        VR: Value Representation.
        value: Associated value or description.

    Returns:
        A dict with lowercase, trimmed string fields.
    """
    return {
        "tag": normalize_dcm_string(tag),
        "VR": normalize_dcm_string(VR),
        "value": normalize_dcm_string(value)
    }


def add_dicom_dataset_to_tree(
    window_tag: Union[str, int],
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
        window_tag: The tag of the parent window.
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
    # Early exit if window no longer exists
    if not dpg.does_item_exist(window_tag):
        return
    
    if current_depth > max_depth:
        dpg.add_text(
            default_value=f"{label}: (Max recursion depth reached)",
            parent=parent,
            user_data=build_userdata(tag=label, VR=None, value="(Max recursion depth reached)")
        )
        return
    
    def add_empty_value(parent, key_or_label):
        with dpg.group(parent=parent):
            dpg.add_text(
                default_value=f"{key_or_label}:",
                wrap=text_wrap_width,
                bullet=True,
                color=text_color_one,
                user_data=build_userdata(tag=key_or_label, VR=None, value="")  # No value provided
            )
            dpg.add_text(
                default_value="\tN/A",
                wrap=text_wrap_width,
                color=text_color_two,
                user_data=build_userdata(tag=key_or_label, VR=None, value="N/A")
            )
    
    # Handle pydicom Dataset
    if isinstance(data, Dataset):
        if label:
            new_parent = dpg.add_tree_node(
                label=label,
                parent=parent,
                user_data=build_userdata(tag=label, VR=None, value=None)
            )
        else:
            new_parent = parent
        for elem in data:
            # Check if window still exists before each element
            if not dpg.does_item_exist(window_tag):
                return
            
            tag = elem.tag
            tag_name = elem.name if elem.name != "Unknown" else f"Private Tag {tag}"
            tag_label = f"{tag_name} {tag}" if str(tag).startswith("(") and str(tag).endswith(")") else f"{tag_name} ({tag})"
            add_dicom_dataset_to_tree(
                window_tag=window_tag,
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
            user_data=build_userdata(tag=data.tag, VR=data.VR, value=data.value)
        )
        if data.value is not None:
            tag = data.tag
            tag_name = data.name if data.name != "Unknown" else f"Private Tag {tag}"
            value = data.value
            tag_VR = data.VR
            tag_VR_type = convert_VR_string_to_python_type(str(data.VR))
            if isinstance(value, Dataset):
                add_dicom_dataset_to_tree(
                    window_tag=window_tag,
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
                # Special handling for Contour Sequence
                is_contour_sequence = (data.name == "Contour Sequence" or 
                                    ("Contour Sequence" in label and not "ROI" in label) or
                                    "(3006,0040)" in label or 
                                    str(data.tag) == "(3006,0040)")
                
                if is_contour_sequence and len(value) > 1:
                    # Only show first item
                    if not dpg.does_item_exist(window_tag):
                        return
                    
                    add_dicom_dataset_to_tree(
                        window_tag=window_tag,
                        data=value[0],
                        label="Item #0 (Example)",
                        parent=new_parent,
                        text_wrap_width=text_wrap_width,
                        text_color_one=text_color_one,
                        text_color_two=text_color_two,
                        max_depth=max_depth,
                        current_depth=current_depth + 1
                    )
                    
                    # Add truncation notice
                    dpg.add_text(
                        default_value=f"... and {len(value) - 1} more items (truncated for performance)",
                        parent=new_parent,
                        wrap=text_wrap_width,
                        color=(255, 165, 0),  # Orange color for the notice
                        user_data=build_userdata(tag="Truncation Notice", VR=None, value=f"{len(value) - 1} items hidden")
                    )
                else:
                    for idx, item in enumerate(value):
                        # Check if window still exists before each item
                        if not dpg.does_item_exist(window_tag):
                            return

                        item_label = f"Item #{idx}"
                        add_dicom_dataset_to_tree(
                            window_tag=window_tag,
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
                    user_data=build_userdata(tag=tag, VR=tag_VR, value=value)
                )
                with dpg.tooltip(parent=dpg.last_item()):
                    dpg.add_text(
                        default_value=f"VR: {tag_VR} ---> Value Representation: {tag_VR_type}",
                        wrap=text_wrap_width,
                        color=text_color_two,
                        user_data=build_userdata(tag="VR Info", VR=tag_VR, value=tag_VR_type)
                    )
            else:
                dpg.add_text(
                    default_value=f"Value: {value}",
                    parent=new_parent,
                    wrap=text_wrap_width,
                    color=text_color_two,
                    user_data=build_userdata(tag=tag, VR=tag_VR, value=value)
                )
                with dpg.tooltip(parent=dpg.last_item()):
                    dpg.add_text(
                        default_value=f"VR: {tag_VR} ---> Value Representation: {tag_VR_type}",
                        wrap=text_wrap_width,
                        color=text_color_two,
                        user_data=build_userdata(tag="VR Info", VR=tag_VR, value=tag_VR_type)
                    )
        else:
            add_empty_value(new_parent, "Value")
    # Handle pydicom Sequence
    elif isinstance(data, Sequence):
        # Check if this is a Contour Sequence based on the label
        is_contour_sequence = (("Contour Sequence" in label and not "ROI" in label) or "(3006,0040)" in label if label else False)

        new_parent = dpg.add_tree_node(
            label=label if label else "Sequence",
            parent=parent,
            user_data=build_userdata(tag=label if label else "Sequence", VR=None, value=None)
        )
        
        if is_contour_sequence and len(data) > 1:
            # Only show first item for Contour Sequence
            if not dpg.does_item_exist(window_tag):
                return
            
            add_dicom_dataset_to_tree(
                window_tag=window_tag,
                data=data[0],
                label="Item #0 (Example)",
                parent=new_parent,
                text_wrap_width=text_wrap_width,
                text_color_one=text_color_one,
                text_color_two=text_color_two,
                max_depth=max_depth,
                current_depth=current_depth + 1
            )
            
            # Add truncation notice
            dpg.add_text(
                default_value=f"... and {len(data) - 1} more items (truncated for performance)",
                parent=new_parent,
                wrap=text_wrap_width,
                color=(255, 165, 0),  # Orange color
                user_data=build_userdata(tag="Truncation Notice", VR=None, value=f"{len(data) - 1} items hidden")
            )
        else:
            for idx, item in enumerate(data):
                # Check if window still exists before each item
                if not dpg.does_item_exist(window_tag):
                    return
                
                item_label = f"Item #{idx}"
                add_dicom_dataset_to_tree(
                    window_tag=window_tag,
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
            user_data=build_userdata(tag=label if label else "dict", VR=None, value=None)
        )
        for key, value in data.items():
            # Check if window still exists before each item
            if not dpg.does_item_exist(window_tag):
                return
            
            if value:
                add_dicom_dataset_to_tree(
                    window_tag=window_tag,
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
            user_data=build_userdata(tag=label if label else "list", VR=None, value=None)
        )
        for idx, item in enumerate(data):
            # Check if window still exists before each item
            if not dpg.does_item_exist(window_tag):
                return
            
            item_label = f"Item #{idx}"
            if item:
                add_dicom_dataset_to_tree(
                    window_tag=window_tag,
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
                user_data=build_userdata(tag=label, VR=None, value=str(data))
            )
            dpg.add_text(
                default_value=f"\t{str(data)}",
                wrap=text_wrap_width,
                color=text_color_two,
                user_data=build_userdata(tag=label, VR=None, value=str(data))
            )


def modify_table_rows(
    table_tag: Union[str, int],
    delete: bool = False,
    show: Optional[bool] = None
) -> None:
    """
    Modify existing rows in a Dear PyGUI table.

    Args:
        table_tag: The tag of the table to modify.
        delete: If True, delete the rows.
        show: If specified, show or hide the rows.

    Raises:
        ValueError: If both 'delete' and 'show' are None or if invalid types are provided.
    """
    if not isinstance(delete, (bool, type(None))) or not isinstance(show, (bool, type(None))):
        raise ValueError(f"'delete' and 'show' must be booleans or None. Received: delete={delete}, show={show}")
    if not delete and show is None:
        raise ValueError("Either 'delete' or 'show' must be specified.")
    if not isinstance(table_tag, (str, int)) or not dpg.does_item_exist(table_tag):
        logger.error(f"Table tag '{table_tag}' does not exist; modification requested with delete={delete} and show={show}.")
        return

    table_tags = dpg.get_item_children(table_tag)
    if table_tags and len(table_tags) > 1:
        for row_tag in table_tags[1]:
            if delete:
                dpg.delete_item(row_tag)
            elif show is not None:
                dpg.configure_item(row_tag, show=show)


def modify_table_cols(
    table_tag: Union[str, int],
    delete: bool = False,
    show: Optional[bool] = None
) -> None:
    """
    Modify existing columns in a Dear PyGUI table.

    Args:
        table_tag: The tag of the table to modify.
        delete: If True, delete the columns.
        show: If specified, show or hide the columns.

    Raises:
        ValueError: If both 'delete' and 'show' are None or if invalid types are provided.
    """
    if not isinstance(delete, (bool, type(None))) or not isinstance(show, (bool, type(None))):
        raise ValueError(f"'delete' and 'show' must be booleans or None. Received: delete={delete}, show={show}")
    if not delete and show is None:
        raise ValueError("Either 'delete' or 'show' must be specified.")
    if not isinstance(table_tag, (str, int)) or not dpg.does_item_exist(table_tag):
        logger.error(f"Table tag '{table_tag}' does not exist; modification requested with delete={delete} and show={show}.")
        return

    table_tags = dpg.get_item_children(table_tag)
    if table_tags and len(table_tags[0]) > 2:
        for col_tag in table_tags[0][2:]:
            if delete:
                dpg.delete_item(col_tag)
            elif show is not None:
                dpg.configure_item(col_tag, show=show)


def match_child_tags(
    parent_tag: Union[str, int],
    match_criteria: Optional[Union[str, Callable[[Any], bool]]] = None
) -> List[Any]:
    """
    Find all child tags of a given parent item that match specified criteria, searching recursively.

    Args:
        parent_tag: The tag of the parent item.
        match_criteria: A substring to match or a callable function to filter tags.

    Returns:
        A list of tags that meet the criteria.
    """
    if not dpg.does_item_exist(parent_tag):
        return []
    
    # Cache DPG functions for speed
    get_children = dpg.get_item_children
    get_alias = dpg.get_item_alias

    match_by_str = isinstance(match_criteria, str)
    match_str = match_criteria.lower() if match_by_str else ""

    stack = [parent_tag]
    result: List[Any] = []
    
    # Depth-first search
    while stack:
        current = stack.pop()
        
        children_lists = get_children(current)
        children = sum(children_lists.values(), [])

        for child in children:
            stack.append(child)
            if match_criteria is None:
                result.append(child)
            elif match_by_str:
                alias = child if isinstance(child, str) else get_alias(child)
                if match_str in alias.lower():
                    result.append(child)
            elif callable(match_criteria):
                if match_criteria(child):
                    result.append(child)
    
    return result

