# RTE 原生算法适配与真实题目验收

本轮新增的 [RTEAdapter](../../src/powergrid_bench/rte.py) 将完整算法快照、原生求解接口、独立校验和统一生命周期连接起来。适配器调用候选算法生成排程，再由固定版本的独立 RTE checker 检查约束和目标值。候选算法提供的自报分数不进入选择和排行。

这份记录区分真实 RTE 数据上的本地集成校准与实际 Harbor / Docker 端到端验收。**截至 2026-10-15，RTE 真实模型／Harbor n=0、n=1 canary 已全部通过。** 当前范围见[实际集群完成说明](../completion-step3-cluster-20261015.md)、[脱敏机器证据](../evidence/harbor-cluster-acceptance-20261015.json)与[Harbor 实验验收说明](harbor-live-acceptance.md)。这不是完整 RTE release、五任务认证或 benchmark 生产认证。

## 1. 已实现的提交与执行接口

候选提交是完整算法包，包括 `candidate.json`、`solver.py`、依赖锁文件和所需源码。本原生适配要求 `candidate.json.entrypoint` 严格声明为 `["python3", "solver.py", "--instance", "{input}", "--output", "{output}"]`。声明不同入口会在受理前拒绝，不能校验一个入口却执行另一个。控制器固定 Python 运行时，并注入锁定面板的时限与种子：

```text
python -E -s solver.py --instance instance.json --output schedule.txt \
  --time-limit <每个实例的显式时限> --seed <显式种子>
```

每个实例均在新工作目录运行。输入来自控制器选定的已锁定数据文件；执行前核对实例哈希，输入暂存后设为只读。候选源码来自不可变快照，执行后再次检查快照哈希。`-E -s` 忽略外部 Python 环境和 user site，同时保留冻结算法包内辅助模块的导入。独立 checker 在候选进程结束后读取有界、普通文件格式的排程，检查可行性与原始目标值。静态历史排程不能替代重新执行算法。

`RTEAdapter.evaluate(...)` 返回以下可信记录：

| 字段 | 含义 |
|---|---|
| `status` | `succeeded`、`candidate_error`、`timeout` 或 `infrastructure_error` |
| `feasible` | 所有实例是否通过独立约束检查 |
| `score` / `raw_objective` | 可行结果的平均原始目标值，按 `lower` 选择；失败结果不参与可行候选选择 |
| `candidate_sha256` | 完整算法快照标识 |
| `panel_sha256` | 数据面板文件标识 |
| `checker_sha256` | 原始 checker 标识 |
| `checker_adapter_sha256` / `source_lock_sha256` | 外部严格输出校验适配与来源锁标识 |
| `cases` | 控制器保留的逐例约束、排程哈希与进程证据 |

原始官方积分依赖参赛方法集合、实例排名和并列处理。本适配器的平均原始目标值是集成验收的选择指标；它不等于原始比赛积分，也不能直接插入历史排行榜。

## 2. 四个角色与校准数据

验收使用四个互不重叠的实例角色：

| 角色 | 实例 | 可见性与用途 |
|---|---|---|
| development | `A_07` | 开发阶段公开输入 |
| public-selection | `A_09` | 公开选择最佳候选，不消耗 protected feedback 次数 |
| protected-feedback | `A_08` | 通过 broker 的固定反馈接口调用，受 `n` 和截止时间控制 |
| final-test | `A_12` | 冻结后执行最终算法，不反向选择候选 |

四个实例均已在历史预实验中暴露，因此这次只验证生命周期行为与真实题目接口。它们不能作为未见测试集、泛化结果或正式 benchmark 排名的证据。后续研究需要按公平排行协议建立独立、固定且具有明确暴露记录的数据面板。

## 3. 真实题目校准结果

本地校准采用显式验收参数：每例监督时限 10 秒、种子 2020、单线程 NumPy / SciPy 原生求解器。它们是这次低成本集成测试的参数，不填入未来研究的 Configuration 默认值。

| 数据角色 | 实例 | 独立 checker 可行性 | 原始目标值，越低越好 |
|---|---|---|---:|
| public-selection | `A_09` | 通过 | 1507.2847843137256 |
| protected-feedback | `A_08` | 通过 | 744.510294117647 |
| final-test | `A_12` | 通过 | 793.095889937107 |

校验使用来源锁固定的 [RTE 官方 checker](https://github.com/rte-france/challenge-roadef-2020/blob/052def4d47271f913f89a68169083059732360f3/RTE_ChallengeROADEF2020_checker.py)，SHA-256 为 `9f1d7be2c5610d79ccbdd762c5c8736308fddc34e1ab39e6a6619be761f8322a`。严格输出适配、来源锁和面板均分别记录完整哈希。运行环境提供 NumPy 2.2.6、SciPy 1.15.3。

校准原始证据保留在本地工作目录的 `calibration-results.json`，包含完整算法快照标识、逐例输入哈希、约束结果和进程记录。私有上游源码、求解器、数据与原始内部路径没有作为这次新代码的一部分上传到公共仓库。

后续实际集群两组采用相同 T=180 秒、每例 10 秒／seed=2020 的验收 profile，分别完成 5／8 次真实模型调用；n=0 的 protected 受理／完成／ACK 为 0／0／0，n=1 为 1／1／1。两组均在 deadline 前实际停止开发，选择已检查公共 checkpoint，冻结后在原数值镜像的独立 verifier 上重新执行 A12，均为 AC，原始目标均为 793.095889937107。两组选中的是未修改 starter；本次证明接口和生命周期，未证明算法提升或反馈效果。

## 4. 反馈隐私与失败分类

`feedback_payload(result)` 将可信 evaluator 结果投影为固定的 `rte-aggregate-feedback-v1`：仅包含 `status`、`feasible`、`score`、`raw_objective` 和 schema 版本。候选 stdout、stderr、排程文本、逐例私有路径及任意候选控制的字符串留在控制器审计中，不能通过 protected feedback 返回开发 agent。

算法崩溃、缺少输出、无效排程与进程超时都是一次已接受调用的候选失败。独立 checker 故障属于基础设施错误；控制器重试必须保持同一候选、面板、checker、种子、资源与反馈作业标识，不能借重试获得另一个候选或额外反馈名额。

数据、算法包或 checker 哈希不一致时，适配器拒绝执行；不能默默更新快照或替换测试集。最终评分的可行性失败不能变成一个数值为零的有效优化结果。

## 5. 隔离与部署边界

`trusted_local=True` 仅允许控制器已经信任的本地基线校准。只读文件权限、进程组清理和显式环境变量能够验证普通接口行为，但不构成恶意代码隔离。

真实 agent 产生的代码需要经控制器验证的隔离后端。适配器接受控制器提供的 `certified_runner` 与 `backend_certification_sha256`；控制器负责验证证书内容、镜像标识、输入挂载、网络隔离、资源配额、候选进程清理和 checker 可见性。传入任意回调及一个哈希字符串不能自行取得部署认证。

适配器限制每个候选进程的时长。包括 checker 在内的完整反馈作业与最终批次时限由统一 broker / controller 监督；异步回调超时后，控制器还必须等待真实后端完成清理。该责任不能由一个线程的等待超时替代。

## 6. 自动化检查与后续验收

[适配器测试](../../tests/test_rte.py) 验证真正执行算法、完整冻结包内模块导入、使用独立目标值、拒绝未声明的本地执行、锁定 checker 和数据、阻止路径逃逸、无效排程分类、checker 故障分类、候选超时以及反馈字段投影。入口声明不一致的回归检查也已加入；最终检查数量与结果见本轮完成说明。

原有私有 Harbor runner 只导出单个 `solver.py`，使用 `-I` 执行。它能够承载本次独立单文件基线校准；复杂多文件候选必须采用完整包挂载与相应导入接口，不能以本次单文件验收代替多文件后端认证。

实际 Harbor / Docker 已取得 `n=0`／`n=1`、公共选择、显式 ACK、实际容器停止、冻结身份与独立最终评分的联合证据，并在完成后用新进程重开记录核对原 n/T、冻结与 final job／attempt。该恢复检查只针对完成后的持久状态，**未认证开发中完整 Harbor／会话／Pod 重启**；跨节点 SQLite WAL、目标并发、实际超额／断流／丢回执和终评基础设施重试等故障演练仍待补齐。

完整 C+X 面板、原赛时限语义、强基线同平台重评、新泛化面板和其他四任务的真实绑定仍按逐任务合同验收。五个任务的 `release_ready` 与 benchmark 生产认证不因这次单文件 RTE canary 自动改变。
