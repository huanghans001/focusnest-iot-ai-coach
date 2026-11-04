#!/data/data/com.termux/files/usr/bin/bash
# Setup satu kali di Termux (HP). Jalankan dari folder repo:  bash scripts/setup_termux.sh
set -e  # berhenti jika ada perintah yang gagal

echo "[1/4] Update paket Termux..."
pkg update -y  # perbarui daftar paket

echo "[2/4] Pasang python, git, termux-api..."
pkg install -y python git termux-api  # paket yang dibutuhkan

echo "[3/4] Pasang library Python..."
pip install -r requirements-termux.txt  # paho-mqtt dan python-dotenv

echo "[4/4] Siapkan file .env..."
[ -f .env ] || cp .env.example .env  # salin template bila belum ada
echo "Isi PROJECT_ID dulu:  nano .env   (Ctrl+O simpan, Ctrl+X keluar)"

echo ""
echo "Cek sensor HP (harus ada Accelerometer dan Light):"
termux-sensor -l | grep -iE "accelerometer|light" || echo "!! Sensor tidak terbaca. Pastikan aplikasi Termux:API terpasang dari F-Droid."
