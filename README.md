# ⚡ SpeedHack

Linux 游戏变速器。通过 `LD_PRELOAD` 劫持时间函数，让游戏以任意倍速运行，用于快速跳过无法跳过的动画或过场。

> 灵感来源：Windows 上的 Cheat Engine 变速功能，但适用于 Linux 原生游戏和 Proton/Wine 游戏。

![screenshot](screenshot.png)

## 功能

- **图形界面**：速度预设按钮 + 滑块，实时调速
- **自动扫描**：每 2 秒自动检测已注入的游戏进程，无需手动填 PID
- **运行时调速**：游戏运行中随时改变速度，无需重启
- **兼容 Snap + Steam**：支持 pressure-vessel 容器隔离（Steam Linux Runtime）
- **覆盖广**：劫持 `clock_gettime`、`gettimeofday`、`nanosleep`、`usleep`，兼容 SDL2、Unity、Godot、Wine/Proton 等

## 依赖

```
gcc  make  python3  python3-tk
```

Ubuntu/Debian：
```bash
sudo apt install build-essential python3-tk
```

## 编译

```bash
git clone https://github.com/你的用户名/speedhack
cd speedhack
make
```

## 使用方法

### 图形界面（推荐）

```bash
python3 speedhack_gui.py
```

或双击桌面图标（运行 `make install` 后自动安装）。

### Steam 游戏（Proton/Wine）

在 Steam 中右键游戏 → 属性 → 启动选项，填入：

```
SPEEDHACK_FACTOR=1.0 LD_PRELOAD=/path/to/speedhack.so %command%
```

然后正常启动游戏，GUI 会自动检测到进程。

### 原生 Linux 游戏

```bash
# 指定初始速度启动
./run.sh -s 3 ./your_game

# 或手动注入
SPEEDHACK_FACTOR=2.0 LD_PRELOAD=./speedhack.so ./your_game
```

### 命令行调速

```bash
# 查找 PID
pgrep -n 游戏进程名

# 调速
./speedctl <pid> 3.0    # 3 倍速
./speedctl <pid> 1.0    # 恢复正常
./speedctl <pid>        # 查询当前速度
```

## 安装桌面图标

```bash
make install
```

## 工作原理

`speedhack.so` 通过 `LD_PRELOAD` 在游戏启动时注入，劫持以下 libc 函数：

| 函数 | 作用 |
|------|------|
| `clock_gettime` | 单调时钟（SDL2、Unity、Godot、std::chrono） |
| `gettimeofday` | 墙钟（老引擎、Wine） |
| `nanosleep` / `usleep` | 帧率限制睡眠也同步缩短 |

游戏感知到的时间以 `speed` 倍率流逝，同时通过 Unix socket 接受运行时调速命令。调速时采用基准点推进算法，时间轴不会跳变。

**Snap/pressure-vessel 兼容**：优先使用 `SNAP_REAL_HOME`（`/home/用户名`）作为 socket 路径，该目录在容器内外共享，避免 `/run/user/N` 在容器内外是不同挂载点的问题。

## 已知限制

- 静态链接的游戏或直接使用 VDSO syscall 的进程不受影响（极少见）
- Wine 的 `GetTickCount` 使用共享内存而非 `clock_gettime`，部分老游戏的帧计时可能不受影响
- 反作弊系统（EAC、BattlEye 等）可能检测 `LD_PRELOAD`，仅用于单人游戏

## License

MIT
