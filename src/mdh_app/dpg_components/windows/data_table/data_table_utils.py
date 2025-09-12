from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Union, Any, Dict, Tuple, Optional, Set, List
from enum import Enum
from dataclasses import dataclass, field
from os.path import basename
from datetime import datetime
from functools import partial


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.gui_lifecycle import wrap_with_cleanup
from mdh_app.dpg_components.core.utils import get_tag, get_user_data
from mdh_app.dpg_components.rendering.texture_manager import request_texture_update
from mdh_app.dpg_components.widgets.patient_ui.fill_menu import fill_right_col_ptdata
from mdh_app.dpg_components.windows.confirmation.confirm_window import create_confirmation_popup
from mdh_app.dpg_components.windows.dicom_inspection.dcm_inspect_win import create_popup_dicom_inspection
from mdh_app.utils.dpg_utils import safe_delete
from mdh_app.utils.general_utils import get_json_list


if TYPE_CHECKING:
    from mdh_app.database.models import Patient, File, FileMetadata
    from mdh_app.managers.config_manager import ConfigManager
    from mdh_app.managers.data_manager import DataManager
    from mdh_app.managers.dicom_manager import DicomManager
    from mdh_app.managers.shared_state_manager import SharedStateManager


logger = logging.getLogger(__name__)


class ContainerKind(Enum):
    DOSES = "Dose(s)"
    PLANS = "Plan(s)"
    STRUCTURE_SETS = "StructureSet(s)"
    IMAGE_SERIES_GROUPS = "ImageSeriesGroup(s)"


class NodeType(Enum):
    DOSE = "Dose"
    PLAN = "Plan"
    STRUCTURE_SET = "Structure Set"
    IMAGE_SERIES = "Image Series"


@dataclass
class Node:
    kind: NodeType
    label: str
    description: str
    date_and_time: str
    file_objs: List[Any] = field(default_factory=list)   # actual File objects from Patient
    metadata: Optional[Any] = None  # original FileMetadata or related info
    children: List["Node"] = field(default_factory=list)


def _format_dcm_str_datetime(date_str: str, time_str: str, *, mode: str = "full") -> str:
    """
    Format DICOM date and time strings into readable format.
    mode = "full" -> YYYY-MM-DD HH:MM:SS
    mode = "hm"   -> YYYY-MM-DD HH:MM
    """
    if date_str and time_str:
        try:
            if mode == "hm":
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}"
            else:  # full
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
        except Exception:
            return f"{date_str} {time_str}"
    elif date_str:
        try:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        except Exception:
            return date_str
    return "N/A"


def get_patient_dates(patient: Patient) -> Dict[str, Optional[str]]:
    # Helper to return date fields as iso or "N/A"
    def dt_fmt(dt) -> str:
        if not dt:
            return "N/A"
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return str(dt)

    return {
        "DateCreated": dt_fmt(getattr(patient, "created_at", None)),
        "DateLastModified": dt_fmt(getattr(patient, "modified_at", None)),
        "DateLastAccessed": dt_fmt(getattr(patient, "accessed_at", None)),
        "DateLastProcessed": dt_fmt(getattr(patient, "processed_at", None)),
    }


def confirm_removal_callback(sender: Union[str, int], app_data: Any, user_data: Tuple[Union[str, int], Patient]) -> None:
    """Remove a patient data object after confirmation."""
    dcm_mgr: DicomManager = get_user_data(td_key="dicom_manager")
    tag_data_window = get_tag("data_display_window")
    
    pd_row_tag: Union[str, int] = user_data[0]
    patient_obj: Patient = user_data[1]
    pt_key = (patient_obj.mrn, patient_obj.name)
    mrn, name = pt_key
    
    def delete_func(sender, app_data, user_data) -> None:
        dcm_mgr.delete_patient_from_db(mrn, name)
        safe_delete(pd_row_tag)
        all_patient_data: Dict[Tuple[str, str], Patient] = dpg.get_item_user_data(tag_data_window)
        if all_patient_data and pt_key in all_patient_data:
            all_patient_data.pop(pt_key, None)
            dpg.set_item_user_data(tag_data_window, all_patient_data)
    
    def submit_removal_func(sender, app_data, user_data) -> None:
        clean_wrap = wrap_with_cleanup(delete_func)
        clean_wrap(sender, app_data, user_data)
    
    create_confirmation_popup(
        button_callback=submit_removal_func,
        confirmation_text=f"Removing patient: MRN {mrn}, Name {name}",
        warning_string=(
            f"Are you sure you want to remove the patient:\n"
            f"MRN: {mrn}\nName: {name}\n"
            "This action is irreversible. You would need to re-import the data to access it again.\n"
            "Remove this patient?"
        )
    )


def build_dicom_structure(patient: Patient, selected_files: Set[str]) -> None:
    # DICOM Viewing Callback
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_view_cb = lambda s, a, u: ss_mgr.submit_action(partial(create_popup_dicom_inspection, s, a, u))
    
    # Build Node structure (returns container nodes: Doses, Plans, Structure Sets, Image Series)
    dicom_nodes: List[Node] = _build_dicom_nodes(patient)
    
    # Create the checkbox callback
    checkbox_callback = _create_checkbox_callback(selected_files)

    # Render top-level containers: one checkbox + one tree_node containing their children
    tag_data_table = get_tag("data_table")
    for row_num, node in enumerate(dicom_nodes, start=1):
        num_files = _count_subtree_files(node)
        
        with dpg.table_row(parent=tag_data_table):
            with dpg.group(horizontal=True):
                # container-level checkbox (only one)
                container_ud = _node_user_data(node, None)
                cbox = dpg.add_checkbox(callback=checkbox_callback, user_data=container_ud)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text(node.description or "")
                container_ud["checkbox"] = cbox

                # single tree node which will contain all linked files and child nodes
                with dpg.tree_node(label=f"{row_num}. Grouped Files ({num_files} files)", default_open=False, span_text_width=True):
                    # render each child (child may create its own tree node if it meets 'must_tree')
                    for child in node.children:
                        child_ud = _render_node_inline(child, container_ud, checkbox_callback, dcm_view_cb)
                        container_ud["children"].append(child_ud)

            # Metadata columns
            buckets = gather_metadata(node)
            dpg.add_text(format_metadata_lines(buckets["names"]))
            dpg.add_text(format_metadata_lines(buckets["labels"]))
            dpg.add_text(format_metadata_lines(buckets["descriptions"]))
            dpg.add_text(format_metadata_lines(buckets["datetimes"]))


# ---------- Aggregation Helpers for Metadata Columns ----------

def gather_metadata(node: Node) -> Dict[str, Dict[ContainerKind, List[str]]]:
    """Collect metadata values from a node subtree, grouped by ContainerKind and field type."""

    buckets = {
        "names": {ck: [] for ck in ContainerKind},
        "labels": {ck: [] for ck in ContainerKind},
        "descriptions": {ck: [] for ck in ContainerKind},
        "datetimes": {ck: [] for ck in ContainerKind},
    }
    
    def visit(n: Node):
        # Map a NodeType into its logical container
        if n.kind == NodeType.DOSE:
            ckind = ContainerKind.DOSES
        elif n.kind == NodeType.PLAN:
            ckind = ContainerKind.PLANS
        elif n.kind == NodeType.STRUCTURE_SET:
            ckind = ContainerKind.STRUCTURE_SETS
        elif n.kind == NodeType.IMAGE_SERIES:
            ckind = ContainerKind.IMAGE_SERIES_GROUPS
        else:
            ckind = None

        if ckind:
            for fobj in getattr(n, "file_objs", []) or []:
                md: FileMetadata = getattr(fobj, "file_metadata", None)
                if not md:
                    continue
                if md.name:
                    buckets["names"][ckind].append(md.name)
                if md.label:
                    buckets["labels"][ckind].append(md.label)
                if md.description:
                    buckets["descriptions"][ckind].append(md.description)
                if md.date or md.time:
                    buckets["datetimes"][ckind].append(
                        _format_dcm_str_datetime(md.date, md.time, mode="hm")
                    )
                
                if n.kind == NodeType.IMAGE_SERIES:
                    break  # only need one file's metadata for series-level info
        for c in n.children:
            visit(c)

    visit(node)

    return buckets


def format_metadata_lines(bucket: Dict[ContainerKind, List[str]], suffix: str = "") -> str:
    """Format a single metadata bucket into newline text with container labels."""
    suffix = f" {suffix}" if suffix else ""
    lines = []
    for ckind in ContainerKind:
        vals = bucket.get(ckind, [])
        if vals:
            lines.append(f"{ckind.value}{suffix}:\n\t{', '.join(vals)}")
    return "\n".join(lines)


def load_patient_data(sender: Union[int, str], app_data: Any, user_data: Tuple[Patient, Set[str]]) -> None:
    """Load selected patient data into the application."""
    patient: Patient = user_data[0]
    selected_files: Set[str] = user_data[1]
    
    if not selected_files:
        logger.info("No files selected for loading.")
        return
    
    # Load data and update UI
    logger.info("Starting to load selected data. Please wait...")
    data_mgr: DataManager = get_user_data(td_key="data_manager")
    data_mgr.load_all_dicom_data(patient, selected_files)
    fill_right_col_ptdata(patient)
    request_texture_update(texture_action_type="initialize")
    logger.info(f"Loaded {len(selected_files)} files for patient {patient.name}")


def _node_user_data(node: Node, parent_ud: Optional[Dict] = None) -> Dict[str, Any]:
    """Helper to create user_data from Node"""
    paths = [f.path for f in getattr(node, "file_objs", []) or []]
    ud = {
        "node": node,
        "files": paths,
        "children": [],
        "parent": parent_ud,
        "checkbox": None,
        "is_group": bool(node.children) or len(paths) != 1,
    }
    return ud


def _is_fully_checked(node_ud: Dict[str, Any]) -> bool:
    """Recursively check if a node and all its descendants are checked"""
    cb = node_ud.get("checkbox")
    if cb and not dpg.get_value(cb):
        return False
    return all(_is_fully_checked(c) for c in node_ud.get("children", []))


def _propagate_down(ud: Dict[str, Any], state: bool, checkbox_callback, selected_files: Set[str]) -> None:
    """Toggle every descendant checkbox and keep selection in sync"""
    for child in ud.get("children", []):
        cb = child.get("checkbox")
        if cb is not None and dpg.get_value(cb) != state:
            dpg.set_value(cb, state)
            fpaths = child.get("files", [])
            if state:
                selected_files.update(fpaths)
            else:
                selected_files.difference_update(fpaths)
            # recurse so selected_files and deeper nodes are updated
            checkbox_callback(cb, state, child)
        _propagate_down(child, state, checkbox_callback, selected_files)


def _update_ancestors(ud: Dict[str, Any], selected_files: Set[str]) -> None:
    """Recompute ancestor checkbox states based on descendants"""
    parent = ud.get("parent")
    while parent:
        p_cb = parent.get("checkbox")
        if p_cb:
            new_state = all(_is_fully_checked(c) for c in parent.get("children", []))
            if dpg.get_value(p_cb) != new_state:
                dpg.set_value(p_cb, new_state)
                parent_files = parent.get("files", [])
                if new_state:
                    selected_files.update(parent_files)
                else:
                    selected_files.difference_update(parent_files)
        parent = parent.get("parent")


def _create_checkbox_callback(selected_files: Set[str]):
    """Factory to create the checkbox callback"""
    callback_active = {"running": False}   # lock flag
    
    def checkbox_callback(sender: int, app_data: bool, user_data: Dict[str, Any]) -> None:
        # prevent re-entry
        if callback_active["running"]:
            return
        callback_active["running"] = True
        
        try:
            # update selected files set
            fpaths = user_data.get("files", [])
            if app_data: # Checked
                selected_files.update(fpaths)
            else: # Unchecked
                selected_files.difference_update(fpaths)
            
            # propagate down
            _propagate_down(user_data, app_data, checkbox_callback, selected_files)
            
            # update ancestors
            _update_ancestors(user_data, selected_files)
        finally:
            callback_active["running"] = False
    
    return checkbox_callback


def _count_subtree_files(n: Node) -> int:
    """Count all files in a node and its descendants"""
    total = len(getattr(n, "file_objs", []) or [])
    for c in n.children:
        total += _count_subtree_files(c)
    return total


def _render_node_inline(node: Node, parent_ud: Optional[Dict], checkbox_callback, dcm_view_cb) -> Dict[str, Any]:
    """Render a non-container node inline"""
    ud = _node_user_data(node, parent_ud)
    file_objs = getattr(node, "file_objs", []) or []
    num_files = len(file_objs)
    num_children = len(node.children or [])
    must_tree = (num_children > 1) or (num_files > 1)

    # bypass parent when it only wraps a single child and has no files
    if num_children == 1 and num_files == 0:
        return _render_node_inline(node.children[0], parent_ud, checkbox_callback, dcm_view_cb)
    
    if must_tree:
        with dpg.group(horizontal=True):
            cb = dpg.add_checkbox(callback=checkbox_callback, user_data=ud)
            ud["checkbox"] = cb

            files_count = num_files + sum(len(getattr(c, "file_objs", []) or []) for c in node.children)
            with dpg.tree_node(label=f"{node.label} ({files_count} files)", default_open=False):
                # direct files (each gets checkbox + button)
                for fobj in file_objs:
                    fobj: File
                    fmd: Optional[FileMetadata] = getattr(fobj, "file_metadata", None)
                    fpath = getattr(fobj, "path", None)
                    if not fpath:
                        continue
                    child_ud = {"node": None, "files": [fpath], "children": [], "parent": ud, "checkbox": None, "is_group": False}
                    with dpg.group(horizontal=True):
                        child_cb = dpg.add_checkbox(callback=checkbox_callback, user_data=child_ud)
                        child_ud["checkbox"] = child_cb
                        dpg.add_button(label=f"{node.label} - {basename(fpath)}", user_data=fpath, callback=dcm_view_cb)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(
                                (
                                    f"Label: {fmd.label or 'N/A'}\n"
                                    f"Name: {fmd.name or 'N/A'}\n"
                                    f"Description: {fmd.description or 'N/A'}\n"
                                    f"Date/Time: {_format_dcm_str_datetime(fmd.date, fmd.time) or 'N/A'}\n"
                                    f"Frame of Reference UID: {fmd.frame_of_reference_uid or 'N/A'}\n"
                                    f"Modality: {fmd.modality or 'N/A'}\n"
                                    f"SOP Instance UID: {fmd.sop_instance_uid or 'N/A'}\n"
                                    f"Series Instance UID: {fmd.series_instance_uid or 'N/A'}\n"
                                    f"File Path: {fpath}\n"
                                ) if fmd is not None else "No metadata available"
                            )
                    ud["children"].append(child_ud)

                # child nodes
                for child in node.children:
                    child_ud = _render_node_inline(child, ud, checkbox_callback, dcm_view_cb)
                    ud["children"].append(child_ud)

    else:
        # single file -> inline file row
        if num_files == 1:
            fobj: File = file_objs[0]
            fmd: Optional[FileMetadata] = getattr(fobj, "file_metadata", None)
            fpath = getattr(fobj, "path", None)
            if fpath:
                file_ud = {"node": None, "files": [fpath], "children": [], "parent": ud, "checkbox": None, "is_group": False}
                with dpg.group(horizontal=True):
                    fcb = dpg.add_checkbox(callback=checkbox_callback, user_data=file_ud)
                    file_ud["checkbox"] = fcb
                    dpg.add_button(label=f"{node.label} - {basename(fpath)}", user_data=fpath, callback=dcm_view_cb)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(
                            (
                                f"Label: {fmd.label or 'N/A'}\n"
                                f"Name: {fmd.name or 'N/A'}\n"
                                f"Description: {fmd.description or 'N/A'}\n"
                                f"Date/Time: {_format_dcm_str_datetime(fmd.date, fmd.time) or 'N/A'}\n"
                                f"Frame of Reference UID: {fmd.frame_of_reference_uid or 'N/A'}\n"
                                f"Modality: {fmd.modality or 'N/A'}\n"
                                f"SOP Instance UID: {fmd.sop_instance_uid or 'N/A'}\n"
                                f"Series Instance UID: {fmd.series_instance_uid or 'N/A'}\n"
                                f"File Path: {fpath}\n"
                            ) if fmd is not None else "No metadata available"
                        )
                ud["children"].append(file_ud)
        
        # add child inline if present
        if num_children == 1:
            child = node.children[0]
            child_ud = _render_node_inline(child, ud, checkbox_callback, dcm_view_cb)
            ud["children"].append(child_ud)

        # leaf: no files and no children
        else:
            cb = dpg.add_checkbox(callback=checkbox_callback, user_data=ud)
            ud["checkbox"] = cb

    return ud


def _aggregate_file_objs(nodes: List[Node]) -> List[Any]:
    """Aggregate all file objects from a list of nodes and their children"""
    out: List[Any] = []
    for n in nodes:
        out.extend(getattr(n, "file_objs", []) or [])
        for c in n.children:
            out.extend(getattr(c, "file_objs", []) or [])
    return out


def _build_dicom_nodes(patient: Patient) -> List[Node]:
    """Return four container Nodes:
       - Doses (children = dose nodes)
       - Plans (children = plan nodes)
       - Structure Sets (children = struct nodes)
       - Image Series (children = series nodes)

    Each leaf node references actual File objects in node.file_objs.
    """
    conf_mgr: ConfigManager = get_user_data("config_manager")
    modalities = conf_mgr.get_dicom_modalities()

    series_map: Dict[str, Node] = {}
    struct_map: Dict[str, Node] = {}
    plan_map: Dict[str, Node] = {}
    doses_grouped_by_plan: Dict[str, List[Any]] = {}   # plan_sopi -> [File,...]
    orphan_dose_files: List[Any] = []                  # dose files with no ref_plan

    # 1) classify files
    for file_obj in getattr(patient, "files", []):
        file_obj: File
        if not hasattr(file_obj, "file_metadata"):
            continue
        
        md: FileMetadata = file_obj.file_metadata
        if not md:
            continue
        
        # Basic metadata
        modality = (md.modality or "").upper()
        dt = _format_dcm_str_datetime(md.date, md.time)
        label = md.label or md.name or md.modality or md.sop_instance_uid or "Unknown"
        desc = md.description or ""
        
        if modality in modalities.get("image", set()) and md.series_instance_uid:
            s_uid = md.series_instance_uid
            series = series_map.setdefault(
                s_uid,
                Node(
                    kind=NodeType.IMAGE_SERIES,
                    label=md.description or label,
                    description=desc,
                    date_and_time=dt,
                    file_objs=[],
                    metadata={"modality": modality, "series_uid": s_uid, "sopi_to_file": {}},
                ),
            )
            series.file_objs.append(file_obj)
            series.metadata["sopi_to_file"][md.sop_instance_uid] = file_obj

        elif modality in modalities.get("rtstruct", set()):
            struct_map[md.sop_instance_uid] = Node(
                kind=NodeType.STRUCTURE_SET,
                label=label,
                description=desc,
                date_and_time=dt,
                file_objs=[file_obj],
                metadata={"ref_series": get_json_list(md.referenced_series_instance_uid_seq)},
            )

        elif modality in modalities.get("rtplan", set()):
            plan_map[md.sop_instance_uid] = Node(
                kind=NodeType.PLAN,
                label=label,
                description=desc,
                date_and_time=dt,
                file_objs=[file_obj],
                metadata={"ref_structs": get_json_list(md.referenced_structure_set_sopi_seq)},
            )

        elif modality in modalities.get("rtdose", set()):
            ref_plans = get_json_list(md.referenced_rt_plan_sopi_seq)
            if ref_plans:
                for ref in ref_plans:
                    doses_grouped_by_plan.setdefault(ref, []).append(file_obj)
            else:
                orphan_dose_files.append(file_obj)
    
    # 2) wire relationships: series -> struct, struct -> plan, plan -> dose (dose via grouping later)
    for struct_node in list(struct_map.values()):
        for series_uid in struct_node.metadata.get("ref_series", []):
            series_node = series_map.get(series_uid)
            if series_node and series_node not in struct_node.children:
                struct_node.children.append(series_node)

    for plan_node in list(plan_map.values()):
        for struct_sopi in plan_node.metadata.get("ref_structs", []):
            s_node = struct_map.get(struct_sopi)
            if s_node and s_node not in plan_node.children:
                plan_node.children.append(s_node)
    
    # 3) build dose nodes grouped by plan; attach plan node as child when available
    dose_children: List[Node] = []
    for plan_sopi, files in doses_grouped_by_plan.items():
        plan_node = plan_map.get(plan_sopi)
        label = f"Dose for Plan: '{plan_node.label}'" if plan_node else f"Dose for Plan {plan_sopi}"
        children: List[Node] = []
        if plan_node:
            # append the plan node as a child of the dose node so the dose tree drills into the plan
            children.append(plan_node)
        dose_node = Node(
            kind=NodeType.DOSE,
            label=label,
            description="Dose files grouped by referenced plan",
            date_and_time="",
            file_objs=list(files),
            metadata={"ref_plan": plan_sopi},
            children=children,
        )
        dose_children.append(dose_node)

    # orphan dose files become individual dose nodes
    for fobj in orphan_dose_files:
        fobj: File
        md = fobj.file_metadata
        dt = _format_dcm_str_datetime(md.date, md.time)
        label = md.label or md.name or "Dose"
        dn = Node(
            kind=NodeType.DOSE,
            label=label,
            description=md.description or "",
            date_and_time=dt,
            file_objs=[fobj],
            metadata={},
            children=[],
        )
        dose_children.append(dn)

    # 4) collect maps -> lists
    all_plan_nodes = list(plan_map.items())       # list of (sopi, node)
    all_struct_nodes = list(struct_map.items())   # (sopi, node)
    all_series_nodes = list(series_map.items())   # (series_uid, node)

    # 5) exclude plans that are referenced by any dose group (so they only appear under dose tree)
    referenced_plan_sopis = set(doses_grouped_by_plan.keys())
    plan_children = [node for sopi, node in all_plan_nodes if sopi not in referenced_plan_sopis]

    # exclude structs referenced by any plan (so they will appear under plans if referenced, otherwise here)
    referenced_struct_sopis = {s for p in plan_map.values() for s in p.metadata.get("ref_structs", [])}
    struct_children = [node for sopi, node in all_struct_nodes if sopi not in referenced_struct_sopis]

    # exclude series referenced by any struct
    referenced_series = {uid for s in struct_map.values() for uid in s.metadata.get("ref_series", [])}
    series_children = [node for uid, node in all_series_nodes if uid not in referenced_series]
    
    # 6) create category containers (aggregate file_objs for counts)
    containers: List[Node] = []

    if dose_children:
        containers.append(
            Node(
                kind=ContainerKind.DOSES,
                label="Doses",
                description="RT Dose Container\nMay contain referenced RT Plan(s), Structure Set(s), and Image Series Group(s)",
                date_and_time="",
                file_objs=_aggregate_file_objs(dose_children),
                metadata=None,
                children=dose_children,
            )
        )

    if plan_children:
        containers.append(
            Node(
                kind=ContainerKind.PLANS,
                label="Plans",
                description="RT Plan Container\nMay contain referenced Structure Set(s) and Image Series Group(s)",
                date_and_time="",
                file_objs=_aggregate_file_objs(plan_children),
                metadata=None,
                children=plan_children,
            )
        )

    if struct_children:
        containers.append(
            Node(
                kind=ContainerKind.STRUCTURE_SETS,
                label="Structure Sets",
                description="Structure Set Container\nMay contain referenced Image Series Group(s)",
                date_and_time="",
                file_objs=_aggregate_file_objs(struct_children),
                metadata=None,
                children=struct_children,
            )
        )

    if series_children:
        containers.append(
            Node(
                kind=ContainerKind.IMAGE_SERIES_GROUPS,
                label="Image Series Groups",
                description="Image Series Container",
                date_and_time="",
                file_objs=_aggregate_file_objs(series_children),
                metadata=None,
                children=series_children,
            )
        )

    return containers

