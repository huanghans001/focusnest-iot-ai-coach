"""Fungsi pengolahan data sensor. Murni Python (tanpa numpy) supaya jalan di Termux."""
import math  # fungsi matematika

GRAVITY = 9.81  # percepatan gravitasi (m/s2)


def clamp(value, low=0.0, high=100.0):
    """Batasi nilai ke rentang [low, high]."""
    return max(low, min(high, value))  # potong nilai di luar rentang


def lerp_score(x, x0, s0, x1, s1):
    """Peta linear: x=x0 -> skor s0, x=x1 -> skor s1 (dibatasi 0-100)."""
    if x1 == x0:
        return s1  # hindari pembagian nol
    return clamp(s0 + (x - x0) * (s1 - s0) / (x1 - x0))  # interpolasi linear


# ---------- PENGOLAHAN 1 (HP): RMS getaran dari accelerometer ----------
def rms_motion(samples):
    """samples = [(x, y, z), ...] dalam m/s2. Hasil = RMS selisih magnitudo terhadap gravitasi."""
    errors = [math.sqrt(x * x + y * y + z * z) - GRAVITY for x, y, z in samples]  # magnitudo - 9.81
    return math.sqrt(sum(e * e for e in errors) / len(errors))  # akar rata-rata kuadrat


# ---------- PENGOLAHAN 2 (HP): klasifikasi orientasi HP ----------
def orientation(mean_z):
    """Dari rata-rata sumbu z: layar menghadap bawah / atas / miring."""
    if mean_z <= -6.0:
        return "face_down"  # HP telungkup (mode fokus)
    if mean_z >= 6.0:
        return "face_up"  # HP telentang
    return "tilted"  # HP miring atau dipegang


# ---------- PENGOLAHAN 3 (HP): penghalusan cahaya (EWMA) ----------
def ewma(previous, value, alpha=0.3):
    """Exponentially weighted moving average; previous=None berarti nilai pertama."""
    return value if previous is None else alpha * value + (1 - alpha) * previous  # campur nilai baru dan lama


# ---------- PENGOLAHAN 4 (laptop): level suara dari mikrofon ----------
def noise_dbfs(rms):
    """Ubah RMS audio (0..1) menjadi dBFS (0 = paling keras, negatif = lebih pelan)."""
    return 20.0 * math.log10(max(rms, 1e-6))  # batas bawah agar log tidak error


# ---------- Skor komponen (0-100, makin tinggi makin mendukung fokus) ----------
def noise_score(delta_db):
    """delta_db = kenaikan suara dari baseline ruangan. <=3 dB aman, >=20 dB sangat berisik."""
    return lerp_score(delta_db, 3.0, 100.0, 20.0, 0.0)  # makin keras makin rendah


def light_score(lux):
    """Cahaya ideal belajar 300-1000 lux; terlalu gelap atau silau menurunkan skor."""
    if lux < 300:
        return lerp_score(lux, 50.0, 10.0, 300.0, 100.0)  # gelap -> naik sampai 300 lux
    if lux <= 1000:
        return 100.0  # rentang ideal
    return lerp_score(lux, 1000.0, 100.0, 3000.0, 50.0)  # silau -> turun pelan


def phone_score(motion_rms, orient, threshold):
    """HP bergerak = 0; HP diam telungkup = 100; HP diam tapi layar terlihat = 80."""
    if motion_rms >= threshold:
        return 0.0  # HP sedang diangkat/dipegang
    return 100.0 if orient == "face_down" else 80.0  # diam: telungkup lebih baik


def activity_score(keys_per_min, mouse_moves):
    """Aktivitas mengetik/mouse di laptop (bobot kecil karena membaca juga bentuk fokus)."""
    typing = min(100.0, keys_per_min / 60.0 * 100.0)  # 60 ketukan/menit = 100
    browsing = 40.0 if mouse_moves >= 5 else 0.0  # hanya menggerakkan mouse = 40
    return max(typing, browsing)  # ambil yang terbesar


WEIGHTS = {"noise": 0.30, "light": 0.20, "phone": 0.35, "activity": 0.15}  # bobot sensor fusion


def focus_score(scores):
    """Rata-rata berbobot; skor None (data tidak valid) dilewati dan bobot dinormalkan ulang."""
    used = {k: v for k, v in scores.items() if v is not None}  # buang yang tidak ada
    if not used:
        return 0.0  # tidak ada data sama sekali
    total_weight = sum(WEIGHTS[k] for k in used)  # jumlah bobot yang dipakai
    return sum(WEIGHTS[k] * v for k, v in used.items()) / total_weight  # rata-rata berbobot


# ---------- ALGORITMA: deteksi anomali z-score berbasis EWMA ----------
class EwmaStats:
    """Menghitung z-score terhadap rata-rata dan simpangan baku bergerak."""

    def __init__(self, alpha=0.1):
        self.alpha = alpha  # kecepatan adaptasi
        self.mean = None  # rata-rata bergerak
        self.var = 1.0  # varians bergerak

    def zscore(self, x):
        """Kembalikan z-score x; lonjakan (z>3) tidak ikut memperbarui statistik."""
        if self.mean is None:
            self.mean = x  # data pertama jadi acuan
            return 0.0
        std = max(math.sqrt(self.var), 1.0)  # batas bawah 1 dB agar tidak terlalu sensitif
        z = (x - self.mean) / std  # jarak dari rata-rata dalam satuan std
        if z > 3.0:
            return z  # lonjakan: jangan dipelajari sebagai kondisi normal
        diff = x - self.mean  # selisih terhadap rata-rata lama
        self.mean += self.alpha * diff  # geser rata-rata
        self.var = (1 - self.alpha) * (self.var + self.alpha * diff * diff)  # perbarui varians
        return z
