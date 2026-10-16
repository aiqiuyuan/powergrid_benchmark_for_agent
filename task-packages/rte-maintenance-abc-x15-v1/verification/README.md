# Portable verification

从仓库根目录运行：

```sh
python -m pip install numpy==2.2.6 scipy==1.15.3 ijson==3.4.0.post0
python -m unittest discover -s task-packages/rte-maintenance-abc-x15-v1/verification -v
```

测试只需要 Python 3.12 和上述依赖，不需要下载能源实例、安装私有实验框架、启动 Docker 或调用模型服务。临时目录中的微型实例采用官方输入 schema，实际执行 starter、候选子进程和固定版本官方 checker，并验证进程隔离、并发上限、结果排序、失败清理、完整面板入口、冻结与最终评测时限。准备测试使用 60 个微型合成实例，保留源码包原始锁文件。

数据切分和来源锁检查验证已提交的 60 例元数据；不替代真实数据字节校验。并发集成测试使用 `secure=False`。安全命令构造使用 mock；`sched_setaffinity` 的静态回归检查不代表 seccomp 已执行通过。目标服务器Linux／cgroup、完整X15资源和真实微型Docker／Harbor验收已有下述独立实测；正式12小时开发与5400秒／例最终结果仍待完成，不由portable测试替代。

## 实际Linux小例

GitHub CI另行编译实际`images/exec_candidate.c`，以root运行`probe_linux_sandbox.py`，验证降权、内存／进程额度、单CPU绑定、可读写各自文件、禁止替换output目录入口，以及扩核、fork、socket的EPERM。它使用微型输入，不下载正式数据；[已通过的运行](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38714329430)对应源码`3f10b4a9f944c2d3798ef430e13c7bc6ff4a2320`。这项检查不替代目标Docker／Harbor镜像、完整X15吞吐／内存与egress验收。

上面的CI链接保留为此前8GiB版本的历史证据。2026-10-16当前候选地址空间统一为16GiB、verifier256GiB，portable的23项检查已通过；当前源码的新GitHub CI待本轮发布触发并确认，不能借用旧CI宣称本轮源码已通过。

本轮服务器v5已通过16GiB真实Linux小例探针及完整X15资源门禁：无MemoryError／OOM、90条有效资源采样，8 AC／2 RE／5 TLE；`memory.peak`不可用，不把采样最大值当作内核真实峰值。v6经任务、数据、runtime与资源一致性来源核对复用v5凭据，并另行通过真实n0／n1微型生命周期、模型／工具、0／1反馈计数及可信网络检查。15个正式run已于16:10提交，最终研究结果尚待；详见[实验记录](../../../docs/experiments/rte-abc-x15-formal-20261015.md)与[中文完成说明](../../../docs/completion-rte-formal-launch-20261015.md)。复用不增加完整面板实测次数，微型数据也不构成原始X15成绩。
