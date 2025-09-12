from pydicom.tag import Tag


class DicomTags:
    # General tags
    patient_id = Tag(0x0010, 0x0020)
    patients_name = Tag(0x0010, 0x0010)
    frame_of_reference_uid = Tag(0x0020, 0x0052)
    modality = Tag(0x0008, 0x0060)
    dose_summation_type = Tag(0x3004, 0x000A)
    series_instance_uid = Tag(0x0020, 0x000E)
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
    
    @property
    def label_tags(self):
        return [self.rt_plan_label, self.structure_set_label, self.rt_image_label]

    @property
    def name_tags(self):
        return [self.rt_plan_name, self.structure_set_name, self.rt_image_name]

    @property
    def description_tags(self):
        return [
            self.rt_dose_comment,
            self.image_comments,
            self.rt_plan_description,
            self.structure_set_description,
            self.series_description,
            self.rt_image_description,
            self.study_description,
        ]

    @property
    def date_tags(self):
        return [
            self.rt_plan_date,
            self.structure_set_date,
            self.content_date,
            self.series_date,
            self.study_date,
        ]

    @property
    def time_tags(self):
        return [
            self.rt_plan_time,
            self.structure_set_time,
            self.content_time,
            self.series_time,
            self.study_time,
        ]

    @property
    def link_worker_tags(self):
        return [
            self.patient_id,
            self.patients_name,
            self.frame_of_reference_uid,
            self.modality,
            self.dose_summation_type,
            self.series_instance_uid,
            self.sop_class_uid,
            self.sop_instance_uid,
            self.referenced_sop_class_uid,
            self.referenced_sop_instance_uid,
            self.referenced_rt_plan_sequence,
            self.referenced_structure_set_sequence,
            self.referenced_dose_sequence,
            self.referenced_frame_of_reference_sequence,
            self.rt_referenced_study_sequence,
            self.rt_referenced_series_sequence,
        ] + self.label_tags + self.name_tags + self.description_tags + self.date_tags + self.time_tags
    
    @staticmethod
    def tag_to_str(tag: Tag) -> str:
        """Return a string representation of a Tag."""
        return f"({tag.group:04X},{tag.element:04X})"
