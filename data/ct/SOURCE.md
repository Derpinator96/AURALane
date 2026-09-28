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
