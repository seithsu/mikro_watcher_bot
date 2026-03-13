# GitHub Upload Checklist

Tanggal: 2026-03-13
Project: `mikro_watcher`

## Tujuan

Checklist ini untuk memastikan repository aman sebelum dipush ke GitHub, terutama jika repo akan dibuat publik.

## Jangan Upload

File/folder berikut tidak boleh ikut ke repository publik:

- `.env`
- `data/`
- `logs/`
- file backup router seperti `*.rsc` dan `*.backup`
- file sertifikat / private key di `certs/`
- dokumen operasional privat:
  - `HANDOVER_*.md`
  - `HANDOVER_OPERATOR_*.md`
  - `DEEP_ANALISIS_*.md`
  - `AUDIT_*.md`

## Kondisi Saat Ini

1. `.gitignore` sudah mengecualikan file sensitif dan runtime.
2. `.env` live berisi secret aktif dan harus tetap lokal.
3. `.env.example` sudah disanitasi dan aman untuk dipublikasikan.
4. Bot dan monitor sedang berjalan normal.

## Pra-Cek

Jalankan:

```powershell
git status --short
```

Pastikan yang terlihat tidak mencakup:

- `.env`
- file di `logs/`
- file di `data/`
- file sertifikat/key
- dokumen handover/audit privat

## Jika Ada File Sensitif Sudah Terlanjur Ke-Track

Keluarkan dari tracking tanpa menghapus file lokal:

```powershell
git rm --cached .env
git rm --cached -r logs
git rm --cached -r data
git rm --cached HANDOVER_2026-03-13_AGENT_SWITCH.md
git rm --cached HANDOVER_OPERATOR_2026-03-13.md
git rm --cached DEEP_ANALISIS_PASCA_RESET_2026-03-13.md
```

Jika ada file audit lain yang pernah ter-track, keluarkan juga dengan pola yang sama.

## Review Isi Commit

Tambahkan file:

```powershell
git add .
```

Lalu review:

```powershell
git status
git diff --cached
```

Periksa hal berikut:

1. Tidak ada `.env`
2. Tidak ada token/password/IP internal sensitif di file publik
3. Tidak ada `logs/` atau `data/`
4. Tidak ada file backup/certificate privat
5. `README.md` dan `.env.example` sudah jadi referensi publik utama

## Commit

```powershell
git commit -m "Initial public release"
```

## Hubungkan Ke GitHub

Jika repo lokal belum punya remote:

```powershell
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

Jika remote sudah ada:

```powershell
git remote set-url origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

## Setelah Push

Cek isi repository di GitHub dan pastikan yang tampil hanya:

- source code
- `README.md`
- `.env.example`
- dokumentasi desain yang memang ingin dipublikasikan

## Catatan Operasional

Karena `.env` live berisi secret aktif:

1. jangan pernah upload `.env`
2. jangan screenshot isi `.env` ke publik
3. jika token/password pernah terlanjur tersebar, lakukan rotasi:
   - Telegram bot token
   - password user API MikroTik
