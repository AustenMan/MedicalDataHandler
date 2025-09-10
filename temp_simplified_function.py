def _display_patient_files_table(sender: Union[str, int], app_data: Any, user_data: "Patient") -> None:
    patient = get_patient_full(user_data.id)
    if not patient:
        logger.error("Patient not found / could not load.")
        return

    g = build_patient_graph(patient)
    reg = CheckboxRegistry()
    size_dict = get_user_data(td_key="size_dict")
    toggle_data_window(force_show=True, label=f"Data for Patient: {(patient.mrn, patient.name)}")
    _create_new_data_table()
    tag_data_table = get_tag("data_table")

    dpg.add_table_column(parent=tag_data_table, label="Select", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Data Group", width_fixed=True) 
    dpg.add_table_column(parent=tag_data_table, label="Label/Name", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Description", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Date/Time", width_fixed=True)
    dpg.add_table_column(parent=tag_data_table, label="Components", width_fixed=True)

    with dpg.table_row(parent=tag_data_table):
        with dpg.group(horizontal=True):
            dpg.add_button(label="Go Back", width=size_dict["button_width"], height=size_dict["button_height"], callback=_create_ptobj_table)
            dpg.add_button(label="Load Selected Data", width=size_dict["button_width"], height=size_dict["button_height"], 
                          callback=wrap_with_cleanup(_load_selected_data), user_data=(patient, g, reg))
    
    ss_mgr: SharedStateManager = get_user_data(td_key="shared_state_manager")
    dcm_view_cb = lambda s, a, u: ss_mgr.submit_action(partial(create_popup_dicom_inspection, s, a, u))
    
    def hierarchical_checkbox_callback(sender: int, app_data: bool, user_data: Dict[str, Any]) -> None:
        if not hasattr(hierarchical_checkbox_callback, '_suppress'):
            hierarchical_checkbox_callback._suppress = False
        if hierarchical_checkbox_callback._suppress:
            return
        try:
            hierarchical_checkbox_callback._suppress = True
            def find_and_update(node: Dict[str, Any]) -> bool:
                if node.get('cbox') == sender:
                    dpg.set_value(sender, app_data)
                    for child in node.get('children', []):
                        set_subtree(child, app_data)
                    return True
                for child in node.get('children', []):
                    if find_and_update(child):
                        states = [dpg.get_value(c['cbox']) for c in node['children'] if c.get('cbox')]
                        if states and node.get('cbox'):
                            dpg.set_value(node['cbox'], all(states))
                        return True
                return False
            def set_subtree(node: Dict[str, Any], value: bool):
                if node.get('cbox'):
                    dpg.set_value(node['cbox'], value)
                for child in node.get('children', []):
                    set_subtree(child, value)
            find_and_update(user_data)
        finally:
            hierarchical_checkbox_callback._suppress = False
    
    def get_metadata_info(item: Dict[str, Any]) -> Tuple[str, str, str, str]:
        path = item.get("path", "")
        if not path or path not in g.path_to_md:
            return "N/A", "N/A", "N/A", "N/A"
        md = g.path_to_md[path]
        label = md.label or "N/A"
        name = md.name or "N/A"
        description = md.description or "N/A"
        date_str, time_str = md.date or "", md.time or ""
        if date_str and time_str:
            try:
                datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            except:
                datetime_str = f"{date_str} {time_str}"
        elif date_str:
            try:
                datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            except:
                datetime_str = date_str
        else:
            datetime_str = "N/A"
        return label, name, description, datetime_str
    
    def add_item_hierarchy(parent_dict: Dict[str, Any], item: Dict[str, Any], item_type: str, all_paths: List[str]) -> None:
        item_dict = {'cbox': None, 'children': []}
        item_dict['cbox'] = dpg.add_checkbox(
            label=build_dicom_label(item, item_type), 
            callback=hierarchical_checkbox_callback, 
            user_data=parent_dict
        )
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(build_dicom_tooltip(item))
        
        key_funcs = {"RD": k_rd_plan, "RP": k_rp, "RS": k_rs, "IMG": k_img}
        if item_type in key_funcs:
            if item_type == "IMG":
                suid = item.get("series_uid", "")
                reg.register_item_link(item_dict['cbox'], key_funcs[item_type](suid), g.collect_paths_for_series(suid))
                all_paths.extend(g.collect_paths_for_series(suid))
            else:
                reg.register_item_link(item_dict['cbox'], key_funcs[item_type](item.get("sopi", "")), [item["path"]])
                all_paths.append(item["path"])
        
        parent_dict['children'].append(item_dict)
        return item_dict

    # Build hierarchical data groups (RTD > RTP > RTS > Images priority)
    top_level_groups = []
    
    # RTDOSE Plan groups
    for rtdose in g.doses_plan:
        label, name, description, datetime_str = get_metadata_info(rtdose)
        ref_plans = rtdose.get("ref_plans", [])
        ref_structs = rtdose.get("ref_structs", [])
        total_images = sum(len(g.collect_paths_for_series(suid)) 
                          for plan_sopi in ref_plans if (plan := g.plans_by_sopi.get(plan_sopi))
                          for struct_sopi in plan.get("ref_structs", []) if (struct := g.structs_by_sopi.get(struct_sopi))
                          for suid in struct.get("ref_series", []))
        components = f"1 Dose, {len(ref_plans)} Plans, {len(ref_structs)} Structs, {total_images} Images"
        
        def build_hierarchy(group_dict: Dict[str, Any], all_paths: List[str]) -> None:
            dose_dict = add_item_hierarchy(group_dict, rtdose, "RD", all_paths)
            for plan_sopi in ref_plans:
                if plan := g.plans_by_sopi.get(plan_sopi):
                    with dpg.tree_node(label=build_dicom_label(plan, "RP")):
                        plan_dict = add_item_hierarchy(dose_dict, plan, "RP", all_paths)
                        for struct_sopi in plan.get("ref_structs", []):
                            if struct := g.structs_by_sopi.get(struct_sopi):
                                with dpg.tree_node(label=build_dicom_label(struct, "RS")):
                                    struct_dict = add_item_hierarchy(plan_dict, struct, "RS", all_paths)
                                    for suid in struct.get("ref_series", []):
                                        if img_series := g.images_by_series.get(suid):
                                            add_item_hierarchy(struct_dict, {**img_series, "series_uid": suid}, "IMG", all_paths)
        
        top_level_groups.append(("RT Dose (Plan)", rtdose, label, name, description, datetime_str, components, build_hierarchy))
    
    # RTDOSE Beam groups
    for plan_sopi, doses in sorted(g.doses_beam_groups.items()):
        first_dose = doses[0] if doses else {}
        label, name, description, datetime_str = get_metadata_info(first_dose)
        components = f"{len(doses)} Beam Doses"
        
        def build_hierarchy(group_dict: Dict[str, Any], all_paths: List[str]) -> None:
            with dpg.tree_node(label=f"Beam Doses ({len(doses)})"):
                for dose in doses:
                    with dpg.group(horizontal=True):
                        dose_dict = {'cbox': None, 'children': []}
                        dose_dict['cbox'] = dpg.add_checkbox(callback=hierarchical_checkbox_callback, user_data=group_dict)
                        dpg.add_button(label=build_dicom_label(dose, "Beam: "), user_data=dose["path"], callback=dcm_view_cb)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(build_dicom_tooltip(dose))
                    reg.register_file_checkbox(dose_dict['cbox'], dose["path"])
                    all_paths.append(dose["path"])
                    group_dict['children'].append(dose_dict)
        
        top_level_groups.append(("RT Dose (Beams)", first_dose, label, name, description, datetime_str, components, build_hierarchy))
    
    # Standalone RTPLAN groups
    used_plan_sopis = set()
    for rtdose in g.doses_plan:
        used_plan_sopis.update(rtdose.get("ref_plans", []))
    for plan_sopi in g.doses_beam_groups:
        used_plan_sopis.add(plan_sopi)
    
    for plan_sopi, plan in sorted(g.plans_by_sopi.items()):
        if plan_sopi not in used_plan_sopis:
            label, name, description, datetime_str = get_metadata_info(plan)
            ref_structs = plan.get("ref_structs", [])
            total_images = sum(len(g.collect_paths_for_series(suid)) 
                              for struct_sopi in ref_structs if (struct := g.structs_by_sopi.get(struct_sopi))
                              for suid in struct.get("ref_series", []))
            components = f"1 Plan, {len(ref_structs)} Structs, {total_images} Images"
            
            def build_hierarchy(group_dict: Dict[str, Any], all_paths: List[str]) -> None:
                plan_dict = add_item_hierarchy(group_dict, plan, "RP", all_paths)
                if ref_structs:
                    with dpg.tree_node(label=f"Referenced Structs ({len(ref_structs)})"):
                        for struct_sopi in ref_structs:
                            if struct := g.structs_by_sopi.get(struct_sopi):
                                with dpg.tree_node(label=build_dicom_label(struct, "RS")):
                                    struct_dict = add_item_hierarchy(plan_dict, struct, "RS", all_paths)
                                    for suid in struct.get("ref_series", []):
                                        if img_series := g.images_by_series.get(suid):
                                            add_item_hierarchy(struct_dict, {**img_series, "series_uid": suid}, "IMG", all_paths)
            
            top_level_groups.append(("RT Plan", plan, label, name, description, datetime_str, components, build_hierarchy))
    
    # Standalone RTSTRUCT groups
    used_struct_sopis = set()
    for plan in g.plans_by_sopi.values():
        used_struct_sopis.update(plan.get("ref_structs", []))
    
    for struct_sopi, struct in sorted(g.structs_by_sopi.items()):
        if struct_sopi not in used_struct_sopis:
            label, name, description, datetime_str = get_metadata_info(struct)
            ref_series = struct.get("ref_series", [])
            total_images = sum(len(g.collect_paths_for_series(suid)) for suid in ref_series)
            components = f"1 Struct, {total_images} Images"
            
            def build_hierarchy(group_dict: Dict[str, Any], all_paths: List[str]) -> None:
                struct_dict = add_item_hierarchy(group_dict, struct, "RS", all_paths)
                if ref_series:
                    with dpg.tree_node(label=f"Referenced Images ({len(ref_series)} series)"):
                        for suid in ref_series:
                            if img_series := g.images_by_series.get(suid):
                                add_item_hierarchy(struct_dict, {**img_series, "series_uid": suid}, "IMG", all_paths)
            
            top_level_groups.append(("RT Struct", struct, label, name, description, datetime_str, components, build_hierarchy))
    
    # Standalone Image groups
    used_series_uids = set()
    for struct in g.structs_by_sopi.values():
        used_series_uids.update(struct.get("ref_series", []))
    
    for series_uid, entry in sorted(g.images_by_series.items()):
        if series_uid not in used_series_uids:
            first_file_path = entry["files"][0][1] if entry["files"] else ""
            label, name, description, datetime_str = get_metadata_info({"path": first_file_path})
            if label == "N/A":
                label = entry.get("label", "N/A")
            if name == "N/A":
                name = entry.get("name", "N/A")
            if description == "N/A":
                description = entry.get("description", "N/A")
            components = f"{len(entry['files'])} Images"
            
            def build_hierarchy(group_dict: Dict[str, Any], all_paths: List[str]) -> None:
                img_dict = add_item_hierarchy(group_dict, {**entry, "series_uid": series_uid}, "IMG", all_paths)
                with dpg.tree_node(label=f"Individual Files ({len(entry['files'])})"):
                    for sopi, path in entry["files"]:
                        with dpg.group(horizontal=True):
                            file_dict = {'cbox': None, 'children': []}
                            file_dict['cbox'] = dpg.add_checkbox(callback=hierarchical_checkbox_callback, user_data=img_dict)
                            dpg.add_button(label=f"{entry['modality']}: {sopi}", user_data=path, callback=dcm_view_cb)
                            with dpg.tooltip(dpg.last_item()):
                                dpg.add_text(f"Path: {path}")
                        reg.register_file_checkbox(file_dict['cbox'], path)
                        img_dict['children'].append(file_dict)
            
            top_level_groups.append(("Image Series", {"path": first_file_path}, label, name, description, datetime_str, components, build_hierarchy))
    
    # Create table rows
    for group_type, primary_item, label, name, description, datetime_str, components, hierarchy_builder in top_level_groups:
        with dpg.table_row(parent=tag_data_table):
            with dpg.group():
                group_dict = {'cbox': None, 'children': []}
                group_dict['cbox'] = dpg.add_checkbox(label=group_type, callback=hierarchical_checkbox_callback, user_data=group_dict)
                with dpg.tree_node(label=components, default_open=False):
                    all_paths = []
                    hierarchy_builder(group_dict, all_paths)
                    if all_paths:
                        reg.register_master(group_dict['cbox'], all_paths)
            
            dpg.add_text(group_type)
            dpg.add_text(f"{label} / {name}")
            dpg.add_text(description[:50] + "..." if len(description) > 50 else description)
            dpg.add_text(datetime_str)
            dpg.add_text(components)