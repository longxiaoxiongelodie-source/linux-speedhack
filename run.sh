#!/usr/bin/env bash
# run.sh — 启动器，自动注入 speedhack.so
#
# 用法：
#   ./run.sh [-s 倍速] <游戏命令> [参数...]
#
# 示例：
#   ./run.sh -s 3 ./mygame          # 3 倍速启动
#   ./run.sh ./mygame               # 1 倍速启动（可之后用 speedctl 调整）
#   ./run.sh -s 2 wine game.exe     # Wine 游戏

set -e
SPEED="1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SO="$SCRIPT_DIR/speedhack.so"

while getopts "s:h" opt; do
    case $opt in
        s) SPEED="$OPTARG" ;;
        h)
            echo "用法: $0 [-s 速度] <命令> [参数...]"
            echo "  -s SPEED   初始速度倍率（默认 1.0，范围 0.01-100.0）"
            echo ""
            echo "运行时调速："
            echo "  $SCRIPT_DIR/speedctl \$(pgrep -n <游戏名>) 2.0"
            exit 0
            ;;
        *) echo "未知选项: -$OPTARG"; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -eq 0 ]; then
    echo "错误: 未指定命令。用 -h 查看帮助。"
    exit 1
fi

if [ ! -f "$SO" ]; then
    echo "未找到 $SO，请先执行 make"
    exit 1
fi

exec env SPEEDHACK_FACTOR="$SPEED" \
         LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$SO" \
         "$@"
