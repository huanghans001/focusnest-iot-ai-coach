"""Pengaturan bersama untuk HP dan laptop (dibaca dari file .env)."""
import os  # membaca environment variable
import re  # membersihkan PROJECT_ID
import socket  # mencari IP laptop di jaringan
from dotenv import load_dotenv  # membaca file .env

load_dotenv()  # muat isi file .env ke environment

PROJECT_ID = re.sub(r"[^A-Za-z0-9_-]", "_", os.getenv("PROJECT_ID", "focusnest_demo"))  # nama unik kelompok
MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")  # alamat broker
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))  # 8883 = MQTT over TLS
MQTT_TLS = os.getenv("MQTT_TLS", "true").lower() == "true"  # pakai TLS atau tidak
MQTT_USER = os.getenv("MQTT_USER", "")  # username (kosong untuk broker publik)
MQTT_PASS = os.getenv("MQTT_PASS", "")  # password (kosong untuk broker publik)
WINDOW_SEC = float(os.getenv("WINDOW_SEC", "2"))  # panjang jendela pengolahan (detik)
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))  # port dashboard web
MOVE_RMS_THRESHOLD = float(os.getenv("MOVE_RMS_THRESHOLD", "0.7"))  # ambang HP dianggap bergerak (m/s2)
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() == "true"  # AI Coach lewat LLM (default mati = tidak ada data keluar)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()  # penyedia LLM (saat ini: anthropic)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")  # kunci API (HANYA dari .env, jangan dikirim ke MQTT)
LLM_MODEL = os.getenv("LLM_MODEL", "")  # nama model (dari .env, tidak ditulis di kode)
LLM_TIMEOUT_SEC = 10.0  # batas waktu satu panggilan LLM
LLM_MAX_RETRIES = 1  # maksimal ulang sekali bila gagal
STALE_SEC = 10.0  # data lebih tua dari ini dianggap hilang
ALERT_COOLDOWN_SEC = 15.0  # jeda minimal antar alert sejenis


def topic(suffix):
    """Bentuk topic MQTT: focusnest/<PROJECT_ID>/<suffix>."""
    return f"focusnest/{PROJECT_ID}/{suffix}"  # contoh: focusnest/kel_07/edge/edge1/telemetry


def lan_ip():
    """Cari IP laptop di jaringan WiFi/hotspot (untuk membuka dashboard dari HP)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # socket UDP (tidak benar-benar mengirim)
    try:
        s.connect(("8.8.8.8", 80))  # pilih antarmuka jaringan yang aktif
        return s.getsockname()[0]  # ambil alamat IP lokal
    except OSError:
        return "127.0.0.1"  # tidak ada jaringan
    finally:
        s.close()  # tutup socket
