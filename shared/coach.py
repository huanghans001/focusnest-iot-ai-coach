"""AI Coach: ringkasan + saran belajar dari statistik sesi. LLM bila tersedia, aturan sederhana bila tidak.

Hanya data AGREGAT numerik yang boleh keluar dari laptop (lihat sanitize_summary).
"""
import json  # ubah ringkasan menjadi teks JSON untuk LLM
import math  # cek nilai nan/inf
from shared import config  # pengaturan LLM dari .env

EVENT_TYPES = ("PHONE_DISTRACTION", "NOISE_SPIKE", "TOO_DARK")  # jenis event yang dikenal
COMPONENTS = ("noise", "light", "phone", "activity")  # komponen skor
SUMMARY_KEYS = (  # WHITELIST key level atas; selain ini dibuang
    "duration_s", "focus_s", "focus_pct", "event_counts",
    "avg_score", "avg_component_scores", "min_score", "events",
)
MAX_EVENTS = 20  # batas daftar kejadian
MAX_TEXT = 1200  # batas panjang teks saran
MIN_SESSION_S = 180  # sesi lebih pendek dari ini terlalu singkat untuk disimpulkan
ISSUE_MIN = 3  # jumlah event sejenis yang dianggap "sering"

SYSTEM_PROMPT = (
    "Kamu adalah pelatih belajar yang suportif untuk mahasiswa. "
    "Jawab dalam Bahasa Indonesia, maksimal 4 kalimat, lalu tepat 2 saran konkret berbentuk poin "
    "(awali tiap poin dengan \"- \"). Jangan menghakimi dan jangan membuat klaim medis. "
    "Gunakan HANYA angka pada JSON yang diberikan dan jangan mengarang data yang tidak ada di input. "
    "Arti field: duration_s dan focus_s dalam detik; focus_pct dalam persen; skor 0-100; "
    "event_counts = jumlah gangguan per jenis (PHONE_DISTRACTION = HP terangkat, NOISE_SPIKE = suara mendadak keras, "
    "TOO_DARK = ruangan terlalu gelap); events = daftar kejadian dengan menit ke-N sejak sesi mulai (menit pertama = 1); "
    "nilai null berarti tidak ada data, jangan ditafsirkan."
)


# ---------- Sanitasi: hanya whitelist yang lolos ----------
def _num(v):
    """Angka valid (bukan bool/nan/inf) atau None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None  # tolak teks, bool, dan tipe lain
    return v if math.isfinite(v) else None  # tolak nan/inf


def sanitize_summary(raw):
    """Loloskan HANYA key whitelist dengan nilai numerik; sisanya (nama, NIM, PROJECT_ID, teks bebas, dll) dibuang."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in ("duration_s", "focus_s", "focus_pct", "avg_score", "min_score"):
        if key in raw and (raw[key] is None or _num(raw[key]) is not None):
            out[key] = raw[key]  # angka atau None
    counts = raw.get("event_counts")
    if isinstance(counts, dict):
        out["event_counts"] = {k: int(_num(counts[k])) for k in EVENT_TYPES if _num(counts.get(k)) is not None}  # hanya jenis dikenal
    comps = raw.get("avg_component_scores")
    if isinstance(comps, dict):
        out["avg_component_scores"] = {k: comps[k] for k in COMPONENTS if k in comps and (comps[k] is None or _num(comps[k]) is not None)}
    events = raw.get("events")
    if isinstance(events, list):
        clean = []
        for e in events:
            if isinstance(e, dict) and e.get("type") in EVENT_TYPES and _num(e.get("minute")) is not None:
                clean.append({"minute": int(e["minute"]), "type": e["type"]})  # buang key lain
        out["events"] = clean[:MAX_EVENTS]
    return out


# ---------- Mode LLM ----------
def _call_llm(summary):
    """Panggil LLM lewat SDK resmi; return teks. Error dibiarkan naik (ditangkap generate_advice)."""
    if config.LLM_PROVIDER != "anthropic":
        raise ValueError("provider LLM tidak didukung")
    import anthropic  # import saat dibutuhkan agar fallback tetap jalan tanpa library
    client = anthropic.Anthropic(api_key=config.LLM_API_KEY, timeout=config.LLM_TIMEOUT_SEC, max_retries=config.LLM_MAX_RETRIES)
    reply = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(summary, ensure_ascii=False)}],  # hanya ringkasan hasil sanitasi
    )
    return "".join(b.text for b in reply.content if getattr(b, "type", "") == "text")


# ---------- Mode fallback (tanpa internet, deterministik) ----------
def _dur(seconds):
    """Format detik menjadi teks, contoh '25 menit 10 detik'."""
    m, s = divmod(int(seconds), 60)
    return f"{m} menit {s} detik" if m else f"{s} detik"


TIPS = {  # (kalimat masalah, saran) per jenis event
    "PHONE_DISTRACTION": ("HP terangkat {n} kali", "Letakkan HP telungkup atau simpan di tas selama sesi, dan matikan notifikasi yang tidak perlu."),
    "NOISE_SPIKE": ("suara mendadak keras muncul {n} kali", "Cari tempat yang lebih tenang atau pakai headphone saat butuh konsentrasi penuh."),
    "TOO_DARK": ("ruangan terlalu gelap {n} kali", "Nyalakan lampu atau pindah ke tempat yang lebih terang sebelum mulai sesi."),
}
DEFAULT_TIPS = (
    "Tetapkan satu target kecil di awal sesi, misalnya menyelesaikan satu bagian tugas.",
    "Beri jeda singkat sekitar 5 menit setiap 25 menit belajar agar fokus tetap terjaga.",
)


def fallback_advice(summary):
    """Saran berbasis aturan dari angka summary. Hasil sama untuk input sama."""
    s = sanitize_summary(summary)
    duration = s.get("duration_s") or 0
    if duration < MIN_SESSION_S:
        return (f"Sesi ini baru berjalan {_dur(duration)}, terlalu singkat untuk disimpulkan.\n"
                f"- {DEFAULT_TIPS[0]}\n- Coba belajar minimal 15-25 menit agar ringkasan lebih bermakna.")
    pct = s.get("focus_pct") or 0
    counts = s.get("event_counts") or {}
    issues = sorted((t for t in EVENT_TYPES if counts.get(t, 0) >= ISSUE_MIN), key=lambda t: (-counts[t], EVENT_TYPES.index(t)))  # terbanyak dulu, urutan tetap
    sentences = [f"Sesi {_dur(duration)} dengan {pct:.0f}% waktu berada di zona fokus."]
    if pct >= 80:
        sentences.append("Konsistensimu sangat baik di sesi ini.")
    elif pct >= 50:
        sentences.append("Fokusmu cukup baik dan masih bisa ditingkatkan.")
    else:
        sentences.append("Fokus belum stabil kali ini, dan itu bisa diperbaiki dari kebiasaan kecil.")
    if issues:
        sentences.append("Gangguan yang paling sering: " + TIPS[issues[0]][0].format(n=counts[issues[0]]) + ".")
    elif sum(counts.values()) > 0:
        sentences.append(f"Gangguan hanya muncul {sum(counts.values())} kali, jadi sesinya relatif tenang.")
    first = (s.get("events") or [None])[0]
    if first and len(sentences) < 4:
        sentences.append(f"Gangguan pertama muncul di menit ke-{first['minute']}.")
    tips = [TIPS[t][1] for t in issues[:2]]
    if pct >= 80 and not issues:
        tips = ["Pertahankan pola belajar ini: lingkungan dan posisi HP yang sama.", DEFAULT_TIPS[1]]
    tips += [t for t in DEFAULT_TIPS if t not in tips]  # lengkapi sampai 2 saran
    return " ".join(sentences) + "\n" + "\n".join(f"- {t}" for t in tips[:2])


# ---------- Pintu masuk ----------
def generate_advice(summary):
    """Return {"source": "llm"|"fallback", "text": str}. Tidak pernah melempar exception."""
    try:
        clean = sanitize_summary(summary)  # lapis kedua: pastikan hanya whitelist yang diproses
    except Exception:
        clean = {}
    if config.LLM_ENABLED and config.LLM_API_KEY and config.LLM_MODEL:
        try:
            text = (_call_llm(clean) or "").strip()[:MAX_TEXT]
            if text:
                return {"source": "llm", "text": text}
            print("[COACH] LLM mengembalikan teks kosong, pakai fallback")
        except Exception as err:
            print(f"[COACH] LLM gagal ({type(err).__name__}), pakai fallback")  # hanya nama error (tanpa detail)
    try:
        return {"source": "fallback", "text": fallback_advice(clean)}
    except Exception:
        return {"source": "fallback", "text": "Sesi selesai. Ringkasan belum bisa disusun saat ini."}
