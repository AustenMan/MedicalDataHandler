from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.utils.dpg_utils import get_popup_params


if TYPE_CHECKING:
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.dicom_manager import DicomManager


logger = logging.getLogger(__name__)


def _get_directory(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Open a file dialog to select a DICOM directory, then start processing the directory."""
    conf_mgr: ConfigManager = get_user_data(td_key="config_manager")
    popup_width, popup_height, popup_pos = get_popup_params(height_ratio=0.5)
    tag_fd = dpg.generate_uuid()
    
    dpg.add_file_dialog(
        tag=tag_fd,
        label="Choose a directory containing DICOM files",
        directory_selector=True,
        default_path=conf_mgr.get_project_dir(),
        modal=True,
        callback=wrap_with_cleanup(_start_processing_directory),
        width=popup_width,
        height=popup_height,
    )


def _start_processing_directory(sender: Union[str, int], app_data: Any, user_data: Any) -> None:
    """Start processing the selected DICOM directory."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    dcm_mgr.process_dicom_directory(app_data.get("file_path_name"))

