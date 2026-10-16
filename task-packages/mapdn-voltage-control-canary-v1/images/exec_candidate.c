/* Landlock confines files; seccomp forbids networking, processes and shared IPC. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <linux/sched.h>
#include <seccomp.h>
#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Bookworm ships Linux 6.1 UAPI headers; negotiate the actual ABI below. */
#ifndef LANDLOCK_ACCESS_FS_TRUNCATE
#define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
#endif

static const __u64 fs_read = LANDLOCK_ACCESS_FS_EXECUTE |
    LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;

static const __u64 fs_all = LANDLOCK_ACCESS_FS_EXECUTE |
    LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_READ_FILE |
    LANDLOCK_ACCESS_FS_READ_DIR | LANDLOCK_ACCESS_FS_REMOVE_DIR |
    LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR |
    LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
    LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
    LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM |
    LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE;

static int add_path(int ruleset, const char *path, __u64 access, int optional) {
    int descriptor = open(path, O_PATH | O_CLOEXEC);
    if (descriptor < 0) return optional && errno == ENOENT ? 0 : -1;
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access, .parent_fd = descriptor
    };
    int status = syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH,
                         &rule, 0);
    close(descriptor);
    return status;
}

static int restrict_files(void) {
    int abi = syscall(SYS_landlock_create_ruleset, NULL, 0,
                      LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) {
        fprintf(stderr, "Landlock ABI >= 1 is required; refusing unsandboxed execution\n");
        return -1;
    }
    /* Compile-time CI switch, never controlled by the candidate environment. */
#ifdef DISTRIBUTION_TEST_MAX_ABI
#if DISTRIBUTION_TEST_MAX_ABI < 1
#error DISTRIBUTION_TEST_MAX_ABI must be positive
#endif
    if (abi > DISTRIBUTION_TEST_MAX_ABI) abi = DISTRIBUTION_TEST_MAX_ABI;
#endif
    __u64 handled = fs_all;
    if (abi < 3) handled &= ~LANDLOCK_ACCESS_FS_TRUNCATE;
    /* ABI 1 already forbids cross-directory rename/link, without REFER. */
    if (abi < 2) handled &= ~LANDLOCK_ACCESS_FS_REFER;
    struct landlock_ruleset_attr rules = {.handled_access_fs = handled};
    int descriptor = syscall(SYS_landlock_create_ruleset, &rules, sizeof(rules), 0);
    if (descriptor < 0) return -1;
    const char *runtime[] = {"/usr/local", "/usr/lib", "/usr/bin", "/lib", "/lib64",
                             "/bin", "/opt/mapdn", NULL};
    for (int i = 0; runtime[i]; ++i) {
        if (add_path(descriptor, runtime[i], fs_read, 1) < 0) goto failure;
    }
    if (add_path(descriptor, "/etc/ld.so.cache", LANDLOCK_ACCESS_FS_READ_FILE, 1) < 0)
        goto failure;
    /* cwd is one private actor directory. Never grant /tmp, /dev/shm or /proc. */
    if (add_path(descriptor, ".", handled, 0) < 0) goto failure;
    const char *source = getenv("DISTRIBUTION_READONLY_DIR");
    if (source && add_path(descriptor, source, fs_read, 0) < 0) goto failure;
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
        syscall(SYS_landlock_restrict_self, descriptor, 0) < 0) goto failure;
    close(descriptor);
    return abi;
failure:
    close(descriptor);
    return -1;
}

static int restrict_legacy_truncation(scmp_filter_ctx filter) {
    /* ABI 1/2 cannot confine truncation by path. Deny every truncation entry
       point, even inside the actor directory. Exclusive creation remains valid.
       Only the native architecture is in this filter; compat ABIs are killed. */
    const char *blocked[] = {"truncate", "truncate64", "ftruncate", "ftruncate64",
                             "creat", NULL};
    for (int i = 0; blocked[i]; ++i) {
        int number = seccomp_syscall_resolve_name(blocked[i]);
        if (number >= 0 &&
            seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), number, 0) < 0)
            return -1;
    }
    /* openat2 hides its flags behind a pointer, which seccomp cannot inspect. */
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(openat2), 0) < 0 ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(open), 1,
                         SCMP_CMP(1, SCMP_CMP_MASKED_EQ, O_TRUNC, O_TRUNC)) < 0 ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(openat), 1,
                         SCMP_CMP(2, SCMP_CMP_MASKED_EQ, O_TRUNC, O_TRUNC)) < 0)
        return -1;
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) return 125;
    /* setpriv has already dropped UID. Prevent orphan candidates on worker death. */
    pid_t supervisor = getppid();
    /* A native Docker entrypoint is legitimately PID 1. Keep the death signal
       and race check; rejecting that supervisor would reject every direct child. */
    if (prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 || getppid() != supervisor)
        return 125;
    int abi = restrict_files();
    if (abi < 0) {
        perror("distribution filesystem sandbox setup failed");
        return 125;
    }
    scmp_filter_ctx filter = seccomp_init(SCMP_ACT_ALLOW);
    if (!filter) return 125;
    if (seccomp_attr_set(filter, SCMP_FLTATR_ACT_BADARCH, SCMP_ACT_KILL_PROCESS) < 0 ||
        (abi < 3 && restrict_legacy_truncation(filter) < 0)) {
        seccomp_release(filter);
        return 125;
    }
    const char *blocked[] = {
        "fork", "vfork", "setsid", "setpgid", "unshare", "sched_setaffinity",
        "socket", "ptrace", "process_vm_readv", "process_vm_writev",
        "kill", "tkill", "tgkill", "pidfd_send_signal", "rt_sigqueueinfo",
        "rt_tgsigqueueinfo", "bpf", "mount", "setns",
        "shmget", "shmat", "shmctl", "shmdt", "msgget", "msgsnd", "msgrcv", "msgctl",
        "semget", "semctl", "semop", "semtimedop", "ipc",
        "mq_open", "mq_unlink", "mq_timedsend", "mq_timedreceive", "mq_notify", "mq_getsetattr",
        "keyctl", "add_key", "request_key", "io_uring_setup", "io_uring_enter", "io_uring_register",
        NULL
    };
    for (int i = 0; blocked[i]; ++i) {
        int syscall = seccomp_syscall_resolve_name(blocked[i]);
        if (syscall >= 0 && seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), syscall, 0) < 0) {
            seccomp_release(filter);
            return 125;
        }
    }
    /* glibc falls back to clone(2) when clone3(2) reports ENOSYS. */
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(clone3), 0) < 0 ||
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(clone), 1,
                         SCMP_CMP(0, SCMP_CMP_MASKED_EQ, CLONE_THREAD, 0)) < 0) {
        seccomp_release(filter);
        return 125;
    }
    if (seccomp_load(filter) < 0) {
        perror("RTE sandbox setup failed");
        seccomp_release(filter);
        return 125;
    }
    seccomp_release(filter);
    execvp(argv[1], argv + 1);
    perror("RTE solver exec failed");
    return 125;
}
