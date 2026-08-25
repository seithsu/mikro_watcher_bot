# Panduan Konfigurasi MikroTik (Setup Guide)

Agar **Mikro Watcher Bot** dapat memantau dan mengeksekusi perintah di router MikroTik Anda secara optimal, Anda perlu melakukan beberapa konfigurasi di sisi RouterOS. 

Panduan ini mencakup pembuatan akun pengguna, aktivasi API, hingga penyiapan target pemantauan.

---

## 1. Pembuatan Akun Khusus Bot (Rekomendasi Keamanan)

Sangat tidak disarankan menggunakan akun `admin` (Full Access) untuk bot. Buatlah grup khusus dengan izin terbatas.

Buka **Terminal** MikroTik (via Winbox/WebFig) lalu jalankan perintah berikut:

```routeros
# 1. Membuat grup khusus bernama 'api-bot'
/user group add name=api-bot policy=api,read,write,test,policy,reboot

# 2. Membuat pengguna baru bernama 'bot-monitor' yang dimasukkan ke grup 'api-bot'
# Ganti "KataSandiSuperKuat" dengan password pilihan Anda
/user add name=bot-monitor group=api-bot password="KataSandiSuperKuat"
```
*Catatan:*
- Izin `write` dan `policy` dibutuhkan bot agar dapat menonaktifkan (`disable`) antarmuka yang terkena *flood/anomaly* serta memblokir IP pelaku *brute-force*.
- Izin `reboot` dibutuhkan agar bot bisa mengeksekusi fitur restart dari jarak jauh (`/reboot`).

---

## 2. Mengaktifkan Layanan API (API & API-SSL)

Bot berkomunikasi dengan RouterOS melalui protokol API (Port 8728) atau API-SSL (Port 8729).

```routeros
# Aktifkan API biasa (kurang aman untuk jaringan publik)
/ip service enable api
/ip service set api port=8728

# Aktifkan API-SSL (Sangat Direkomendasikan)
/ip service enable api-ssl
/ip service set api-ssl port=8729
```

> **Wajib Tahu:** Jika Anda mengaktifkan `api-ssl`, pastikan router Anda memiliki Sertifikat (Certificate). Anda bisa men- *generate* sertifikat secara otomatis di mikrotik versi v6.48+ atau v7 menggunakan perintah:
> ```routeros
> /certificate add name=api-cert common-name=api-cert days-valid=3650 key-usage=tls-server
> /certificate sign api-cert
> /ip service set api-ssl certificate=api-cert
> ```

---

## 3. Konfigurasi Sistem Pencatatan (Logging)

Agar bot dapat mendeteksi percobaan peretasan (*Brute-force SSH/Winbox*), Anda harus memastikan log untuk aktivitas kritis tersimpan di memori router.

```routeros
# Memastikan login failure tercatat
/system logging add action=memory topics=system,error,critical
/system logging add action=memory topics=account
```
*Catatan: Pastikan `System -> Logging -> Actions -> memory` memiliki cukup memori alokasi (misal 1000 baris).*

---

## 4. Persiapan Pemantauan Top Bandwidth

Fitur **Top Bandwidth Alert** bot bergantung pada data di **Simple Queues**. Jika Anda tidak menggunakan *Simple Queue* sama sekali, fitur ini tidak akan bekerja. 

Minimal, buat satu *queue* utama yang membatasi/memantau seluruh *bandwidth* lokal:
```routeros
/queue simple add name="TOTAL-BANDWIDTH" target=192.168.88.0/24 max-limit=100M/100M
```
Pastikan IP lokal disesuaikan dengan segmen LAN Anda.

---

## 5. Konfigurasi Auto-Block (Firewall)

Fitur proteksi (Auto-Block) bot secara cerdas memblokir IP *hacker* menggunakan **Address List**. Pastikan MikroTik Anda men- *drop* koneksi dari IP yang masuk ke daftar tersebut.

```routeros
# Rule untuk memblokir siapapun yang ada di address list "blocked_by_bot"
/ip firewall filter add action=drop chain=input src-address-list=blocked_by_bot comment="Drop IP Blocked by Mikro Watcher" place-before=0
```

---

## 6. Sinkronisasi Waktu (NTP Client)

Agar *timestamp* peringatan dan insiden bot akurat (tidak dari masa lampau 1970), pastikan router Anda mendapat waktu sinkron dari internet.

```routeros
/system ntp client set enabled=yes
/system ntp client servers add address=pool.ntp.org
/system clock set time-zone-name=Asia/Jakarta
```

---

## 🎉 Selesai

MikroTik Anda sekarang sepenuhnya siap dipantau dan dikontrol secara cerdas oleh **Mikro Watcher Bot**! 
Jangan lupa sesuaikan nilai di *file* `.env` bot (kolom `MIKROTIK_IP`, `MIKROTIK_USER`, `MIKROTIK_PASS`) dengan data yang Anda buat pada langkah 1.
