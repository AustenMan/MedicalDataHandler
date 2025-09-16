from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple, Union


import dearpygui.dearpygui as dpg
from dearpygui.dearpygui import (
    set_value, configure_item, get_item_user_data,
    get_item_type, get_item_children, get_item_parent
)

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
        "name": normalize_dcm_string(dpg.get_value(tag_search_tag)),  # reuse same input
        "VR": normalize_dcm_string(dpg.get_value(tag_search_vr)),
        "value": normalize_dcm_string(dpg.get_value(tag_search_value))
    }
    
    logger.info(
        f"Filtering DICOM inspection with search terms: "
        f"Tag='{search_terms['tag']}', VR='{search_terms['VR']}', Value='{search_terms['value']}'"
        "... This may take a while, please wait!"
    )
    
    tree_node_type = "mvAppItemType::mvTreeNode"
    
    # If no search terms are provided, collapse all nodes and exit
    if not any(search_terms.values()):
        [set_value(node, False) for node in match_child_tags(tag_tree_group, lambda tag: get_item_type(tag) == tree_node_type)]
        configure_item(sender, label=sender_orig_label, enabled=True)
        logger.info("No search terms were provided; collapsed all nodes to reflect no matches.")
        return
    
    # Build a flattened dictionary of all tree node IDs and their associated user_data fields (as a tuple).
    def get_combined_userdata(node: Union[str, int]) -> Dict[str, str]:
        ud = get_item_user_data(node)
        if not isinstance(ud, dict):
            return {"tag": "", "name": "", "VR": "", "value": ""}
        return {
            "tag": ud.get("tag", ""),
            "name": ud.get("name", ""),
            "VR": ud.get("VR", ""),
            "value": ud.get("value", "")
        }
    
    # Determine which nodes match the search terms.
    all_tree_nodes: List[Union[str, int]] = get_all_tree_nodes(tag_tree_group)
    nodes_to_open: Set[Union[str, int]] = set()
    for node in all_tree_nodes:
        data = get_combined_userdata(node)
        if (
            ( not search_terms["tag"] or (search_terms["tag"] in data["tag"]) or (search_terms["tag"] in data["name"]) ) and
            ( not search_terms["VR"] or (search_terms["VR"] in data["VR"]) ) and
            ( not search_terms["value"] or (search_terms["value"] in data["value"]) ) 
        ):
            nodes_to_open.add(node)
            nodes_to_open.update(get_all_parents(node, tag_tree_group))
            logger.debug(f"Matched node {node} with data: {data}")

    [set_value(node, node in nodes_to_open) for node in all_tree_nodes]
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
    tree_node_type = "mvAppItemType::mvTreeNode"

    # Cache for performance
    append = result.append
    extend = stack.extend
    
    while stack:
        current = stack.pop()
        if get_item_type(current) == tree_node_type:
            append(current)
        try:
            extend(get_item_children(current, 1))  # slot=1 for children
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
    tree_node_type = "mvAppItemType::mvTreeNode"
    
    # Cache for performance
    add = parents.add
    
    while node and node != stop_node:
        node = get_item_parent(node)
        if node and node != stop_node and get_item_type(node) == tree_node_type:
            add(node)
    return parents

