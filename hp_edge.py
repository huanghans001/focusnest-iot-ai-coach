"""EDGE 1 (HP / Termux): baca accelerometer + light, olah di HP, kirim telemetri, terima alert.

Jalankan:  python hp_edge.py                (otomatis pakai sensor asli di Termux)
           python hp_edge.py --source simulator   (latihan tanpa sensor)
"""
import argparse  # membaca argumen perintah
import json  # parsing JSON
import random  # data simulasi
import shutil  # cek apakah termux-sensor ada
import subprocess  # menjalankan perintah Termux
import threading  # thread pembaca sensor
import time  # jeda dan cap waktu
from shared import config, mqtt_client  # pengaturan dan MQTT
from shared import processing as p  # fungsi pengolahan data

DEVICE_ID = "edge1"  # nama perangkat ini
STATE = {"last_state": None}  # status terakhir yang sudah dicetak


class TermuxSensors:
    """Membaca stream termux-sensor (accelerometer 10 Hz + light) di thread terpisah."""

    def __init__(self):
        self.lock = threading.Lock()  # kunci data bersama
        self.accel = []  # sampel accelerometer pada jendela ini
        self.lux = None  # nilai cahaya terakhir
        cmd = ["termux-sensor", "-s", "accelerometer,light", "-d", "100"]  # stream tiap 100 ms
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)  # mulai stream
        threading.Thread(target=self._read, daemon=True).start()  # pembaca berjalan di latar belakang

    def _read(self):
        """Gabungkan baris-baris keluaran menjadi satu objek JSON utuh, lalu proses."""
        depth, buf = 0, []  # kedalaman kurung kurawal dan penampung baris
        for line in self.proc.stdout:
            depth += line.count("{") - line.count("}")  # lacak kurung kurawal
            buf.append(line)  # simpan baris
            if depth == 0:
                text = "".join(buf).strip()  # satu objek lengkap
                buf = []  # kosongkan penampung
                if text:
                    try:
                        self._handle(json.loads(text))  # proses objek sensor
                    except ValueError:
                        pass  # abaikan potongan rusak

    def _handle(self, obj):
        """Pisahkan nilai accelerometer dan cahaya berdasarkan nama sensor."""
        with self.lock:
            for name, data in obj.items():
                values = data.get("values", [])  # daftar angka sensor
                key = name.lower()  # nama sensor huruf kecil
                if "accelerometer" in key and "uncalibrated" not in key and len(values) >= 3:
                    self.accel.append(tuple(float(v) for v in values[:3]))  # simpan x, y, z
                elif "light" in key and values:
                    self.lux = float(values[0])  # simpan lux

    def pop_window(self):
        """Ambil semua sampel sejak pemanggilan terakhir, lalu kosongkan."""
        with self.lock:
            samples, self.accel = self.accel, []  # tukar dengan list kosong
            return samples, self.lux

    def close(self):
        """Hentikan stream dan bersihkan sensor Termux."""
        self.proc.terminate()  # matikan proses stream
        subprocess.run(["termux-sensor", "-c"], capture_output=True)  # lepas sensor


class SimSensors:
    """Simulasi siklus 40 detik: telentang, telungkup, diangkat 8 detik, telentang lagi."""

    def pop_window(self):
        t = time.time() % 40  # posisi dalam siklus
        n = max(3, int(config.WINDOW_SEC * 10))  # jumlah sampel (10 Hz)
        if 30 <= t < 38:  # HP diangkat
            samples = [(random.gauss(2, 2), random.gauss(1, 2), random.gauss(6, 2)) for _ in range(n)]
            return samples, 320.0
        if 15 <= t < 30:  # telungkup
            return [(random.gauss(0, .03), random.gauss(0, .03), -9.81 + random.gauss(0, .03)) for _ in range(n)], 0.0
        return [(random.gauss(0, .03), random.gauss(0, .03), 9.81 + random.gauss(0, .03)) for _ in range(n)], 400 + random.gauss(0, 15)

    def close(self):
        pass  # tidak ada yang perlu dibersihkan


def run_quiet(cmd):
    """Jalankan perintah Termux:API tanpa menunggu; di luar Termux cukup dicetak."""
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # jalankan di latar belakang
    except FileNotFoundError:
        print("[ALARM-SIM]", " ".join(cmd))  # bukan Termux


def on_message(client, userdata, msg):
    """Pesan dari laptop: alert -> getar + notifikasi; status -> cetak saat berubah."""
    try:
        data = json.loads(msg.payload)  # baca JSON
    except ValueError:
        return  # bukan JSON
    if msg.topic == config.topic("alerts"):
        text = data.get("message", "Kembali fokus!")  # isi peringatan
        print(f"[ALERT] {data.get('type')}: {text}")  # tampilkan di terminal
        run_quiet(["termux-vibrate", "-d", "1200"])  # getarkan HP
        run_quiet(["termux-notification", "--id", "focusnest", "--title", "FocusNest", "--content", text, "--priority", "high"])  # notifikasi
    elif msg.topic == config.topic("status"):
        state = data.get("state")  # status terbaru
        if state != STATE["last_state"]:
            STATE["last_state"] = state  # simpan agar tidak dicetak berulang
            print(f"[STATUS] {state} (skor {data.get('focus_score')})")


def main():
    parser = argparse.ArgumentParser()  # parser argumen
    parser.add_argument("--source", choices=["auto", "termux", "simulator"], default="auto")  # sumber data
    args = parser.parse_args()  # baca argumen
    use_termux = args.source == "termux" or (args.source == "auto" and shutil.which("termux-sensor"))  # pilih sumber
    sensors = TermuxSensors() if use_termux else SimSensors()  # buat pembaca sensor
    print(f"[EDGE1] sumber: {'termux' if use_termux else 'simulator'} | PROJECT_ID: {config.PROJECT_ID}")
    try:
        client = mqtt_client.make_client(DEVICE_ID, subscribe=[config.topic("alerts"), config.topic("status")], on_message=on_message, is_edge=True)  # sambung MQTT
    except OSError as err:
        print(f"[EDGE1] tidak bisa terhubung ke broker: {err}. Cek internet/hotspot.")
        return
    sequence, lux_smooth = 0, None  # nomor paket dan lux yang dihaluskan
    print(f"[EDGE1] kirim ke {config.topic('edge/edge1/telemetry')} tiap {config.WINDOW_SEC}s. Ctrl+C untuk berhenti.")
    try:
        while True:
            time.sleep(config.WINDOW_SEC)  # tunggu satu jendela
            samples, lux = sensors.pop_window()  # ambil data jendela ini
            if len(samples) < 3:
                print("[EDGE1] sensor belum mengirim data. Cek izin Termux:API.")
                continue  # lewati jendela ini
            motion = p.rms_motion(samples)  # PENGOLAHAN 1: RMS getaran
            orient = p.orientation(sum(s[2] for s in samples) / len(samples))  # PENGOLAHAN 2: orientasi
            if lux is not None and orient != "face_down":
                lux_smooth = p.ewma(lux_smooth, lux)  # PENGOLAHAN 3: haluskan cahaya (abaikan saat tertutup)
            sequence += 1  # naikkan nomor paket
            payload = {
                "device_id": DEVICE_ID,  # identitas edge
                "sequence": sequence,  # nomor urut
                "sent_at_ms": int(time.time() * 1000),  # cap waktu kirim
                "motion_rms": round(motion, 3),  # RMS getaran (m/s2)
                "orientation": orient,  # face_up / face_down / tilted
                "lux": None if orient == "face_down" or lux_smooth is None else round(lux_smooth, 1),  # cahaya
                "samples": len(samples),  # jumlah sampel di jendela
            }
            mqtt_client.publish_json(client, "edge/edge1/telemetry", payload, qos=1)  # kirim hasil olahan, bukan data mentah
            print(f"[EDGE1] #{sequence} rms={payload['motion_rms']} {orient} lux={payload['lux']}")
    except KeyboardInterrupt:
        print("\n[EDGE1] berhenti.")
    finally:
        sensors.close()  # bersihkan sensor
        mqtt_client.close_edge(client, DEVICE_ID)  # tandai offline


if __name__ == "__main__":
    main()
