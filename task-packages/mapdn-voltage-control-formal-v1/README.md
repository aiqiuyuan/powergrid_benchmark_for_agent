# MAPDN 正式固定案例包 v1

本包在已完成强参照资格实验后，固定 33 节点网络的 **2012-02-03、480 个三分钟间隔**。开发反馈和独立终评使用同一完整案例，研究对象是反馈预算对固定案例算法开发的影响，不检验跨日泛化。历史 canary 与资格实验源码保持冻结。

同信息 starter 是已验证的局部松弛 droop：先将 `20*(1-v)` 截至 `[-1,1]`，再截至动作界 `[-0.8,0.8]`，与本设备当前观测得到的上一动作按 `0.9/0.1` 混合。该日资格实验的电压合规率为 100%，真实有功损耗为 1.8352510375191953 MWh。原版迭代 droop 移植有额外的时刻内物理测量权限，集中式 AC OPF 有更多网络信息，均单列参照。

可信准备使用已经锁定的选择池，不重新选日，也不重新估计容量：

```sh
python3.12 freeze_case.py --pool /trusted/mapdn33-final --output /trusted/mapdn33-formal-case
python3.12 prepare_stage.py --case /trusted/mapdn33-formal-case --wheels /trusted/linux-cp312-wheels
docker build -t mapdn-formal-runtime:1 images
```

`--pool` 必须匹配 `support/mapdn_contract.py` 固定的 pool SHA-256；仅复制已校验的该日轨迹和模型，manifest 内容也逐字节验证。容量来自完整原始 PV CSV 每列最大值的 1.2 倍，不从目标日重估。`prepare.py` 保留固定 HF 快照的成员下载工具；如需从源重新建立选择池，应使用已冻结的选择工具与协议，所得 pool SHA 必须一致，不能绕过锁检查。四个完整 ZIP 成员验证 CRC32 与 SHA-256，不声称核验未完整下载的 3.7 GB archive SHA。

暂存只将三个私有 case 文件放入 `tests/data/`，数值 wheel 放入 `images/wheels/`；这些均忽略 Git。开发镜像只复制 `environment/app/`，包含公共 starter 与合成接口检查，不包含轨迹、模型、评分代码、选择池或参考成绩文件。可信支持代码、验证探针与 case 只进入独立 verifier。

六个 actor 使用不同 UID、独立进程和工作目录；JSON 仅携带合法本地观测。Landlock ABI≥1、seccomp、无网络及无 IPC 均为必需条件；缺少条件时拒绝执行。ABI1/2 还禁止截断、`creat`、`O_TRUNC` 与 `openat2`，自己的文件可独占新建或追加。不同 actor 不能共享 `/tmp`、`/dev/shm`、`/proc` 或通信。

本地真实后端可用 `support.runner.evaluate(candidate, case, secure=False)` 检查数值对齐；该结果明确标记未隔离，不能替代 Linux 验收。上线须在正式 runtime 内运行：

```sh
python3.12 verification/validate_runtime.py --case /trusted/mapdn33-formal-case --candidate environment/app/submission/controller.py --output /trusted/mapdn-formal-acceptance.json
```

该验收独立回放、核对完整 960 次潮流、强 starter 数值、损耗平衡，以及文件/网络/IPC 和超内存失败探针。部署方还需冻结真实镜像 digest、受计数反馈入口、开发截止与独立终评收据；`formal-lock.json` 不把尚未进行的集群验收写成已通过。
