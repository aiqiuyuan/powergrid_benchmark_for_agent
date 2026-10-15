# MAPDN 真实后端流程 canary

本包将锁定 MAPDN 的 33 节点模型和真实 P/Q 负荷、PV 数据接入因果 Pandapower 运行器，提供完整 480 步自然日、局部进程控制、实际损耗交叉检查和原生评分入口。用途为 n=0/1 流程验证，`release_ready=false`；不能替代后续强基线与难例认证。

可信准备步骤（禁止向开发镜像拷贝 raw 或 case）：

```sh
python prepare.py --output /trusted/mapdn33-raw
python freeze_case.py --raw /trusted/mapdn33-raw --output /trusted/mapdn33-case
```

prepare 仅下载固定 HF 快照中四个完整的 33 节点 ZIP 成员，约 297 MB 压缩数据，验证 ZIP CRC32 并记录成员 SHA-256；不会声称验证未完整下载的 3.7 GB archive SHA-256。freeze 校验来源，冻结最早完整对齐自然日、不加噪声、初始零动作；额定容量为原始完整 PV CSV 每列最大值的 1.2 倍。source 成员、时标、文件哈希和 solver 设置全部记录在可信 manifest。

`images/requirements.txt` 锁定 Python 3.12 的数值依赖。下载该清单的 Linux amd64 CPython 3.12 离线 wheels（包含 manylinux_2_28 标签）后，使用可重复暂存工具校验 case、生成 wheel SHA-256 锁并同步 worker：

```sh
python prepare_stage.py --case /trusted/mapdn33-case --wheels /trusted/linux-cp312-wheels
docker build -t mapdn-canary-runtime:1 images
```

暂存工具将 `support/*.py` 拷贝到 `tests/support/`，将可信 case 的三个文件拷贝到 `tests/data/`。这些路径均为可信构建暂存，不向开发容器挂载；数据不提交 Git。environment/Dockerfile 只拷贝 app 中的公开 starter 和合成接口检查，并预装 Gateway 所需 procps。tests/Dockerfile 运行时把 `/tests` 设为 root-only，并使用 runtime 中公开可执行的 actor bridge、不同 UID、资源限制、Landlock ABI≥3 和 seccomp。Landlock 仅允许读取 Python 运行时与本 actor 源码、读写自身工作目录；不开放共享 `/tmp`、`/dev/shm` 或 `/proc`。seccomp 禁止网络、派生进程和 System V/POSIX IPC。子环境不继承私有环境变量。

本地数值校准允许直接调用 `support.runner.evaluate(candidate, case_dir, secure=False)`；它明确输出 `secure_execution=false`，不算隔离验收。集群评分 `tests/score.py` 始终 `secure=True`，缺少 Linux root、seccomp 工具或公开 worker 会失败。根目录被保护后，受计数 feedback 只公开 aggregate；完整逐步记录只保留在可信进程返回值中。

上线前必须在构建的 Linux runtime 中执行 `verification/probe_sandbox.py`，验证私有 cwd 的正例和共享文件、其他 actor、网络、System V IPC 的负例。要求 Landlock ABI≥3，低版本或不支持时拒绝执行，不能回落为普通不同 UID 子进程。Mac 数值验证不等于 Linux 隔离验收。

运行器的 `pp.runpp` 参数固定为 Newton-Raphson、不启用 Numba、容差 1e-9 MVA、最多 30 次迭代。source CSV 的未排序列顺序与上游一致，网络索引写入 manifest。此适配修复上游混时标、239 次 step 与任意候选 RNG 改变外生噪声的问题，不复用论文旧数值。
