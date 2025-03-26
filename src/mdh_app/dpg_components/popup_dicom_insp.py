import logging
import dearpygui.dearpygui as dpg
from functools import partial
from typing import Any, Dict, List, Set, Tuple, Union

from mdh_app.dpg_components.custom_utils import (
    get_tag, get_user_data, add_custom_button, add_custom_separator
)
from mdh_app.dpg_components.themes import get_hidden_button_theme
from mdh_app.managers.shared_state_manager import SharedStateManager
from mdh_app.utils.dpg_utils import (
    safe_delete, get_popup_params, normalize_dcm_string, 
    match_child_tags, add_dicom_dataset_to_tree
)
from mdh_app.utils.dicom_utils import read_dcm_file

logger = logging.getLogger(__name__)

def create_popup_dicom_inspection(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """
    Create and display a popup with detailed DICOM file information.

    Args:
        sender: The tag of the initiating item.
        app_data: Additional event data.
        user_data: Custom user data passed to the callback.
    """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_file: str = dpg.get_item_label(sender)
    tag_inspect_dcm = get_tag("inspect_dicom_popup")
    size_dict: Dict[str, Any] = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # Delete any pre-existing popup
    safe_delete(tag_inspect_dcm)
    
    # Try to read the DICOM file
    dicom_dataset = read_dcm_file(dcm_file)
    if not dicom_dataset:
        return
    
    tag_hidden_theme = get_hidden_button_theme()
    
    # Create the popup
    with dpg.window(
        tag=tag_inspect_dcm, 
        label=f"Inspecting a DICOM File", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        popup=True,
        modal=True, 
        no_open_over_existing_popup=False, 
        horizontal_scrollbar=True
        ):
        # Add input fields for search terms
        tag_tree_group = dpg.generate_uuid()
        with dpg.group(horizontal=False):
            add_custom_button(
                label="NOTE: Applying filters is currently experimental; you may experience performance issues with large datasets.",
                theme_tag=tag_hidden_theme
            )
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp, width=size_dict["table_w"]):
                dpg.add_table_column(init_width_or_weight=0.3)
                dpg.add_table_column(init_width_or_weight=0.7)
                with dpg.table_row():
                    tag_search_tag_text = dpg.add_text(default_value="Search for DICOM Tag:", bullet=True)
                    with dpg.tooltip(parent=tag_search_tag_text):
                        dpg.add_text(default_value="Search for a DICOM tag. Examples: '0008,0005', '0020,0013', etc.", wrap=size_dict["tooltip_width"])
                    tag_search_tag = dpg.add_input_text(width=size_dict["button_width"], height=size_dict["button_height"])
                with dpg.table_row():
                    tag_search_vr_text = dpg.add_text(default_value="Search for DICOM VR:", bullet=True)
                    with dpg.tooltip(parent=tag_search_vr_text):
                        dpg.add_text(default_value="Search for a DICOM Value Representation (VR). Examples: 'CS', 'DS', 'TM', etc.", wrap=size_dict["tooltip_width"])
                    tag_search_vr = dpg.add_input_text(width=size_dict["button_width"], height=size_dict["button_height"])
                with dpg.table_row():
                    tag_search_value_text = dpg.add_text(default_value="Search for DICOM Value:", bullet=True)
                    with dpg.tooltip(parent=tag_search_value_text):
                        dpg.add_text(default_value="Search for a DICOM value. Examples: 'HFS', 'AXIAL', 'CT', etc.", wrap=size_dict["tooltip_width"])
                    tag_search_value = dpg.add_input_text(width=size_dict["button_width"], height=size_dict["button_height"])
            tag_start_search = add_custom_button(
                label="Apply Filters", 
                callback=lambda s, a, u: ss_mgr.submit_action(partial(filter_dicom_inspection, s, a, u)),
                user_data=(tag_tree_group, tag_search_tag, tag_search_vr, tag_search_value), 
                enabled=False,
                tooltip_text="Apply the search filters to the DICOM dataset. Filtering is only available after loading the full dataset."
            )
        
        tag_status_text = add_custom_button(
            label="*** STILL LOADING THE FULL DICOM INFO ***",
            theme_tag=tag_hidden_theme,
            add_separator_before=True,
        )
        add_custom_button(
            label=f"File Location: {str(dcm_file)[:100]}...",
            theme_tag=tag_hidden_theme,
            add_separator_after=True,
            tooltip_text=f"File location: {dcm_file}"
        )
    
    # Add the DICOM dataset to the tree
    with dpg.group(tag=tag_tree_group, parent=tag_inspect_dcm, user_data=False):
        add_dicom_dataset_to_tree(
            data=dicom_dataset, 
            label=None, 
            parent=tag_tree_group, 
            text_wrap_width=round(0.95 * popup_width), 
            max_depth=5
        )
    
    # Update the status text
    dpg.configure_item(tag_status_text, label="Full DICOM info is loaded")
    dpg.configure_item(tag_start_search, enabled=True)

def filter_dicom_inspection(
    sender: Union[str, int], 
    app_data: Any, 
    user_data: Tuple[Union[str, int], Union[str, int], Union[str, int], Union[str, int]]
) -> None:
    """
    Filter the DICOM popup content based on provided search terms.

    Args:
        sender: The tag of the triggering item.
        app_data: Additional event data.
        user_data: Tuple containing tags for the tree group and search input fields (tag, VR, value).
    """
    sender_orig_label = dpg.get_item_label(sender)
    dpg.configure_item(sender, label="Applying Filters...", enabled=False)
    
    tag_tree_group, tag_search_tag, tag_search_vr, tag_search_value = user_data
    
    # Normalize input search terms
    search_terms = {
        "tag": normalize_dcm_string(dpg.get_value(tag_search_tag)),
        "VR": normalize_dcm_string(dpg.get_value(tag_search_vr)),
        "value": normalize_dcm_string(dpg.get_value(tag_search_value))
    }
    
    logger.info(
        f"Filtering DICOM inspection with search terms: "
        f"Tag='{search_terms['tag']}', VR='{search_terms['VR']}', Value='{search_terms['value']}'"
        "... This may take a while, please wait!"
    )
    
    # Cache lookup functions & constants
    set_value = dpg.set_value
    get_item_type = dpg.get_item_type
    tree_node_type = "mvAppItemType::mvTreeNode"
    configure_item = dpg.configure_item
    get_item_user_data = dpg.get_item_user_data
    
    # If no search terms are provided, collapse all nodes and exit
    if not any(search_terms.values()):
        [set_value(node, False) for node in match_child_tags(tag_tree_group, lambda tag: get_item_type(tag) == tree_node_type)]
        configure_item(sender, label=sender_orig_label, enabled=True)
        return
    
    # Build a flattened dictionary of all tree node IDs and their associated user_data fields (as a tuple).
    def get_combined_userdata(node: Union[str, int]) -> Dict[str, str]:
        ud = get_item_user_data(node)
        if not isinstance(ud, dict):
            return {"tag": "", "VR": "", "value": ""}
        if "tag" not in ud or not ud["tag"]:
            ud["tag"] = ""
        if "VR" not in ud or not ud["VR"]:
            ud["VR"] = ""
        if "value" not in ud or not ud["value"]:
            ud["value"] = ""
        return ud
    
    node_info: Dict[Union[str, int], Dict[str, str]] = {
        node: get_combined_userdata(node) for node in get_all_tree_nodes(tag_tree_group)
    }
    
    # Determine which nodes match the search terms.
    nodes_to_open: Set[Union[str, int]] = set()
    for node, data in node_info.items():
        if all(not term or term in data[field] for field, term in search_terms.items()):
            nodes_to_open.add(node)
            nodes_to_open.update(get_all_parents(node, tag_tree_group))
            logger.debug(f"Matched node {node} with data: {data}")
    
    [set_value(node, node in nodes_to_open) for node in node_info.keys()]
    logger.info(f"Filtered DICOM inspection: {len(nodes_to_open)} nodes matched the search terms.")
    dpg.configure_item(sender, label=sender_orig_label, enabled=True)

def get_all_tree_nodes(root: Union[str, int]) -> List[Union[str, int]]:
    """
    Retrieve all tree node IDs under a given root using an iterative approach.

    Args:
        root: The root tree node ID.

    Returns:
        A list of tree node IDs.
    """
    result: List[Union[str, int]] = []
    stack = [root]
    
    # Cache lookup functions & constants
    get_type = dpg.get_item_type
    get_children = dpg.get_item_children
    tree_node_type = "mvAppItemType::mvTreeNode"

    append = result.append
    extend = stack.extend
    
    while stack:
        current = stack.pop()
        if get_type(current) == tree_node_type:
            append(current)
        try:
            extend(get_children(current, 1))  # slot=1 for children
        except:
            pass
    return result

def get_all_parents(node: Union[str, int], stop_node: Union[str, int]) -> Set[Union[str, int]]:
    """
    Return all parent tree node IDs of a given node up to a specified stop node.

    Args:
        node: The starting node ID.
        stop_node: The node ID to stop at.

    Returns:
        A set of parent node IDs.
    """
    parents: Set[Union[str, int]] = set()
    
    # Cache lookup functions & constants
    get_item_parent = dpg.get_item_parent
    get_item_type = dpg.get_item_type
    tree_node_type = "mvAppItemType::mvTreeNode"
    
    add = parents.add
    
    while node and node != stop_node:
        node = get_item_parent(node)
        if node and node != stop_node and get_item_type(node) == tree_node_type:
            add(node)
    return parents

