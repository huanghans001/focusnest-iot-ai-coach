"""Uji unit pengolahan data dan mesin fusion. Jalankan: python -m unittest discover -s tests -v"""
import os, sys, unittest  # modul standar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agar folder shared terbaca
from shared import processing as p  # fungsi pengolahan
from shared.engine import FocusEngine  # mesin fusion


def hp(rms=0.02, orient="face_down", lux=None, stamp=1):
    """Telemetri HP palsu."""
    return {"motion_rms": rms, "orientation": orient, "lux": lux, "sent_at_ms": stamp}


def pc(noise=-52.0, kpm=0.0, moves=0):
    """Telemetri laptop palsu."""
    return {"noise_dbfs": noise, "keys_per_min": kpm, "mouse_moves": moves}


class TestProcessing(unittest.TestCase):
    def test_rms_diam_hampir_nol(self):
        self.assertAlmostEqual(p.rms_motion([(0, 0, 9.81)] * 10), 0.0, places=3)  # HP diam

    def test_rms_bergerak(self):
        self.assertGreater(p.rms_motion([(0, 0, 12.0), (0, 0, 7.0)] * 5), 2.0)  # HP bergoyang

    def test_orientasi(self):
        self.assertEqual(p.orientation(-9.8), "face_down")  # telungkup
        self.assertEqual(p.orientation(9.8), "face_up")  # telentang
        self.assertEqual(p.orientation(2.0), "tilted")  # miring

    def test_dbfs(self):
        self.assertAlmostEqual(p.noise_dbfs(1.0), 0.0)  # skala penuh
        self.assertAlmostEqual(p.noise_dbfs(0.1), -20.0)  # 1/10 amplitudo

    def test_skor_suara_dan_cahaya(self):
        self.assertEqual(p.noise_score(0), 100.0)  # tenang
        self.assertEqual(p.noise_score(25), 0.0)  # sangat berisik
        self.assertEqual(p.light_score(500), 100.0)  # ideal
        self.assertLess(p.light_score(60), 20.0)  # gelap

    def test_fusion_normalisasi_bobot(self):
        self.assertAlmostEqual(p.focus_score({"noise": 100, "light": None, "phone": 100, "activity": 100}), 100.0)  # None dilewati

    def test_zscore_lonjakan(self):
        s = p.EwmaStats()  # statistik baru
        for _ in range(20):
            s.zscore(0.0)  # belajar kondisi tenang
        self.assertGreater(s.zscore(15.0), 3.0)  # lonjakan 15 dB terdeteksi


class TestEngine(unittest.TestCase):
    def test_menunggu_data(self):
        status, _ = FocusEngine().update(None, pc(), 0.0)  # edge1 belum ada
        self.assertEqual(status["state"], "WAITING")

    def test_idle_sebelum_sesi(self):
        status, alerts = FocusEngine().update(hp(), pc(), 0.0)  # sesi belum dimulai
        self.assertEqual(status["state"], "IDLE")
        self.assertEqual(alerts, [])  # tidak ada alert

    def test_fokus(self):
        e = FocusEngine(); e.start_session(0.0)  # mulai sesi
        status, _ = e.update(hp(), pc(kpm=100), 1.0)  # HP diam telungkup, laptop aktif
        self.assertEqual(status["state"], "FOCUS")

    def test_hp_diangkat_saat_laptop_sepi(self):
        e = FocusEngine(); e.start_session(0.0)
        e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=1), pc(), 1.0)  # jendela 1 bergerak
        status, alerts = e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=2), pc(), 2.0)  # jendela 2 bergerak
        self.assertEqual(status["state"], "PHONE_DISTRACTION")
        self.assertEqual(alerts[0]["type"], "PHONE_DISTRACTION")  # alert dikirim ke HP

    def test_hp_bergerak_saat_mengetik_bukan_gangguan(self):
        e = FocusEngine(); e.start_session(0.0)
        e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=1), pc(kpm=120), 1.0)
        status, alerts = e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=2), pc(kpm=120), 2.0)
        self.assertNotEqual(status["state"], "PHONE_DISTRACTION")  # laptop aktif -> bukan gangguan
        self.assertEqual(alerts, [])

    def test_lonjakan_suara(self):
        e = FocusEngine(); e.start_session(0.0)
        for i in range(15):
            e.update(hp(stamp=i), pc(noise=-52.0), float(i))  # kondisi tenang
        status, alerts = e.update(hp(stamp=99), pc(noise=-30.0), 16.0)  # +22 dB
        self.assertEqual(status["state"], "NOISE_SPIKE")

    def test_cooldown_alert(self):
        e = FocusEngine(); e.start_session(0.0)
        total = 0
        for i in range(6):  # 6 detik terus bergerak
            _, alerts = e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=i), pc(), float(i))
            total += len(alerts)
        self.assertEqual(total, 1)  # hanya 1 alert karena cooldown 15 detik


if __name__ == "__main__":
    unittest.main()
