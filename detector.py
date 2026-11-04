"""NODE 3 (laptop): menerima telemetri dari edge1 & edge2, sensor fusion, kirim status + alert, host dashboard.

Jalankan:  python detector.py
"""
import functools  # membuat handler HTTP dengan folder tertentu
import http.server  # server web sederhana untuk dashboard
import json  # parsing JSON
import pathlib  # path folder dashboard
import threading  # lock dan thread server web
import time  # jeda dan waktu
from shared import coach, config, mqtt_client  # AI Coach, pengaturan, dan MQTT
from shared.engine import FocusEngine  # mesin sensor fusion

DASH_DIR = pathlib.Path(__file__).parent / "dashboard"  # folder dashboard
LOCK = threading.Lock()  # lindungi data bersama antar thread
LATEST = {}  # device_id -> (telemetri, waktu terima)
ENGINE = FocusEngine()  # mesin fusion


def run_coach(client, summary):
    """Susun saran AI Coach lalu publish ke topik coach. Dijalankan di thread terpisah (panggilan LLM bisa lambat)."""
    try:
        clean = coach.sanitize_summary(summary)  # hanya key whitelist yang boleh keluar
        advice = coach.generate_advice(clean)  # LLM atau fallback (tidak pernah melempar error)
        payload = {"source": advice["source"], "text": advice["text"], "summary": clean, "sent_at_ms": int(time.time() * 1000)}
        mqtt_client.publish_json(client, "coach", payload, qos=1, retain=True)  # topik focusnest/<PROJECT_ID>/coach
        print(f"[COACH] saran terkirim (sumber: {advice['source']})")
    except Exception as err:
        print(f"[COACH] gagal menyusun saran: {type(err).__name__}")  # jangan sampai detector crash


def on_message(client, userdata, msg):
    """Terima telemetri edge dan perintah dari dashboard."""
    try:
        data = json.loads(msg.payload)  # baca JSON
    except ValueError:
        return  # abaikan pesan rusak
    if msg.topic.endswith("/telemetry"):
        device = msg.topic.split("/")[-2]  # edge1 / edge2
        with LOCK:
            LATEST[device] = (data, time.monotonic())  # simpan paket terbaru
    elif msg.topic == config.topic("cmd"):
        action = data.get("action")  # start / stop
        with LOCK:
            if action == "start":
                ENGINE.start_session(time.monotonic())  # mulai sesi
                print("[CMD] sesi dimulai")
            elif action == "stop":
                was_active = ENGINE.active  # hanya sesi yang benar-benar berjalan yang diringkas
                ENGINE.stop_session(time.monotonic())  # akhiri sesi
                print("[CMD] sesi dihentikan")
                if was_active:
                    summary = ENGINE.build_session_summary()  # statistik agregat sesi
                    threading.Thread(target=run_coach, args=(client, summary), daemon=True).start()  # jangan blokir loop MQTT


def fresh(device, now):
    """Telemetri device bila belum basi, kalau tidak None."""
    item = LATEST.get(device)  # (data, waktu)
    if item and now - item[1] <= config.STALE_SEC:
        return item[0]  # masih segar
    return None  # basi atau belum ada


def serve_dashboard():
    """Jalankan web server statis untuk folder dashboard (bisa dibuka dari HP di jaringan yang sama)."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass  # jangan cetak log tiap request
    handler = functools.partial(Quiet, directory=str(DASH_DIR))  # layani folder dashboard
    server = http.server.ThreadingHTTPServer(("0.0.0.0", config.DASHBOARD_PORT), handler)  # semua antarmuka
    threading.Thread(target=server.serve_forever, daemon=True).start()  # jalankan di latar belakang


def main():
    print("FocusNest - NODE 3 / Laptop (processing server + dashboard)")
    try:
        serve_dashboard()  # nyalakan dashboard
    except OSError as err:
        print(f"[DASHBOARD] gagal membuka port {config.DASHBOARD_PORT}: {err}")
    print(f"[DASHBOARD] di laptop : http://localhost:{config.DASHBOARD_PORT}/?project={config.PROJECT_ID}")
    print(f"[DASHBOARD] dari HP   : http://{config.lan_ip()}:{config.DASHBOARD_PORT}/?project={config.PROJECT_ID}")
    print(f"[CONFIG] PROJECT_ID: {config.PROJECT_ID}")
    try:
        client = mqtt_client.make_client("detector", subscribe=[config.topic("edge/+/telemetry"), config.topic("cmd")], on_message=on_message)  # sambung MQTT
    except OSError as err:
        print(f"[DETECTOR] tidak bisa terhubung ke broker: {err}. Cek internet/hotspot.")
        return
    print("[DETECTOR] menunggu edge1 (HP) dan edge2 (laptop)...")
    last_state = None  # untuk mencetak saat status berubah
    try:
        while True:
            time.sleep(1)  # evaluasi tiap detik
            now = time.monotonic()  # waktu monoton
            with LOCK:
                hp, pc = fresh("edge1", now), fresh("edge2", now)  # data segar
                status, alerts = ENGINE.update(hp, pc, now)  # sensor fusion
            status["edges"] = {"edge1": hp is not None, "edge2": pc is not None}  # edge mana yang aktif
            mqtt_client.publish_json(client, "status", status, qos=0, retain=True)  # kirim ke dashboard & HP
            for alert in alerts:
                mqtt_client.publish_json(client, "alerts", alert, qos=1)  # kirim balik ke HP (arah 2)
                print(f"[ALERT] {alert['type']}: {alert['message']}")
            if status["state"] != last_state:
                last_state = status["state"]  # simpan
                print(f"[STATUS] {status['state']} | skor={status['focus_score']} | {status['reason']}")
    except KeyboardInterrupt:
        print("\n[DETECTOR] berhenti.")
    finally:
        client.loop_stop()  # hentikan loop MQTT
        client.disconnect()  # putus koneksi


if __name__ == "__main__":
    main()
