"""Pembungkus paho-mqtt: koneksi TLS, auto-reconnect, dan status online (LWT)."""
import json  # ubah dict menjadi JSON
import random  # membuat client_id unik
import paho.mqtt.client as mqtt  # library MQTT
from shared import config  # pengaturan bersama


def make_client(name, subscribe=(), on_message=None, is_edge=False):
    """Buat client MQTT, sambungkan ke broker, lalu jalankan loop di thread lain."""
    client_id = f"focusnest-{config.PROJECT_ID}-{name}-{random.randint(1000, 9999)}"  # id unik
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)  # paho-mqtt v2
    if config.MQTT_TLS:
        client.tls_set()  # TLS memakai sertifikat CA bawaan sistem
    if config.MQTT_USER:
        client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)  # login jika broker butuh akun
    online_topic = config.topic(f"edge/{name}/online")  # topic penanda perangkat hidup
    if is_edge:
        client.will_set(online_topic, "0", qos=1, retain=True)  # broker kirim "0" jika koneksi putus mendadak

    def on_connect(c, userdata, flags, reason_code, properties):
        """Dipanggil tiap kali (re)connect: subscribe ulang dan tandai online."""
        if reason_code.is_failure:  # koneksi ditolak
            print(f"[MQTT] gagal terhubung: {reason_code}")
            return
        print(f"[MQTT] terhubung ke {config.MQTT_HOST}:{config.MQTT_PORT} sebagai {client_id}")
        for t in subscribe:
            c.subscribe(t, qos=1)  # berlangganan topic yang diminta
        if is_edge:
            c.publish(online_topic, "1", qos=1, retain=True)  # tandai online

    client.on_connect = on_connect  # pasang callback koneksi
    if on_message:
        client.on_message = on_message  # pasang callback pesan masuk
    client.reconnect_delay_set(1, 30)  # coba sambung ulang tiap 1-30 detik
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)  # sambung ke broker
    client.loop_start()  # jalankan network loop di thread terpisah
    return client


def publish_json(client, suffix, payload, qos=0, retain=False):
    """Kirim dict sebagai JSON ke topic focusnest/<PROJECT_ID>/<suffix>."""
    client.publish(config.topic(suffix), json.dumps(payload), qos=qos, retain=retain)  # publish


def close_edge(client, name):
    """Tandai perangkat offline lalu putus koneksi dengan rapi."""
    info = client.publish(config.topic(f"edge/{name}/online"), "0", qos=1, retain=True)  # tandai offline
    info.wait_for_publish(timeout=3)  # tunggu pesan terkirim
    client.loop_stop()  # hentikan loop
    client.disconnect()  # putus koneksi
