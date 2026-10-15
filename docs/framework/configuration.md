# Configuration：先明确要决定什么

**个人小测范围更新（2026-10-15）：** 本页49字段是独立参考实现与完整研究配置的目录；原生eval-in-loop小测沿用现有配置，不要求先填写本模板或新增配置层。具体工作范围以[精简设计](../decisions/0004-minimal-local-testing.md)为准；下文校验规则仍适用于主动使用该参考实现的场景。

**本轮设置更新（2026-10-15）：** 用户后续已确定五task、n=0／1／3／5／10、每档3次独立开发、T=43200秒、累计token不限／无累计预留截断；L2RPN主线恢复原赛动作范围。RTE已初选完整工业case X04，见[X04配置](../protocol/rte-x04-configuration.md)；其他task的case、模型、资源、实例执行预算等仍待实际核对／校准。取值与理由以[原题对齐与参数决定](../protocol/task-alignment-and-calibration.md)为准；没有为此新增配置层，也未将这些决定写成可直接执行的75项清单。

**状态：字段目录和校验器已实现；模板继续保留为通用待填示例。** 本页初始阶段仅列字段，不代选研究数值；这一历史范围不覆盖上文用户后来明确的决定。配置字段以[config.py](../../src/powergrid_bench/config.py)为来源，机器目录是[configuration-catalog.json](../../configs/configuration-catalog.json)，模板是[experiment.template.json](../../configs/experiment.template.json)。安装及实际CLI入口见[README](../../README.md)。

<a id="1-49个参考字段6项已约定政策"></a>

## 1. 49个参考字段，6项旧参考政策

模板有**49个可配置叶字段**，其值全部为`null`；非模型backend的4个model字段保留`null`且不要求填实，其他正式运行必需项仍须明确。`null`不代表沿用旧值、不限预算或零资源。准备脚本、预实验、测试fixture或部署环境中的默认值不能自动填进研究协议。

以下表格忠实记录机器目录当前保留的旧`policy`，不把文档改动当代码已经支持新政策。第一阶段以[决定0005](../decisions/0005-fixed-case-evolution-first.md)为准：固定高难完整case；完整评分反馈仅走n计数；禁止开发agent获得完整checker或本地完整算分；禁止搜索原赛测评源码；原生artifacts最终文件在T截止冻结，不增加免费selection评分。允许语法／格式／小型示例检查，算法可信执行中的内部目标计算不被禁止。

模板与独立参考selector保留旧政策，第一阶段复用原生eval-in-loop配置而不据此新建配置层。实际新版黑名单启用、开发镜像清理、旁路和截止收集仍待验收。目标case输入开发可见性也未因此自动确定。

机器目录现有政策：

| 字段 | 已约定值 | 含义 |
|---|---|---|
| `cumulative_token_cap` | `null` | 明确不设累计token cap；这里的null表示关闭该政策，不属于未决字段 |
| `token_reservation` | `false` | 不用累计token预留提前终止开发 |
| `feedback_zero_means` | `no-protected-feedback` | 旧参考语义；第一阶段n=0还明确禁止免费完整目标评分，轻量检查仍可用 |
| `selection` | `best-public-selection` | 旧参考实现，第一阶段不采用；不能额外给免费完整selection评分 |
| `tie_break` | `earliest-completed` | 仅适用旧selection；第一阶段收集截止artifacts最终文件，无评分并列选择 |
| `final_test_selects_candidates` | `false` | final-test不用于选候选或checkpoint |

模型单次输出上限、上下文窗口、供应商限流及实际token统计仍需配置/记录；不设累计cap不等于忽略单次请求限制。[统一预算政策](../protocol/evaluation-protocol.md#4-开发时限评测时限与-token)。

## 2. 全部字段与决定责任

以下编号对应当前49个字段，不含顶层`schema_version/status`及6项policy。表中的约束是校验器已实现的类型/下限；具体研究数值未确定。

### 2.1 身份与版本：7项

| # | 配置路径 | 类型／含义 | 谁决定与证据 |
|---:|---|---|---|
| 1 | `identity.run_id` | 非空字符串，独立运行标识 | Coordinator按批次槽位产生，不能重复覆盖旧run |
| 2 | `identity.cohort_id` | 非空字符串，同预算与恢复规则比较组 | 研究协议制定者；变化后的预算/恢复政策建立新组 |
| 3 | `identity.task_id` | 五个登记家族之一 | 从Adapter声明选择；SCUC等扩展另有track合同 |
| 4 | `identity.task_release_sha256` | 64位小写hex，认证task release摘要 | task维护者；绑定输入、接口、评分、环境与验收证据 |
| 5 | `identity.protocol_id` | 非空字符串，研究协议及版本 | 研究者；固定信息、预算、选择、恢复与统计边界 |
| 6 | `identity.split_sha256` | 64位小写hex，计分面板/四角色承诺 | 数据维护者；对应分组/暴露审计及评测端清单 |
| 7 | `identity.evaluator_sha256` | 64位小写hex，可信checker摘要 | Adapter维护者；原始评分、容差和单位须可重放 |

### 2.2 排行范围与权限：3项

| # | 配置路径 | 类型／含义 | 谁决定与证据 |
|---:|---|---|---|
| 8 | `ranking.kind` | `new-benchmark / historical-reference / agent-generalization` | 研究者；对应[公平排行](fair-ranking.md)，不提供本地“官方名次”模式 |
| 9 | `ranking.capability_profile` | 非空字符串，共同动作/工具/solver/信息权限版本 | task维护者和研究者；每个纳入方法同权限认证 |
| 10 | `ranking.aggregation_id` | 非空字符串，任务内聚合/归一化版本 | 发布前校准并冻结；不按算法结果调整权重 |

### 2.3 搜索方法与起点：4项

| # | 配置路径 | 类型／含义 | 谁决定与证据 |
|---:|---|---|---|
| 11 | `method.backend` | `coding-agent / population-evolution / training / solver-reference` | 研究者选择方法类别；枚举存在不表示该生产backend已接入 |
| 12 | `method.version_sha256` | 64位小写hex，方法/agent实现摘要 | 方法维护者；记录代码与适配差异 |
| 13 | `method.initial_artifact_sha256` | 64位小写hex，共同初始/回退算法 | 研究者与task维护者；基线独立验收，禁止弱化起点 |
| 14 | `method.context_policy` | 非空字符串，初始上下文/记忆/工具/外部信息版本 | 研究者；同开发预算比较必须固定合法信息条件 |

### 2.4 模型：4项

| # | 配置路径 | 类型／含义 | 谁决定与证据 |
|---:|---|---|---|
| 15 | `model.identifier` | 非空字符串，模型标识或固定profile | 研究者；精确供应商版本可得时另存运行证据 |
| 16 | `model.single_response_max_tokens` | 整数≥1，单响应输出上限 | 研究者在同cohort固定；不是累计cap |
| 17 | `model.context_policy` | 非空字符串，上下文窗口/压缩版本 | 方法维护者；记录初始上下文及续跑策略 |
| 18 | `model.retry_policy_id` | 非空字符串，有限重试/流式恢复版本 | 部署桥维护者；区分协议错误、限流和基础设施错误 |

当前校验器把`coding-agent`和`population-evolution`视为使用模型的backend；它们要求四个model字段填实。`training`和`solver-reference`要求这些字段保持null。此处只校验类别和配置，人口演化引擎、模型服务及协议bridge仍需额外实现/认证。模型endpoint凭据、API key和内部主机配置不放进公开研究模板。

### 2.5 时间与反馈预算：6项

| # | 配置路径 | 类型／含义 | 决策与计时边界 |
|---:|---|---|---|
| 19 | `budgets.development_seconds` | 正有限数，开发墙钟T | 研究者校准；共同准备完成后一次性开始，含训练、工具、selection和反馈等待 |
| 20 | `budgets.feedback_jobs` | 整数≥0，最多受理作业n | 研究变量；重发/同作业infra重试不重新扣次，实际受理/完成/送达分别报告 |
| 21 | `budgets.feedback_timeout_seconds` | 正有限数，单次反馈执行时限 | task校准；既不增加T，也不保证n条结果会及时送达 |
| 22 | `budgets.build_timeout_seconds` | 正有限数，最终构建/编译时限 | Adapter和部署方校准；共同准备/最终构建不得提前做候选训练 |
| 23 | `budgets.final_case_timeout_seconds` | 正有限数，每例/episode执行时限 | 原始目标与公平权限下校准；task专用Code1/Code2、单步或逐日细分随task release固定 |
| 24 | `budgets.final_batch_timeout_seconds` | 正有限数，完整终评总时限 | 发布面板与目标并发校准；生产桥监督整个checker/批次，不能只控制候选子进程 |

校验器当前正数下限是`0.000001`秒，用于拒绝零/负值；它不是推荐研究时限。原赛RTE的15/90分钟、GOC的10/45分钟和HEFT的报价截止属于原协议参照或任务因果语义，与n/T选择分开保存。预实验旧时间只用作成本校准证据。

### 2.6 三阶段资源：12项

| # | 配置路径 | 类型与单位 | 必须决定的内容 |
|---:|---|---|---|
| 25 | `resources.development.cpus` | 正有限CPU配额 | 全agent、训练、工具和子进程共享总上限 |
| 26 | `resources.development.memory_mb` | 有限数≥1 MB | 开发总内存及实际供给记录 |
| 27 | `resources.development.storage_mb` | 有限数≥1 MB | 工作目录、缓存、checkpoint与临时磁盘 |
| 28 | `resources.development.gpus` | 有限数≥0，GPU配额 | 零代表无GPU；GPU型号/切片/驱动等绑定资源profile和部署证据 |
| 29 | `resources.feedback.cpus` | 正有限CPU配额 | 反馈执行算法与数值库共同上限 |
| 30 | `resources.feedback.memory_mb` | 有限数≥1 MB | 反馈每作业总内存 |
| 31 | `resources.feedback.storage_mb` | 有限数≥1 MB | 反馈输入、解输出、分片及日志 |
| 32 | `resources.feedback.gpus` | 有限数≥0，GPU配额 | 所有方法同允许权限；实际消耗可不同 |
| 33 | `resources.final.cpus` | 正有限CPU配额 | 冻结算法执行的同平台权限 |
| 34 | `resources.final.memory_mb` | 有限数≥1 MB | 终评每作业总内存 |
| 35 | `resources.final.storage_mb` | 有限数≥1 MB | 新工作目录、输出与可信trace存储 |
| 36 | `resources.final.gpus` | 有限数≥0，GPU配额 | 最终能力赛道的GPU许可及型号证据 |

这些字段声明配额，当前本地可信fixture runner不执行CPU/GPU/内存cgroup隔离。实际限制必须由认证的容器/平台bridge实现并验证。配置使用MB，历史任务卡中的GiB/GB须显式换算并留证据，不能把它们当同一单位。solver线程、并发进程、出网、缓存、动作与simulate范围属于task/capability及deployment profile的附加合同，不应添加未登记任意键让校验器忽略。

### 2.7 选择与反馈信息：2项

| # | 配置路径 | 类型／含义 | 决策与证据 |
|---:|---|---|---|
| 37 | `selection.metric_direction` | `higher / lower` | Adapter原目标/冻结归一化决定，所有候选同方向 |
| 38 | `selection.feedback_schema_id` | 非空字符串，允许聚合/诊断/截断版本 | task与研究者确定；n控制哪个非公开信息面板，不能仅计公开checker调用 |

此处Selector实际实现旧best-public-selection和earliest-completed；不表示第一阶段已经支持截止最终文件政策。第一阶段走原生artifacts，并且禁止任何免费完整目标评分（包括借selection命名）。HEFT的因果拟合边界、L2的预训练／simulate权限、solver内部计算和开发端评分边界另存task说明，不能靠方向字段代替。

### 2.8 恢复与产物：4项

| # | 配置路径 | 类型／含义 | 决策与证据 |
|---:|---|---|---|
| 39 | `recovery.policy_id` | 非空字符串，同作业恢复/整个开发重跑版本 | 研究者预注册；infra retry不增T/n，不以较高分决定保留哪个run |
| 40 | `recovery.max_infrastructure_attempts` | 整数≥1，含首次的最大执行尝试次数 | 部署和task校准；只限同输入/候选/上下文的有限重试 |
| 41 | `artifacts.max_files` | 整数≥1，算法包文件数量上限 | task维护者；真实依赖/权重大小与安全限额一起校准 |
| 42 | `artifacts.max_bytes` | 整数≥1，包总字节上限 | task维护者；不足时明确失败，不能静默漏掉源码或checkpoint |

### 2.9 重复、seed和数值准则：4项

| # | 配置路径 | 类型／含义 | 决策与证据 |
|---:|---|---|---|
| 43 | `repetitions.count` | 整数≥1，独立开发重复数 | 研究者；不是实例/episode数量 |
| 44 | `repetitions.development_seeds` | 非空非负整数数组，恰好count个且互不重复 | 研究者预注册配对；不按结果挑seed或以恢复当额外独立重复 |
| 45 | `evaluation.seeds` | 非空非负整数数组 | task协议预注册评测seed；重复同场景不产生更多独立场景 |
| 46 | `evaluation.tolerance_policy_id` | 非空字符串，容差/随机性重放准则 | task维护者校准；区分数值等价、随机波动和真实错误 |

### 2.10 部署与真实验收：3项

| # | 配置路径 | 类型／含义 | 决策与证据 |
|---:|---|---|---|
| 47 | `deployment.backend_profile` | 非空字符串，本机/Harbor/集群环境版本 | 部署维护者；当前有名称不表示Harbor桥已经接入 |
| 48 | `deployment.runtime_image_digest` | `sha256:`加64位小写hex | 部署方锁定可拉取镜像；可变tag、宿主缓存不代替镜像身份 |
| 49 | `deployment.certification_sha256` | 64位小写hex，真实backend验收记录摘要 | 验收维护者；绑定硬截止、资源、隔离、模型/工具往返和目标并发证据 |

## 3. 草稿与完整配置的实际校验行为

`schema_version`固定为`1.0`，顶层`status`为`draft`或`configured`。`validate_configuration()`返回四项：

| 返回项 | 当前实现的含义 |
|---|---|
| `valid_draft` | 没有结构、类型、未知字段、enum、范围及policy错误；null允许作为未决字段 |
| `unresolved` | 本backend仍需填实的字段路径；模型字段的适用性按§2.4判断 |
| `errors` | 明确类型/非法值/政策改变等；布尔值不能混当预算整数，NaN/Infinity不合法 |
| `executable` | 结构合法、无未决必需项且status=configured；**仅表示配置层完整** |

模板的正常结果是合法草稿、49个未决项、`executable=false`。非模型backend排除4项model未决字段；配置仍须保留其null。独立开发seed必须与count数量一致且distinct；未知键被拒绝，以免拼错参数后静默忽略。正式值变更必须有新配置摘要，不能在运行中改cohort。

**完整配置不等于task/backend认证。** 当前校验器检查摘要格式，不验证该64位hash对应真实release、真实镜像或有效certificate。填写看似合法的字符串不能通过生产准入；preflight还必须读取证据、核对内容摘要、确认task/能力/数据与执行bridge认证范围。当前五个Adapter均为design，认证待完成；本地fixture亦不是生产平台。[验收边界](acceptance.md)。

## 4. 何时把参数从null变成正式值

1. 先确定[每个task的比较路线](fair-ranking.md)、原始物理和数据角色；不要先扩大n矩阵。
2. 对starter与强参考运行清洁环境校准，测单次求解、内存、simulations/训练成本、有效率与可改进空间；这些样本登记calibration。
3. 根据结果明确执行/资源/solver能力profile与反馈信息schema，预注册T/n实验矩阵、model、重复seed和选择政策；保持用户希望研究的变量可辨认。
4. 第一阶段固定高难完整case、开发可见性、计数评分／截止artifacts及失败政策；第二阶段才要求独立泛化面板。保存现有task、checker、能力、镜像及验收证据。
5. 填实正式配置，生成摘要并通过配置校验及独立preflight；再在目标并发运行认证批次。新版本改参数或数据需要新protocol/cohort与完整审计。

本页初版未代选数值；用户后来已确定T=43200秒、n=0／1／3／5／10各3次、累计token不限／无累计预留。模型、资源、固定高难case及多数算法限额待校准。49字段与旧selector仍为参考实现，不要求第一阶段逐项填模板；先以原生配置完成必要task与评分权限验收。
