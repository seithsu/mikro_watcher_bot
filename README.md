# Mikro Watcher

Bot Telegram dan monitor background untuk observabilitas MikroTik.

## Komponen

- `bot.py`: command bot Telegram, menu, report, backup, chart.
- `run_monitor.py`: entry point monitor background.
- `monitor/`: task monitoring periodik, alert, netwatch, maintenance.
- `mikrotik/`: wrapper RouterOS API via `librouteros`.
- `core/`: config, database, logging, backup, classification.
- `handlers/`: command dan callback Telegram.
- `services/`: chart service dan runtime config manager.

## Prasyarat

- Python 3.12+ atau versi yang kompatibel dengan dependency aktif.
- RouterOS API aktif.
- Telegram bot token.
- Windows atau environment yang bisa menjalankan PM2 + Python.

## Instalasi

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Konfigurasi

File utama: `.env`

Key minimal:

- `TOKEN`
- `CHAT_ID` atau `ADMIN_IDS`
- `MIKROTIK_IP`
- `MIKROTIK_USER`
- `MIKROTIK_PASS`

Key penting tambahan:

- `BOT_IP`: IP host yang menjalankan bot, untuk mereduksi noise login API.
- `AUTO_BLOCK_TRUSTED_IPS`: daftar IP yang tidak boleh kena auto-block brute-force (pisah koma), mis. IP bot + IP router.
- `API_ACCOUNT_SKIP_USERS`: daftar username RouterOS yang di-skip untuk dedup log account.
- `CRITICAL_DEVICES`: daftar perangkat penting statis format `Nama:IP` (pisah koma), selalu ikut monitor netwatch/status.
- `CRITICAL_DEVICE_NAMES`: daftar nama perangkat penting untuk auto-discovery dari DHCP lease hostname/comment.
- `CRITICAL_DEVICE_WINDOWS`: jadwal monitor per perangkat penting, format `Nama=HH:MM-HH:MM` (pisah koma).
- `MONITOR_VPN_ENABLED`: set `false` jika tidak memakai VPN agar tidak ada alert tunnel.
- `MONITOR_VPN_IGNORE_NAMES`: daftar nama tunnel VPN yang diabaikan (pisah koma).
- `MONITOR_IGNORE_IFACE`: daftar interface yang diabaikan dari alert down (mis. port idle/cadangan).
- `RECOVERY_MIN_UP_SECONDS`: anti-flap, host harus stabil `UP` selama N detik sebelum kirim `RECOVERY`.
- `NETWATCH_UP_MIN_SUCCESS_RATIO`: rasio minimum reply ping per siklus agar host dianggap `UP` (contoh `0.5` dengan `PING_COUNT=4` berarti minimal 2 reply).
- `ALERT_REQUIRE_START`: jika `true`, alert monitor baru aktif setelah admin kirim `/start`.
- `TOP_BW_ALERT_*`: parameter alert penyedot bandwidth berbasis `Simple Queue` (top N + cooldown + recovery).
- `DNS_CHECK_DOMAIN`: bisa diisi beberapa domain (pisah koma), contoh `google.com,cloudflare.com`.

Catatan keamanan:

- Disarankan mengaktifkan API TLS di RouterOS dan memakai `MIKROTIK_USE_SSL=true`.
- Jika sertifikat RouterOS belum di-trust oleh host bot, gunakan `MIKROTIK_TLS_VERIFY=false` sebagai mode transisi.
- Jika sudah punya CA/sertifikat yang benar, isi `MIKROTIK_TLS_CA_FILE` lalu aktifkan `MIKROTIK_TLS_VERIFY=true`.
- Jangan kirim file `.env` ke channel publik atau commit ke repository.

### Mode Non-SSL (Sementara)

Jika sementara belum memakai `api-ssl`, gunakan konfigurasi berikut:

```env
MIKROTIK_PORT=8728
MIKROTIK_USE_SSL=false
MIKROTIK_TLS_VERIFY=false
```

### Mode Full Verify

Target final yang disarankan:

```env
MIKROTIK_PORT=8729
MIKROTIK_USE_SSL=true
MIKROTIK_TLS_VERIFY=true
MIKROTIK_TLS_CA_FILE=certs\\routeros-ca.pem
```

Langkah praktis:

1. Export CA atau sertifikat penandatangan RouterOS ke format PEM.
2. Simpan file tersebut di `certs/routeros-ca.pem`.
3. Ubah `MIKROTIK_TLS_VERIFY=true`.
4. Restart bot dan monitor.

Jika setelah restart koneksi gagal, kembali dulu ke `MIKROTIK_TLS_VERIFY=false`, lalu periksa:

- file PEM benar
- sertifikat yang dipakai untuk `api-ssl` memang ditandatangani oleh CA tersebut
- jam sistem host dan router sinkron

## Menjalankan

Langsung:

```powershell
python bot.py
python run_monitor.py
```

Dengan PM2:

```powershell
pm2 start ecosystem.config.js
pm2 status
pm2 logs
```

## Testing

```powershell
pytest -q
```

## Runtime `/config`

Lihat semua konfigurasi runtime:

```text
/config
```

Set nilai angka:

```text
/config set CPU_THRESHOLD 90
/config set TOP_BW_ALERT_WARN_MBPS 50
```

Set nilai boolean:

```text
/config set TOP_BW_ALERT_ENABLED false
/config set MONITOR_VPN_ENABLED false
/config set ALERT_REQUIRE_START true
```

Reset ke default `.env`:

```text
/config reset CPU_THRESHOLD
```

`pytest.ini` sudah membatasi discovery ke folder `tests/` agar artefak cache Windows tidak ikut dikoleksi.

## Menu Telegram

- Menu utama dan submenu penting sekarang menampilkan footer timestamp lokal bot dengan format `YYYY-MM-DD HH:MM`.
- Tombol `🧹 Reset Data` tersedia di menu awal dan menu `System`.
- `/help` sudah disinkronkan dengan fitur runtime saat ini.
- Loading message singkat dan pesan error cepat tidak semuanya diberi timestamp agar UI tetap ringkas.

## Data Runtime

- `data/downtime.db`: incident, metrics, audit log
- `data/state.json`: snapshot status host dari netwatch
- `data/monitor_state.json`: state alert persisten
- `data/runtime_config.json`: override config dari command `/config`
- `logs/bot.log`, `logs/monitor.log`: log proses

## Pemantauan Perangkat Penting

Jika ada perangkat yang harus selalu dipantau (misalnya komputer pendaftaran), ada 2 opsi:

1. Static mapping (paling pasti)

```env
CRITICAL_DEVICES=DEVICE KRITIS A:192.168.88.50,DEVICE KRITIS B:192.168.88.51
```

2. Auto-discovery dari hostname DHCP lease

```env
CRITICAL_DEVICE_NAMES=DEVICE KRITIS A,DEVICE KRITIS B
```

3. Jadwal monitor per perangkat (opsional)

```env
CRITICAL_DEVICE_WINDOWS=DEVICE KRITIS B=07:00-17:00
```

Keduanya bisa dipakai bersamaan.

## Backup

## Reset Runtime Data

Kalau ingin mengosongkan histori dan state runtime agar baseline fresh lagi, jalankan:

```powershell
python tools\reset_runtime_data.py
```

Opsi tambahan:

```powershell
python tools\reset_runtime_data.py --restart-pm2
python tools\reset_runtime_data.py --clear-runtime-config --restart-pm2
```

Perilaku default script:

- hapus isi tabel `incidents`, `metrics`, `audit_log`
- reset file runtime/IPC seperti `pending_acks.json` dan `ack_events.json`
- hapus `state.json`, `monitor_state.json`, `alert_gate.json`
- kosongkan `data/aktivitas.log` dan log di folder `logs`
- pertahankan `.env` dan `data/runtime_config.json`

Kalau `--clear-runtime-config` dipakai, file `data/runtime_config.json` juga ikut dihapus.

Di menu awal bot juga tersedia tombol `🧹 Reset Data` dengan konfirmasi dua langkah.

Command backup saat ini adalah backup aplikasi, bukan full disaster recovery.

Yang tidak otomatis ikut:

- `.env`
- seluruh state IPC
- seluruh log runtime

Jika butuh restore penuh, simpan secret dan artefak operasional secara terpisah.


## GitHub Hygiene

Sebelum upload ke GitHub, pastikan yang dipublikasikan hanya source code dan dokumentasi yang memang layak dibuka.

Secara default `.gitignore` sudah mengecualikan:

- `.env`
- `data/`
- `logs/`
- file backup router seperti `*.rsc` dan `*.backup`
- file sertifikat / private key di `certs/`
- dokumen operasional privat seperti `HANDOVER_*.md`, `DEEP_ANALISIS_*.md`, dan `AUDIT_*.md`

Praktik aman:

1. Jangan `git add -f` file yang sudah di-ignore kecuali memang sengaja dipublikasikan.
2. Jangan commit log runtime, state, atau dump database.
3. Jangan commit sertifikat/private key RouterOS.
4. Gunakan `.env.example` sebagai template publik, bukan `.env` aktif.

