#!/usr/bin/env bash
# Qingliao Platform plugin for Hermes Agent —— 一键安装
#
# 用法:
#   bash install.sh <目标目录: Hermes profile 的 plugins/<name>>   （推荐）
#   bash install.sh                                                  （缺省当前目录下 qingliao-platform/）
#   # 或从 GitHub 直接运行（无需 clone 本仓库）:
#   bash <(curl -fsSL https://raw.githubusercontent.com/lxm20060513-svg/qingliao-hermes-plugin/main/install.sh) <目标目录>
#
# 目标目录约定：放到 Hermes profile 的 plugins/ 下，取名 <name>=qingliao-platform，
# 使 plugin.yaml 位于 plugins/qingliao-platform/plugin.yaml（Hermes 扫描清单的预期位置）。
set -euo pipefail

REPO="https://github.com/lxm20060513-svg/qingliao-hermes-plugin"
NAME="qingliao-platform"

DEST="${1:-$PWD/$NAME}"
echo "==> 目标安装目录: $DEST"

if [ -f "$DEST/plugin.yaml" ]; then
    echo "==> 目标目录已有插件，执行覆盖更新"
    git -C "$DEST" pull --ff-only 2>/dev/null || true
else
    mkdir -p "$(dirname "$DEST")"
    echo "==> 克隆 $REPO -> $DEST"
    git clone --depth 1 "$REPO" "$DEST" 2>/dev/null || { echo "✗ clone 失败，请检查网络/token"; exit 1; }
fi

# 清掉 .git（避免把仓库历史带进 plugins/ 目录）
rm -rf "$DEST/.git"

if [ ! -f "$DEST/plugin.yaml" ] || [ ! -f "$DEST/adapter.py" ]; then
    echo "✗ 插件文件不完整"; exit 1
fi

echo ""
echo "✅ 已安装到: $DEST"
echo "插件文件:"; ls -1 "$DEST"
echo ""
echo "→ 下一步配置:"
echo "  1. 在 Hermes profile 的 config.yaml 启用平台:"
echo "       platforms:"
echo "         qingliao:"
echo "           enabled: true"
echo "           extra: { token: \"<QINGLIAO_TOKEN>\", allowed_users: [\"*\"] }"
echo "  2. 设置环境变量（或放 config.extra）："
echo "       QINGLIAO_TOKEN       —— 入站 /chat 的 Bearer token"
echo "       QL_HOST              —— 轻聊后端 host（收件箱推送目标）"
echo "       QL_INBOX_PORT        —— 收件箱推送端口（默认 9127）"
echo "       QL_INBOX_TOKEN_FILE  —— 收件箱 X-Inbox-Token 文件路径"
echo "  3. 重启 gateway（如 s6: s6-svc -r /run/service/gateway-<profile>）"
echo "  4. 验证: curl -s http://<qingliao-host>:9130/health"
