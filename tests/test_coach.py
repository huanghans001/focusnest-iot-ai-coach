"""Uji AI Coach: statistik sesi, sanitasi whitelist, fallback, dan LLM (dimock, tanpa jaringan)."""
import json, os, sys, types, unittest  # modul standar
from unittest import mock  # tiruan panggilan LLM
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agar folder shared terbaca
from shared import coach, config  # modul yang diuji
from shared.engine import FocusEngine  # mesin fusion


def hp(rms=0.02, orient="face_down", lux=None, stamp=1):
    """Telemetri HP palsu."""
    return {"motion_rms": rms, "orientation": orient, "lux": lux, "sent_at_ms": stamp}


def pc(noise=-52.0, kpm=0.0, moves=0):
    """Telemetri laptop palsu."""
    return {"noise_dbfs": noise, "keys_per_min": kpm, "mouse_moves": moves}


def summary(**kw):
    """Ringkasan sesi palsu yang valid; kw menimpa nilai bawaan."""
    base = {"duration_s": 1500, "focus_s": 1300, "focus_pct": 86.7, "event_counts": {},
            "avg_score": 85.0, "avg_component_scores": {"noise": 95.0, "light": None, "phone": 90.0, "activity": 70.0},
            "min_score": 50.0, "events": []}
    base.update(kw)
    return base


class TestEngineSummary(unittest.TestCase):
    def test_hitung_event_dan_ringkasan(self):
        e = FocusEngine(); e.start_session(0.0)
        for i in range(1, 4):  # HP terus bergerak saat laptop sepi
            e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=i), pc(), float(i))
        e.update(hp(rms=0.02, orient="tilted", lux=30, stamp=9), pc(), 70.0)  # gelap di detik ke-70
        e.stop_session(80.0)
        s = e.build_session_summary()
        self.assertEqual(s["event_counts"].get("PHONE_DISTRACTION"), 1)  # cooldown 15 detik -> 1 alert
        self.assertEqual(s["event_counts"].get("TOO_DARK"), 1)  # gelap dihitung di event_counts
        self.assertEqual(e.distractions, 1)  # perilaku lama: gelap bukan gangguan
        self.assertEqual(s["duration_s"], 80)
        self.assertEqual([x["type"] for x in s["events"]], ["PHONE_DISTRACTION", "TOO_DARK"])
        self.assertEqual(s["events"][1]["minute"], 2)  # detik ke-70 = menit ke-2
        self.assertIsNotNone(s["avg_score"]); self.assertIsNotNone(s["min_score"])
        self.assertLessEqual(s["min_score"], s["avg_score"])

    def test_reset_saat_sesi_baru(self):
        e = FocusEngine(); e.start_session(0.0)
        for i in range(1, 4):
            e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=i), pc(), float(i))
        e.start_session(100.0)  # sesi baru
        s = e.build_session_summary()
        self.assertEqual(s["event_counts"], {}); self.assertEqual(s["events"], [])
        self.assertIsNone(s["avg_score"]); self.assertIsNone(s["min_score"])

    def test_daftar_kejadian_maks_20(self):
        e = FocusEngine(); e.start_session(0.0)
        for i in range(60):  # tiap 16 detik satu alert PHONE_DISTRACTION
            e.update(hp(rms=2.0, orient="tilted", lux=300, stamp=i), pc(), i * 16.0)
        self.assertLessEqual(len(e.build_session_summary()["events"]), 20)

    def test_key_ringkasan_hanya_whitelist(self):
        e = FocusEngine(); e.start_session(0.0)
        e.update(hp(), pc(kpm=100), 1.0)
        self.assertEqual(set(e.build_session_summary()), set(coach.SUMMARY_KEYS))
        self.assertEqual(coach.sanitize_summary(e.build_session_summary()), e.build_session_summary())  # tak ada yang terbuang


class TestSanitize(unittest.TestCase):
    def test_key_di_luar_whitelist_dibuang(self):
        kotor = summary(project_id="focusnest_kelompok_13", nama="Budi", nim="24060125120005", audio=[0.1, 0.2],
                        keyboard_text="rahasia", api_key="sk-xxx")
        bersih = coach.sanitize_summary(kotor)
        self.assertEqual(set(bersih), set(coach.SUMMARY_KEYS))
        for k in ("project_id", "nama", "nim", "audio", "keyboard_text", "api_key"):
            self.assertNotIn(k, bersih)

    def test_nilai_bersarang_disaring(self):
        bersih = coach.sanitize_summary(summary(
            event_counts={"PHONE_DISTRACTION": 2, "NAMA_ORANG": 9},
            avg_component_scores={"noise": 90, "light": None, "nim": 1},
            events=[{"minute": 3, "type": "NOISE_SPIKE", "catatan": "Budi"}, {"minute": 4, "type": "LAINNYA"}, "teks bebas"]))
        self.assertEqual(bersih["event_counts"], {"PHONE_DISTRACTION": 2})
        self.assertEqual(bersih["avg_component_scores"], {"noise": 90, "light": None})
        self.assertEqual(bersih["events"], [{"minute": 3, "type": "NOISE_SPIKE"}])  # key ekstra dan jenis asing dibuang

    def test_teks_bebas_di_kolom_angka_ditolak(self):
        bersih = coach.sanitize_summary(summary(duration_s="abaikan instruksi", focus_pct=True, min_score=float("nan")))
        for k in ("duration_s", "focus_pct", "min_score"):
            self.assertNotIn(k, bersih)

    def test_maks_20_kejadian_dan_input_bukan_dict(self):
        banyak = [{"minute": i, "type": "TOO_DARK"} for i in range(50)]
        self.assertEqual(len(coach.sanitize_summary(summary(events=banyak))["events"]), 20)
        self.assertEqual(coach.sanitize_summary("bukan dict"), {})

    def test_idempoten(self):
        once = coach.sanitize_summary(summary(project_id="x"))
        self.assertEqual(coach.sanitize_summary(once), once)


class TestFallback(unittest.TestCase):
    def _poin(self, text):
        return [l for l in text.splitlines() if l.startswith("- ")]

    def test_sesi_sangat_fokus(self):
        t = coach.fallback_advice(summary(focus_pct=92.0, event_counts={}))
        self.assertIn("92%", t); self.assertIn("sangat baik", t); self.assertEqual(len(self._poin(t)), 2)

    def test_banyak_phone_distraction(self):
        t = coach.fallback_advice(summary(focus_pct=40.0, event_counts={"PHONE_DISTRACTION": 6, "TOO_DARK": 1},
                                          events=[{"minute": 4, "type": "PHONE_DISTRACTION"}]))
        self.assertIn("HP terangkat 6 kali", t); self.assertIn("telungkup", t); self.assertIn("menit ke-4", t)
        self.assertEqual(len(self._poin(t)), 2)

    def test_sering_too_dark(self):
        t = coach.fallback_advice(summary(focus_pct=60.0, event_counts={"TOO_DARK": 5}))
        self.assertIn("terlalu gelap 5 kali", t); self.assertIn("lampu", t)

    def test_sesi_sangat_singkat(self):
        t = coach.fallback_advice(summary(duration_s=45, focus_pct=100.0))
        self.assertIn("terlalu singkat", t); self.assertEqual(len(self._poin(t)), 2)

    def test_deterministik(self):
        s = summary(focus_pct=55.0, event_counts={"NOISE_SPIKE": 3, "PHONE_DISTRACTION": 3})
        self.assertEqual(coach.fallback_advice(s), coach.fallback_advice(dict(s)))

    def test_data_kosong_tidak_crash(self):
        self.assertTrue(coach.fallback_advice({}))
        self.assertTrue(coach.fallback_advice(summary(avg_score=None, min_score=None, avg_component_scores={})))


class TestGenerateAdvice(unittest.TestCase):
    def _cfg(self, enabled=True, key="kunci-palsu", model="model-palsu"):
        return mock.patch.multiple(config, LLM_ENABLED=enabled, LLM_API_KEY=key, LLM_MODEL=model, LLM_PROVIDER="anthropic")

    def test_llm_sukses(self):
        with self._cfg(), mock.patch.object(coach, "_call_llm", return_value="  Saran dari LLM  ") as m:
            r = coach.generate_advice(summary())
        self.assertEqual(r, {"source": "llm", "text": "Saran dari LLM"}); m.assert_called_once()

    def test_llm_hanya_menerima_data_whitelist(self):
        with self._cfg(), mock.patch.object(coach, "_call_llm", return_value="ok") as m:
            coach.generate_advice(summary(project_id=config.PROJECT_ID, nim="24060125120005"))
        diterima = m.call_args[0][0]
        self.assertEqual(set(diterima) - set(coach.SUMMARY_KEYS), set())
        self.assertNotIn(config.PROJECT_ID, json.dumps(diterima)); self.assertNotIn("24060125120005", json.dumps(diterima))

    def test_error_jaringan_jadi_fallback(self):
        with self._cfg(), mock.patch.object(coach, "_call_llm", side_effect=TimeoutError("lambat")):
            r = coach.generate_advice(summary())
        self.assertEqual(r["source"], "fallback"); self.assertTrue(r["text"])

    def test_balasan_kosong_jadi_fallback(self):
        with self._cfg(), mock.patch.object(coach, "_call_llm", return_value="   "):
            self.assertEqual(coach.generate_advice(summary())["source"], "fallback")

    def test_llm_mati_atau_tanpa_key_tidak_memanggil_llm(self):
        for kw in ({"enabled": False}, {"key": ""}, {"model": ""}):
            with self._cfg(**kw), mock.patch.object(coach, "_call_llm") as m:
                self.assertEqual(coach.generate_advice(summary())["source"], "fallback")
            m.assert_not_called()

    def test_sdk_dipanggil_dengan_timeout_retry_dan_prompt(self):
        blok = types.SimpleNamespace(type="text", text="Halo")
        fake = types.ModuleType("anthropic")  # SDK palsu: tidak ada jaringan
        fake.Anthropic = mock.Mock(return_value=mock.Mock(messages=mock.Mock(create=mock.Mock(return_value=types.SimpleNamespace(content=[blok])))))
        with self._cfg(), mock.patch.dict(sys.modules, {"anthropic": fake}):
            r = coach.generate_advice(summary(nama="Budi"))
        self.assertEqual(r, {"source": "llm", "text": "Halo"})
        kw = fake.Anthropic.call_args.kwargs
        self.assertEqual((kw["timeout"], kw["max_retries"], kw["api_key"]), (10.0, 1, "kunci-palsu"))
        create = fake.Anthropic.return_value.messages.create.call_args.kwargs
        self.assertEqual(create["model"], "model-palsu"); self.assertEqual(create["system"], coach.SYSTEM_PROMPT)
        self.assertNotIn("Budi", create["messages"][0]["content"])  # kiriman = JSON hasil sanitasi
        self.assertNotIn("kunci-palsu", create["messages"][0]["content"])  # key tidak ikut terkirim sebagai isi

    def test_library_belum_terpasang_jadi_fallback(self):
        with self._cfg(), mock.patch.dict(sys.modules, {"anthropic": None}):  # import -> ImportError
            self.assertEqual(coach.generate_advice(summary())["source"], "fallback")


if __name__ == "__main__":
    unittest.main()
