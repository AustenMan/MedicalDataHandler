from __future__ import annotations


import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Set, Optional, Iterable, Callable


import dearpygui.dearpygui as dpg


from mdh_app.dpg_components.core.utils import get_user_data
from mdh_app.utils.general_utils import get_json_list


if TYPE_CHECKING:
    from mdh_app.database.models import Patient, FileMetadata
    from mdh_app.managers.config_manager import ConfigManager
    

logger = logging.getLogger(__name__)


class PatientGraph:
    """
    In-memory graph of a patient's DICOM relationships for UI + loading.
    """
    def __init__(self) -> None:
        # IMAGES
        # series_uid -> { "modality": str, "files": [(sop_instance_uid, path), ...] }
        self.images_by_series: Dict[str, Dict[str, Any]] = {}

        # STRUCTS
        # struct_sopi -> { "path": str, "modality": str, "ref_series": [series_uid, ...] }
        self.structs_by_sopi: Dict[str, Dict[str, Any]] = {}

        # PLANS
        # plan_sopi -> { "path": str, "modality": str, "ref_structs": [struct_sopi, ...], "ref_series": [series_uid, ...] }
        self.plans_by_sopi: Dict[str, Dict[str, Any]] = {}

        # DOSE (plan-type)
        # list of { "sopi": str, "path": str, "modality": str, "dose_type": str, "ref_plans": [plan_sopi,...], "ref_structs": [...], "ref_doses": [...] }
        self.doses_plan: List[Dict[str, Any]] = []

        # DOSE (beam-type) GROUPS
        # plan_sopi -> [ {same shape as dose_plan item}, ... ]
        self.doses_beam_groups: Dict[str, List[Dict[str, Any]]] = {}

        # Quick path index to metadata
        self.path_to_md: Dict[str, FileMetadata] = {}
    
    def collect_paths_for_series(self, series_uid: str) -> List[str]:
        return _collect_paths_for_series(self, series_uid)
    
    def collect_paths_for_struct(self, struct_sopi: str) -> List[str]:
        return _collect_paths_for_struct(self, struct_sopi)
    
    def collect_paths_for_plan(self, plan_sopi: str) -> List[str]:
        return _collect_paths_for_plan(self, plan_sopi)
    
    def collect_paths_for_dose_plan_item(self, dose_item: Dict[str, Any]) -> List[str]:
        return _collect_paths_for_dose_plan_item(self, dose_item)
    
    def collect_paths_for_dose_beam_group(self, plan_sopi: str) -> List[str]:
        return _collect_paths_for_dose_beam_group(self, plan_sopi)
    

def build_patient_graph(patient: Patient) -> PatientGraph:
    """
    Build a normalized view of the patient's DICOM data from ORM rows.
    Assumes patient.files and file.file_metadata are eagerly loaded.
    """
    g = PatientGraph()
    
    conf_mgr: ConfigManager = get_user_data("config_manager")
    modality_dict = conf_mgr.get_dicom_modalities()
    IMAGE_MODALITIES: Set[str]  = modality_dict.get("image", set())
    STRUCT_MODALITIES: Set[str] = modality_dict.get("structure", set())
    PLAN_MODALITIES: Set[str]   = modality_dict.get("plan", set())
    DOSE_MODALITIES: Set[str]   = modality_dict.get("dose", set())
    
    for f in getattr(patient, "files", []):
        md: Optional[FileMetadata] = getattr(f, "file_metadata", None)
        if not md:
            continue

        path = f.path
        g.path_to_md[path] = md
        modality = md.modality or ""
        sopi = md.sop_instance_uid or ""
        label = md.label or ""
        name = md.name or ""
        description = md.description or ""
        date = md.date or ""
        time = md.time or ""
        
        # Match modality case-insensitively
        upper_mod = modality.upper()
        
        # IMAGES
        if upper_mod in IMAGE_MODALITIES and md.series_instance_uid:
            series_default = {"modality": modality, "files": [], "label": label, "name": name, "description": description, "date": date, "time": time}
            e = g.images_by_series.setdefault(md.series_instance_uid, series_default)
            # Keep modality consistent if unknown
            if e["modality"] is None:
                e["modality"] = modality
            if not e["label"]:
                e["label"] = label
            if not e["name"]:
                e["name"] = name
            if not e["description"]:
                e["description"] = description
            if not e["date"]:
                e["date"] = date
            if not e["time"]:
                e["time"] = time
            e["files"].append((sopi, path))
            continue

        # STRUCTS
        if upper_mod in STRUCT_MODALITIES:
            g.structs_by_sopi[sopi] = {
                "path": path,
                "modality": modality,
                "label": label,
                "name": name,
                "description": description,
                "date": date,
                "time": time,
                "ref_series": get_json_list(md.referenced_series_instance_uid_seq),
            }
            continue

        # PLANS
        if upper_mod in PLAN_MODALITIES:
            ref_structs = get_json_list(md.referenced_structure_set_sopi_seq)
            g.plans_by_sopi[sopi] = {
                "path": path,
                "modality": modality,
                "label": label,
                "name": name,
                "description": description,
                "date": date,
                "time": time,
                "ref_structs": ref_structs,
                "ref_series": [], # derive from referenced structs (filled after pass)
            }
            continue

        # DOSE
        if upper_mod in DOSE_MODALITIES:
            dose_type = (md.dose_summation_type or "").lower()  # 'beam' vs 'plan' (or blank)
            dose_entry = {
                "sopi": sopi,
                "path": path,
                "modality": modality,
                "label": label,
                "name": name,
                "description": description,
                "date": date,
                "time": time,
                "dose_type": dose_type,
                "ref_doses": get_json_list(md.referenced_dose_sopi_seq),
                "ref_plans": get_json_list(md.referenced_rt_plan_sopi_seq),
                "ref_structs": [], # derive from referenced plans (filled after pass)
                "ref_series": [],  # derive from referenced structs (filled after pass)
            }
            if dose_type == "beam" and dose_entry["ref_plans"]:
                for plan_sopi in dose_entry["ref_plans"]:
                    g.doses_beam_groups.setdefault(plan_sopi, []).append(dose_entry)
            else:
                g.doses_plan.append(dose_entry)

    # After building base, derive plan -> image-series via its referenced RTSTRUCTs
    for plan_sopi, plan in g.plans_by_sopi.items():
        derived_series: Set[str] = set()
        for struct_sopi in plan["ref_structs"]:
            s = g.structs_by_sopi.get(struct_sopi)
            if not s:
                continue
            derived_series.update(s["ref_series"])
        plan["ref_series"] = sorted(derived_series)
    
    # Derive dose -> struct/image-series via referenced plans
    for dose in g.doses_plan:
        derived_structs: Set[str] = set()
        derived_series: Set[str] = set()
        for plan_sopi in dose["ref_plans"]:
            p = g.plans_by_sopi.get(plan_sopi)
            if not p:
                continue
            derived_structs.update(p["ref_structs"])
            derived_series.update(p["ref_series"])
        dose["ref_structs"] = sorted(derived_structs)
        dose["ref_series"] = sorted(derived_series)

    return g


########################################
##### File path collection helpers #####
########################################


def _collect_paths_for_series(g: PatientGraph, series_uid: str) -> List[str]:
    return [p for _sopi, p in g.images_by_series.get(series_uid, {}).get("files", [])]


def _collect_paths_for_struct(g: PatientGraph, struct_sopi: str) -> List[str]:
    """Struct checkbox selects itself + all image files of referenced series."""
    s = g.structs_by_sopi.get(struct_sopi)
    paths: List[str] = []
    if s:
        paths.append(s["path"])
        for series_uid in s["ref_series"]:
            paths.extend(_collect_paths_for_series(g, series_uid))
    return list(dict.fromkeys(paths))  # dedupe, keep order


def _collect_paths_for_plan(g: PatientGraph, plan_sopi: str) -> List[str]:
    """Plan checkbox selects itself + all structs it references + their image series."""
    p = g.plans_by_sopi.get(plan_sopi)
    paths: List[str] = []
    if p:
        paths.append(p["path"])
        for struct_sopi in p["ref_structs"]:
            paths.extend(_collect_paths_for_struct(g, struct_sopi))
    return list(dict.fromkeys(paths))


def _collect_paths_for_dose_plan_item(g: PatientGraph, dose_item: Dict[str, Any]) -> List[str]:
    """Plan dose: select itself + linked plans (and their structs/images)."""
    paths = [dose_item["path"]]
    for plan_sopi in dose_item["ref_plans"]:
        paths.extend(_collect_paths_for_plan(g, plan_sopi))
    return list(dict.fromkeys(paths))


def _collect_paths_for_dose_beam_group(g: PatientGraph, plan_sopi: str) -> List[str]:
    """Beam dose group node: all beam dose files in group + underlying plans/structs/images."""
    paths: List[str] = []
    for dose_item in g.doses_beam_groups.get(plan_sopi, []):
        paths.append(dose_item["path"])
        paths.extend(_collect_paths_for_dose_plan_item(g, dose_item))
    return list(dict.fromkeys(paths))


#######################################
######## Checkbox sync helpers ########
#######################################


# logical item keys (strings are enough; keep short & stable)
def k_file(path: str) -> str:          return f"F|{path}"
def k_img(series_uid: str) -> str:     return f"I|{series_uid}"
def k_rs(sopi: str) -> str:            return f"S|{sopi}"
def k_rp(sopi: str) -> str:            return f"P|{sopi}"
def k_rd_beams(plan_sopi: str) -> str: return f"B|{plan_sopi}"
def k_rd_plan(sopi: str) -> str:       return f"D|{sopi}"


class CheckboxRegistry:
    """
    Manages state and relationships between UI checkboxes.

    This registry ensures that all master checkboxes are correctly updated when
    their underlying file states change, regardless of what initiated the change.
    """

    def __init__(self) -> None:
        self.item_to_cbs: Dict[str, Set[int]] = defaultdict(set)
        self.cb_represents: Dict[int, Set[str]] = {}
        self.cb_controls: Dict[int, Set[str]] = {}
        self.cb_files: Dict[int, Set[str]] = {}
        self.master_cb_files: Dict[int, Set[str]] = {}
        # Reverse map to find all masters associated with a given file path.
        self.file_to_masters: Dict[str, Set[int]] = defaultdict(set)
        self._suppress: bool = False

    def _link(
        self,
        cb_id: int,
        represents: Iterable[str],
        controls: Iterable[str],
        files: Iterable[str],
        is_master: bool = False,
    ) -> None:
        rset = set(represents)
        cset = set(controls)
        fset = set(files)

        self.cb_represents[cb_id] = rset
        self.cb_controls[cb_id] = cset
        self.cb_files[cb_id] = fset

        for item in rset:
            self.item_to_cbs[item].add(cb_id)

        if is_master:
            self.master_cb_files[cb_id] = fset

    # ---- Public Registration API ----

    def register_master(self, cb_id: int, file_paths: Iterable[str]) -> None:
        """Registers a master checkbox that controls a group of files."""
        file_paths = list(file_paths)
        file_items = [k_file(p) for p in file_paths]

        # Populate the file -> masters reverse map.
        for p in file_paths:
            self.file_to_masters[p].add(cb_id)

        self._link(cb_id, represents=[], controls=file_items, files=file_paths, is_master=True)

    def register_file_checkbox(self, cb_id: int, path: str) -> None:
        """Registers a leaf checkbox for a single file."""
        item = k_file(path)
        self._link(cb_id, represents={item}, controls={item}, files={path})

    def register_item_link(self, cb_id: int, item_key: str, file_paths: Iterable[str]) -> None:
        """Registers a checkbox that represents a logical DICOM item (e.g., an image series)."""
        file_paths = list(file_paths)
        file_items = [k_file(p) for p in file_paths]
        
        # Series checkbox represents itself and files.
        self.cb_represents[cb_id] = {item_key, *file_items}
        self.cb_controls[cb_id] = {item_key, *file_items}   # series drives files
        self.cb_files[cb_id] = set(file_paths)

        for item in self.cb_represents[cb_id]:
            self.item_to_cbs[item].add(cb_id)

    # ---- Callback Logic ----

    def on_change(self, sender: int, app_data: bool, user_data: Dict[str, Any]) -> None:
        if self._suppress:
            return
        try:
            self._suppress = True

            def update(node: Dict[str, Any]) -> bool:
                """Return True if sender found in this subtree."""
                if node["cbox"] == sender:
                    dpg.set_value(sender, app_data)
                    # cascade down
                    for child in node["children"]:
                        set_subtree(child, app_data)
                    return True
                for child in node["children"]:
                    if update(child):
                        # recompute this node’s state based on children
                        states = [dpg.get_value(c["cbox"]) for c in node["children"]]
                        dpg.set_value(node["cbox"], all(states))
                        return True
                return False

            def set_subtree(node: Dict[str, Any], value: bool):
                dpg.set_value(node["cbox"], value)
                for child in node["children"]:
                    set_subtree(child, value)

            update(user_data)

        finally:
            self._suppress = False

    def _update_specific_masters(self, masters: Iterable[int]) -> None:
        """Updates the state of master checkboxes based on their children's states."""
        for m in masters:
            files = self.master_cb_files.get(m)
            if not files:
                continue
            
            states = []
            for p in files:
                cbs = self.item_to_cbs.get(k_file(p))
                if cbs:
                    any_cb = next(iter(cbs))
                    states.append(bool(dpg.get_value(any_cb)))

            # If not all child checkboxes are registered or found, uncheck the master.
            if len(states) != len(files):
                if dpg.get_value(m):
                    dpg.set_value(m, False)
                continue

            all_true = all(states)
            if dpg.get_value(m) != all_true:
                dpg.set_value(m, all_true)


def add_file_checkbox(path: str, reg: CheckboxRegistry, label: str = "") -> int:
    """Adds a standard file checkbox to the UI."""
    cb = dpg.add_checkbox(label=label, callback=lambda s, a: reg.on_change(s, a))
    reg.register_file_checkbox(cb, path)
    return cb


def add_master_checkbox(label: str, file_paths: Iterable[str], reg: CheckboxRegistry) -> int:
    """Adds a master checkbox to the UI."""
    cb = dpg.add_checkbox(label=label, callback=lambda s, a: reg.on_change(s, a))
    reg.register_master(cb, file_paths)
    return cb


def add_item_link_checkbox(
    label: str, tooltip: str, item_type: str, item_value: str, file_paths: Iterable[str], reg: CheckboxRegistry, dcm_view_cb: Callable,
) -> int:
    """Adds a logical item checkbox (e.g., for an image series) to the UI."""
    key_map = {
        "img": k_img,
        "rs": k_rs,
        "rp": k_rp,
        "rd_beams": k_rd_beams,
        "rd_plan": k_rd_plan,
    }
    if item_type not in key_map:
        raise ValueError(f"Invalid item type: {item_type}")

    item_key = key_map[item_type](item_value)

    with dpg.group(horizontal=True):
        cb = dpg.add_checkbox(callback=lambda s, a: reg.on_change(s, a))
        if len(file_paths) == 1:
            dpg.add_button(
                label=label,
                user_data=file_paths[0],
                callback=dcm_view_cb,
            )
        else:
            dpg.add_text(label)
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(tooltip)
    reg.register_item_link(cb, item_key, list(file_paths))
    return cb

