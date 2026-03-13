# Design Plan: Multi-Router Modular Architecture

Tanggal: 2026-03-09
Status: planning only
Scope: refactor bertahap dari single-router ke multi-router, tetap backward-compatible

## Tujuan

Mengubah bot dari desain yang saat ini terikat ke satu MikroTik menjadi arsitektur modular yang:

- bisa menangani banyak router
- tetap kompatibel dengan setup lama
- mendukung failover/hot swap lebih rapi
- memisahkan state, metrics, alert, dan koneksi per router

## Kondisi Saat Ini

Arsitektur sekarang masih single-router centric:

- `core/config.py` menyimpan satu set kredensial/router aktif
- `mikrotik/connection.py` memakai connection singleton global
- hampir semua fungsi `mikrotik/*.py` mengasumsikan satu target
- monitor, state, dan alert key belum memasukkan `router_id`
- handler Telegram juga belum punya konsep pemilihan router

Konsekuensinya:

- sulit menambah router baru tanpa mengubah core logic
- failover antar perangkat kurang eksplisit
- metrics dan incident belum bisa dipisah per router

## Sasaran Akhir

### Fungsional

- bot bisa menyimpan banyak MikroTik aktif/nonaktif
- command bisa menargetkan router tertentu
- monitor berjalan per router
- alert dan incident menyebut router asal
- satu router default tetap tersedia untuk kompatibilitas

### Non-Fungsional

- migrasi bertahap, bukan rewrite total
- setup lama tetap bisa jalan
- perubahan di setiap fase harus bisa diuji
- schema database dimigrasikan tanpa kehilangan data lama

## Prinsip Desain

1. Backward-compatible first
2. Router harus menjadi entitas eksplisit, bukan implicit global
3. Semua operasi router wajib bisa menerima `router_id`
4. State dan alert harus memiliki namespace per router
5. Registry router harus menjadi single source of truth

## Model Arsitektur Baru

### 1. Router Registry

Tambah registry router sebagai sumber konfigurasi semua target.

Lokasi yang disarankan:

- `data/routers.json`

Fallback:

- jika file belum ada, generate router `default` dari `.env`

Contoh schema:

```json
[
  {
    "id": "default",
    "label": "MikroTik Utama",
    "host": "192.168.3.1",
    "port": 8729,
    "username": "admin",
    "password": "secret",
    "use_ssl": true,
    "tls_verify": false,
    "tls_ca_file": "",
    "enabled": true,
    "tags": ["primary"]
  }
]
```

### 2. Connection Manager Per Router

Refactor connection layer menjadi registry pool per router:

- `pool["default"]`
- `pool["router-b"]`

Setiap router punya:

- active connection counter sendiri
- reconnect backoff sendiri
- health check sendiri
- reset sendiri

### 3. Service Layer Router-Aware

Semua fungsi di `mikrotik/*.py` diubah agar menerima:

```python
router_id="default"
```

Contoh:

```python
get_status(router_id="default")
get_interfaces(router_id="default")
reboot_router(router_id="default")
```

### 4. State dan Alert Namespace

Semua state runtime dan alert key harus memasukkan `router_id`.

Contoh:

- `down_default_192.168.3.10`
- `traffic_mt-backup_ether1`

State file ideal:

```json
{
  "default": {
    "kategori": "NORMAL",
    "hosts": {}
  },
  "backup": {
    "kategori": "NORMAL",
    "hosts": {}
  }
}
```

### 5. Database Router-Aware

Tambahkan `router_id` ke tabel penting:

- `incidents`
- `metrics`
- `audit_log` jika diperlukan untuk trace command lintas router

Tujuannya:

- report per router
- chart per router
- audit lebih jelas

### 6. Telegram UI Multi-Router

Dua mode yang bisa dipakai:

- command argumen: `/status default`
- inline keyboard: pilih router dulu, lalu pilih aksi

Saran implementasi:

- fallback otomatis ke `default` jika hanya ada satu router aktif
- untuk command sensitif seperti reboot dan backup, target router harus eksplisit

## Fase Implementasi

### Fase 0: Desain dan Inventaris

Tujuan:

- petakan semua fungsi yang implicit ke satu router
- definisikan kontrak `router_id`

Output:

- dokumen desain ini
- daftar file terdampak
- daftar test yang perlu ditambah

### Fase 1: Router Registry

Tujuan:

- tambahkan `services/router_registry.py`
- support router `default` dari `.env`
- support `data/routers.json`

Output:

- loader registry
- validator schema
- fallback dari `.env`

Definisi selesai:

- project tetap jalan tanpa `routers.json`
- router `default` tersedia dari setup lama

### Fase 2: Connection Layer Per Router

Tujuan:

- ubah pool global menjadi pool per router
- setiap operasi koneksi harus tahu `router_id`

Output:

- `RouterConnectionManager`
- registry of pools
- compatibility wrapper untuk router default

Definisi selesai:

- satu router lama tetap jalan
- dua router bisa diinisialisasi bersamaan

### Fase 3: Refactor MikroTik API Layer

Tujuan:

- semua wrapper di `mikrotik/*.py` menerima `router_id`

Output:

- signature baru di seluruh service MikroTik
- adapter untuk default behavior

Definisi selesai:

- semua operasi dasar support `router_id`
- test existing tetap hijau

### Fase 4: Database dan State

Tujuan:

- tambahkan `router_id` ke storage
- buat migrasi non-destruktif

Output:

- migrasi schema
- state file keyed by router
- alert key terisolasi per router

Definisi selesai:

- incident, metrics, dan report bisa difilter per router

### Fase 5: Monitor Multi-Router

Tujuan:

- monitor loop per router aktif
- netwatch, traffic, DHCP, log, alert maintenance sadar router

Output:

- orchestrator yang spawn kerja per router
- state per router
- alert per router

Definisi selesai:

- 2 router aktif bisa dimonitor tanpa tabrakan state

### Fase 6: Handler dan UI Telegram

Tujuan:

- command support target router
- keyboard untuk pemilihan router

Output:

- router selector
- fallback ke `default`
- target eksplisit untuk operasi sensitif

Definisi selesai:

- admin bisa memilih router dari chat

### Fase 7: Admin Management Router

Tujuan:

- tambah command untuk kelola registry

Contoh:

- `/routers`
- `/router_select`
- `/router_enable`
- `/router_disable`

Catatan:

- fase ini opsional dan bisa ditunda sampai core multi-router stabil

### Fase 8: Hardening dan Testing

Tujuan:

- tambah test khusus multi-router
- verifikasi tidak ada regression single-router

Fokus test:

- registry fallback
- connection pool per router
- state per router
- alert key per router
- command target router

Definisi selesai:

- single-router mode tetap hijau
- multi-router mode punya coverage dasar

## File yang Paling Terdampak

### Sangat Terdampak

- `core/config.py`
- `mikrotik/connection.py`
- `monitor/tasks.py`
- `monitor/netwatch.py`
- `monitor/checks.py`
- `monitor/alerts.py`

### Terdampak Menengah

- seluruh `mikrotik/*.py`
- `handlers/general.py`
- `handlers/network.py`
- `handlers/tools.py`
- `handlers/report.py`
- `handlers/charts.py`

### Terdampak Ringan

- `services/config_manager.py`
- `services/chart_service.py`
- `tests/*`

## Risiko Utama

### 1. Coupling ke Global Config

Banyak modul saat ini membaca langsung nilai global dari `core.config`.

Dampak:

- refactor rawan regression tersembunyi

Mitigasi:

- mulai dari registry + adapter
- jangan ubah semua callsite sekaligus

### 2. Alert Collision

Jika `router_id` tidak masuk ke key alert/state, dua router bisa saling overwrite.

Mitigasi:

- namespace semua key sejak fase monitor

### 3. Migrasi Database

Penambahan `router_id` harus tetap membaca data lama.

Mitigasi:

- gunakan default `router_id='default'` untuk row lama

### 4. Handler Complexity

UI Telegram bisa cepat menjadi rumit jika pemilihan router dimasukkan ke semua command sekaligus.

Mitigasi:

- mulai dari fallback `default`
- pilih router dulu hanya pada command penting

## Strategi Migrasi yang Disarankan

Urutan aman:

1. Fase 1
2. Fase 2
3. Fase 3
4. Fase 4
5. Fase 5
6. Fase 6
7. Fase 8
8. Fase 7 belakangan

Alasan:

- registry dan connection layer harus beres dulu
- UI jangan diubah sebelum core service benar-benar router-aware

## MVP yang Disarankan

MVP multi-router:

- registry router sudah ada
- semua fungsi MikroTik menerima `router_id`
- monitor bisa jalan untuk lebih dari satu router
- command utama support router default + argumen target
- tanpa admin UI router dulu

Ini cukup untuk mulai pakai lebih dari satu router tanpa rewrite total.

## Definisi Selesai Fase 1 MVP

Fase awal dianggap berhasil jika:

- setup lama tetap jalan tanpa perubahan besar
- ada `RouterRegistry`
- router `default` tetap tersedia
- test lama tetap hijau
- minimal satu operasi MikroTik bisa dipanggil berdasarkan `router_id`

## Next Step yang Disarankan

Kalau lanjut implementasi, tahap pertama yang paling rasional adalah:

1. buat `services/router_registry.py`
2. buat schema `data/routers.json`
3. refactor `mikrotik/connection.py` menjadi per-router registry
4. pertahankan semua call lama agar tetap default ke `default`
