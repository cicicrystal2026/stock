#!/bin/bash
# 优选决策台 · 服务器一键部署（在 Ubuntu/Debian 香港服务器上，root 执行）
#
# 前置：
#   1) 代码已放到 /opt/stock-screener（可用 scp/rsync/git 上传）
#   2) 已安装 python3-venv、caddy
#   3) 域名 stock.migucomi.com 已解析到本机公网 IP
#
# 用法：  sudo STOCK_APP_PASSWORD='你的密码' bash deploy/install.sh
set -e

APP=/opt/stock-screener
PASSWORD="${STOCK_APP_PASSWORD:?请设置 STOCK_APP_PASSWORD 环境变量后重试}"
PY=python3

echo "==> 安装依赖（venv）"
$PY -m venv "$APP/venv"
"$APP/venv/bin/pip" install --upgrade pip -q
"$APP/venv/bin/pip" install -r "$APP/requirements.txt" -q

echo "==> 写入 systemd 服务（注入密码）"
sed "s/__PASSWORD__/${PASSWORD}/g" \
  "$APP/deploy/stock-screener.service" > /etc/systemd/system/stock-screener.service
systemctl daemon-reload
systemctl enable --now stock-screener

echo "==> 配置每日自动更新（工作日 16:00）"
mkdir -p "$APP/logs"
CRON_LINE="0 16 * * 1-5 cd $APP && bash deploy/update.sh >> $APP/logs/update.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'deploy/update.sh' ; echo "$CRON_LINE" ) | crontab -

echo "==> 配置 Caddy"
mkdir -p /etc/caddy
cp "$APP/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo ""
echo "✅ 部署完成"
echo "  看板地址： https://stock.migucomi.com"
echo "  访问密码： （你刚设置的那个）"
echo "  检查状态： systemctl status stock-screener"
echo "  查看日志： journalctl -u stock-screener -f"
echo "  更新日志： tail -f $APP/logs/update.log"
