/* Restrict candidate reads to runtime/current inputs and writes to its output. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <sched.h>
#include <seccomp.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifndef LANDLOCK_ACCESS_FS_TRUNCATE
#define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
#endif

static int allow(int fd, const char *name, __u64 access) {
    int parent = open(name, O_PATH | O_CLOEXEC);
    if (parent < 0) return errno == ENOENT ? 0 : -1;
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access, .parent_fd = parent};
    int result = syscall(__NR_landlock_add_rule, fd,
                         LANDLOCK_RULE_PATH_BENEATH, &rule, 0);
    close(parent);
    return result;
}

int main(int argc, char **argv) {
    if (argc < 7 || strcmp(argv[1], "--code") || strcmp(argv[3], "--data") ||
        strcmp(argv[5], "--output")) return 125;
    if (argc < 10 || strcmp(argv[7], "--")) return 125;
    int abi = syscall(__NR_landlock_create_ruleset, NULL, 0,
                      LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) return 125;
    __u64 read = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR |
        LANDLOCK_ACCESS_FS_EXECUTE;
    __u64 write = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG;
    /* ABI 1 has no TRUNCATE right; seccomp below closes all truncation bypasses. */
    if (abi >= 2) write |= LANDLOCK_ACCESS_FS_REFER;
    if (abi >= 3) write |= LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_ruleset_attr rules = {.handled_access_fs = read | write |
        LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_SOCK |
        LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK |
        LANDLOCK_ACCESS_FS_MAKE_SYM};
    int fd = syscall(__NR_landlock_create_ruleset, &rules, sizeof(rules), 0);
    if (fd < 0) return 125;
    const char *runtime[] = {"/usr", "/lib", "/lib64", "/bin", "/opt/venv", NULL};
    for (int i = 0; runtime[i]; ++i)
        if (allow(fd, runtime[i], read)) return 125;
    const char *devices[] = {"/dev/null", "/dev/urandom", "/dev/random", "/etc/ld.so.cache", NULL};
    for (int i = 0; devices[i]; ++i)
        if (allow(fd, devices[i], LANDLOCK_ACCESS_FS_READ_FILE)) return 125;
    /* Reference-runtime compatibility: only this process's RSS statistic. */
    int statm = open("/proc/self/statm", O_PATH | O_CLOEXEC);
    if (statm < 0) return 125;
    struct landlock_path_beneath_attr statm_rule = {
        .allowed_access = LANDLOCK_ACCESS_FS_READ_FILE, .parent_fd = statm};
    int statm_result = syscall(__NR_landlock_add_rule, fd,
                              LANDLOCK_RULE_PATH_BENEATH, &statm_rule, 0);
    close(statm);
    if (statm_result) return 125;
    if (allow(fd, argv[2], read) || allow(fd, argv[4], read) ||
        allow(fd, argv[6], read | write) ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(__NR_landlock_restrict_self, fd, 0)) return 125;
    close(fd);
    scmp_filter_ctx filter = seccomp_init(SCMP_ACT_ALLOW);
    if (!filter) return 125;
    const char *blocked[] = {"fork", "vfork", "socket", "ptrace", "process_vm_readv",
        "process_vm_writev", "kill", "tkill", "pidfd_send_signal", "rt_sigqueueinfo",
        "rt_tgsigqueueinfo", "bpf", "mount", "setns", "unshare", "setsid", "setpgid",
        "shmget", "shmat", "shmdt", "shmctl", "semget", "semop", "semtimedop",
        "semctl", "msgget", "msgsnd", "msgrcv", "msgctl", "io_uring_setup",
        "io_uring_register", "io_uring_enter", "add_key", "request_key", "keyctl",
        "mq_open", "mq_unlink", "mq_timedsend", "mq_timedreceive", "mq_notify",
        "mq_getsetattr", "chmod", "fchmod", "fchmodat", "fchmodat2", "chown",
        "fchown", "fchownat", "lchown", "utimensat", "utime", "utimes", "futimesat",
        "truncate", "ftruncate", "link", "linkat", "rename", "renameat", "renameat2", NULL};
    for (int i = 0; blocked[i]; ++i) {
        int call = seccomp_syscall_resolve_name(blocked[i]);
        if (call < 0 || seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), call, 0)) return 125;
    }
    /* openat2 hides its flags behind a pointer, so use the ordinary open fallback. */
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(openat2), 0) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(open), 1,
            SCMP_A1(SCMP_CMP_MASKED_EQ, O_ACCMODE | O_TRUNC, O_RDONLY | O_TRUNC)) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(openat), 1,
            SCMP_A2(SCMP_CMP_MASKED_EQ, O_ACCMODE | O_TRUNC, O_RDONLY | O_TRUNC)) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(open), 1,
            SCMP_A1(SCMP_CMP_MASKED_EQ, O_ACCMODE, O_ACCMODE)) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(openat), 1,
            SCMP_A2(SCMP_CMP_MASKED_EQ, O_ACCMODE, O_ACCMODE)) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(clone3), 0) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(clone), 1,
            SCMP_A0(SCMP_CMP_MASKED_EQ, CLONE_THREAD, 0)) ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(tgkill), 1,
            SCMP_A0(SCMP_CMP_NE, getpid())) || seccomp_load(filter)) return 125;
    seccomp_release(filter);
    execvp(argv[8], argv + 8);
    perror("HEFT candidate exec failed");
    return 125;
}
