#!/bin/bash
# =============================================
#   TVBox Desktop — 一键安装脚本 (Linux/macOS)
# =============================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     📺 TVBox Desktop — 一键安装脚本     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# -----------------------------------------
#  1. 检查 Python
# -----------------------------------------
echo -e "${CYAN}[1/5]${NC} 检查 Python 环境..."

PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ 未找到 Python！${NC}"
    echo ""

    # 尝试自动安装
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            echo "正在用 Homebrew 安装 Python..."
            brew install python@3.12
            PYTHON_CMD="python3"
        else
            echo "请先安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo "然后运行: brew install python@3.12"
            exit 1
        fi
    elif command -v apt-get &>/dev/null; then
        echo "正在用 apt 安装 Python..."
        sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv
        PYTHON_CMD="python3"
    elif command -v dnf &>/dev/null; then
        echo "正在用 dnf 安装 Python..."
        sudo dnf install -y python3 python3-pip
        PYTHON_CMD="python3"
    elif command -v pacman &>/dev/null; then
        echo "正在用 pacman 安装 Python..."
        sudo pacman -S --noconfirm python python-pip
        PYTHON_CMD="python3"
    else
        echo -e "${RED}无法自动安装 Python，请手动安装 3.10+${NC}"
        exit 1
    fi
fi

PYVER=$($PYTHON_CMD --version 2>&1)
echo -e "${GREEN}✅ $PYVER${NC}"

# 检查版本 >= 3.10
$PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Python 版本过低，需要 3.10+${NC}"
    exit 1
fi

# -----------------------------------------
#  2. 升级 pip
# -----------------------------------------
echo ""
echo -e "${CYAN}[2/5]${NC} 升级 pip..."
$PYTHON_CMD -m pip install --upgrade pip -q 2>/dev/null || \
$PYTHON_CMD -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q 2>/dev/null
echo -e "${GREEN}✅ pip 已更新${NC}"

# -----------------------------------------
#  3. 安装 Python 依赖
# -----------------------------------------
echo ""
echo -e "${CYAN}[3/5]${NC} 安装 Python 依赖..."

pip install -r requirements.txt -q 2>/dev/null || \
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q 2>/dev/null

echo -e "${GREEN}✅ Python 依赖安装完成${NC}"

# -----------------------------------------
#  4. 安装 mpv 播放器
# -----------------------------------------
echo ""
echo -e "${CYAN}[4/5]${NC} 检查 mpv 播放器..."

MPV_OK=0

if command -v mpv &>/dev/null; then
    MPV_VER=$(mpv --version 2>/dev/null | head -1)
    echo -e "${GREEN}✅ mpv 已安装: $MPV_VER${NC}"
    MPV_OK=1
fi

# 检查 libmpv
if [ "$MPV_OK" -eq 0 ]; then
    if ldconfig -p 2>/dev/null | grep -q libmpv; then
        echo -e "${GREEN}✅ libmpv 已安装${NC}"
        MPV_OK=1
    fi
    if [ -f "/usr/local/lib/libmpv.dylib" ] || [ -f "/opt/homebrew/lib/libmpv.dylib" ]; then
        echo -e "${GREEN}✅ libmpv 已安装${NC}"
        MPV_OK=1
    fi
fi

if [ "$MPV_OK" -eq 0 ]; then
    echo -e "${YELLOW}⏳ 正在安装 mpv...${NC}"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            brew install mpv && MPV_OK=1
        fi
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y mpv libmpv-dev && MPV_OK=1
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y mpv mpv-libs-devel && MPV_OK=1
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm mpv && MPV_OK=1
    fi

    if [ "$MPV_OK" -eq 1 ]; then
        echo -e "${GREEN}✅ mpv 安装成功${NC}"
    else
        echo -e "${YELLOW}⚠️ mpv 自动安装失败${NC}"
        echo ""
        echo "请手动安装:"
        echo "  macOS:   brew install mpv"
        echo "  Ubuntu:  sudo apt install mpv libmpv-dev"
        echo "  Fedora:  sudo dnf install mpv mpv-libs-devel"
        echo "  Arch:    sudo pacman -S mpv"
        echo ""
        echo "没有 mpv 也可以运行程序，但播放功能不可用"
        echo ""
    fi
fi

# -----------------------------------------
#  5. 创建启动脚本
# -----------------------------------------
echo ""
echo -e "${CYAN}[5/5]${NC} 创建启动脚本..."

cat > "$SCRIPT_DIR/start.sh" << 'LAUNCH'
#!/bin/bash
cd "$(dirname "$0")"
python3 main.py 2>/dev/null || python main.py
LAUNCH
chmod +x "$SCRIPT_DIR/start.sh"

# 创建桌面快捷方式 (Linux)
if [ -d "$HOME/Desktop" ]; then
    cat > "$HOME/Desktop/tvbox-desktop.desktop" << EOF
[Desktop Entry]
Name=TVBox Desktop
Comment=TVBox 桌面播放器
Exec=$SCRIPT_DIR/start.sh
Icon=video-player
Terminal=false
Type=Categories=AudioVideo;Video;Player;
EOF
    chmod +x "$HOME/Desktop/tvbox-desktop.desktop" 2>/dev/null
    echo -e "${GREEN}✅ 桌面快捷方式已创建${NC}"
else
    echo -e "${GREEN}✅ 启动脚本已创建: start.sh${NC}"
fi

# -----------------------------------------
#  完成
# -----------------------------------------
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✅ 安装完成！                  ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}║  启动方式:                               ║${NC}"
echo -e "${GREEN}║    ./start.sh                            ║${NC}"
echo -e "${GREEN}║    或: python3 main.py                   ║${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}║  打包:                                   ║${NC}"
echo -e "${GREEN}║    chmod +x build.sh && ./build.sh       ║${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

read -p "是否立即启动 TVBox Desktop? (y/n): " LAUNCH
if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 启动中..."
    exec "$SCRIPT_DIR/start.sh"
fi
