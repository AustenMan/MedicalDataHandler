import dearpygui.dearpygui as dpg
from dpg_components.custom_utils import get_tag, get_user_data, add_custom_button, add_custom_separator
from utils.dpg_utils import safe_delete, get_popup_params, match_child_tags, add_dicom_dataset_to_tree
from utils.dicom_utils import read_dcm_file
from utils.general_utils import get_traceback

def try_inspect_dicom_file(sender, app_data, user_data):
    """
    Displays detailed information about a selected DICOM file in a popup window.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (any): Custom user data passed to the callback.
    """
    # Check if an action is already in progress
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.cleanup_event.is_set() or shared_state_manager.is_action_in_queue():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    # Start the action
    shared_state_manager.add_action(lambda: _create_popup_dicom_inspection(sender, app_data, user_data))

def _create_popup_dicom_inspection(sender, app_data, user_data):
    """ Displays detailed information about a selected DICOM file in a popup window. Params passed from inspect_dicom_file. """
    # Get necessary parameters
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        dcm_file=dpg.get_item_label(sender)
        tag_inspect_dcm = get_tag("inspect_dicom_popup")
        size_dict = get_user_data(td_key="size_dict")
        popup_width, popup_height, popup_pos = get_popup_params()
        
        # Delete any pre-existing popup
        safe_delete(tag_inspect_dcm)
        
        # Try to read the DICOM file
        dicom_dataset = read_dcm_file(dcm_file)
        if not dicom_dataset:
            shared_state_manager.action_event.clear()
            return
        
        # Create the popup
        with dpg.window(
            tag=tag_inspect_dcm, 
            label=f"Inspecting a DICOM File", 
            width=popup_width, 
            height=popup_height, 
            pos=popup_pos, 
            no_open_over_existing_popup=False, 
            popup=True,
            modal=True, 
            no_title_bar=False, 
            no_close=False, 
            on_close=lambda: safe_delete(tag_inspect_dcm),
            horizontal_scrollbar=True
            ):
            tag_status_text = dpg.generate_uuid()
            dpg.add_text(tag=tag_status_text, default_value=f"*** STILL LOADING THE FULL DICOM INFO ***")
            dpg.add_text(default_value=f"File Location: {dcm_file}")
            add_custom_separator()
            
            # Add input fields for search terms
            tag_tree_group = dpg.generate_uuid()
            tag_search_key = dpg.generate_uuid()
            tag_search_vr = dpg.generate_uuid()
            tag_search_value = dpg.generate_uuid()
            tag_apply_button = dpg.generate_uuid()
            with dpg.group(horizontal=False):
                dpg.add_text(default_value="NOTE: Applying filters is currently experimental and may crash the program if there are an extremely large number of items.")
                with dpg.group(horizontal=True):
                    dpg.add_text(default_value="Search for a Key:".ljust(20), bullet=True)
                    dpg.add_input_text(tag=tag_search_key, width=size_dict["button_width"], height=size_dict["button_height"])
                with dpg.group(horizontal=True):
                    dpg.add_text(default_value="Search for a VR:".ljust(20), bullet=True)
                    dpg.add_input_text(tag=tag_search_vr, width=size_dict["button_width"], height=size_dict["button_height"])
                with dpg.group(horizontal=True):
                    dpg.add_text(default_value="Search for a Value:".ljust(20), bullet=True)
                    dpg.add_input_text(tag=tag_search_value, width=size_dict["button_width"], height=size_dict["button_height"])
                add_custom_button(tag=tag_apply_button, label="Apply Filters", callback=_try_filter_dicom_inspection, user_data=(tag_tree_group, tag_search_key, tag_search_vr, tag_search_value), add_separator_after=True)
        
        # Add the DICOM dataset to the tree
        with dpg.group(tag=tag_tree_group, parent=tag_inspect_dcm, user_data=False):
            add_dicom_dataset_to_tree(data=dicom_dataset, label=None, parent=tag_tree_group, text_wrap_width=round(0.95 * popup_width), max_depth=5)
        
        # Update the status text
        dpg.configure_item(tag_status_text, default_value="Full DICOM info is loaded")
    except Exception as e:
        print(get_traceback(e))
        print("Failed to inspect the DICOM file. Please review the log error message and try again.")
    finally:
        shared_state_manager.action_event.clear()

def _try_filter_dicom_inspection(sender, app_data, user_data):
    """
    Attempts to filter the displayed content of a DICOM file popup based on search terms.
    
    Args:
        sender (str or int): The tag of the sender that triggered this action.
        app_data (any): Additional data from the sender.
        user_data (tuple): Tags for the tree group and search inputs (key, VR, value).
    """
    # Check if an action is already in progress
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    if shared_state_manager.cleanup_event.is_set() or shared_state_manager.is_action_in_queue():
        print("An action is in progress. Please wait for the action(s) to complete.")
        return
    
    # Start the action
    shared_state_manager.add_action(lambda: _filter_dicom_inspection(sender, app_data, user_data))

def _filter_dicom_inspection(sender, app_data, user_data):
    """ Filters the displayed content of a DICOM file popup based on search terms. Params passed from _try_filter_dicom_inspection. """
    shared_state_manager = get_user_data(td_key="shared_state_manager")
    shared_state_manager.action_event.set()
    
    try:
        tag_tree_group, tag_search_key, tag_search_vr, tag_search_value = user_data
        
        # Get search terms and normalize them to lowercase for case-insensitive matching
        search_key = (dpg.get_value(tag_search_key) or "").strip().lower()
        search_vr = (dpg.get_value(tag_search_vr) or "").strip().lower()
        search_value = (dpg.get_value(tag_search_value) or "").strip().lower()
        
        print(f"Filtering DICOM inspection with search terms: Key='{search_key}', VR='{search_vr}', Value='{search_value}'... This may take a while, please wait!")
        
        # If no search terms are provided, collapse all nodes and exit
        if not (search_key or search_vr or search_value):
            [dpg.set_value(node, False) for node in match_child_tags(tag_tree_group, lambda tag: dpg.get_item_type(tag) == "mvAppItemType::mvTreeNode")]
            shared_state_manager.action_event.clear()
            return
        
        # Build a flattened dictionary of all tree node IDs and their associated user_data fields (as a tuple).
        def get_combined_userdata(node):
            ud = dpg.get_item_user_data(node)
            # If no valid dict was found, we default to empty strings.
            if not isinstance(ud, dict):
                return "", "", ""
            return (
                str(ud.get("key") or "").lower(),
                str(ud.get("VR") or "").lower(),
                str(ud.get("value") or "").lower()
            )
        node_info = {node: get_combined_userdata(node) for node in get_all_tree_nodes(tag_tree_group)}
        
        # Determine which nodes match the search terms.
        nodes_to_open = set()
        for node, (ud_key, ud_VR, ud_value) in node_info.items():
            key_match = not search_key or search_key in ud_key
            vr_match = not search_vr or search_vr in ud_VR
            value_match = not search_value or search_value in ud_value

            if key_match and vr_match and value_match:
                nodes_to_open.add(node)
                # Also add all parent tree nodes so the matched node becomes visible.
                nodes_to_open.update(get_all_parents(node, tag_tree_group))
        
        [dpg.set_value(node, node in nodes_to_open) for node in node_info.keys()]
        print(f"Filtered DICOM inspection: {len(nodes_to_open)} nodes matched the search terms.")
    except Exception as e:
        print(get_traceback(e))
        print("Failed to filter the DICOM file. Please review the log error message and try again.")
    finally:
        shared_state_manager.action_event.clear()

def get_all_tree_nodes(root):
    """
    Returns a list of all tree node IDs under the given root using an iterative approach.
    
    Args:
        root (int): The root tree node ID.
    
    Returns:
        list: List of tree node IDs.
    """
    nodes = []
    stack = [root]
    while stack:
        current = stack.pop()
        if dpg.get_item_type(current) == "mvAppItemType::mvTreeNode":
            nodes.append(current)
        try:
            children = dpg.get_item_children(current, slot=1)
            stack.extend(children)
        except Exception:
            pass
    return nodes

def get_all_parents(node, stop_node):
    """
    Returns a set of all parent tree nodes of the given node up to stop_node.
    
    Args:
        node (int): The node ID.
        stop_node (int): The node ID at which to stop.
    
    Returns:
        set: Set of parent node IDs.
    """
    parents = set()
    while node and node != stop_node:
        node = dpg.get_item_parent(node)
        if node and node != stop_node and dpg.get_item_type(node) == "mvAppItemType::mvTreeNode":
            parents.add(node)
    return parents

