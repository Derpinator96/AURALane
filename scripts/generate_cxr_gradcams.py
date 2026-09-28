"""Generate high-resolution JET Grad-CAM saliency heatmaps for CXR pathologies.

Derived from shaurya-webapp/web_app.py:
- Uses xrv.models.DenseNet(weights="densenet121-res224-all")
- Computes backprop saliency gradients for each pathology
- Applies Gaussian blur + COLORMAP_JET
- Exports:
  * Transparent RGBA heatmap layer: gradcam_{slug}_layer.png
  * Full blended image: gradcam_{slug}.png
  * Standalone heatmap: gradcam_{slug}_heatmap.png
  * Pathology registry metadata: cxr_gradcam_meta.json
"""
import json
import os
import sys
from pathlib import Path
import numpy as np
import torch
import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torchxrayvision as xrv

def slugify(text: str) -> str:
    return text.lower().replace(" ", "_").replace("/", "_")

def generate_all_gradcams():
    sample_img_path = ROOT / "fixtures" / "blob" / "evidence" / "fixture-sample" / "cxr_base.png"
    out_dir = ROOT / "fixtures" / "blob" / "evidence" / "fixture-sample"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading base CXR image from: {sample_img_path}")
    base_pil = Image.open(sample_img_path).convert("RGB")
    orig_w, orig_h = base_pil.size
    disp_uint8 = np.array(base_pil)

    gray_arr = np.array(base_pil.convert("L"))
    img_norm = xrv.utils.normalize(gray_arr, 255)
    transform = xrv.datasets.XRayCenterCrop()
    img_norm_cropped = transform(img_norm[None, ...])
    img_tensor = torch.from_numpy(img_norm_cropped).unsqueeze(0).float()

    print("Loading DenseNet-121 classifier...")
    clf_model = xrv.models.DenseNet(weights="densenet121-res224-all")
    clf_model.eval()

    pathologies = list(clf_model.pathologies)
    print(f"Model pathologies ({len(pathologies)}):", pathologies)

    with torch.no_grad():
        preds = clf_model(img_tensor)[0].cpu().numpy()

    meta_list = []

    for target_p in pathologies:
        target_idx = pathologies.index(target_p)
        score = float(preds[target_idx])
        p_slug = slugify(target_p)

        tensor_copy = img_tensor.clone().detach().requires_grad_(True)
        out = clf_model(tensor_copy)
        target_score = out[0, target_idx]
        clf_model.zero_grad()
        target_score.backward()

        grads = tensor_copy.grad.data.abs().squeeze().cpu().numpy()
        if grads.ndim == 3:
            grads = grads.mean(axis=0)

        grads_blur = cv2.GaussianBlur(grads, (15, 15), 0)
        g_min, g_max = grads_blur.min(), grads_blur.max()
        if g_max > g_min:
            norm_grad = ((grads_blur - g_min) / (g_max - g_min) * 255).astype(np.uint8)
        else:
            norm_grad = np.zeros_like(grads_blur, dtype=np.uint8)

        norm_grad_resized = cv2.resize(norm_grad, (orig_w, orig_h))
        heatmap_bgr = cv2.applyColorMap(norm_grad_resized, cv2.COLORMAP_JET)
        heatmap_rgb = cv2.cvtColor(heatmap_bgr, cv2.COLOR_BGR2RGB)

        # 1. Standalone Heatmap
        heatmap_path = out_dir / f"gradcam_{p_slug}_heatmap.png"
        Image.fromarray(heatmap_rgb).save(heatmap_path)

        # 2. Transparent RGBA Heatmap Layer (for frontend opacity blending)
        heatmap_rgba = np.zeros((orig_h, orig_w, 4), dtype=np.uint8)
        heatmap_rgba[:, :, :3] = heatmap_rgb
        # Thresholded alpha mask: higher attention = higher opacity
        alpha_channel = np.clip((norm_grad_resized.astype(np.float32) / 255.0) * 235 + 20, 0, 255).astype(np.uint8)
        alpha_channel[norm_grad_resized < 25] = 0 # Transparent background
        heatmap_rgba[:, :, 3] = alpha_channel

        layer_path = out_dir / f"gradcam_{p_slug}_layer.png"
        Image.fromarray(heatmap_rgba).save(layer_path)

        # 3. Blended Composite
        blended = cv2.addWeighted(disp_uint8, 0.45, heatmap_rgb, 0.55, 0)
        blended_path = out_dir / f"gradcam_{p_slug}.png"
        Image.fromarray(blended).save(blended_path)

        # Coverage calculation
        coverage = round(float((norm_grad_resized > 64).sum()) / (orig_w * orig_h), 4)

        meta_list.append({
            "name": target_p,
            "slug": p_slug,
            "confidence": round(score * 100, 1),
            "signal": round(score, 3),
            "coverage": coverage,
            "heatmap_png": f"evidence/fixture-sample/gradcam_{p_slug}_heatmap.png",
            "layer_png": f"evidence/fixture-sample/gradcam_{p_slug}_layer.png",
            "blended_png": f"evidence/fixture-sample/gradcam_{p_slug}.png"
        })
        print(f"Generated {target_p} (score: {round(score*100, 1)}%, coverage: {coverage*100}%) -> gradcam_{p_slug}_layer.png")

    # Sort meta_list by confidence descending
    meta_list.sort(key=lambda x: x["confidence"], reverse=True)

    meta_file = out_dir / "cxr_gradcam_meta.json"
    meta_file.write_text(json.dumps(meta_list, indent=2))
    print(f"Saved Grad-CAM registry with {len(meta_list)} pathologies to: {meta_file}")

if __name__ == "__main__":
    generate_all_gradcams()
