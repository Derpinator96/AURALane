# Brain MRI data source

## Dataset

RSNA-ASNR-MICCAI BraTS 2021, Task 1 (segmentation).

- Obtained from the Kaggle mirror `dschettler8845/brats-2021-task1`, per-case
  tar files, downloaded 2026-09-25.
- Underlying source: RSNA-ASNR-MICCAI-BRATS-2021 on The Cancer Imaging Archive.
- Licence: CC BY 4.0.

## Cases in this repository

Two cases, both from the per-case tars rather than the 13.4 GB full archive.

- BraTS2021_00495
- BraTS2021_00621

Each case has five volumes: t1, t1ce, t2, flair, seg.

## Verified properties

Checked with nibabel on 2026-09-25:

- `ndim = 3` for every volume. These are four separate sequences, not a 4D
  time series. The converter asserts this.
- Shape 240 x 240 x 155, 1 mm isotropic, template registered, skull stripped.
- dtype int16 for the image sequences, uint16 for the segmentation.
- Segmentation labels present: 0, 1 (necrotic core), 2 (edema), 4 (enhancing
  tumour).
- NIfTI `descrip` and `aux_file` header fields are empty in all ten files, so
  no identifiers leaked from whoever performed the original DICOM to NIfTI
  conversion.

## Privacy

NIfTI headers carry no patient identifiers by design. Conversion from DICOM to
NIfTI is itself the de-identification step in neuroimaging research, which is
why this data arrives already de-identified.

Task 1 volumes are skull stripped, so the facial reidentification risk that TCIA
flags for the original-resolution Task 2 DICOM does not apply here.

Synthetic identifiers are injected during DICOM conversion so that the
de-identification pipeline has something real to remove.

## Citation

Cite all three when using this data:

- Menze et al. (2015), IEEE Transactions on Medical Imaging 34(10):1993-2024
- Bakas et al. (2017), Scientific Data 4:170117
- Baid et al. (2021), arXiv:2107.02314
