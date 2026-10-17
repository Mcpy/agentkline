#!/bin/bash
# AgentKline 服务管理脚本
# 用法：./scripts/service.sh start|stop|restart|status|logs [n]
# 优先委托 user systemd 单元（独立 cgroup，dsh 重启不受牵连；未 enable、Restart=no，
# 遵循用户裁决：不做任何自动拉起——掉了手动 start 或喊助手）。
# 无单元文件时回落 pidfile 单实例管理（规避 pkill 误杀）。
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT="$HOME/.config/systemd/user/agentkline.service"
PIDFILE="$DIR/.agentkline.pid"
LOG="${AGENTKLINE_LOG:-/tmp/agentkline.log}"

have_unit() { [ -f "$UNIT" ] && systemctl --user list-unit-files agentkline.service >/dev/null 2>&1; }

running() {
    if have_unit; then
        [ "$(systemctl --user is-active agentkline 2>/dev/null)" = "active" ] && return 0 || return 1
    fi
    [ -f "$PIDFILE" ] || return 1
    local pid; pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start() {
    if running; then echo "already running"; status; return 0; fi
    if have_unit; then
        systemctl --user start agentkline && sleep 5 && { echo "started (systemd user unit)"; status; return 0; }
        echo "start failed — see $LOG"; return 1
    fi
    if ss -tln 2>/dev/null | grep -qE ':876[56] '; then
        echo "port 8765/8766 occupied but not managed — stop the manual instance first"; return 1
    fi
    cd "$DIR" || exit 1
    if [ -x "$DIR/.venv/bin/python" ]; then
        setsid nohup env PYTHONPATH="$DIR" "$DIR/.venv/bin/python" -m agentkline.api.app >>"$LOG" 2>&1 < /dev/null &
    else
        setsid nohup env PYTHONPATH="$DIR" uv run python -m agentkline.api.app >>"$LOG" 2>&1 < /dev/null &
    fi
    echo $! > "$PIDFILE"
    sleep 6
    if running; then echo "started (pid $(cat "$PIDFILE")), log: $LOG"; else echo "start failed — see $LOG"; rm -f "$PIDFILE"; return 1; fi
}

stop() {
    if have_unit && [ "$(systemctl --user is-active agentkline 2>/dev/null)" = "active" ]; then
        systemctl --user stop agentkline; echo "stopped (systemd user unit)"; return 0
    fi
    if ! running; then echo "not running"; rm -f "$PIDFILE"; return 0; fi
    local pid; pid=$(cat "$PIDFILE")
    kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 15); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    rm -f "$PIDFILE"
    echo "stopped"
}

status() {
    if running; then
        ss -tln | grep -E ':876[56] ' || echo "warn: ports not listening"
        if have_unit; then echo "pid $(systemctl --user show agentkline -p MainPID --value)";
        elif [ -f "$PIDFILE" ]; then echo "pid $(cat "$PIDFILE")"; fi
    else
        echo "not running"
    fi
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  status ;;
    logs)    tail -n "${2:-50}" "$LOG" ;;
    *)       echo "usage: $0 start|stop|restart|status|logs [n]"; exit 2 ;;
esac
