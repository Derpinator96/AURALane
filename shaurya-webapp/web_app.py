import os
import sys
import io
import base64
import numpy as np
from PIL import Image
import cv2
import skimage.io
import torch
import torch.nn.functional as F

from flask import Flask, render_template, request, jsonify, send_from_directory

# Ensure local torchxrayvision import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torchxrayvision as xrv

app = Flask(__name__, template_folder="templates", static_folder="static")

# Directory setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(BASE_DIR, "tests")

# Model Caches
CLASSIFICATION_MODELS = {}
SEGMENTATION_MODEL = None
AUTOENCODER_MODEL = None

MODEL_OPTIONS = {
    "densenet121-res224-all": "DenseNet 121 (All Datasets - 18 Pathologies)",
    "densenet121-res224-nih": "DenseNet 121 (NIH ChestX-ray8)",
    "densenet121-res224-chex": "DenseNet 121 (Stanford CheXpert)",
    "densenet121-res224-mimic_ch": "DenseNet 121 (MIMIC-CXR)",
    "densenet121-res224-rsna": "DenseNet 121 (RSNA Pneumonia)",
    "densenet121-res224-pc": "DenseNet 121 (PadChest)",
    "densenet121-res224-mimic_nb": "DenseNet 121 (MIMIC-CXR NB)",
    "resnet50-res512-all": "ResNet-50 512x512 (All Datasets)"
}

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

def get_clf_model(weight_name="densenet121-res224-all"):
    if weight_name not in CLASSIFICATION_MODELS:
        print(f"Loading classification model: {weight_name}...")
        if "resnet" in weight_name:
            model = xrv.models.ResNet(weights=weight_name)
        else:
            model = xrv.models.DenseNet(weights=weight_name)
        model.eval()
        CLASSIFICATION_MODELS[weight_name] = model
    return CLASSIFICATION_MODELS[weight_name]

def get_seg_model():
    global SEGMENTATION_MODEL
    if SEGMENTATION_MODEL is None:
        print("Loading PSPNet Anatomical Segmentation Model...")
        SEGMENTATION_MODEL = xrv.baseline_models.chestx_det.PSPNet()
        SEGMENTATION_MODEL.eval()
    return SEGMENTATION_MODEL

def get_ae_model():
    global AUTOENCODER_MODEL
    if AUTOENCODER_MODEL is None:
        print("Loading ResNet-101 Autoencoder Model...")
        AUTOENCODER_MODEL = xrv.autoencoders.ResNetAE(weights="101-elastic")
        AUTOENCODER_MODEL.eval()
    return AUTOENCODER_MODEL

def load_and_preprocess_image(file_source):
    """
    Loads an image from file path or byte stream, standardizes range to [-1024, 1024],
    and creates both a displayable RGB version and a PyTorch tensor for XRV.
    """
    if isinstance(file_source, str):
        # xrv.utils.load_image loads DICOM or PNG/JPG and returns normalized array in range [-1024, 1024] with shape (1, H, W)
        img_norm = xrv.utils.load_image(file_source)
        if file_source.lower().endswith(".dcm"):
            raw_disp = img_norm[0]
        else:
            raw_disp = skimage.io.imread(file_source)
    else:
        # File storage stream from custom upload
        img_bytes = file_source.read()
        pil_img = Image.open(io.BytesIO(img_bytes))
        raw_disp = np.array(pil_img)
        
        # Check range and normalize to [-1024, 1024]
        img_arr = raw_disp.copy()
        if img_arr.ndim == 3:
            img_arr = img_arr.mean(2)
        
        max_val = img_arr.max()
        if max_val <= 255:
            img_norm = xrv.datasets.normalize(img_arr, 255)
        elif max_val <= 1024:
            img_norm = img_arr
        else:
            img_norm = xrv.datasets.normalize(img_arr, max_val)
        
        if img_norm.ndim == 2:
            img_norm = img_norm[None, ...] # Add channel dimension -> (1, H, W)

    # 1. Create displayable 8-bit image uint8 (0-255)
    disp_img = raw_disp.copy()
    if disp_img.ndim == 3 and disp_img.shape[2] == 4:
        disp_img = cv2.cvtColor(disp_img, cv2.COLOR_RGBA2RGB)
    elif disp_img.ndim == 3 and disp_img.shape[2] == 3:
        pass
    elif disp_img.ndim == 2:
        disp_img = cv2.cvtColor(disp_img, cv2.COLOR_GRAY2RGB)
    elif disp_img.ndim == 3 and disp_img.shape[0] == 1:
        disp_img = cv2.cvtColor(disp_img[0], cv2.COLOR_GRAY2RGB)
    
    # Standardize display image to [0, 255] uint8
    disp_min, disp_max = disp_img.min(), disp_img.max()
    if disp_max > disp_min:
        disp_img_uint8 = ((disp_img.astype(np.float32) - disp_min) / (disp_max - disp_min) * 255).astype(np.uint8)
    else:
        disp_img_uint8 = np.zeros_like(disp_img, dtype=np.uint8)

    # 2. Prepare PyTorch tensor
    if img_norm.ndim == 2:
        img_norm = img_norm[None, ...]

    # Apply Center Crop transform
    transform = xrv.datasets.XRayCenterCrop()
    img_norm = transform(img_norm)

    # Tensor format [1, 1, H, W]
    img_tensor = torch.from_numpy(img_norm).unsqueeze(0).float()
    return disp_img_uint8, img_tensor

def numpy_to_base64_png(img_array):
    """Converts a numpy RGB or RGBA array to base64 PNG string."""
    pil_img = Image.fromarray(img_array.astype(np.uint8))
    buffered = io.BytesIO()
    pil_img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode('utf-8')

@app.route("/")
def index():
    return render_template("index.html")

def categorize_sample(rel_path):
    """Assigns clinical category, title, description, and projection to test cases."""
    rel_lower = rel_path.lower()
    fname = os.path.basename(rel_path)
    
    if rel_lower.endswith(".dcm"):
        category = "DICOM Modality"
        title = f"DICOM Image ({fname})"
        desc = "Medical DICOM standard scan file with native 16-bit dynamic depth."
    elif "tb00" in rel_lower or "tuberculosis" in rel_lower:
        category = "Tuberculosis (TBX11k)"
        title = f"TB Positive PA Scan ({fname})"
        desc = "Active Tuberculosis pulmonary infiltration from TBX11k benchmark dataset."
    elif "h00" in rel_lower or "health" in rel_lower:
        category = "Normal Chest PA"
        title = f"Healthy Control PA Scan ({fname})"
        desc = "Normal clear chest radiograph with clear lung fields."
    elif "covid" in rel_lower:
        category = "COVID-19 Pneumonia"
        title = "COVID-19 Pneumonia Scan"
        desc = "Bilateral ground-glass opacity / viral pneumonia features."
    elif "16747" in rel_lower:
        category = "Pediatric / Foreign Object"
        title = "Pediatric Radiograph"
        desc = "Chest X-ray scan with foreign medical device/object context."
    elif "00027426" in rel_lower:
        category = "Cardiomegaly / Effusion"
        title = "Cardiomegaly & Effusion Scan"
        desc = "Enlarged cardiac silhouette and pleural effusion markings."
    else:
        category = "General Chest Radiograph"
        title = f"Chest X-Ray ({fname})"
        desc = "Frontal PA/AP radiograph sample for multi-pathology analysis."
        
    return {
        "category": category,
        "title": title,
        "description": desc,
        "projection": "PA View" if ("000" in fname or "h0" in fname or "tb" in fname) else "AP View"
    }

@app.route("/api/samples", methods=["GET"])
def list_samples():
    """Returns list of all available sample X-ray images in tests directory recursively."""
    sample_files = []
    valid_exts = {".png", ".jpg", ".jpeg", ".dcm"}
    categories_found = set()
    
    if os.path.exists(TESTS_DIR):
        for root, dirs, files in os.walk(TESTS_DIR):
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext in valid_exts:
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, TESTS_DIR).replace("\\", "/")
                    meta = categorize_sample(rel_p)
                    categories_found.add(meta["category"])
                    
                    sample_files.append({
                        "filename": rel_p,
                        "display_name": f,
                        "type": "DICOM" if ext == ".dcm" else "Standard Image",
                        "size_kb": round(os.path.getsize(full_p) / 1024, 1),
                        "category": meta["category"],
                        "title": meta["title"],
                        "description": meta["description"],
                        "projection": meta["projection"]
                    })

    # Optional category filter query
    req_cat = request.args.get("category", "").strip()
    if req_cat and req_cat.lower() != "all":
        sample_files = [s for s in sample_files if s["category"].lower() == req_cat.lower()]

    return jsonify({
        "samples": sample_files,
        "models": MODEL_OPTIONS,
        "categories": sorted(list(categories_found))
    })

@app.route("/api/sample_img/<path:filename>")
def get_sample_image(filename):
    """Serves sample image safely from tests directory tree."""
    safe_path = os.path.abspath(os.path.join(TESTS_DIR, filename))
    if not safe_path.startswith(os.path.abspath(TESTS_DIR)) or not os.path.exists(safe_path):
        return "File not found", 404
    
    dir_name = os.path.dirname(safe_path)
    base_name = os.path.basename(safe_path)

    if filename.lower().endswith(".dcm"):
        disp_uint8, _ = load_and_preprocess_image(safe_path)
        pil_img = Image.fromarray(disp_uint8)
        img_io = io.BytesIO()
        pil_img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_from_directory(dir_name, base_name, mimetype="image/png")
    return send_from_directory(dir_name, base_name)

@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        model_name = request.form.get("model_name", "densenet121-res224-all")
        sample_name = request.form.get("sample_name", "")
        file_obj = request.files.get("file", None)

        if file_obj and file_obj.filename != "":
            disp_uint8, img_tensor = load_and_preprocess_image(file_obj)
            source_name = file_obj.filename
        elif sample_name:
            safe_path = os.path.abspath(os.path.join(TESTS_DIR, sample_name))
            if not safe_path.startswith(os.path.abspath(TESTS_DIR)) or not os.path.exists(safe_path):
                return jsonify({"error": f"Sample file {sample_name} not found"}), 404
            disp_uint8, img_tensor = load_and_preprocess_image(safe_path)
            source_name = os.path.basename(sample_name)
        else:
            return jsonify({"error": "No image sample selected or uploaded"}), 400

        # Resize display uint8 image to match tensor height/width for alignment
        _, _, tensor_h, tensor_w = img_tensor.shape
        disp_resized = cv2.resize(disp_uint8, (tensor_w, tensor_h))
        orig_base64 = numpy_to_base64_png(disp_resized)

        # --- 1. PATHOLOGY CLASSIFICATION ---
        clf_model = get_clf_model(model_name)
        with torch.no_grad():
            preds = clf_model(img_tensor)[0].cpu().numpy()
        
        pathologies_list = []
        for path_name, prob_val in zip(clf_model.pathologies, preds):
            prob = float(prob_val)
            prob_clamped = max(0.0, min(1.0, prob))
            
            if prob_clamped >= 0.50:
                severity = "High Risk"
                badge_class = "danger"
            elif prob_clamped >= 0.25:
                severity = "Moderate Risk"
                badge_class = "warning"
            else:
                severity = "Low Risk"
                badge_class = "success"

            pathologies_list.append({
                "pathology": path_name,
                "confidence": round(prob_clamped * 100, 2),
                "prob": round(prob_clamped, 4),
                "severity": severity,
                "badge_class": badge_class
            })

        pathologies_list.sort(key=lambda x: x["confidence"], reverse=True)

        # --- 2. ANATOMICAL SEGREGATION / SEGMENTATION ---
        seg_model = get_seg_model()
        with torch.no_grad():
            seg_out = seg_model(img_tensor)[0].cpu().numpy() # [14, H, W]

        num_targets, seg_h, seg_w = seg_out.shape
        disp_seg_base = cv2.resize(disp_resized, (seg_w, seg_h))

        composite_overlay = disp_seg_base.copy().astype(np.float32)
        segmentation_details = []
        target_names = seg_model.targets

        # Segregated Organ System maps
        system_indices = {
            "Pulmonary": [4, 5, 6, 7, 12],
            "Cardiovascular": [8, 9, 11],
            "Musculoskeletal": [0, 1, 2, 3, 13],
            "Diaphragmatic": [10]
        }

        system_overlays_raw = {
            sys_key: disp_seg_base.copy().astype(np.float32)
            for sys_key in system_indices
        }

        for i in range(num_targets):
            t_name = target_names[i]
            target_mask = seg_out[i]
            
            mask_sig = 1.0 / (1.0 + np.exp(-target_mask))
            binary_mask = (mask_sig > 0.5).astype(np.uint8)
            
            color = SEGMENTATION_COLORS[i % len(SEGMENTATION_COLORS)]
            coverage_pct = round(float(binary_mask.sum()) / (seg_h * seg_w) * 100, 2)

            indiv_overlay = np.zeros((seg_h, seg_w, 4), dtype=np.uint8)
            indiv_overlay[binary_mask == 1, 0] = color[0]
            indiv_overlay[binary_mask == 1, 1] = color[1]
            indiv_overlay[binary_mask == 1, 2] = color[2]
            indiv_overlay[binary_mask == 1, 3] = 160

            if binary_mask.sum() > 0:
                color_arr = np.array(color, dtype=np.float32)
                alpha = 0.4
                mask_3d = np.repeat(binary_mask[:, :, np.newaxis], 3, axis=2)
                
                # Update composite
                composite_overlay = np.where(
                    mask_3d == 1,
                    (1 - alpha) * composite_overlay + alpha * color_arr,
                    composite_overlay
                )

                # Update organ system composite overlays
                for sys_key, target_list in system_indices.items():
                    if i in target_list:
                        system_overlays_raw[sys_key] = np.where(
                            mask_3d == 1,
                            (1 - alpha) * system_overlays_raw[sys_key] + alpha * color_arr,
                            system_overlays_raw[sys_key]
                        )

            # Determine system label for single target
            sys_belong = "Other"
            for sk, tlist in system_indices.items():
                if i in tlist:
                    sys_belong = sk
                    break

            indiv_base64 = numpy_to_base64_png(indiv_overlay)
            segmentation_details.append({
                "id": i,
                "name": t_name,
                "system": sys_belong,
                "color_rgb": color,
                "color_hex": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                "coverage_pct": coverage_pct,
                "mask_base64": indiv_base64
            })

        composite_overlay_uint8 = np.clip(composite_overlay, 0, 255).astype(np.uint8)
        composite_base64 = numpy_to_base64_png(composite_overlay_uint8)

        # Base64 for system-segregated overlays
        segregated_system_overlays = {}
        for sk, raw_mat in system_overlays_raw.items():
            mat_uint8 = np.clip(raw_mat, 0, 255).astype(np.uint8)
            segregated_system_overlays[sk] = numpy_to_base64_png(mat_uint8)

        top_findings = [p for p in pathologies_list if p["severity"] in ["High Risk", "Moderate Risk"]][:3]

        return jsonify({
            "success": True,
            "source": source_name,
            "model_used": MODEL_OPTIONS.get(model_name, model_name),
            "original_image": orig_base64,
            "composite_segmentation": composite_base64,
            "segregated_systems": segregated_system_overlays,
            "segmentation_regions": segmentation_details,
            "pathologies": pathologies_list,
            "top_findings": top_findings
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/gradcam", methods=["POST"])
def gradcam():
    """Generates Grad-CAM / Saliency heatmaps for explainable AI localization."""
    try:
        model_name = request.form.get("model_name", "densenet121-res224-all")
        sample_name = request.form.get("sample_name", "")
        target_pathology = request.form.get("pathology", "")
        file_obj = request.files.get("file", None)

        if file_obj and file_obj.filename != "":
            disp_uint8, img_tensor = load_and_preprocess_image(file_obj)
        elif sample_name:
            safe_path = os.path.abspath(os.path.join(TESTS_DIR, sample_name))
            if not safe_path.startswith(os.path.abspath(TESTS_DIR)) or not os.path.exists(safe_path):
                return jsonify({"error": f"Sample file {sample_name} not found"}), 404
            disp_uint8, img_tensor = load_and_preprocess_image(safe_path)
        else:
            return jsonify({"error": "No image sample selected or uploaded"}), 400

        clf_model = get_clf_model(model_name)
        if target_pathology not in clf_model.pathologies:
            target_idx = 0
            target_pathology = clf_model.pathologies[0]
        else:
            target_idx = clf_model.pathologies.index(target_pathology)

        tensor_copy = img_tensor.clone().detach().requires_grad_(True)
        preds = clf_model(tensor_copy)
        target_score = preds[0, target_idx]
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

        h, w = disp_uint8.shape[:2]
        norm_grad_resized = cv2.resize(norm_grad, (w, h))
        heatmap_color = cv2.applyColorMap(norm_grad_resized, cv2.COLORMAP_JET)
        heatmap_color = cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)

        blended = cv2.addWeighted(disp_uint8, 0.45, heatmap_color, 0.55, 0)
        heatmap_b64 = numpy_to_base64_png(heatmap_color)
        blended_b64 = numpy_to_base64_png(blended)

        return jsonify({
            "success": True,
            "pathology": target_pathology,
            "confidence": round(float(preds[0, target_idx].detach().cpu().numpy()) * 100, 2),
            "heatmap": heatmap_b64,
            "blended": blended_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/autoencode", methods=["POST"])
def autoencode():
    """Generates ResNet-101 Autoencoder reconstruction and anomaly residual heatmap."""
    try:
        sample_name = request.form.get("sample_name", "")
        file_obj = request.files.get("file", None)

        if file_obj and file_obj.filename != "":
            disp_uint8, img_tensor = load_and_preprocess_image(file_obj)
        elif sample_name:
            safe_path = os.path.abspath(os.path.join(TESTS_DIR, sample_name))
            if not safe_path.startswith(os.path.abspath(TESTS_DIR)) or not os.path.exists(safe_path):
                return jsonify({"error": f"Sample file {sample_name} not found"}), 404
            disp_uint8, img_tensor = load_and_preprocess_image(safe_path)
        else:
            return jsonify({"error": "No image specified"}), 400

        ae_model = get_ae_model()
        ae_input = F.interpolate(img_tensor, size=(224, 224), mode="bilinear", align_corners=False)
        with torch.no_grad():
            rec_out = ae_model(ae_input)
            rec_tensor = rec_out["out"] if isinstance(rec_out, dict) else rec_out

        diff = torch.abs(ae_input - rec_tensor).squeeze().cpu().numpy()
        rec_np = rec_tensor.squeeze().cpu().numpy()
        if rec_np.ndim == 3:
            rec_np = rec_np.mean(axis=0)
        if diff.ndim == 3:
            diff = diff.mean(axis=0)

        rec_min, rec_max = rec_np.min(), rec_np.max()
        if rec_max > rec_min:
            rec_uint8 = ((rec_np - rec_min) / (rec_max - rec_min) * 255).astype(np.uint8)
        else:
            rec_uint8 = np.zeros_like(rec_np, dtype=np.uint8)

        rec_rgb = cv2.cvtColor(rec_uint8, cv2.COLOR_GRAY2RGB)
        h, w = disp_uint8.shape[:2]
        rec_rgb_resized = cv2.resize(rec_rgb, (w, h))

        diff_blur = cv2.GaussianBlur(diff, (11, 11), 0)
        d_min, d_max = diff_blur.min(), diff_blur.max()
        if d_max > d_min:
            diff_norm = ((diff_blur - d_min) / (d_max - d_min) * 255).astype(np.uint8)
        else:
            diff_norm = np.zeros_like(diff_blur, dtype=np.uint8)

        diff_norm_resized = cv2.resize(diff_norm, (w, h))
        diff_color = cv2.applyColorMap(diff_norm_resized, cv2.COLORMAP_TURBO)
        diff_color = cv2.cvtColor(diff_color, cv2.COLOR_BGR2RGB)
        anomaly_overlay = cv2.addWeighted(disp_uint8, 0.4, diff_color, 0.6, 0)

        return jsonify({
            "success": True,
            "reconstructed_image": numpy_to_base64_png(rec_rgb_resized),
            "anomaly_map": numpy_to_base64_png(diff_color),
            "anomaly_overlay": numpy_to_base64_png(anomaly_overlay)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/process_image", methods=["POST"])
def process_image():
    """Applies CLAHE, brightness/contrast adjustments, and grayscale inversion."""
    try:
        sample_name = request.form.get("sample_name", "")
        file_obj = request.files.get("file", None)

        apply_clahe = request.form.get("clahe", "false").lower() == "true"
        clip_limit = float(request.form.get("clip_limit", 2.0))
        brightness = float(request.form.get("brightness", 0))
        contrast = float(request.form.get("contrast", 1.0))
        invert = request.form.get("invert", "false").lower() == "true"

        if file_obj and file_obj.filename != "":
            disp_uint8, _ = load_and_preprocess_image(file_obj)
        elif sample_name:
            safe_path = os.path.abspath(os.path.join(TESTS_DIR, sample_name))
            if not safe_path.startswith(os.path.abspath(TESTS_DIR)) or not os.path.exists(safe_path):
                return jsonify({"error": f"Sample file {sample_name} not found"}), 404
            disp_uint8, _ = load_and_preprocess_image(safe_path)
        else:
            return jsonify({"error": "No image specified"}), 400

        img = disp_uint8.copy()

        if apply_clahe:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
            gray_clahe = clahe.apply(gray)
            img = cv2.cvtColor(gray_clahe, cv2.COLOR_GRAY2RGB)

        img = cv2.convertScaleAbs(img, alpha=contrast, beta=brightness)

        if invert:
            img = 255 - img

        return jsonify({
            "success": True,
            "processed_image": numpy_to_base64_png(img)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

