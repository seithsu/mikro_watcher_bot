import time
import uuid
import logging
import threading
from datetime import datetime
from html import escape as _html_escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import core.config as cfg
from core.logger import catat
from mikrotik.decorators import format_bytes as format_bytes_auto

logger = logging.getLogger(__name__)

_GENERIC_ERROR_TEXT = "❌ <b>Terjadi gangguan internal.</b>\nCek log bot untuk detail teknis."


def menu_timestamp_text():
    """Timestamp singkat untuk footer menu Telegram."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def with_menu_timestamp(text):
    """Tambahkan timestamp ke layar menu/submenu agar konsisten."""
    base = str(text or "").rstrip()
    return f"{base}\n\n🗓️ <i>{menu_timestamp_text()}</i>"


def read_state_json():
    """Baca state.json yang ditulis oleh monitor.py (shared utility).

    Return dict {'hosts': {}, 'kategori': '...', 'last_update': '...'}
    """
    import json
    state_file = cfg.DATA_DIR / "state.json"
    try:
        if state_file.exists():
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.debug("read_state_json gagal: %s", e)
    return {
        'hosts': {},
        'fails': {},
        'kategori': '🟢 NORMAL',
        'api_connected': True,
        'api_error': '',
        'monitor_degraded': False,
        'degraded_reason': '',
    }


def get_back_button(back_to=None):
    """Footer navigasi konsisten: ⬅️ Back + 🏠 Home.

    back_to: callback_data untuk tombol Back (default: cmd_start / Home).
              Contoh: 'menu_monitor', 'menu_network', dll.
    """
    if back_to and back_to != 'cmd_start':
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back", callback_data=back_to),
            InlineKeyboardButton("🏠 Home", callback_data='cmd_start'),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home", callback_data='cmd_start'),
    ]])


def append_back_button(reply_markup, back_to=None):
    """Tambahkan footer navigasi ke existing keyboard.

    back_to: callback_data untuk tombol Back.
    """
    if not reply_markup:
        return get_back_button(back_to)
    footer = []
    if back_to and back_to != 'cmd_start':
        footer.append(InlineKeyboardButton("⬅️ Back", callback_data=back_to))
    footer.append(InlineKeyboardButton("🏠 Home", callback_data='cmd_start'))
    new_keyboard = list(reply_markup.inline_keyboard) + [footer]
    return InlineKeyboardMarkup(new_keyboard)

# ============ RATE LIMITER ============


class RateLimiter:
    """Rate limiter sederhana per-user, per-menit. Thread-safe."""

    def __init__(self, max_per_minute):
        self._max = max_per_minute
        self._requests = {}  # {user_id: [timestamp, ...]}
        self._last_cleanup = time.time()
        self._lock = threading.Lock()

    def is_allowed(self, user_id):
        """Cek apakah user masih boleh request."""
        now = time.time()

        with self._lock:
            # Global cleanup tiap 1 jam untuk GC user idle
            if now - self._last_cleanup > 3600:
                self._cleanup_idle_users(now)
                self._last_cleanup = now

            cutoff = now - 60

            if user_id not in self._requests:
                self._requests[user_id] = []

            # Hapus request lama
            self._requests[user_id] = [
                t for t in self._requests[user_id] if t > cutoff
            ]

            if len(self._requests[user_id]) >= self._max:
                return False

            self._requests[user_id].append(now)
            return True

    def _cleanup_idle_users(self, now):
        """Hapus user yang tidak beraktivitas lebih dari 10 menit (600s) dari memory.

        Caller harus sudah memegang self._lock."""
        idle_cutoff = now - 600
        active_users = {}
        for uid, reqs in self._requests.items():
            valid_reqs = [t for t in reqs if t > idle_cutoff]
            if valid_reqs:
                active_users[uid] = valid_reqs
        self._requests = active_users


_rate_limiter = RateLimiter(int(getattr(cfg, "RATE_LIMIT_PER_MINUTE", 20)))


# ============ HELPERS ============

def cek_admin(user_id):
    """Cek apakah user adalah admin yang sah (multi-admin)."""
    return user_id in getattr(cfg, "ADMIN_IDS", [])

# format_bytes_auto diimpor dari mikrotik.decorators.format_bytes (canonical source)
# Menghindari duplikasi logika yang identik.


def _format_bytes(bytes_val):
    """Alias untuk format_bytes_auto (canonical source: mikrotik.decorators.format_bytes)."""
    return format_bytes_auto(bytes_val)


def format_duration_hms(seconds):
    """Format durasi detik ke string 'Xh Xm Xs' yang human-readable.

    Single source of truth — dipakai oleh cmd_history, daily report, dll.
    """
    seconds = max(0, int(seconds or 0))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def format_voltage(v):
    """Format nilai voltage dari MikroTik ke string yang human-readable.

    FIND-26 FIX: Single source of truth — menggantikan duplikasi logika
    di handlers/general.py dan handlers/jobs.py.

    RouterOS kadang mengembalikan voltage dalam decidegrees (mis. 241 = 24.1V).
    Jika nilai > 100, dibagi 10 untuk konversi ke volt nyata.

    Return string mis. '24.1V' atau '' jika v tidak valid.
    """
    if not v:
        return ""
    try:
        v_val = float(v)
        if v_val > 100:
            v_val = v_val / 10
        return f"{v_val:.1f}V"
    except (TypeError, ValueError):
        return f"{v}V"


def escape_html(value):
    """Escape aman untuk field dinamis pada parse_mode='HTML' (body text)."""
    return _html_escape(str(value), quote=False)


def escape_html_attr(value):
    """Escape aman untuk nilai di dalam atribut HTML (quote=True).

    Gunakan ini saat value disisipkan di atribut tag, misalnya
    <a href="..."> atau <img alt="...">.
    Untuk teks biasa dalam body, gunakan escape_html().
    """
    return _html_escape(str(value), quote=True)


def generic_error_html(prefix=None):
    """Pesan error aman untuk user (tanpa bocor exception internal)."""
    if prefix:
        return f"❌ <b>{
            escape_html(prefix)}</b>\nCek log bot untuk detail teknis."
    return _GENERIC_ERROR_TEXT


def set_cache_with_ts(bot_data, key, value):
    """Simpan cache + timestamp agar bisa di-cleanup TTL terpusat."""
    bot_data[key] = value
    bot_data[f"ts_{key}"] = time.time()


def get_cache_if_fresh(bot_data, key, ttl_seconds):
    """Ambil cache jika belum kedaluwarsa."""
    value = bot_data.get(key)
    if value is None:
        return None
    ts = bot_data.get(f"ts_{key}", 0) or 0
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        age = ttl_seconds + 1
    if age > ttl_seconds:
        bot_data.pop(key, None)
        bot_data.pop(f"ts_{key}", None)
        return None
    return value


def put_callback_payload(bot_data, namespace, payload, ttl_seconds=1800):
    """Simpan payload callback dinamis dan return token pendek aman Telegram."""
    token = uuid.uuid4().hex[:10]
    cache_key = f"cb_{namespace}_{token}"
    set_cache_with_ts(bot_data, cache_key, payload)
    # TTL dipakai saat retrieval, disini hanya return token.
    return token


def get_callback_payload(bot_data, namespace, token, ttl_seconds=1800):
    """Ambil payload callback berdasarkan token pendek."""
    cache_key = f"cb_{namespace}_{token}"
    return get_cache_if_fresh(bot_data, cache_key, ttl_seconds=ttl_seconds)


def format_interface_list(interfaces):
    """Format list interface jadi text yang rapi."""
    text = "[NET] DAFTAR INTERFACE\n"
    text += "=" * 25 + "\n\n"

    for iface in interfaces:
        if iface['running'] and iface['enabled']:
            status = "[ON] UP"
        elif not iface['enabled']:
            status = "[OFF] DISABLED"
        else:
            status = "[DOWN] DOWN"

        text += f"{status} {iface['name']}\n"
        text += f"   Type: {iface['type']}\n"

        if iface['comment']:
            text += f"   Note: {iface['comment']}\n"

        text += "\n"

    return text


_unknown_user_notified = set()  # Track unknown user_ids yang sudah dinotifikasi
_UNKNOWN_USER_NOTIFIED_MAX = 5000   # IMP-7: cap agar tidak tumbuh tanpa batas
_UNKNOWN_USER_NOTIFIED_EVICT = 1000  # Buang sejumlah ini saat cap tercapai


async def _check_access(update, user, command):
    """Helper: cek admin + rate limit. Return True jika ditolak."""
    # Sync runtime override (shared file) agar proses bot ikut nilai terbaru.
    try:
        cfg.reload_runtime_overrides(min_interval=5)
        cfg.reload_router_env(min_interval=10)
        _rate_limiter._max = int(cfg.RATE_LIMIT_PER_MINUTE)
    except Exception as e:
        logger.debug("reload runtime config gagal: %s", e)

    async def send_warning(text):
        if update.message:
            await update.effective_message.reply_text(text)
        elif update.callback_query:
            await update.callback_query.answer(text, show_alert=True)

    if not cek_admin(user.id):
        catat(user.id, user.username, command, "ditolak-bukan-admin")
        logger.warning(
            "[SEC] Akses ditolak: user_id=%s username=%s command=%s",
            user.id, user.username or "?", command,
        )
        # Notifikasi admin saat ada user tidak dikenal mencoba akses (1x per
        # user per session)
        if user.id not in _unknown_user_notified:
            # IMP-7 FIX: Jaga ukuran set agar tidak memory leak saat flood
            # attack
            if len(_unknown_user_notified) >= _UNKNOWN_USER_NOTIFIED_MAX:
                try:
                    evict = set(
                        list(_unknown_user_notified)[
                            :_UNKNOWN_USER_NOTIFIED_EVICT])
                    _unknown_user_notified.difference_update(evict)
                    logger.debug(
                        "_unknown_user_notified evicted %d entries.",
                        len(evict))
                except Exception:
                    pass
            _unknown_user_notified.add(user.id)
            try:
                from telegram import Bot
                _notify_bot = Bot(token=cfg.TOKEN)
                for admin_id in getattr(cfg, "ADMIN_IDS", []):
                    try:
                        await _notify_bot.send_message(
                            chat_id=admin_id,
                            text=(
                                f"🚨 <b>AKSES TIDAK SAH TERDETEKSI</b>\n\n"
                                f"User: <code>{user.id}</code>\n"
                                f"Username: @{user.username or '?'}\n"
                                f"Nama: {user.first_name or ''} {user.last_name or ''}\n"
                                f"Command: <code>{command}</code>\n\n"
                                f"<i>User ini bukan admin yang terdaftar.</i>"
                            ),
                            parse_mode='HTML',
                        )
                    except Exception:
                        pass
            except Exception:
                pass
        await send_warning("[DENIED] Akses ditolak!")
        return True

    if not _rate_limiter.is_allowed(user.id):
        await send_warning(
            "[LIMIT] Terlalu banyak request!\n"
            "Tunggu sebentar sebelum coba lagi."
        )
        return True

    return False
