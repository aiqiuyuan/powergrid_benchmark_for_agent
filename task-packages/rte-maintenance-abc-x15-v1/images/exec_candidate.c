/* Permit worker threads while forbidding child processes and network access. */
#include <errno.h>
#include <linux/sched.h>
#include <seccomp.h>
#include <stdio.h>
#include <signal.h>
#include <sys/prctl.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) return 125;
    /* setpriv has already dropped UID. Prevent orphan candidates on worker death. */
    pid_t supervisor = getppid();
    if (supervisor == 1 || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 || getppid() != supervisor)
        return 125;
    scmp_filter_ctx filter = seccomp_init(SCMP_ACT_ALLOW);
    if (!filter) return 125;
    const char *blocked[] = {
        "fork", "vfork", "setsid", "setpgid", "unshare", "sched_setaffinity",
        "socket", "ptrace", "process_vm_readv", "process_vm_writev",
        "kill", "tkill", "tgkill", "pidfd_send_signal", "rt_sigqueueinfo",
        "rt_tgsigqueueinfo", "bpf", "mount", "setns", NULL
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
