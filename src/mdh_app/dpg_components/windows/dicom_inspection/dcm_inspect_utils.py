from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple, Union


import dearpygui.dearpygui as dpg


from mdh_app.utils.dpg_utils import normalize_dcm_string, match_child_tags


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


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

