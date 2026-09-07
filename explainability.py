"""Explainability, Grad-CAM saliency & Anatomical Segregation generator for AURALane.

Generates:
1. Gradient-based attention heatmaps overlaying source X-ray images (Grad-CAM).
2. PSPNet 14-target anatomical segmentation & organ system segregation overlays.
3. Pathological categorization across anatomical chest portions (Pulmonary, Cardiovascular, Pleural, Musculoskeletal).
"""
import io
import base64
import numpy as np
import cv2
import torch
import torchxrayvision as xrv

import imaging

_SEGMENTATION_MODEL = None

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

ORGAN_SYSTEM_INDICES = {
    "Pulmonary": [4, 5, 6, 7, 12],
    "Cardiovascular": [8, 9, 11],
    "Pleural": [10],
    "Musculoskeletal": [0, 1, 2, 3, 13]
}

PATHOLOGY_ORGAN_SYSTEM_MAP = {
    "Pneumothorax": "Pulmonary",
    "Pneumonia": "Pulmonary",
    "Consolidation": "Pulmonary",
    "Edema": "Pulmonary",
    "Infiltration": "Pulmonary",
    "Atelectasis": "Pulmonary",
    "Emphysema": "Pulmonary",
    "Fibrosis": "Pulmonary",
    "Nodule": "Pulmonary",
    "Mass": "Pulmonary",
    "Lung Opacity": "Pulmonary",
    "Lung Lesion": "Pulmonary",
    "Cardiomegaly": "Cardiovascular",
    "Enlarged Cardiomediastinum": "Cardiovascular",
    "Effusion": "Pleural",
    "Pleural Thickening": "Pleural",
    "Hernia": "Pleural",
    "Fracture": "Musculoskeletal"
}


def get_seg_model():
    """Lazily load PSPNet anatomical segmentation model."""
    global _SEGMENTATION_MODEL
    if _SEGMENTATION_MODEL is None:
        _SEGMENTATION_MODEL = xrv.baseline_models.chestx_det.PSPNet()
        _SEGMENTATION_MODEL.eval()
    return _SEGMENTATION_MODEL


def numpy_to_base64_png(img_np: np.ndarray) -> str:
    """Convert RGB numpy uint8 image array to base64 PNG data URL."""
    if img_np.dtype != np.uint8:
        img_np = (np.clip(img_np, 0, 1) * 255).astype(np.uint8)
    
    if img_np.ndim == 2:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
        
    bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    success, buffer = cv2.imencode(".png", bgr)
    if not success:
        raise ValueError("Failed to encode image to PNG format")
    b64_str = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


def generate_anatomical_segmentation(image_source, disp_rgb: np.ndarray) -> dict:
    """Run PSPNet anatomical segmentation and generate color-coded system overlays."""
    try:
        seg_model = get_seg_model()
        img_tensor = imaging.to_model_input(image_source)
        
        with torch.no_grad():
            seg_out = seg_model(img_tensor)[0].cpu().numpy()  # shape [14, H, W]

        num_targets, seg_h, seg_w = seg_out.shape
        disp_seg_base = cv2.resize(disp_rgb, (seg_w, seg_h))

        composite_overlay = disp_seg_base.copy().astype(np.float32)
        system_overlays_raw = {
            sys_key: disp_seg_base.copy().astype(np.float32)
            for sys_key in ORGAN_SYSTEM_INDICES
        }

        target_names = seg_model.targets

        for i in range(num_targets):
            target_mask = seg_out[i]
            mask_sig = 1.0 / (1.0 + np.exp(-target_mask))
            binary_mask = (mask_sig > 0.5).astype(np.uint8)
            
            color = SEGMENTATION_COLORS[i % len(SEGMENTATION_COLORS)]

            if binary_mask.sum() > 0:
                color_arr = np.array(color, dtype=np.float32)
                alpha = 0.45
                mask_3d = np.repeat(binary_mask[:, :, np.newaxis], 3, axis=2)
                
                # Update composite mask
                composite_overlay = np.where(
                    mask_3d == 1,
                    (1 - alpha) * composite_overlay + alpha * color_arr,
                    composite_overlay
                )

                # Update organ system composite overlays
                for sys_key, target_list in ORGAN_SYSTEM_INDICES.items():
                    if i in target_list:
                        system_overlays_raw[sys_key] = np.where(
                            mask_3d == 1,
                            (1 - alpha) * system_overlays_raw[sys_key] + alpha * color_arr,
                            system_overlays_raw[sys_key]
                        )

        composite_uint8 = np.clip(composite_overlay, 0, 255).astype(np.uint8)
        composite_b64 = numpy_to_base64_png(composite_uint8)

        segregated_system_overlays = {}
        for sk, raw_mat in system_overlays_raw.items():
            mat_uint8 = np.clip(raw_mat, 0, 255).astype(np.uint8)
            segregated_system_overlays[sk] = numpy_to_base64_png(mat_uint8)

        return {
            "supported": True,
            "composite_segmentation": composite_b64,
            "segregated_systems": segregated_system_overlays
        }
    except Exception as e:
        return {
            "supported": False,
            "error": str(e)
        }


def generate_explainability(model, image_source, target_pathology: str = "Pneumothorax") -> dict:
    """Generate Grad-CAM heatmap, anatomical segmentation, and system segregation overlays."""
    try:
        # Preprocess original grayscale image and model input tensor
        disp_img, maxval = imaging.read_grayscale(image_source)
        
        # Format disp_uint8 for display
        disp_norm = np.clip(disp_img / maxval * 255.0, 0, 255).astype(np.uint8)
        if disp_norm.ndim == 2:
            disp_rgb = cv2.cvtColor(disp_norm, cv2.COLOR_GRAY2RGB)
        else:
            disp_rgb = disp_norm

        img_tensor = imaging.to_model_input(image_source)
        
        # Set gradients on input tensor for Grad-CAM
        tensor_copy = img_tensor.clone().detach().requires_grad_(True)
        preds = model(tensor_copy)
        
        if target_pathology in model.pathologies:
            target_idx = model.pathologies.index(target_pathology)
        else:
            target_idx = 0
            target_pathology = model.pathologies[0]
            
        target_score = preds[0, target_idx]
        model.zero_grad()
        target_score.backward()
        
        # Calculate gradient magnitude
        grads = tensor_copy.grad.data.abs().squeeze().cpu().numpy()
        if grads.ndim == 3:
            grads = grads.mean(axis=0)
            
        # Apply Gaussian blur & normalize 0-255
        grads_blur = cv2.GaussianBlur(grads, (15, 15), 0)
        g_min, g_max = grads_blur.min(), grads_blur.max()
        if g_max > g_min:
            norm_grad = ((grads_blur - g_min) / (g_max - g_min) * 255).astype(np.uint8)
        else:
            norm_grad = np.zeros_like(grads_blur, dtype=np.uint8)
            
        h, w = disp_rgb.shape[:2]
        norm_grad_resized = cv2.resize(norm_grad, (w, h))
        heatmap_color = cv2.applyColorMap(norm_grad_resized, cv2.COLORMAP_JET)
        heatmap_color = cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)
        
        blended = cv2.addWeighted(disp_rgb, 0.45, heatmap_color, 0.55, 0)
        
        original_b64 = numpy_to_base64_png(disp_rgb)
        heatmap_b64 = numpy_to_base64_png(heatmap_color)
        blended_b64 = numpy_to_base64_png(blended)
        
        # PSPNet Anatomical Segmentation & System Segregation
        seg_res = generate_anatomical_segmentation(image_source, disp_rgb)

        return {
            "supported": True,
            "modality": "CXR",
            "model_name": getattr(model, "weights", "densenet121-res224-all"),
            "pathology": target_pathology,
            "raw_confidence": round(float(target_score.detach().cpu().numpy()), 4),
            "original_b64": original_b64,
            "heatmap_b64": heatmap_b64,
            "overlay_b64": blended_b64,
            "segmentation_b64": seg_res.get("composite_segmentation") if seg_res.get("supported") else original_b64,
            "segregated_systems": seg_res.get("segregated_systems", {}),
            "pathology_system_map": PATHOLOGY_ORGAN_SYSTEM_MAP,
            "dimensions": f"{w}x{h}",
            "legend": "Model attention & anatomical region segregation — not a diagnostic annotation."
        }
    except Exception as e:
        return {
            "supported": False,
            "reason": f"Explainability generation failed: {e}",
            "legend": "Explainability unavailable for this study."
        }
