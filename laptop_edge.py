"""EDGE 2 (laptop): baca mikrofon + aktivitas keyboard/mouse, olah, kirim telemetri ke MQTT.

PRIVASI: yang dihitung hanya JUMLAH ketukan dan gerakan mouse. Tombol apa yang ditekan TIDAK dibaca/disimpan,
dan audio TIDAK direkam: hanya level kekerasan (dBFS) tiap jendela yang dikirim.

Jalankan:  python laptop_edge.py
           python laptop_edge.py --source simulator   (latihan tanpa mikrofon/keyboard)
"""
import argparse  # membaca argumen perintah
import math  # akar kuadrat
import random  # data simulasi
import threading  # kunci data bersama
import time  # jeda dan cap waktu
from shared import config, mqtt_client  # pengaturan dan MQTT
from shared import processing as p  # fungsi pengolahan data

DEVICE_ID = "edge2"  # nama perangkat ini


class RealInputs:
    """Sensor asli laptop: mikrofon (sounddevice) dan keyboard/mouse (pynput)."""

    def __init__(self):
        import sounddevice as sd  # library mikrofon
        from pynput import keyboard, mouse  # library keyboard/mouse
        self.lock = threading.Lock()  # kunci data bersama
        self.sumsq, self.count = 0.0, 0  # jumlah kuadrat sampel audio dan banyaknya
        self.keys, self.moves = 0, 0  # jumlah ketukan dan gerakan mouse
        self.stream = sd.InputStream(channels=1, samplerate=16000, callback=self._audio)  # aliran mikrofon
        self.stream.start()  # mulai merekam level (tidak disimpan)
        self.kl = keyboard.Listener(on_press=self._key)  # pendengar keyboard
        self.ml = mouse.Listener(on_move=self._move)  # pendengar mouse
        self.kl.start()  # jalankan pendengar keyboard
        self.ml.start()  # jalankan pendengar mouse

    def _audio(self, indata, frames, time_info, status):
        with self.lock:
            self.sumsq += float((indata ** 2).sum())  # tambah energi sinyal
            self.count += frames  # tambah jumlah sampel

    def _key(self, key):
        with self.lock:
            self.keys += 1  # hitung saja, isi tombol diabaikan

    def _move(self, x, y):
        with self.lock:
            self.moves += 1  # hitung gerakan mouse

    def pop_window(self, seconds):
        """Hasil satu jendela: (noise_dbfs, keys_per_min, mouse_moves) lalu reset penghitung."""
        with self.lock:
            rms = math.sqrt(self.sumsq / max(self.count, 1))  # RMS audio
            keys, moves = self.keys, self.moves  # salin penghitung
            self.sumsq, self.count, self.keys, self.moves = 0.0, 0, 0, 0  # reset
        return p.noise_dbfs(rms), keys / seconds * 60.0, moves  # PENGOLAHAN 4 & 5

    def close(self):
        self.stream.stop()  # hentikan mikrofon
        self.kl.stop()  # hentikan pendengar keyboard
        self.ml.stop()  # hentikan pendengar mouse


class SimInputs:
    """Simulasi siklus 40 detik: tenang+mengetik, tenang+diam, lonjakan suara."""

    def pop_window(self, seconds):
        t = time.time() % 40  # posisi dalam siklus
        noise = -52 + random.gauss(0, 0.8)  # suara ruangan tenang
        if 33 <= t < 37:
            noise = -30 + random.gauss(0, 1)  # lonjakan suara (mis. orang berteriak)
        if t < 20:
            return noise, random.uniform(80, 160), random.randint(0, 40)  # sedang mengetik
        return noise, 0.0, 0  # diam

    def close(self):
        pass  # tidak ada yang perlu dibersihkan


def main():
    parser = argparse.ArgumentParser()  # parser argumen
    parser.add_argument("--source", choices=["auto", "real", "simulator"], default="auto")  # sumber data
    args = parser.parse_args()  # baca argumen
    inputs, mode = None, "simulator"  # default simulator
    if args.source in ("auto", "real"):
        try:
            inputs, mode = RealInputs(), "real"  # coba sensor asli
        except Exception as err:  # driver/izin tidak tersedia
            print(f"[EDGE2] sensor asli gagal ({err}). Pakai simulator.")
    if inputs is None:
        inputs = SimInputs()  # pakai simulasi
    print(f"[EDGE2] sumber: {mode} | PROJECT_ID: {config.PROJECT_ID}")
    try:
        client = mqtt_client.make_client(DEVICE_ID, is_edge=True)  # sambung MQTT
    except OSError as err:
        print(f"[EDGE2] tidak bisa terhubung ke broker: {err}. Cek internet/hotspot.")
        return
    sequence = 0  # nomor paket
    print(f"[EDGE2] kirim ke {config.topic('edge/edge2/telemetry')} tiap {config.WINDOW_SEC}s. Ctrl+C untuk berhenti.")
    try:
        while True:
            time.sleep(config.WINDOW_SEC)  # tunggu satu jendela
            noise, kpm, moves = inputs.pop_window(config.WINDOW_SEC)  # ambil hasil olahan jendela ini
            sequence += 1  # naikkan nomor paket
            payload = {
                "device_id": DEVICE_ID,  # identitas edge
                "sequence": sequence,  # nomor urut
                "sent_at_ms": int(time.time() * 1000),  # cap waktu kirim
                "noise_dbfs": round(noise, 1),  # level suara (dBFS)
                "keys_per_min": round(kpm, 1),  # ketukan per menit
                "mouse_moves": moves,  # jumlah gerakan mouse di jendela
            }
            mqtt_client.publish_json(client, "edge/edge2/telemetry", payload, qos=1)  # kirim hasil olahan
            print(f"[EDGE2] #{sequence} noise={payload['noise_dbfs']} dBFS keys/min={payload['keys_per_min']} mouse={moves}")
    except KeyboardInterrupt:
        print("\n[EDGE2] berhenti.")
    finally:
        inputs.close()  # bersihkan sensor
        mqtt_client.close_edge(client, DEVICE_ID)  # tandai offline


if __name__ == "__main__":
    main()
