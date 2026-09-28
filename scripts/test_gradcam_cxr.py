import time
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

sample_img_path = ROOT / "fixtures" / "blob" / "evidence" / "fixture-sample" / "gradcam_edema.png"
base_pil = Image.open(sample_img_path).convert("RGB")
orig_w, orig_h = base_pil.size
disp_uint8 = np.array(base_pil)

# Preprocessing exactly like shaurya-webapp
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

# Run inference
with torch.no_grad():
    preds = clf_model(img_tensor)[0].cpu().numpy()

for i, p in enumerate(pathologies):
    score = float(preds[i])
    print(f"  {p}: {round(score * 100, 2)}%")

# Test generating Grad-CAM for Edema and Cardiomegaly
for target_p in ["Edema", "Cardiomegaly", "Effusion", "Pneumonia", "Consolidation", "Atelectasis", "Nodule", "Infiltration"]:
    target_idx = pathologies.index(target_p)
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
    heatmap_color = cv2.applyColorMap(norm_grad_resized, cv2.COLORMAP_JET)
    heatmap_rgb = cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)

    # Transparent RGBA heatmap layer
    # Alpha proportional to gradient intensity so cold/background areas are semi-transparent and hot spots are opaque
    heatmap_rgba = np.zeros((orig_h, orig_w, 4), dtype=np.uint8)
    heatmap_rgba[:, :, :3] = heatmap_rgb
    alpha_mask = np.clip((norm_grad_resized.astype(np.float32) / 255.0) * 230 + 25, 0, 255).astype(np.uint8)
    # Zero out very low gradients
    alpha_mask[norm_grad_resized < 30] = 0
    heatmap_rgba[:, :, 3] = alpha_mask

    print(f"Generated Grad-CAM for {target_p}: max alpha = {heatmap_rgba[:, :, 3].max()}, nonzero = {(heatmap_rgba[:, :, 3] > 0).sum()}")
