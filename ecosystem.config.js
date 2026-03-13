// ============================================
// PM2 Config - MikroTik Bot
// ============================================
//
// LOG FILES:
//   logs/bot.log      -> Semua output bot
//   logs/monitor.log  -> Semua output monitor
//
// COMMANDS:
//   pm2 start ecosystem.config.js  -> Jalankan
//   pm2 stop all                   -> Stop
//   pm2 restart all                -> Restart
//   pm2 logs                       -> Lihat log live
//   pm2 flush                      -> Hapus semua log
//   pm2 status                     -> Cek status
// ============================================

module.exports = {
    apps: [
        {
            name: "MIKRO_WATCHER",
            script: "./bot.py",
            interpreter: "python",
            interpreter_args: "-B",  // Disable __pycache__ (no stale .pyc)
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: "200M",

            // PM2 only captures raw stdout/stderr fallback.
            // Log utama dikelola aplikasi dengan rotation internal.
            out_file: "./logs/pm2-bot.log",
            error_file: "./logs/pm2-bot.log",
            merge_logs: true,
            log_date_format: "YYYY-MM-DD HH:mm:ss",
            env: {
                APP_LOG_FILE: "./logs/bot.log",
                APP_LOG_TO_STDOUT: "false",
            },

            // Stability
            exp_backoff_restart_delay: 100, // Starts at 100ms, doubles on crash
            restart_delay: 5000,
            max_restarts: 10,
            min_uptime: "10s",

            // Windows
            windowsHide: true,
            exec_mode: "fork"
        },
        {
            name: "MIKRO_MONITOR",
            script: "./run_monitor.py",
            interpreter: "python",
            interpreter_args: "-B",  // Disable __pycache__ (no stale .pyc)
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: "150M",

            // PM2 only captures raw stdout/stderr fallback.
            // Log utama dikelola aplikasi dengan rotation internal.
            out_file: "./logs/pm2-monitor.log",
            error_file: "./logs/pm2-monitor.log",
            merge_logs: true,
            log_date_format: "YYYY-MM-DD HH:mm:ss",
            env: {
                APP_LOG_FILE: "./logs/monitor.log",
                APP_LOG_TO_STDOUT: "false",
            },

            // Stability
            exp_backoff_restart_delay: 100, // Starts at 100ms, doubles on crash
            restart_delay: 5000,
            max_restarts: 10,
            min_uptime: "10s",

            // Windows
            windowsHide: true,
            exec_mode: "fork"
        }
    ]
};
