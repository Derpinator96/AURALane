import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_app import app

class TorchXRayVisionAppTestCase(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_samples_endpoint(self):
        """Test listing available sample images, categories, and model definitions recursively."""
        response = self.client.get('/api/samples')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('samples', data)
        self.assertIn('models', data)
        self.assertIn('categories', data)
        self.assertGreater(len(data['samples']), 4)
        print(f"Found {len(data['samples'])} sample images across {len(data['categories'])} categories.")

    def test_category_filtering(self):
        """Test filtering sample scans by category."""
        response = self.client.get('/api/samples?category=DICOM%20Modality')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(all(s['category'] == 'DICOM Modality' for s in data['samples']))

    def test_subfolder_sample_image_endpoint(self):
        """Test serving sample image from subfolder (TBX11k dataset)."""
        rel_path = "tbx11k_test_data/imgs/tb/tb0005.png"
        response = self.client.get(f'/api/sample_img/{rel_path}')
        self.assertEqual(response.status_code, 200)

    def test_analyze_sample_image_and_segregation(self):
        """Test full diagnostic pipeline and organ system segregation."""
        sample_name = "00000001_000.png"
        response = self.client.post('/api/analyze', data={
            'sample_name': sample_name,
            'model_name': 'densenet121-res224-all'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('original_image', data)
        self.assertIn('composite_segmentation', data)
        self.assertIn('segregated_systems', data)
        self.assertIn('segmentation_regions', data)
        self.assertIn('pathologies', data)

        # Check organ system segregated maps
        seg_sys = data['segregated_systems']
        self.assertIn('Pulmonary', seg_sys)
        self.assertIn('Cardiovascular', seg_sys)
        self.assertIn('Musculoskeletal', seg_sys)
        self.assertIn('Diaphragmatic', seg_sys)

        # Check segmentation targets
        self.assertEqual(len(data['segmentation_regions']), 14)
        print("Successfully generated 14 anatomical segmentation targets and 4 organ system segregated overlays.")

        # Check pathology predictions
        self.assertGreater(len(data['pathologies']), 0)
        top_path = data['pathologies'][0]
        print(f"Top pathology prediction: {top_path['pathology']} with {top_path['confidence']}% confidence.")

    def test_analyze_dicom_sample(self):
        """Test diagnostic pipeline on DICOM format file."""
        sample_name = "1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm"
        response = self.client.post('/api/analyze', data={
            'sample_name': sample_name,
            'model_name': 'densenet121-res224-all'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('composite_segmentation', data)

    def test_gradcam_endpoint(self):
        """Test Grad-CAM explainability heatmap generator."""
        response = self.client.post('/api/gradcam', data={
            'sample_name': '00000001_000.png',
            'model_name': 'densenet121-res224-all',
            'pathology': 'Cardiomegaly'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('heatmap', data)
        self.assertIn('blended', data)
        self.assertEqual(data['pathology'], 'Cardiomegaly')

    def test_autoencode_endpoint(self):
        """Test ResNet-101 Autoencoder reconstruction & residual anomaly map."""
        response = self.client.post('/api/autoencode', data={
            'sample_name': '00000001_000.png'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('reconstructed_image', data)
        self.assertIn('anomaly_map', data)
        self.assertIn('anomaly_overlay', data)

    def test_process_image_endpoint(self):
        """Test CLAHE, contrast, brightness, and inversion processing."""
        response = self.client.post('/api/process_image', data={
            'sample_name': '00000001_000.png',
            'clahe': 'true',
            'contrast': '1.2',
            'brightness': '10',
            'invert': 'true'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('processed_image', data)

if __name__ == '__main__':
    unittest.main()

