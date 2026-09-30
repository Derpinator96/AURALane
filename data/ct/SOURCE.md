# Head CT studies: source

Two studies from **CQ500** (qure.ai), anonymised non-contrast head CT released
for research under CC BY-NC-SA 4.0 with an end-user licence agreement. Public
and openly licensed, the same standing as NIH ChestX-ray14 and BraTS 2021
here. Not in git (`data/ct/raw/` is ignored).

| study | download | size | radiologist reads (reads.csv, R1 to R3) | slices |
|---|---|---|---|---|
| CQ500-CT-419 | `https://s3.ap-south-1.amazonaws.com/qure.headct.study/CQ500-CT-419.zip` | 3.7 MB | intracranial hemorrhage, 3 of 3 readers | 36 (CT 5mm) |
| CQ500-CT-5 | `https://s3.ap-south-1.amazonaws.com/qure.headct.study/CQ500-CT-5.zip` | 12.6 MB | no hemorrhage, 3 of 3 readers | 53 (CT Plain 3mm) |

Chosen as the smallest study with a unanimous bleed and the smallest with a
unanimous negative among those sized (`reads.csv` from the same bucket).

    curl -O https://s3.ap-south-1.amazonaws.com/qure.headct.study/CQ500-CT-419.zip
    curl -O https://s3.ap-south-1.amazonaws.com/qure.headct.study/CQ500-CT-5.zip

then unzip both into `data/ct/raw/`. The pixel data is JPEG lossless;
de-identification decompresses a slice when it masks one
(`sim/edge/deid.py`).

The readers' labels are used here only to pick one positive and one negative
study. No figure is computed from them.

## RSNA head CT studies (seven)

Seven studies from the RSNA Intracranial Hemorrhage Detection set, supplied by the
team in `ct scan data/` and copied one folder each to `data/ct/raw/RSNA-ID_<id>/`
(17 to 53 slices). They are public, but the licence terms were not checked here, so
check them before any of these goes in a deck or a repository. The files carry an
`ID_<hash>` StudyInstanceUID, which is not a valid UID, and no SOPClassUID in the
dataset (only in the file meta); de-identification remaps the UIDs and
`core.pipeline._conform` fills the SOP class in, so Orthanc accepts them. Scored by
the head CT model they spread across every lane, two of them into the abstention tray.
