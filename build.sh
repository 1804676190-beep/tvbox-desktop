#!/bin/bash
# TVBox Desktop — Linux/macOS 打包脚本

set -e
echo "========================================"
echo "  TVBox Desktop — 打包脚本"
echo "========================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3"
    exit 1
fi

# 安装依赖
echo "[1/2] 安装依赖..."
pip3 install -r requirements.txt pyinstaller -q

# 打包
echo "[2/2] 正在打包..."
pyinstaller tvbox.spec --clean --noconfirm

echo
echo "========================================"
echo "  打包完成！"
echo "  输出目录: dist/TVBox Desktop/"
echo "========================================"
