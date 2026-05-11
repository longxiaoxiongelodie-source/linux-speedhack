#!/usr/bin/env bash
# install.sh — SpeedHack 一键安装脚本
set -e

INSTALL_DIR="$HOME/.local/share/speedhack"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/128x128/apps"
DESKTOP_DIR="$HOME/Desktop"

echo "⚡ SpeedHack 安装程序"
echo "安装到: $INSTALL_DIR"
echo ""

# 检查依赖
MISSING=()
command -v python3 >/dev/null || MISSING+=("python3")
python3 -c "import tkinter" 2>/dev/null || MISSING+=("python3-tk")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "缺少依赖: ${MISSING[*]}"
    echo "请先运行: sudo apt install ${MISSING[*]}"
    exit 1
fi

# 复制文件
mkdir -p "$INSTALL_DIR"
cp speedhack.so     "$INSTALL_DIR/"
cp speedctl         "$INSTALL_DIR/"
cp speedhack_gui.py "$INSTALL_DIR/"
cp run.sh           "$INSTALL_DIR/"
cp speedhack.svg    "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/run.sh"
chmod +x "$INSTALL_DIR/speedhack_gui.py"

# 生成 PNG 图标
if command -v convert >/dev/null; then
    convert -background none "$INSTALL_DIR/speedhack.svg" \
            -resize 128x128 "$INSTALL_DIR/speedhack.png" 2>/dev/null
elif command -v rsvg-convert >/dev/null; then
    rsvg-convert -w 128 -h 128 "$INSTALL_DIR/speedhack.svg" \
                 -o "$INSTALL_DIR/speedhack.png" 2>/dev/null
fi

# 安装桌面图标
mkdir -p "$APP_DIR" "$ICON_DIR"
[ -f "$INSTALL_DIR/speedhack.png" ] && \
    cp "$INSTALL_DIR/speedhack.png" "$ICON_DIR/speedhack.png"

cat > "$APP_DIR/speedhack.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=SpeedHack
Comment=Linux 游戏变速器
Exec=/usr/bin/python3 $INSTALL_DIR/speedhack_gui.py
Icon=$INSTALL_DIR/speedhack.png
Terminal=false
StartupNotify=true
Categories=Game;
EOF
chmod +x "$APP_DIR/speedhack.desktop"

# 桌面快捷方式
if [ -d "$DESKTOP_DIR" ]; then
    cp "$APP_DIR/speedhack.desktop" "$DESKTOP_DIR/speedhack.desktop"
    chmod +x "$DESKTOP_DIR/speedhack.desktop"
    gio set "$DESKTOP_DIR/speedhack.desktop" metadata::trusted true 2>/dev/null || true
fi

# 刷新缓存
update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "$ICON_DIR/../../.." 2>/dev/null || true

echo ""
echo "✓ 安装完成！"
echo ""
echo "使用方法："
echo "  1. 在应用菜单搜索「SpeedHack」启动图形界面"
echo "  2. 在 Steam 游戏启动选项里加入："
echo "     SPEEDHACK_FACTOR=1.0 LD_PRELOAD=$INSTALL_DIR/speedhack.so %command%"
echo "  3. 启动游戏后，GUI 会自动检测并连接"
