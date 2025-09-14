from pydicom.tag import Tag


class DicomTags:
    # General tags
    patient_id = Tag(0x0010, 0x0020)
    patients_name = Tag(0x0010, 0x0010)
    frame_of_reference_uid = Tag(0x0020, 0x0052)
    modality = Tag(0x0008, 0x0060)
    dose_summation_type = Tag(0x3004, 0x000A)
    series_instance_uid = Tag(0x0020, 0x000E)
    study_instance_uid = Tag(0x0020, 0x000D)
    sop_class_uid = Tag(0x0008, 0x0016)
    sop_instance_uid = Tag(0x0008, 0x0018)
    referenced_sop_class_uid = Tag(0x0008, 0x1150)
    referenced_sop_instance_uid = Tag(0x0008, 0x1155)
    referenced_rt_plan_sequence = Tag(0x300C, 0x0002)
    referenced_structure_set_sequence = Tag(0x300C, 0x0060)
    referenced_dose_sequence = Tag(0x300C, 0x0080)
    referenced_frame_of_reference_sequence = Tag(0x3006, 0x0010)
    rt_referenced_study_sequence = Tag(0x3006, 0x0012)
    rt_referenced_series_sequence = Tag(0x3006, 0x0014)
    
    # Label tags
    rt_plan_label = Tag(0x300A, 0x0002)
    structure_set_label = Tag(0x3006, 0x0002)
    rt_image_label = Tag(0x3002, 0x0002)
    
    # Name tags
    rt_plan_name = Tag(0x300A, 0x0003)
    structure_set_name = Tag(0x3006, 0x0004)
    rt_image_name = Tag(0x3002, 0x0003)

    # Comment tags
    rt_dose_comment = Tag(0x3004, 0x0006)
    image_comments = Tag(0x0020, 0x4000)
    
    # Description tags
    rt_plan_description = Tag(0x300A, 0x0004)
    structure_set_description = Tag(0x3006, 0x0006)
    series_description = Tag(0x0008, 0x103E)
    rt_image_description = Tag(0x3002, 0x0004)
    study_description = Tag(0x0008, 0x1030)

    # Date tags
    rt_plan_date = Tag(0x300A, 0x0006)
    structure_set_date = Tag(0x3006, 0x0008)
    content_date = Tag(0x0008, 0x0023)
    series_date = Tag(0x0008, 0x0021)
    study_date = Tag(0x0008, 0x0020)

    # Time tags
    rt_plan_time = Tag(0x300A, 0x0007)
    structure_set_time = Tag(0x3006, 0x0009)
    content_time = Tag(0x0008, 0x0033)
    series_time = Tag(0x0008, 0x0031)
    study_time = Tag(0x0008, 0x0030)

    label_tags = [
        rt_plan_label,
        structure_set_label,
        rt_image_label
    ]

    name_tags = [
        rt_plan_name,
        structure_set_name,
        rt_image_name
    ]
    
    description_tags = [
        rt_dose_comment,
        image_comments,
        rt_plan_description,
        structure_set_description,
        series_description,
        rt_image_description,
        study_description,
    ]
    
    date_tags = [
        rt_plan_date,
        structure_set_date,
        content_date,
        series_date,
        study_date,
    ]
    
    time_tags = [
        rt_plan_time,
        structure_set_time,
        content_time,
        series_time,
        study_time,
    ]

    link_worker_tags = [
        patient_id,
        patients_name,
        frame_of_reference_uid,
        modality,
        dose_summation_type,
        series_instance_uid,
        sop_class_uid,
        sop_instance_uid,
        referenced_sop_class_uid,
        referenced_sop_instance_uid,
        referenced_rt_plan_sequence,
        referenced_structure_set_sequence,
        referenced_dose_sequence,
        referenced_frame_of_reference_sequence,
        rt_referenced_study_sequence,
        rt_referenced_series_sequence,
    ] + label_tags + name_tags + description_tags + date_tags + time_tags
    
    @staticmethod
    def tag_to_str(tag: Tag) -> str:
        """Return a string representation of a Tag."""
        return f"({tag.group:04X},{tag.element:04X})"
