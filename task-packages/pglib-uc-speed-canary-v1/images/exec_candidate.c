/* Julia needs threads; permit CLONE_THREAD but deny process creation and sockets. */
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

/* Bookworm headers can predate ABI 3; runtime availability is checked below. */
#ifndef LANDLOCK_ACCESS_FS_TRUNCATE
#define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
#endif

static int restrict_writes(const char *output) {
    int abi = syscall(__NR_landlock_create_ruleset, NULL, 0,
                      LANDLOCK_CREATE_RULESET_VERSION);
    /* ABI 3 closes O_TRUNC as well as ordinary write/create/rename channels. */
    if (abi < 3) return -1;
    __u64 access = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR |
        LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
        LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM |
        LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_ruleset_attr rules = {.handled_access_fs = access};
    int fd = syscall(__NR_landlock_create_ruleset, &rules, sizeof(rules), 0);
    if (fd < 0) return -1;
    struct landlock_path_beneath_attr path = {
        .allowed_access = access,
        .parent_fd = open(output, O_PATH | O_DIRECTORY | O_CLOEXEC)
    };
    int result = -1;
    if (path.parent_fd >= 0 &&
        syscall(__NR_landlock_add_rule, fd, LANDLOCK_RULE_PATH_BENEATH, &path, 0) == 0 &&
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0 &&
        syscall(__NR_landlock_restrict_self, fd, 0) == 0) result = 0;
    if (path.parent_fd >= 0) close(path.parent_fd);
    close(fd);
    return result;
}

int main(int argc, char **argv) {
    if (argc < 5 || strcmp(argv[1], "--write-root") || strcmp(argv[3], "--")) return 125;
    if (restrict_writes(argv[2]) != 0) return 125;
    scmp_filter_ctx filter = seccomp_init(SCMP_ACT_ALLOW);
    if (!filter) return 125;
    const char *blocked[] = {
        "fork", "vfork", "setsid", "setpgid", "unshare", "socket",
        "ptrace", "process_vm_readv", "process_vm_writev", "kill", "tkill",
        "pidfd_send_signal", "rt_sigqueueinfo", "rt_tgsigqueueinfo", "bpf",
        "mount", "setns", "shmget", "shmat", "shmdt", "shmctl", "semget",
        "semop", "semtimedop", "semctl", "msgget", "msgsnd", "msgrcv", "msgctl",
        "io_uring_setup", "io_uring_register", "io_uring_enter", NULL
    };
    for (int i = 0; blocked[i]; ++i) {
        int call = seccomp_syscall_resolve_name(blocked[i]);
        if (call >= 0 && seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), call, 0) < 0)
            goto fail;
    }
    /* glibc falls back to clone only on ENOSYS, not on EPERM. */
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(clone3), 0) < 0)
        goto fail;
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(clone), 1,
        SCMP_A0(SCMP_CMP_MASKED_EQ, CLONE_THREAD, 0)) < 0) goto fail;
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(tgkill), 1,
        SCMP_A0(SCMP_CMP_NE, getpid())) < 0) goto fail;
    if (seccomp_load(filter) < 0) goto fail;
    seccomp_release(filter);
    execvp(argv[4], argv + 4);
    perror("UC solver exec failed");
    return 125;
fail:
    seccomp_release(filter);
    return 125;
}
