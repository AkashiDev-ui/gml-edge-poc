import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.geo_engine import GeoDataError, ZfeMonitor, Zone           # noqa: E402
from src.safety_engine import SafetyDataError, analyse              # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


class TestGeo(unittest.TestCase):
    def setUp(self):
        self.zone = Zone.from_file(os.path.join(DATA, "lyon_polygon.json"))

    def test_points_hors_bbox(self):
        self.assertEqual(self.zone.contains(45.8100, 4.7500), (False, "bbox"))
        self.assertEqual(self.zone.contains(45.8000, 4.7800), (False, "bbox"))

    def test_points_centre(self):
        self.assertTrue(self.zone.contains(45.7600, 4.8357)[0])
        self.assertTrue(self.zone.contains(45.7500, 4.8500)[0])

    def test_point3_dans_bbox_mais_hors_polygone(self):
        inside, method = self.zone.contains(45.7850, 4.8050)
        self.assertEqual(method, "ray_casting")
        self.assertFalse(inside)

    def test_une_seule_alerte_par_entree(self):
        m = ZfeMonitor(self.zone)
        with open(os.path.join(DATA, "truck_gps.json")) as f:
            for p in json.load(f):
                m.process(p)
        self.assertEqual(len(m.alerts), 1)
        self.assertEqual(m.alerts[0]["id"], 4)

    def test_gps_corrompu_ne_plante_pas(self):
        m = ZfeMonitor(self.zone)
        with open(os.path.join(DATA, "truck_gps_corrupted.json")) as f:
            for p in json.load(f):
                m.process(p)
        m.process(None)
        self.assertEqual(m.stats["rejected"], 4)
        self.assertEqual(len(m.alerts), 1)

    def test_polygone_invalide(self):
        with self.assertRaises(GeoDataError):
            Zone([{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}])
        with self.assertRaises(GeoDataError):
            Zone.from_file("inexistant.json")


class TestSafety(unittest.TestCase):
    def test_freinage_detecte(self):
        r = analyse(os.path.join(DATA, "accelerometer_data.csv"))
        self.assertEqual(r["summary"]["harsh_braking_count"], 1)
        self.assertEqual(r["events"][0]["timestamp"], 1678880005)
        self.assertEqual(r["events"][0]["peak_acc_y_ms2"], -3.45)

    def test_csv_corrompu(self):
        r = analyse(os.path.join(DATA, "accelerometer_corrupted.csv"))
        self.assertEqual(r["summary"]["harsh_braking_count"], 1)
        self.assertEqual(r["processing"]["lines_rejected"], 5)

    def test_100hz_regroupement_et_lissage(self):
        # 2 s de bruit à 100 Hz + freinage réel de 0,5 s + pic parasite isolé (nid-de-poule)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("timestamp,acc_x,acc_y,acc_z\n")
            for i in range(300):
                y = -3.5 if 100 <= i < 150 else (-6.0 if i == 250 else 0.1)
                f.write(f"{i/100},0.1,{y},9.81\n")
            path = f.name
        try:
            r = analyse(path)
            self.assertEqual(r["processing"]["smoothing_window"], 20)
            self.assertEqual(r["summary"]["harsh_braking_count"], 1)   # pic isolé filtré
        finally:
            os.remove(path)

    def test_fichier_absent(self):
        with self.assertRaises(SafetyDataError):
            analyse("inexistant.csv")


if __name__ == "__main__":
    unittest.main(verbosity=2)
