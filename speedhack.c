/*
 * speedhack.so — LD_PRELOAD game speed multiplier
 *
 * 劫持的函数：
 *   clock_gettime  (CLOCK_MONOTONIC / CLOCK_REALTIME 系列)
 *   gettimeofday
 *   nanosleep / usleep   (帧率锁也能被加速)
 *
 * 使用方式：
 *   SPEEDHACK_FACTOR=3.0 LD_PRELOAD=./speedhack.so ./game
 *
 * 运行时调速（另开终端）：
 *   ./speedctl <pid> 2.0
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <time.h>
#include <sys/time.h>
#include <sys/prctl.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>
#include <errno.h>

/* ------------------------------------------------------------------ */
/*  全局状态                                                             */
/* ------------------------------------------------------------------ */

static double           g_speed          = 1.0;
static int              g_sleep_hack     = 0;   /* 默认关：不缩短 sleep，避免 vsync 卡顿 */
static int64_t          g_real_mono_base = 0;   /* 上次调速时的真实单调时钟 (ns) */
static int64_t          g_fake_mono_base = 0;   /* 对应的虚假单调时钟 (ns)      */
static int64_t          g_real_wall_base = 0;   /* 上次调速时的真实墙钟 (us)    */
static int64_t          g_fake_wall_base = 0;   /* 对应的虚假墙钟 (us)          */
static pthread_rwlock_t g_lock           = PTHREAD_RWLOCK_INITIALIZER;
static char             g_sock_path[108] = {0};

/* 原始函数指针 */
static int (*real_clock_gettime)(clockid_t, struct timespec *);
static int (*real_gettimeofday)(struct timeval *, void *);
static int (*real_nanosleep)(const struct timespec *, struct timespec *);
static int (*real_usleep)(useconds_t);

/* ------------------------------------------------------------------ */
/*  音频线程检测（TLS 缓存，每线程只做一次 prctl 系统调用）              */
/* ------------------------------------------------------------------ */

/* -1=未检测  0=普通线程  1=音频线程 */
static __thread int tls_is_audio = -1;

static int is_audio_thread(void)
{
    if (tls_is_audio >= 0)
        return tls_is_audio;

    char name[16] = {0};
    prctl(PR_GET_NAME, name, 0, 0, 0);

    /* Wine/Proton 音频线程名关键字（winealsa / winepulse / pipewire / WASAPI…） */
    static const char * const AUDIO_KEYS[] = {
        "audio", "Audio", "sound", "Sound",
        "wasapi", "WASAPI", "mmdevapi",
        "winealsa", "winepulse", "wineoss",
        "pulse", "pipewire", "alsa",
        "mmix", "period",           /* alsa period 线程 */
        NULL
    };
    tls_is_audio = 0;
    for (int i = 0; AUDIO_KEYS[i]; i++) {
        if (strstr(name, AUDIO_KEYS[i])) {
            tls_is_audio = 1;
            break;
        }
    }
    return tls_is_audio;
}

/* ------------------------------------------------------------------ */
/*  内部辅助                                                             */
/* ------------------------------------------------------------------ */

static int64_t read_real_mono_ns(void)
{
    struct timespec ts;
    real_clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static int64_t read_real_wall_us(void)
{
    struct timeval tv;
    real_gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000000LL + tv.tv_usec;
}

/* 调速时推进基准点，必须在持有写锁的情况下调用 */
static void commit_speed_locked(double new_speed)
{
    int64_t rn = read_real_mono_ns();
    int64_t rw = read_real_wall_us();
    g_fake_mono_base += (int64_t)((rn - g_real_mono_base) * g_speed);
    g_fake_wall_base += (int64_t)((rw - g_real_wall_base) * g_speed);
    g_real_mono_base  = rn;
    g_real_wall_base  = rw;
    g_speed           = new_speed;
}

/* ------------------------------------------------------------------ */
/*  控制线程：监听 Unix socket，接受调速命令                              */
/* ------------------------------------------------------------------ */

static void *ctrl_thread(void *arg)
{
    (void)arg;

    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv < 0) return NULL;

    struct sockaddr_un sa;
    memset(&sa, 0, sizeof(sa));
    sa.sun_family = AF_UNIX;
    snprintf(sa.sun_path, sizeof(sa.sun_path), "%s", g_sock_path);
    unlink(g_sock_path);

    if (bind(srv, (struct sockaddr *)&sa, sizeof(sa)) < 0 ||
        listen(srv, 4) < 0) {
        close(srv);
        return NULL;
    }

    fprintf(stderr, "[speedhack] pid=%d  socket=%s\n", (int)getpid(), g_sock_path);

    char buf[64];
    for (;;) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;

        int n = (int)read(cl, buf, sizeof(buf) - 1);
        if (n > 0) {
            buf[n] = '\0';
            /* 去掉换行 */
            char *nl = strchr(buf, '\n');
            if (nl) *nl = '\0';

            if (buf[0] == '?' || buf[0] == '\0') {
                pthread_rwlock_rdlock(&g_lock);
                dprintf(cl, "speed=%.3f sleep=%d\n", g_speed, g_sleep_hack);
                pthread_rwlock_unlock(&g_lock);
            } else if (strncmp(buf, "sleep=", 6) == 0) {
                int v = atoi(buf + 6);
                pthread_rwlock_wrlock(&g_lock);
                g_sleep_hack = v ? 1 : 0;
                pthread_rwlock_unlock(&g_lock);
                dprintf(cl, "OK sleep=%d\n", g_sleep_hack);
                fprintf(stderr, "[speedhack] sleep_hack -> %d\n", g_sleep_hack);
            } else {
                double s = atof(buf);
                if (s >= 0.01 && s <= 100.0) {
                    pthread_rwlock_wrlock(&g_lock);
                    commit_speed_locked(s);
                    pthread_rwlock_unlock(&g_lock);
                    dprintf(cl, "OK speed=%.3f\n", s);
                    fprintf(stderr, "[speedhack] speed -> %.3fx\n", s);
                } else {
                    dprintf(cl, "ERR 速度范围 0.01-100.0\n");
                }
            }
        }
        close(cl);
    }
    return NULL;
}

/* ------------------------------------------------------------------ */
/*  库构造函数（在 main 之前运行）                                        */
/* ------------------------------------------------------------------ */

__attribute__((constructor))
static void speedhack_init(void)
{
    real_clock_gettime = dlsym(RTLD_NEXT, "clock_gettime");
    real_gettimeofday  = dlsym(RTLD_NEXT, "gettimeofday");
    real_nanosleep     = dlsym(RTLD_NEXT, "nanosleep");
    real_usleep        = dlsym(RTLD_NEXT, "usleep");

    g_real_mono_base = read_real_mono_ns();
    g_fake_mono_base = g_real_mono_base;
    g_real_wall_base = read_real_wall_us();
    g_fake_wall_base = g_real_wall_base;

    const char *env = getenv("SPEEDHACK_FACTOR");
    if (env) {
        double s = atof(env);
        if (s >= 0.01 && s <= 100.0) {
            g_speed = s;
            fprintf(stderr, "[speedhack] 初始速度 %.3fx\n", g_speed);
        }
    }
    const char *env_sleep = getenv("SPEEDHACK_SLEEP");
    if (env_sleep && env_sleep[0] == '1') {
        g_sleep_hack = 1;
        fprintf(stderr, "[speedhack] sleep_hack 已启用\n");
    }

    /*
     * 路径优先级：
     *   SNAP_REAL_HOME  — Snap 容器内设置的真实 HOME，容器内外都可访问
     *   XDG_RUNTIME_DIR — 普通情况
     *   HOME            — 兜底
     *   /tmp            — 最后手段
     * Snap + pressure-vessel 双重隔离时，容器内的 /run/user/N 和宿主机不同，
     * 但 /home/user 是共享挂载，所以 SNAP_REAL_HOME 是最可靠的选择。
     */
    const char *run_dir = getenv("SNAP_REAL_HOME");
    if (!run_dir || run_dir[0] == '\0') run_dir = getenv("XDG_RUNTIME_DIR");
    if (!run_dir || run_dir[0] == '\0') run_dir = getenv("HOME");
    if (!run_dir || run_dir[0] == '\0') run_dir = "/tmp";
    snprintf(g_sock_path, sizeof(g_sock_path),
             "%s/.speedhack_%d.sock", run_dir, (int)getpid());

    pthread_t tid;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&tid, &attr, ctrl_thread, NULL);
    pthread_attr_destroy(&attr);
}

__attribute__((destructor))
static void speedhack_fini(void)
{
    if (g_sock_path[0])
        unlink(g_sock_path);
}

/* ------------------------------------------------------------------ */
/*  劫持：clock_gettime                                                  */
/* ------------------------------------------------------------------ */

int clock_gettime(clockid_t clk, struct timespec *ts)
{
    /* 音频线程始终返回真实时钟，避免 PipeWire/ALSA 缓冲区溢出 */
    if (is_audio_thread())
        return real_clock_gettime(clk, ts);

    /* 单调时钟族 */
    if (clk == CLOCK_MONOTONIC     ||
        clk == CLOCK_MONOTONIC_COARSE ||
        clk == CLOCK_MONOTONIC_RAW ||
        clk == CLOCK_BOOTTIME) {
        int64_t rn = read_real_mono_ns();
        pthread_rwlock_rdlock(&g_lock);
        int64_t fn = g_fake_mono_base +
                     (int64_t)((rn - g_real_mono_base) * g_speed);
        pthread_rwlock_unlock(&g_lock);
        ts->tv_sec  =  fn / 1000000000LL;
        ts->tv_nsec =  fn % 1000000000LL;
        if (ts->tv_nsec < 0) { ts->tv_sec--; ts->tv_nsec += 1000000000LL; }
        return 0;
    }

    /* 墙钟族（部分游戏用来算 delta）*/
    if (clk == CLOCK_REALTIME || clk == CLOCK_REALTIME_COARSE) {
        int64_t rw = read_real_wall_us();
        pthread_rwlock_rdlock(&g_lock);
        int64_t fw = g_fake_wall_base +
                     (int64_t)((rw - g_real_wall_base) * g_speed);
        pthread_rwlock_unlock(&g_lock);
        ts->tv_sec  =  fw / 1000000LL;
        ts->tv_nsec = (fw % 1000000LL) * 1000LL;
        if (ts->tv_nsec < 0) { ts->tv_sec--; ts->tv_nsec += 1000000000LL; }
        return 0;
    }

    return real_clock_gettime(clk, ts);
}

/* ------------------------------------------------------------------ */
/*  劫持：gettimeofday                                                   */
/* ------------------------------------------------------------------ */

int gettimeofday(struct timeval *tv, void *tz)
{
    if (is_audio_thread())
        return real_gettimeofday(tv, tz);
    {
        int64_t rw = read_real_wall_us();
        pthread_rwlock_rdlock(&g_lock);
        int64_t fw = g_fake_wall_base +
                     (int64_t)((rw - g_real_wall_base) * g_speed);
        pthread_rwlock_unlock(&g_lock);
        tv->tv_sec  =  fw / 1000000LL;
        tv->tv_usec =  fw % 1000000LL;
        if (tv->tv_usec < 0) { tv->tv_sec--; tv->tv_usec += 1000000LL; }
    }
    if (tz) real_gettimeofday(NULL, tz);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  劫持：nanosleep                                                      */
/* ------------------------------------------------------------------ */

int nanosleep(const struct timespec *req, struct timespec *rem)
{
    pthread_rwlock_rdlock(&g_lock);
    double speed      = g_speed;
    int    sleep_hack = g_sleep_hack;
    pthread_rwlock_unlock(&g_lock);

    if (!sleep_hack || speed < 1.0 + 1e-9 || is_audio_thread())
        return real_nanosleep(req, rem);

    int64_t ns     = (int64_t)req->tv_sec * 1000000000LL + req->tv_nsec;
    int64_t scaled = (int64_t)(ns / speed);
    if (scaled < 0) scaled = 0;

    struct timespec scaled_req = {
        .tv_sec  = scaled / 1000000000LL,
        .tv_nsec = scaled % 1000000000LL,
    };
    int r = real_nanosleep(&scaled_req, rem);
    /* 若被信号中断，把剩余时间按比例放大还给调用方 */
    if (r != 0 && rem) {
        int64_t rem_ns     = (int64_t)rem->tv_sec * 1000000000LL + rem->tv_nsec;
        int64_t rem_scaled = (int64_t)(rem_ns * speed);
        rem->tv_sec  = rem_scaled / 1000000000LL;
        rem->tv_nsec = rem_scaled % 1000000000LL;
    }
    return r;
}

/* ------------------------------------------------------------------ */
/*  劫持：usleep                                                         */
/* ------------------------------------------------------------------ */

int usleep(useconds_t usec)
{
    pthread_rwlock_rdlock(&g_lock);
    double speed      = g_speed;
    int    sleep_hack = g_sleep_hack;
    pthread_rwlock_unlock(&g_lock);

    if (!sleep_hack || speed < 1.0 + 1e-9 || is_audio_thread())
        return real_usleep(usec);

    useconds_t scaled = (useconds_t)(usec / speed);
    return real_usleep(scaled);
}
