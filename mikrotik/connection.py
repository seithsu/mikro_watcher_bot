# ============================================
# MIKROTIK/CONNECTION - Connection Pool (librouteros)
# Thread-safe connection pool ke MikroTik
# Setiap thread mendapat koneksi sendiri (thread-local)
# ============================================

import logging
import threading
import asyncio
import ssl
import time

import librouteros
from librouteros.login import plain, token

import core.config as cfg

logger = logging.getLogger(__name__)

# Socket timeout untuk operasi API (detik)
# Harus cukup besar untuk operasi ping (count=10 ~ 10 detik)
_SOCKET_TIMEOUT = 15


def _login_auto(api, username, password):
    """Compat login for both old and new RouterOS API auth flows."""
    last_exc = None
    for method in (token, plain):
        try:
            method(api=api, username=username, password=password)
            # Verify auth really succeeded (plain on old ROS can return !done without login).
            tuple(api("/system/identity/print", **{".proplist": "name"}))
            return
        except Exception as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc


class MikroTikConnection:
    """Thread-safe connection pool ke MikroTik via librouteros.

    Menggunakan thread-local storage agar setiap thread
    mendapat koneksi independen untuk menghindari race condition
    pada socket TCP yang tidak thread-safe.
    """

    _instance = None
    _local = threading.local()
    _global_lock = threading.Lock()
    
    _MAX_CONNECTIONS = 5
    _active_connections = 0
    _reset_version = 0  # Incremented oleh reset_all() untuk invalidate semua thread
    _connect_fail_count = 0
    _next_connect_allowed_ts = 0.0
    _last_connect_error = ""
    _last_limit_warning_ts = 0.0

    @classmethod
    def _connection_max_age_sec(cls):
        """Ambil max-age koneksi dari config (0 = nonaktif)."""
        try:
            return max(0, int(getattr(cfg, "MIKROTIK_CONNECTION_MAX_AGE_SEC", 0)))
        except Exception:
            return 0

    @classmethod
    def _prune_stale_counter(cls):
        """Best-effort cleanup untuk mencegah counter koneksi nyangkut."""
        live_threads = sum(1 for t in threading.enumerate() if t.ident is not None)
        if cls._active_connections > live_threads:
            cls._active_connections = live_threads

    @classmethod
    def _max_connections(cls):
        """Ambil batas koneksi maksimal dari config runtime."""
        try:
            return max(1, int(getattr(cfg, "MIKROTIK_MAX_CONNECTIONS", cls._MAX_CONNECTIONS)))
        except Exception:
            return cls._MAX_CONNECTIONS

    @classmethod
    def _register_connect_failure(cls, exc):
        """Set exponential backoff untuk menahan connect storm saat router down/swap."""
        cls._connect_fail_count += 1
        base = max(1, int(getattr(cfg, "MIKROTIK_RECONNECT_BASE_BACKOFF", 1)))
        max_wait = max(base, int(getattr(cfg, "MIKROTIK_RECONNECT_MAX_BACKOFF", 30)))
        wait = min(max_wait, base * (2 ** min(cls._connect_fail_count - 1, 6)))
        cls._next_connect_allowed_ts = time.time() + wait
        cls._last_connect_error = str(exc)

    @classmethod
    def _clear_connect_backoff(cls):
        cls._connect_fail_count = 0
        cls._next_connect_allowed_ts = 0.0
        cls._last_connect_error = ""

    @classmethod
    def _warn_limit_throttled(cls, max_conns):
        now = time.time()
        # Cegah log flood: warning maksimal 1x per 30 detik.
        if (now - cls._last_limit_warning_ts) >= 30:
            logger.warning(f"librouteros: max connections reached ({max_conns}), waiting...")
            cls._last_limit_warning_ts = now

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _create_connection():
        """Buat koneksi baru ke MikroTik."""
        # Hot-swap support: jika .env berubah, kredensial/IP baru akan dipakai
        # pada koneksi berikutnya tanpa restart proses.
        cfg.reload_router_env(min_interval=5)

        connect_kwargs = {
            'host': cfg.MIKROTIK_IP,
            'username': cfg.MIKROTIK_USER,
            'password': cfg.MIKROTIK_PASS,
            'port': int(cfg.MIKROTIK_PORT),
            'timeout': _SOCKET_TIMEOUT,
            'login_method': _login_auto,
        }

        # SSL support
        if cfg.MIKROTIK_USE_SSL:
            if getattr(cfg, "MIKROTIK_TLS_VERIFY", True):
                cafile = getattr(cfg, "MIKROTIK_TLS_CA_FILE", "") or None
                ctx = ssl.create_default_context(cafile=cafile)
                # Banyak deployment menggunakan IP langsung; hostname check dimatikan
                # namun verifikasi chain sertifikat tetap aktif.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                logger.warning("MIKROTIK TLS verification dinonaktifkan (insecure mode).")
            connect_kwargs['ssl_wrapper'] = ctx.wrap_socket

        api = librouteros.connect(**connect_kwargs)
        # Verifikasi sesi benar-benar usable. Pada RouterOS lama, connect() bisa
        # berhasil tetapi command pertama langsung dibalas "not logged in".
        tuple(api.path('system', 'identity'))
        return api

    def get_api(self):
        """Ambil API connection untuk thread saat ini.

        Setiap thread mendapat koneksi sendiri (thread-local),
        sehingga tidak ada race condition pada socket.
        Koneksi di-reuse selama masih sehat dan belum terlalu tua.
        Jika reset_all() dipanggil, semua thread akan reconnect pada get_api() berikutnya.
        """
        api = getattr(self._local, '_api', None)
        connected_at = getattr(self._local, '_connected_at', 0)
        try:
            cfg.reload_router_env(min_interval=5)
        except Exception as e:
            logger.debug("reload_router_env failed: %s", e)

        if api is not None:
            # B4 FIX: Cek version counter; jika reset_all() dipanggil, invalidate koneksi ini
            current_ver = self._reset_version
            seen_ver = getattr(self._local, '_reset_version_seen', -1)
            if seen_ver != current_ver:
                logger.info("librouteros: reset_all() terdeteksi, reconnect thread ini...")
                self._close_local()
                api = None
            else:
                # Cek usia koneksi; reconnect proaktif jika terlalu tua
                age = time.time() - connected_at
                max_age = self._connection_max_age_sec()
                if max_age > 0 and age > max_age:
                    logger.info(
                        "librouteros: koneksi usia %ss melebihi max-age %ss, reconnect proaktif",
                        int(age), max_age
                    )
                    self._close_local()
                else:
                    try:
                        # Health check ringan
                        tuple(api.path('system', 'identity'))
                        return api
                    except Exception:
                        logger.warning("librouteros: health check gagal, reconnect...")
                        self._close_local()

        # Saat router down/hot-swap, tahan connect storm dengan backoff singkat.
        now = time.time()
        if now < self._next_connect_allowed_ts:
            wait_left = round(self._next_connect_allowed_ts - now, 1)
            raise RuntimeError(
                f"Reconnect backoff aktif ({wait_left}s tersisa)"
                + (f" | last_error: {self._last_connect_error}" if self._last_connect_error else "")
            )

        max_conns = self._max_connections()

        # Enforce global max connections limit.
        for _wait_attempt in range(3):
            with self._global_lock:
                self._prune_stale_counter()
                if self._active_connections < max_conns:
                    break
            if _wait_attempt == 0:
                self._warn_limit_throttled(max_conns)
            time.sleep(0.5)
        else:
            raise RuntimeError(f"librouteros: max connections reached ({max_conns}), request ditunda")

        try:
            api = self._create_connection()
            self._local._api = api
            self._local._connected_at = time.time()
            self._local._reset_version_seen = self._reset_version
            with self._global_lock:
                self._prune_stale_counter()
                self._active_connections += 1
            self._clear_connect_backoff()
            logger.info(f"librouteros: koneksi baru berhasil + login OK (Active: {self._active_connections})")
        except librouteros.exceptions.TrapError as e:
            self._register_connect_failure(e)
            logger.error(f"librouteros login gagal (TrapError): {e}")
            raise
        except Exception as e:
            self._register_connect_failure(e)
            logger.error(f"librouteros connect gagal: {e}")
            raise
        return api

    def _close_local(self):
        """Tutup koneksi di thread saat ini."""
        api = getattr(self._local, '_api', None)
        if api is not None:
            try:
                api.close()
            except Exception as e:
                logger.debug("api.close() gagal: %s", e)
            finally:
                # W5 FIX: decrement hanya jika benar-benar ada koneksi yang ditutup
                with self._global_lock:
                    self._prune_stale_counter()
                    if self._active_connections > 0:
                        self._active_connections -= 1
                self._local._api = None
                self._local._connected_at = 0

    def reset(self):
        """Reset koneksi di thread saat ini (dipanggil setelah reboot/error)."""
        self._close_local()

    def reset_all(self, clear_backoff=False):
        """Force-reconnect semua thread pada get_api() berikutnya.

        Cara kerja: increment _reset_version (class-level counter).
        Setiap thread yang memanggil get_api() akan mendeteksi
        versi berbeda dan reconnect secara otomatis.
        Thread saat ini juga langsung ditutup.
        """
        with self._global_lock:
            self._reset_version += 1
            self._prune_stale_counter()
            if clear_backoff:
                self._clear_connect_backoff()
        self._close_local()
        logger.info(
            "librouteros: reset_all() versi ke-%s, semua thread akan reconnect (clear_backoff=%s).",
            self._reset_version,
            bool(clear_backoff),
        )

    async def execute_async(self, path_parts, command="", **kwargs):
        """Native async execution via thread pool.

        Args:
            path_parts: tuple of path components, e.g. ('system', 'resource')
            command: optional command to execute, e.g. 'reboot'
            **kwargs: parameters for the command
        """
        def _sync():
            api = self.get_api()
            p = api.path(*path_parts)
            if command:
                return list(p(command, **kwargs))
            return list(p)

        return await asyncio.to_thread(_sync)

    def health_check(self):
        """Ping API untuk deteksi dini koneksi mati."""
        try:
            self.get_api()
            return True
        except Exception:
            return False

    def connection_diagnostics(self):
        """Ringkasan status koneksi terakhir untuk UI/monitoring."""
        now = time.time()
        wait_left = max(0.0, float(self._next_connect_allowed_ts) - now)
        local_api = getattr(self._local, "_api", None)
        local_seen_ver = getattr(self._local, "_reset_version_seen", -1)
        local_connected_at = float(getattr(self._local, "_connected_at", 0) or 0)
        local_api_valid = local_api is not None and local_seen_ver == self._reset_version

        max_age = self._connection_max_age_sec()
        if local_api_valid and max_age > 0 and local_connected_at > 0:
            local_age = max(0.0, now - local_connected_at)
            if local_age > max_age:
                local_api_valid = False

        active_connections = max(0, int(self._active_connections))
        healthy = bool(
            wait_left <= 0.0
            and (
                active_connections > 0
                or local_api_valid
                or not str(self._last_connect_error or "").strip()
            )
        )
        return {
            "healthy": healthy,
            "fail_count": int(self._connect_fail_count),
            "backoff_seconds": round(wait_left, 1),
            "last_error": str(self._last_connect_error or ""),
            "active_connections": active_connections,
            "has_local_api": bool(local_api_valid),
        }


pool = MikroTikConnection()
