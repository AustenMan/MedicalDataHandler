from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, Dict, Union
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data, add_custom_button
from mdh_app.dpg_components.themes.button_themes import get_hidden_button_theme
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_utils import filter_dicom_inspection
from mdh_app.utils.dicom_utils import read_dcm_file
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params, add_dicom_dataset_to_tree


if TYPE_CHECKING:
    from pydicom import Dataset
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


def create_popup_dicom_inspection(sender: Union[str, int], app_data: Any, user_data: Union[str, Dataset]) -> None:
    """
    Create and display a popup with detailed DICOM file information.

    Args:
        sender: The tag of the initiating item.
        app_data: Additional event data.
        user_data: Custom user data passed to the callback.
    """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    tag_inspect_dcm = get_tag("inspect_dicom_popup")
    size_dict: Dict[str, Any] = get_user_data(td_key="size_dict")
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # Delete any pre-existing popup
    safe_delete(tag_inspect_dcm)
    
    # Get the DICOM dataset
    dicom_dataset = None
    dicom_path = None
    if isinstance(user_data, str):
        dicom_path = user_data
        dicom_dataset = read_dcm_file(dicom_path)
    elif isinstance(user_data, Dataset):
        dicom_dataset = user_data
    if not isinstance(dicom_dataset, Dataset):
        logger.error(f"Failed to fetch DICOM dataset for inspection! Received: {type(dicom_dataset)}")
        return
    
    tag_hidden_theme = get_hidden_button_theme()
    
    # Create the popup
    window_states = {"aborted": False}
    with dpg.window(
        tag=tag_inspect_dcm, 
        label=f"Inspecting a DICOM File", 
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        popup=True,
        modal=True, 
        no_open_over_existing_popup=False, 
        horizontal_scrollbar=True,
        on_close=lambda s, a, u: window_states.update({"aborted": True})
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
        
        if dicom_path is not None:
            add_custom_button(
                label=f"File Location: {str(dicom_path)[:100]}...",
                theme_tag=tag_hidden_theme,
                add_separator_after=True,
                tooltip_text=f"File location: {dicom_path}"
            )
    
    # Add the DICOM dataset to the tree
    with dpg.group(tag=tag_tree_group, parent=tag_inspect_dcm, user_data=False):
        add_dicom_dataset_to_tree(
            window_tag=tag_inspect_dcm,
            window_states=window_states,
            data=dicom_dataset, 
            label=None, 
            parent=tag_tree_group, 
            text_wrap_width=round(0.95 * popup_width), 
            max_depth=5,
        )
    
    # Check in case user closed the popup before finished loading
    if dpg.does_item_exist(tag_inspect_dcm):
        # Update the status text
        dpg.configure_item(tag_status_text, label="Full DICOM info is loaded")
        dpg.configure_item(tag_start_search, enabled=True)



