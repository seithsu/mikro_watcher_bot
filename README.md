<div align="center">
  <img src="https://img.shields.io/badge/Mikro_Watcher-blue?style=for-the-badge&logo=telegram&logoColor=white" alt="Mikro Watcher Logo">
  <br>
  <h1>Mikro Watcher Bot</h1>
  <p><strong>Sistem Observabilitas & Monitoring Cerdas untuk Router MikroTik via Telegram</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square&logo=python&logoColor=white" alt="Python Version">
    <img src="https://img.shields.io/badge/RouterOS-API-red.svg?style=flat-square&logo=mikrotik&logoColor=white" alt="RouterOS">
    <img src="https://img.shields.io/badge/Architecture-Asynchronous-green.svg?style=flat-square" alt="Async">
    <img src="https://img.shields.io/badge/PM2-Ready-orange.svg?style=flat-square" alt="PM2">
  </p>
</div>

---

**Mikro Watcher** adalah asisten Telegram cerdas yang memantau, menganalisis, dan melindungi perangkat MikroTik Anda secara *real-time*. Dibangun dengan arsitektur *asynchronous* yang kokoh, bot ini dapat menangani trafik tinggi tanpa hambatan.

## 🌟 Fitur Unggulan

| Kategori | Fitur | Deskripsi |
| :--- | :--- | :--- |
| 🛡️ **Keamanan** | **Auto-Block IP** | Memblokir otomatis IP pelaku *brute-force* yang terdeteksi via log. |
| 🛡️ **Keamanan** | **Audit Trail** | Mencatat semua perintah dari admin ke dalam basis data SQLite lokal. |
| 📈 **Trafik & Anomali** | **RX Anomaly Shield** | Deteksi *flood* ARP/Broadcast dan mematikan port/bridge secara otomatis lalu menghidupkannya kembali. |
| 📈 **Trafik & Anomali** | **Top Bandwidth** | Memberitahu admin antrean (`Simple Queue`) mana yang menghabiskan *bandwidth*. |
| 🧠 **Arsitektur** | **Decoupled Alert Queue** | Kecepatan respons Mikrotik tidak terpengaruh walau server Telegram lambat/down. |
| 🧠 **Arsitektur** | **PM2 Managed** | Auto-restart dan pengelolaan batas memori yang dikontrol ketat oleh manajer proses Node.js. |
| 🔔 **Notifikasi** | **Smart Recovery** | Sistem *anti-flapping* agar bot tidak melempar notifikasi spam ketika jaringan labil. |

---

## 📂 Struktur Repositori

```text
mikro_watcher/
├── bot.py                  # Entry point bot Telegram (UI & Commands)
├── run_monitor.py          # Entry point daemon pemantau (Background Worker)
├── ecosystem.config.js     # Konfigurasi manajemen proses PM2
├── core/                   # Modul inti (Database, Alert Queue, Logging)
├── mikrotik/               # Wrapper RouterOS API (Asynchronous Thread-safe)
├── monitor/                # Daemon tasks (Netwatch, Traffic, Hardware)
└── handlers/               # Antarmuka UI Telegram (Commands, Callbacks)
```

---

## 🚀 Instalasi & Menjalankan

### Prasyarat
- Python 3.12+ (Rekomendasi)
- Node.js & PM2 (untuk *production deployment*).
- RouterOS dengan konfigurasi khusus (API, Firewall, Queue). 
  👉 **[Wajib Baca: Panduan Setup MikroTik](docs/MIKROTIK_SETUP.md)**

### 1. Instalasi Lingkungan
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 2. Konfigurasi
Buka file `.env` dan isi token Telegram serta detail akses MikroTik Anda.
> **Tips Keamanan:** Gunakan `MIKROTIK_USE_SSL=true` untuk mencegah pencurian kata sandi API di jaringan *layer 2*.

### 3. Menjalankan (Production Mode dengan PM2)
Kami sangat menyarankan menjalankan bot menggunakan PM2 agar sistem bisa melakukan *auto-restart* jika terjadi lonjakan memori atau OS *reboot*.

```powershell
# Memulai bot dan mesin monitor secara paralel
pm2 start ecosystem.config.js

# Mengecek status dan log
pm2 status
pm2 logs
```

---

## 🔧 Konfigurasi Runtime Dinamis (Tanpa Restart)

Bosan membuka `.env` lalu *restart* aplikasi? Mikro Watcher mendukung pengubahan konfigurasi langsung via Telegram!

| Perintah Telegram | Deskripsi |
| :--- | :--- |
| `/config` | Melihat seluruh *runtime parameter* yang sedang berjalan. |
| `/config set CPU_THRESHOLD 90` | Mengubah ambang batas siaga CPU menjadi 90%. |
| `/config set TOP_BW_ALERT_ENABLED false` | Mematikan deteksi anomali top *bandwidth*. |
| `/config reset PING_COUNT` | Mengembalikan parameter ke nilai bawaan `.env`. |

---

## 📊 Manajemen Data & Backup

Bot menyimpan riwayat pemantauan secara rapi di dalam folder `data/`:
- `downtime.db`: Berisi catatan insiden, log metrik, dan *audit log* eksekusi bot.
- `state.json`: Rekaman jejak *netwatch*.
- `runtime_config.json`: Penyimpanan paramater dinamis yang diubah via `/config`.

> **Backup Otomatis:** Bot dapat menjadwalkan *backup script* MikroTik (`.rsc`) ke Telegram setiap minggu!

---
<div align="center">
  <sub>Dibangun dengan ❤️ untuk kelancaran observabilitas sistem jaringan Anda.</sub>
</div>
