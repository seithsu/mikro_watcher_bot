import asyncio
import logging
import time
from telegram.error import RetryAfter, TimedOut, NetworkError
import core.config as cfg

logger = logging.getLogger(__name__)

# Global queue untuk menampung semua alert
_queue = asyncio.Queue()

async def put_alert(chat_id, text, parse_mode='HTML', reply_markup=None):
    """
    Menaruh pesan peringatan ke dalam antrean (non-blocking).
    Akan diproses oleh worker di background.
    """
    await _queue.put({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'reply_markup': reply_markup,
        'retries': 0
    })

async def alert_worker(bot):
    """
    Worker daemon yang berjalan selamanya di background.
    Tugasnya menguras antrean pesan dan mengirimkannya ke Telegram
    secara aman dari rate limit.
    """
    logger.info("[ALERT WORKER] Daemon dimulai...")
    while True:
        try:
            job = await _queue.get()
            
            chat_id = job['chat_id']
            text = job['text']
            parse_mode = job.get('parse_mode', 'HTML')
            reply_markup = job.get('reply_markup')
            retries = job.get('retries', 0)

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                # Jeda tipis untuk menghindari flood control
                await asyncio.sleep(0.5)
            except RetryAfter as e:
                logger.warning(f"[ALERT WORKER] Flood control! Tunggu {e.retry_after}s.")
                await asyncio.sleep(e.retry_after + 1)
                # Masukkan kembali ke antrean jika belum over-retry
                if retries < 3:
                    job['retries'] += 1
                    await _queue.put(job)
            except (TimedOut, NetworkError) as e:
                logger.warning(f"[ALERT WORKER] Network Error: {e}")
                await asyncio.sleep(2)
                if retries < 3:
                    job['retries'] += 1
                    await _queue.put(job)
            except Exception as e:
                logger.error(f"[ALERT WORKER] Gagal kirim pesan ke {chat_id}: {e}")
            finally:
                _queue.task_done()
                
        except asyncio.CancelledError:
            logger.info("[ALERT WORKER] Daemon dihentikan.")
            break
        except Exception as e:
            logger.error(f"[ALERT WORKER] Kesalahan sistem worker: {e}")
            await asyncio.sleep(1)
