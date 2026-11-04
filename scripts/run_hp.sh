#!/data/data/com.termux/files/usr/bin/bash
# Jalankan edge HP dengan wake-lock agar sensor tetap hidup saat layar mati.
termux-wake-lock  # cegah Android menidurkan CPU
trap 'termux-wake-unlock' EXIT  # lepas wake-lock saat program berhenti
python hp_edge.py "$@"  # jalankan program HP (bisa tambah --source simulator)
