from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.utils.dpg_utils import safe_delete, get_popup_params, add_data_to_tree
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_win import create_popup_dicom_inspection


if TYPE_CHECKING:
    from mdh_app.managers.shared_state_manager import SharedStateManager
    from mdh_app.database.models import Patient


logger = logging.getLogger(__name__)


def create_window_ptobj_inspection(
    sender: Union[str, int],
    app_data: Any,
    user_data: Patient
) -> None:
    """
    Create and display a popup window to inspect a patient object.

    This window shows a detailed tree view of the patient data and provides a callback
    to view related DICOM files.

    Args:
        sender: The tag of the element triggering the inspection.
        app_data: Additional event data (unused).
        user_data: A PatientData instance representing the patient.
    """
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    pt_data: Patient = user_data
    mrn, name = pt_data.mrn, pt_data.name
    tag_inspect_ptobj = get_tag("inspect_ptobj_window")
    popup_width, popup_height, popup_pos = get_popup_params()
    
    # Create a new window to inspect
    logger.info(f"Creating patient inspection window for: {name} (MRN: {mrn})")
    safe_delete(tag_inspect_ptobj)
    
    with dpg.window(
        tag=tag_inspect_ptobj,
        label=f"Inspecting: {name} (MRN: {mrn})",
        width=popup_width, 
        height=popup_height, 
        pos=popup_pos, 
        no_open_over_existing_popup=False, 
        no_title_bar=False, 
        horizontal_scrollbar=True
        ):
        add_data_to_tree(
            data=pt_data, 
            parent=tag_inspect_ptobj, 
            text_wrap_width=round(0.95 * popup_width), 
            dcm_viewing_callback=lambda s, a, u: ss_mgr.submit_action(partial(create_popup_dicom_inspection, s, a, u))
        )

