/*
 * speedctl — 运行时调速控制工具
 *
 * 用法：
 *   speedctl <pid>          查询当前速度
 *   speedctl <pid> <speed>  设置速度（0.01–100.0）
 *
 * 示例：
 *   speedctl 12345 3.0    → 加速到 3 倍
 *   speedctl 12345 0.5    → 减速到 0.5 倍（慢动作）
 *   speedctl 12345 1.0    → 恢复正常
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr,
                "用法: %s <pid> [speed]\n"
                "  查询当前速度: %s <pid>\n"
                "  设置速度:     %s <pid> 3.0\n",
                argv[0], argv[0], argv[0]);
        return 1;
    }

    char path[108];
    const char *run_dir = getenv("SNAP_REAL_HOME");
    if (!run_dir || run_dir[0] == '\0') run_dir = getenv("XDG_RUNTIME_DIR");
    if (!run_dir || run_dir[0] == '\0') run_dir = getenv("HOME");
    if (!run_dir || run_dir[0] == '\0') run_dir = "/tmp";
    snprintf(path, sizeof(path), "%s/.speedhack_%s.sock", run_dir, argv[1]);

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }

    struct sockaddr_un sa;
    memset(&sa, 0, sizeof(sa));
    sa.sun_family = AF_UNIX;
    snprintf(sa.sun_path, sizeof(sa.sun_path), "%s", path);

    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        fprintf(stderr, "无法连接 %s: %s\n", path, strerror(errno));
        fprintf(stderr, "请确认游戏是否已用 speedhack.so 启动。\n");
        close(fd);
        return 1;
    }

    /* 发送命令 */
    char msg[64];
    int n;
    if (argc >= 3)
        n = snprintf(msg, sizeof(msg), "%s\n", argv[2]);
    else
        n = snprintf(msg, sizeof(msg), "?\n");
    if (write(fd, msg, n) < 0) { perror("write"); close(fd); return 1; }

    /* 读取回复 */
    char reply[128] = {0};
    int got = (int)read(fd, reply, sizeof(reply) - 1);
    if (got > 0)
        printf("%s", reply);

    close(fd);
    return 0;
}
