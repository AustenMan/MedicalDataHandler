<p align="center">
  <img src="src/resources/assets/MDH_Logo_Credit_DALL-E.png" alt="MedicalDataHandler_Logo" width="200">
</p>

<h1 align="center">MedicalDataHandler</h1>  
<p align="center"><em>A Research-Oriented GUI for DICOM Data Management</em></p>
<p align="center"><em><a href="https://github.com/AustenMan/MedicalDataHandler/releases"><strong>🔗 Only looking for the latest EXE? Click here!</strong></a></em></p>

---

**Contributors:**  
Austen Maniscalco, Yang Park, Andrew Godley, Mu-Han Lin, Steve Jiang, and Dan Nguyen  

**Affiliation:**  
Medical Artificial Intelligence and Automation Laboratory, Department of Radiation Oncology, University of Texas Southwestern Medical Center, Dallas, TX, 75390, USA  

**Contact:**  
Austen Maniscalco ([Austen.Maniscalco@UTSouthwestern.edu](mailto:Austen.Maniscalco@UTSouthwestern.edu))  

---

## 📌 Overview  

### **What is MedicalDataHandler?**  
MedicalDataHandler is a **graphical user interface (GUI) tool** built with [Dear PyGUI](https://github.com/hoffstadt/DearPyGui) for **DICOM data processing, validation, and transformation**. It enables users to:  
- **Manage DICOM data effortlessly** without coding.  
- **Automatically detect and organize DICOM files** into structured datasets.  
- **Inspect and visualize patient data** with **real-time rendering**.  
- **Export data in NRRD format** for seamless integration in downstream pipelines (e.g., AI model training).  

---

<p align="center">
  <img src="images/MDH_Brief_Demo.gif" alt="Brief Demo">
  <br>
  <em>Figure 1: A brief animation to demonstrate basic functionality in MedicalDataHandler.</em>
</p>

---

### **Why was this created?**  
- ✅ **Standardize DICOM data processing** for **researchers, students, and trainees** without requiring programming skills.  
- ✅ **Offer an intuitive, modern GUI** for **flexible, codeless** data visualization and processing.  
- ✅ **Minimize opportunity for user error** with features such as:  
   - **Automated DICOM file identification and organization**, eliminating manual organization of DICOM files across numerous folders.  
   - **Structured tables** displaying patient data and organized by relational DICOM UIDs.  
   - **Automated Structure Name Matching & Renaming** following [TG-263](https://www.aapm.org/pubs/reports/RPT_263.pdf).  
- ✅ **Provide research-focused validation tools** to analyze DICOM metadata and catch errors before they propagate in downstream applications.  
- ✅ **Enable specialized post-processing**, including:  
   - **CT HU-to-RED conversion** (Hounsfield Units → Relative Electron Density)  
     - **Sample values are provided for convenience**, however, it is **STRONGLY ADVISED** to **update** these values in the configuration files to **align with your institutional data** 
       - **ct_HU_map_vals.json** and **ct_RED_map_vals.json** in the **config_files folder**
   - **Region-specific RED overrides** for segmented structures.  
   - **Dose Summation** across multiple dose distributions.  

---

## 🚀 Installation  

### **Option 1: Download Prebuilt EXE (Recommended)**  
> **[🔗 Download the latest release](https://github.com/AustenMan/MedicalDataHandler/releases)**  

### **Option 2: Run from Source**  

#### **Prerequisites**  
- **Python 3.11+**  
- Install dependencies:  
  ```sh
  pip install -r requirements.txt

### **System Requirements**  
- **Recommended specs:**  
   - **OS:** Windows
   - **CPU:** Any modern multi-core processor (tested with i7-12700)  
   - **RAM:** 32+ GB (tested with 32 GB)  
   - **GPU:** Optional (GUI is GPU-accelerated via [Dear PyGUI](https://github.com/hoffstadt/DearPyGui))  

---

## 📂 Features  

### **📊 DICOM Data Management & Processing**  
- ✔ **Automated DICOM file discovery** in user-specified directories.  

  <p align="center">
    <img src="images/2_DicomSearch.png" alt="DICOM Search">
    <br>
    <em>Figure 2: Users can select "Add New Data", and then "Choose a DICOM Directory" to search for DICOM files.</em>
  </p>

- ✔ **SQL database indexing** via [SQLite](https://github.com/sqlite/sqlite) and [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) for persistent storage and efficient querying of DICOM metadata.  

- ✔ **Patient Data Table** for structured display of accessible patient data.  

  <p align="center">
    <img src="images/3_DataTablePatients.png" alt="Data Table Patients">
    <br>
    <em>Figure 4: The patient table supports filtering by MRN, name, processing status, or site-specific metadata.</em>
  </p>

- ✔ **Patient Object Inspection** for backend storage analysis.  

  <p align="center">
    <img src="images/4_PatientInspect.png" alt="Inspection Patient Object">
    <br>
    <em>Figure 4: Clicking "Inspect" in the patient table displays the patient database record and relationships, including associated files.</em>
  </p>

- ✔ **Automated File Grouping** for convenient organization of patient-specific data.  

  <p align="center">
    <img src="images/5_DataTableLoad.png" alt="Data Table Load">
    <br>
    <em>Figure 5: After patient selection, the table shows data grouped by relational DICOM UID values. Metadata columns show labels, names, descriptions, and timestamps for each file.</em>
  </p>

- ✔ **DICOM metadata inspection** using [Pydicom](https://github.com/pydicom/pydicom), with collapsible trees and filters.

  <p align="center">
    <img src="images/6_DicomInspect.png" alt="Inspection DICOM Metadata">
    <br>
    <em>Figure 6: The DICOM metadata inspection panel enables structured viewing and filtering of attributes for individual files.</em>
  </p>



### **🖼️ Interactive 2D Visualization**  
- ✅ **Data visualization** by converting DICOM data to [SimpleITK](https://github.com/SimpleITK/SimpleITK) Images and [NumPy](https://github.com/numpy/numpy) arrays.  

- ✅ **Customizable display toggles** for flexible visualization of any loaded images, dose distributions, and/or structures.  

  <p align="center">
    <img src="images/7_LoadedHomePage.png" alt="DICOM Data Loaded">
    <br>
    <em>Figure 7: A fully loaded dataset displayed with interactive visualization controls and toggle options for images, dose distributions, and structures.</em>
  </p>

- ✅ **Three-pane view support** for axial, sagittal and coronal planes with the ability to:  
  - **Zoom**: `CTRL + Mouse Scroll`  
  - **Pan**: `Middle Mouse Drag`  
  - **Scroll through slices**: `Mouse Scroll`  
  - **Move Crosshairs (Synchronizes all viewing planes)**: `Right Mouse Click`  
  - **Inspect Voxels**: `Right Mouse Click` on a view to display a hovered voxel's:  
    - **Image values**  
    - **Dose values**  
    - **Segmentations present**  
  - **Move viewing planes** to **center of any ROI**.  
  - **Rename, recolor, or remove** segmentations.  

  <p align="center">
    <img src="images/8_ThreeViews.png" alt="Three Views">
    <br>
    <em>Figure 8: Three-pane visualization of axial, sagittal, and coronal views, with voxel-level information displayed at the mouse cursor.</em>
  </p>

- ✅ **Concise beam summary** for each RT Plan to inform users about essential treatment planning details.

  <p align="center">
    <img src="images/9_BeamSummary.png" alt="Inspection Loaded Data">
    <br>
    <em>Figure 9: The beam summary panel includes the treatment machine name, radiation type, angles, and more as extracted from the DICOM metadata.</em>
  </p>

- ✅ **Inspection of loaded data** to view or modify metadata fields.

  <p align="center">
    <img src="images/10_SitkInspect.png" alt="Inspection Loaded Data">
    <br>
    <em>Figure 10: The inspection panel for loaded data allows viewing and/or modifying specific metadata fields, depending on the data type.</em>
  </p>

### **🔄 DICOM-to-NRRD Conversion**  
- ✔ **NRRD export** for each 3D volume while retaining DICOM metadata, and optionally retaining custom modifications.  
- ✔ **Customizable post-processing tools** and flexible **file naming** options.  
- ✔ **Supports both partial (single-item) and batch data saving**.  

  <p align="center">
    <img src="images/12_Save.png" alt="Save">
    <br>
    <em>Figure 12: The save window enables exporting selected data to NRRD format with customizable options.</em>
  </p>

### **🛠 Additional Features**  
- ✔ **Integrated logging window** for debugging.  
- ✔ **Take screenshots** by pressing Ctrl+S or the Print Screen key. Saves to a screenshot folder.  
- ✔ **Optimized performance** with **multiprocessing and multithreading** and a **GPU-accelerated GUI**.  
- ✔ **Settings window** with options such as:  
  - **GUI resizing**  
  - **Crosshair & orientation label adjustments**  
  - **Data rotation or flips**  

  <p align="center">
    <img src="images/11_Settings.png" alt="Settings">
    <br>
    <em>Figure 11: The settings panel provides controls for GUI customization, data rotation/flips, etc.</em>
  </p>

---

## 🔄 Future Development  

### **🛠 Planned Features**  
- ✔ **Direct DICOM import from DAEMON Server**.  
- ✔ **Dose-Volume Histogram (DVH) visualization**.  
- ✔ **Basic image processing tools (e.g., applying filters).**  
- ✔ **Oblique plane visualization support (e.g., beams' eye view).**  
- ✔ **3D RTPLAN beam data representation and beam visualization.**  
- ✔ **Direct NRRD imports** and **writing back to DICOM format**.  
- ✔ **Support for rigid image registration and persistent registration storage.**  
- ✔ **Support for data anonymization.**  
- ✔ **Potential C# re-write** for possible integration with **ESAPI**.  

---

## ⚠️ Disclaimers  

I am relatively new to computer science and software development; I learned as I built this software, and I aim to continually improve this code.

A large language model (LLM) was used to assist with **code review, writing docstrings, and formatting this README**.  

---

### **🔗 Contributing**  
Interested in contributing? **Fork the repository**, make changes, and submit a pull request.  

---

## 📜 Licensing  

This software is licensed under a custom academic license from The University of Texas Southwestern Medical Center. It is available exclusively for academic research use under specific conditions. See [`LICENSE.txt`](LICENSE.txt) for details.  
Additionally, see the **`notices`** folder for third-party open-source software acknowledgments.  

---

## 📢 Acknowledgments  

**This work was supported by:**  
- **NIH grants R01CA237269, R01CA254377, and R01CA258987.**  
