#!/bin/bash
# AgentKline 启动脚本（双端口）
# web   端口: 用户浏览器（无鉴权），默认 0.0.0.0:8765
# agent 端口: AI agent（全量鉴权 + /mcp），默认 127.0.0.1:8766
# 可在 config.yaml 的 server.web / server.agent 或环境变量调整。
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 Starting AgentKline (dual-port)..."
echo "   web   : http://localhost:${AGENTKLINE_WEB_PORT:-8765}"
echo "   agent : http://localhost:${AGENTKLINE_AGENT_PORT:-8766}/mcp/  (需 Bearer token)"
echo ""

cd "$DIR"
export PYTHONPATH="$DIR"
exec python -m agentkline.api.app
