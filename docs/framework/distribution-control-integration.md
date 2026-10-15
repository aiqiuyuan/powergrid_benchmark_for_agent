# MAPDN 与 PowerGym：基础适配与原生接入

2026-10-15 新增两个待校准扩展家族：[MAPDN task card](../task-cards/mapdn-voltage-control.md)、[PowerGym task card](../task-cards/powergym-volt-var-control.md)。它们采用[决定0005](../decisions/0005-fixed-case-evolution-first.md)的完整固定 case、严格计 n 和截止冻结政策。原五任务的 75-run 设计保持原范围；本次没有启动新实验。

**已实现的是接入基础，尚未交付可运行完整目标 case 的原生 task。** 源码准备、数据摘要检查、动作合法性、物理指标计算、确定性负荷打包、starter 与接口小样例可以执行。原生 task 骨架用 `.template` 标记；没有填入未经校准的资源、目标 case 或 reward 参数，也没有以假分数替代缺失的私有仿真评分器。

## 1. 文件与责任

| 内容 | 仓库入口 | 完成范围 |
|---|---|---|
| 任务、信息、动作与评分合同 | 两张 task card；`manifests/task-adapters/` 对应 JSON | 可审阅，`design/pending/false` |
| 固定上游来源与数据摘要 | [distribution-sources.json](../../configs/distribution-sources.json) | commit、PowerGym 负荷源 SHA-256、MAPDN 发布 LFS 元数据 |
| 可信源码准备 | `distribution.preparation`；CLI `distribution-prepare` | 拒绝脏源码、错 commit、符号链接、复用目的目录；每 worker 独立副本和摘要回执 |
| 物理量和合同检查 | `distribution.common`、`.mapdn`、`.powergym` | 有限数值、动作 shape/边界、无功能力、SOC 终态、实际损耗能量积分、电压合规与完整性 |
| PowerGym 负荷来源 | `distribution.profiles` | 显式有序文件打包及来源行映射；不推造原始日期 |
| 公开开发材料 | [task-packages/](../../task-packages/README.md) | 无目标数据和完整 checker 的 starter、人工合成输入、接口自检 |
| 原生框架接入骨架 | 同上两任务目录 | task.toml、两侧镜像、私有评分入口和参考入口模板；不是已验收运行包 |

核心包仍不依赖 Pandapower、Gym、OpenDSS 或 PyTorch。源码版本锁与仿真依赖锁是两件事；上游 requirements 仅作兼容参考，不宣称在本机 Python 3.12 上已复现老环境。MAPDN 与 PowerGym 使用各自镜像，不强行放进同一个 Python 环境。

## 2. 可立即执行的准备与小样例

安装方式见 README。以下命令从本仓库根目录运行；源码克隆只用于**可信评测准备侧**，不能直接作为开发镜像内容。

```sh
git clone https://github.com/Future-Power-Networks/MAPDN.git /trusted/sources/mapdn
git -C /trusted/sources/mapdn checkout 6895f1f0630b112745a3f681d7685d454407f9cb
powergrid-bench distribution-prepare configs/distribution-sources.json mapdn-voltage-control \
  --source /trusted/sources/mapdn --destination /trusted/workers/mapdn-001

git clone https://github.com/siemens/powergym.git /trusted/sources/powergym
git -C /trusted/sources/powergym checkout c9fc6d8357308a1f2bd2389474b56089c2a6bd78
powergrid-bench distribution-prepare configs/distribution-sources.json powergym-volt-var-control \
  --source /trusted/sources/powergym --destination /trusted/workers/powergym-001

python task-packages/mapdn-voltage-control/environment/app/support/check_interface.py
python task-packages/powergym-volt-var-control/environment/app/support/check_interface.py
```

`source-receipt.json`记录每个已跟踪文件的 SHA-256。准备时不执行上游代码、不下载大型数据、不解压 pickle、不进行潮流；目标目录不得重复使用。每个 PowerGym worker 同时需要独立进程和独立文件目录，避免 DSS 单例及会改写的 profile、scale、DSS 文件相互污染。副本不提供恶意代码隔离。

已有 MAPDN 压缩包可在准备时追加 `--archive voltage_control_data.zip=/trusted/data/voltage_control_data.zip`；传统基线包同理。工具流式核对**完整**字节数和 SHA-256，错误即拒绝，尚未提供解压或模型迁移。约 6 GB 的两份包未在本轮下载，元数据匹配不代表模型已可加载。保留上游许可与数据提供方归属，正式发布前分别核对其再分发条件。

接口自检只运行所附人工合成观测并输出动作，不调用完整目标评分，不消耗过程 n，也不证明算法有效或隔离有效。开发镜像只应复制 `environment/app` 中获准内容；不要复制本仓库、完整上游环境、可信准备目录或评分文件。

## 3. 控制器和基础 API

两份 standalone starter 均采用 `Controller(metadata).act(observation)`，返回动作向量，记忆放在实例内。新 episode/actor 创建新实例。依赖声明仅锁定 starter 的标准库范围，未来增加训练或权重时必须重做完整依赖锁及来源记录。

MAPDN 的实例只对应获准 actor；starter 读取 `pv_voltage_pu`，输出局部 PV 的归一化无功动作。可信侧先调用 `mapdn.validate_actions`，再调用 `mapdn.reactive_power` 生成 Q。所有输入功率单位一致，禁止越界后静默 clip。`project_actor_observations`只做结构投影，不能识别被重命名的全局数据；还需独立执行、IPC、文件和网络权限验收，才能主张局部信息实验。

PowerGym 的动作顺序是电容器、调压器、电池。`validate_actions`区分严格整数档位与连续电池；`idle_action`保留当前电容器和分接头，离散电池默认索引16，连续电池0。starter 当前采用 hold；它是接口和基线起点，不是搜索或 PPO/SAC 复现。

`common.voltage_metrics`分别报告全测点均合规的时间步比例、测点合规比例、最大和时间积分越界，并要求完整声明的 horizon 与收敛状态。`integrate_active_loss`显式区分 kW/MW 与 kWh/MWh；调用方还须确定测量含哪些线路、变压器及其他有损元件。函数不把 reward、无功代理或损耗比换名成真实网损。基础统计不定义主榜目标、失败分数、reward 映射或比较优先级。

PowerGym `profiles.pack_profiles`要求调用者显式声明源文件顺序，保留上游按 load/episode 取段的行为与来源映射。不能把打包后的 profile 编号当真实日期；若修正打包或电池物理模型，使用新的适配 release，不称原论文精确复现。

## 4. 原生接入和严格 n

[任务骨架说明](../../task-packages/README.md)列出可复用文件和必须填入的值。完整目标仿真、目标输入和评分程序只进入可信 verifier 镜像，开发镜像仅含获准材料。私有评分程序须固定路径和实际 SHA-256，接受冻结 artifacts，独立构建环境并执行控制器；不得接受候选自报的 reward 或 metrics。缺少评分器时模板直接失败，不生成成功结果。

仍由现有 eval-in-loop 管理反馈与计数：n=0 用 terminal；正 n 用 eval-budget；完整目标过程评分每次受理消耗 n。没有免费的 public-selection；截止直接冻结 `/app/submission` 最终文件，同 case 终验不回流开发、不占过程 n。仿真内部搜索可按声明预算运行，但不能向开发 agent 暴露未计数的完整目标分数或轨迹。

公开 GitHub 模板、路径、hash 和规则不能形成保密性。实际须检查开发镜像、挂载、共享日志、原始数据可重取路径、搜索和直连权限，包含“公开16条profile可枚举”和“完整输入可重写目标”的旁路。只有字段白名单或 separate verifier 不足以证明严格 n。

## 5. 进入完整运行前的剩余工作

| 验收项 | MAPDN | PowerGym |
|---|---|---|
| 环境 | 下载并验完整数据，验证 pickle 与 Pandapower 兼容；锁镜像和全部依赖 | 验证旧 DSS/Gym 环境或披露现代迁移；锁二进制和全部依赖 |
| 物理与时间 | 修复动作限幅、负荷更新后重解与初始化；冻结完整步数和已实现噪声 | 核 Converged、reset/step 时间、tap、battery P/Q 与能量账本 |
| 目标 case | 33节点可作 smoke，141/322依据基线和运行成本选难例，不能仅按节点数 | 34/123同条件运行，按电压/损耗/操作/能量成本选例，不能仅按规模 |
| 参考方法 | 同信息 droop/规则；集中 OPF 另列；新环境重跑 | hold、SOC规则、搜索；DSS是部分设备参照；RL需自备可复现代码 |
| 评分 | 完整PF有效性、电压合规与真实全网损耗；冻结目标及reward | 完整收敛、设备操作、实际kWh与终态SOC；native与energy-neutral分版 |
| 资源与隔离 | actor隔离、每步/episode预算、进程失败与目标评分访问验收 | 单例进程+目录隔离、同能力动作与仿真预算、SOC和评分访问验收 |
| 框架 | 两题均须完成原生静态/动态检查、冻结重放、n=0/n=1真实canary和成本记录 | 同左 |

这些是有明确输入和验收结果的后续实测工作。本轮没有进行完整 PF rollout、RL 训练、Docker/Harbor 或集群实验；`release_ready=false` 保持不变。
