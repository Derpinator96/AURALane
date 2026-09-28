"""Generate PSPNet anatomical segmentation masks and multi-color overlays for CXR.

Derived from shaurya-webapp/web_app.py:
- Uses xrv.baseline_models.chestx_det.PSPNet() (14 anatomical targets)
- Generates:
  * Transparent RGBA multi-color composite layer
  * Organ system segregated layers (Pulmonary, Cardiovascular, Musculoskeletal, Diaphragmatic)
  * Individual anatomical region mask layers
  * Anatomical lookup matrix and metadata for click-to-region pinpoint annotation
"""
import io
import json
import os
import sys
from pathlib import Path
import numpy as np
import torch
import torchvision
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torchxrayvision as xrv

SEGMENTATION_COLORS = [
    [0, 255, 255],     # 0: Left Clavicle (Cyan)
    [255, 165, 0],     # 1: Right Clavicle (Orange)
    [255, 0, 255],     # 2: Left Scapula (Magenta)
    [255, 20, 147],    # 3: Right Scapula (Deep Pink)
    [0, 191, 255],     # 4: Left Lung (Deep Sky Blue)
    [30, 144, 255],    # 5: Right Lung (Dodger Blue)
    [138, 43, 226],    # 6: Left Hilus Pulmonis (Blue Violet)
    [147, 112, 219],   # 7: Right Hilus Pulmonis (Medium Purple)
    [255, 69, 0],      # 8: Heart (Red-Orange)
    [255, 215, 0],     # 9: Aorta (Gold)
    [50, 205, 50],     # 10: Facies Diaphragmatica (Lime Green)
    [0, 250, 154],     # 11: Mediastinum (Medium Spring Green)
    [220, 20, 60],     # 12: Weasand / Trachea (Crimson)
    [124, 252, 0]      # 13: Spine (Lawn Green)
]

SYSTEM_INDICES = {
    "Pulmonary": [4, 5, 6, 7, 12],
    "Cardiovascular": [8, 9, 11],
    "Musculoskeletal": [0, 1, 2, 3, 13],
    "Diaphragmatic": [10]
}

FRIENDLY_NAMES = {
    "Left Clavicle": "Left Clavicle",
    "Right Clavicle": "Right Clavicle",
    "Left Scapula": "Left Scapula",
    "Right Scapula": "Right Scapula",
    "Left Lung": "Left Lung Field",
    "Right Lung": "Right Lung Field",
    "Left Hilus Pulmonis": "Left Pulmonary Hilum",
    "Right Hilus Pulmonis": "Right Pulmonary Hilum",
    "Heart": "Cardiac Silhouette",
    "Aorta": "Aortic Arch & Knob",
    "Facies Diaphragmatica": "Diaphragmatic Surface",
    "Mediastinum": "Mediastinum",
    "Weasand": "Trachea / Main Bronchi",
    "Spine": "Thoracic Spine"
}

def generate():
    sample_img_path = ROOT / "fixtures" / "blob" / "evidence" / "fixture-sample" / "gradcam_edema.png"
    out_dir = ROOT / "fixtures" / "blob" / "evidence" / "fixture-sample"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading base CXR image from: {sample_img_path}")
    base_pil = Image.open(sample_img_path).convert("RGB")
    orig_w, orig_h = base_pil.size
    base_arr = np.array(base_pil)

    # Grayscale normalization for model
    gray_arr = np.array(base_pil.convert("L"))
    img_norm = xrv.utils.normalize(gray_arr, 255)
    
    # PSPNet requires square input
    transform = xrv.datasets.XRayCenterCrop()
    img_norm_cropped = transform(img_norm[None, ...])
    img_t = torch.from_numpy(img_norm_cropped).unsqueeze(0).float()

    print("Loading PSPNet model...")
    seg_model = xrv.baseline_models.chestx_det.PSPNet()
    seg_model.eval()

    print("Running anatomical segmentation inference...")
    with torch.no_grad():
        seg_out = seg_model(img_t)[0].cpu().numpy() # [14, 512, 512]

    num_targets, seg_h, seg_w = seg_out.shape
    target_names = seg_model.targets
    print(f"Model generated {num_targets} targets at resolution {seg_w}x{seg_h}")

    # Resize raw logits to original image resolution (orig_w, orig_h)
    resized_masks = []
    for i in range(num_targets):
        mask_raw = seg_out[i]
        mask_sig = 1.0 / (1.0 + np.exp(-mask_raw))
        # Resize to original image size
        mask_pil = Image.fromarray((mask_sig * 255).astype(np.uint8)).resize((orig_w, orig_h), Image.Resampling.BILINEAR)
        resized_sig = np.array(mask_pil) / 255.0
        binary_mask = (resized_sig > 0.5).astype(np.uint8)
        resized_masks.append(binary_mask)

    # 1. Multi-color composite layer (RGBA transparent)
    composite_rgba = np.zeros((orig_h, orig_w, 4), dtype=np.uint8)
    
    # Also individual system layers
    system_rgbas = {
        sys_name: np.zeros((orig_h, orig_w, 4), dtype=np.uint8)
        for sys_name in SYSTEM_INDICES
    }

    region_details = []
    # Lookup matrix for 2D coordinate clicks: stores target index at each pixel (or -1)
    # Higher index / specific organ takes precedence (e.g. Heart over Lung, Clavicle over Lung)
    priority_order = [4, 5, 0, 1, 2, 3, 10, 11, 13, 6, 7, 12, 9, 8] # Draw lungs first, bones/heart on top
    
    for i in priority_order:
        b_mask = resized_masks[i]
        t_name = target_names[i]
        color = SEGMENTATION_COLORS[i]
        coverage_pct = round(float(b_mask.sum()) / (orig_h * orig_w) * 100, 2)
        color_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

        # Paint onto composite RGBA
        idx = (b_mask == 1)
        composite_rgba[idx, 0] = color[0]
        composite_rgba[idx, 1] = color[1]
        composite_rgba[idx, 2] = color[2]
        composite_rgba[idx, 3] = 165 # ~65% opacity

        # Paint onto system layer
        for sys_name, idx_list in SYSTEM_INDICES.items():
            if i in idx_list:
                system_rgbas[sys_name][idx, 0] = color[0]
                system_rgbas[sys_name][idx, 1] = color[1]
                system_rgbas[sys_name][idx, 2] = color[2]
                system_rgbas[sys_name][idx, 3] = 175

        # Individual mask layer
        indiv_rgba = np.zeros((orig_h, orig_w, 4), dtype=np.uint8)
        indiv_rgba[idx, 0] = color[0]
        indiv_rgba[idx, 1] = color[1]
        indiv_rgba[idx, 2] = color[2]
        indiv_rgba[idx, 3] = 185
        indiv_path = out_dir / f"cxr_mask_{i}.png"
        Image.fromarray(indiv_rgba).save(indiv_path)

        # Identify organ system
        sys_belong = "Other"
        for sk, tlist in SYSTEM_INDICES.items():
            if i in tlist:
                sys_belong = sk
                break

        region_details.append({
            "id": i,
            "raw_name": t_name,
            "name": FRIENDLY_NAMES.get(t_name, t_name),
            "system": sys_belong,
            "color_rgb": color,
            "color_hex": color_hex,
            "coverage_pct": coverage_pct,
            "mask_png": f"evidence/fixture-sample/cxr_mask_{i}.png"
        })

    # Sort details back by id
    region_details.sort(key=lambda x: x["id"])

    # Save composite transparent layer
    comp_layer_path = out_dir / "cxr_segmentation_layer.png"
    Image.fromarray(composite_rgba).save(comp_layer_path)
    print(f"Saved composite segmentation layer: {comp_layer_path}")

    # Save composite blended on top of base radiograph
    alpha = 0.45
    blended_rgb = base_arr.copy().astype(np.float32)
    has_mask = (composite_rgba[:, :, 3] > 0)
    for c in range(3):
        blended_rgb[has_mask, c] = (
            (1.0 - alpha) * base_arr[has_mask, c] + alpha * composite_rgba[has_mask, c]
        )
    blended_img = Image.fromarray(np.clip(blended_rgb, 0, 255).astype(np.uint8))
    comp_blended_path = out_dir / "cxr_segmentation_composite.png"
    blended_img.save(comp_blended_path)
    print(f"Saved composite blended image: {comp_blended_path}")

    # Save system layers
    sys_file_map = {}
    for sys_name, s_rgba in system_rgbas.items():
        s_filename = f"cxr_segmentation_{sys_name.lower()}.png"
        Image.fromarray(s_rgba).save(out_dir / s_filename)
        sys_file_map[sys_name] = f"evidence/fixture-sample/{s_filename}"
        print(f"Saved {sys_name} system layer: {s_filename}")

    # Save meta json
    meta = {
        "modality": "CR",
        "description": "PSPNet 14-target anatomical segmentation",
        "composite_layer_png": "evidence/fixture-sample/cxr_segmentation_layer.png",
        "composite_blended_png": "evidence/fixture-sample/cxr_segmentation_composite.png",
        "systems": sys_file_map,
        "regions": region_details
    }
    meta_path = out_dir / "cxr_segmentation_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"Saved segmentation metadata: {meta_path}")
    print("Done generating CXR segmentation fixtures!")

if __name__ == "__main__":
    generate()
