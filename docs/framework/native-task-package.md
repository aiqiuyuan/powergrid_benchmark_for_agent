# 提交给eval-in-loop的task应整理成什么形式

**核查日期：2026-10-15。** 依据当前使用的`eval-in-loop`工作区及其原生任务模板核对；基线HEAD为`2f998fee5ee4229c02271941e804c17f7a8e6eb5`。该工作区存在既有实验适配，不是干净的上游检出；下文是实际入口核查，不表示已新建或验收五个任务包。

**第一阶段政策更新：** 按[固定case算法演化决定](../decisions/0005-fixed-case-evolution-first.md)，每task优先固定高难完整case，同case开发、计数反馈和截止复核；禁止开发agent取得完整checker、本地完整目标评分或搜索原赛测评源码。无免费public-selection评分，采用原生artifacts最终文件与截止冻结。下文源码核查基线仍为上列提交；已查到新版分支的黑名单能力，实际启用和防绕过须单独验收。

结论：**每个task整理成一个原生Harbor任务目录，沿用现有`tasks/_template`结构。** 先按[公平设置清单](fair-ranking.md)确定数据、算法权限、评分和预算，再填任务目录。框架已有启动、候选打包、反馈judge和终评入口，个人侧只补task真正缺的内容。

## 1. task包和算法产物是两件事

| 项目 | 谁维护 | 包含什么 | 框架怎么使用 |
|---|---|---|---|
| task包 | 出题／评测侧 | 题面、开发环境、starter、数据准备、评测环境、执行和checker、资源声明、参考解 | 按目录路径交给Harbor启动 |
| candidate算法产物 | 开发agent／参评方法 | task声明要收集的源码、参数、权重、必要辅助文件 | 按`task.toml`的`artifacts`清单打包，交给task评分入口 |

算法接口按问题选择。RTE可以是一个Python solver，L2RPN可以是controller，HEFTCom可以是预测交易流水线。无需为了接入框架再统一成新的`candidate.json`、新RPC服务或注册中心。

## 2. 原生目录

```text
tasks/<task-id>/
├── task.toml                    # 资源、超时、工作目录、artifacts、评分元数据
├── instruction.md               # agent看到的题面、权限、算法接口和提交说明
├── environment/
│   ├── Dockerfile               # 开发镜像：可见数据、依赖和starter
│   └── app/                     # 项目惯例，按Dockerfile复制到/app
│       ├── submission/          # starter及agent可编辑的算法文件
│       ├── public/              # 或data/：允许开发使用的数据
│       └── support/             # 仅语法／格式／小型示例工具
├── tests/
│   ├── Dockerfile               # separate verifier／judge镜像
│   ├── test.sh                  # 固定评分入口，支持LOG_DIR
│   ├── score.py                 # 示例名；调用冻结算法、独立校验和计分
│   ├── reward_io.py             # 可复用结果写出工具，非强制文件名
│   ├── support/                # task runner、原生checker等
│   └── data/                   # 可信环境准备的评测数据／成员清单
└── solution/
    └── solve.sh                 # oracle参考解／基线验收入口
```

当前项目检查要求`task.toml`、`instruction.md`、两侧`Dockerfile`、`tests/test.sh`和`solution/solve.sh`存在。`solution/solve.sh`是`exp check`及oracle验收的要求，不代表每次模型实验都会运行oracle。`app/`、`public/`、`support/`、`score.py`和`reward_io.py`的内部名称可以按现有task调整；评分的固定执行入口是`/tests/test.sh`。

建议同目录补`README.md`、来源／许可、数据准备说明和版本／摘要记录。这些服务于复现，不是新运行接口。框架会生成自己的agent指导文件，无需在task中另写框架级`AGENTS.md`／`CLAUDE.md`。

## 3. task.toml需要写什么

沿用原生模板，不新建配置schema。下表列语义，时间与资源数值留待校准；不要把本表当作可直接执行的完整TOML。

| 原生字段 | 要填的内容 | 与公平设置的关系 |
|---|---|---|
| `schema_version` | 当前模板使用`1.3`，以实际运行版本兼容要求为准 | 记录实际版本 |
| `artifacts` | 非空；完整列出要交给judge的算法代码、权重及必要辅助文件，位于`/app`下 | C13／C30；反馈和终评使用这同一清单 |
| `[agent].timeout_sec` | task的terminal默认开发上限；CLI的`--time`可覆盖，in-loop应显式指定本轮时限并核对实际计划 | C21；开发T不能与算法求解限额混用 |
| `[environment]` | 已确认字段`cpus`、`memory_mb`、`storage_mb`及显式`workdir`；其他资源按实际后端能力核对 | C26；候选子进程、训练也在配额内 |
| `[verifier].environment_mode` | 当前项目要求`separate` | 开发和可信评分环境分开 |
| `[verifier].timeout_sec` | 外层评测总时限 | C27；算法内部逐例／阶段／步时限另由task执行器落实 |
| `[verifier.environment]` | 评测环境资源与网络等；显式提供时检查完整生效值 | 不能假定继承开发环境CPU／内存 |
| `[optimization].metric`／`direction` | 与评分结果中的原始metric名称及方向一致；当前方向值为`higher`／`lower` | C17／C18；不能仅改元数据而未改评分 |

`artifacts`是候选清单的唯一依据：不要把整个`/app`无差别列入，也不要漏掉solver调用的源码、依赖配置或权重。原生打包能力存在，不表示任意task都已经收齐了可复现算法。

## 4. 题面、环境和评分各负责什么

`instruction.md`至少讲清问题、允许数据和工具、算法输入输出、允许状态、原始指标及方向、执行限额、提交路径、失败处理和可见反馈。写给agent的承诺须与实际设置一致；目标case哪些输入开发可见须先确定，不能默认全部隐藏或全部公开。完整checker及完整目标评分工具不得进入开发题面／工作区；因果标签权限继续按task约束执行。

`environment/Dockerfile`只准备获准的依赖、starter、数据及轻量示例检查，不复制完整checker、public_eval完整评分入口或完整分数日志。`tests/Dockerfile`准备运行冻结候选所需的依赖、原生checker和可信数据。候选缺少的依赖不能靠评测端不记录地额外补齐；开发端和评测端的版本差异要有依据。

`tests/test.sh`及task评分程序负责：

1. 使用`LOG_DIR`指定的输出位置，默认`/logs/verifier`。
2. 读取`artifacts`交来的算法，按所选成员／时限实际执行，生成本次原生输出。
3. 用独立checker检查完整性、约束、信息与原目标，不信任候选自报分数。
4. 写`reward.json`和`reward-details.json`；候选失败也留下结构化结果，并区分基础设施故障。
5. 每次评测正确清理候选输出和实例状态；固定输入／seed可重放。需要保留的跨步／跨日状态依task合同明确管理。

| 输出文件 | 当前约定 |
|---|---|
| `reward.json` | 数值reward，例如`{"reward": 0.5}`；不是完整能源原始指标 |
| `reward-details.json` | `reward`、`metric`、`metric_name`、`metric_direction`、`valid`、`error`、`feedback`、`details` |

模板的reward写出工具会把reward限制到`[0,1]`，能源原始成本、风险、GBP或合法负分应保留在`metric`。**原始指标到reward的转换也是公平设置**：必须事先固定、单调方向正确，声明零／负值、失败、截断及是否影响选择／反馈。还未决定转换时，先保留原始指标用于校准，不能把不同映射产生的reward直接比较。原生项目的`exp check`重入测试只比较两次reward；task仍需对账实际关心的原始指标、可行性和状态。

## 5. task怎么交给框架

任务目录放在现有仓库`tasks/`，或通过`--tasks-dir`指定任务的**父目录**。实际按`<任务父目录>/<task-id>`定位，最终交给Harbor的参数是`-p <完整task目录>`。

以下是原生入口示意，需在已有`eval-in-loop`环境中执行，不是在本公开文档仓库内执行：

```bash
exp check <task-id> --tasks-dir <任务父目录> --static
exp check <task-id> --tasks-dir <任务父目录>
exp run <task-id> --tasks-dir <任务父目录> --mode terminal --agent oracle
```

第一条检查文件／配置，后两条涉及实际构建和执行。没有可用Docker时，动态检查会被跳过；镜像／执行架构不兼容则可能构建或运行失败。必须看实际执行记录，不能将静态检查通过说成完整任务验收。本轮未执行这些示意命令。

| 研究用途 | 原生模式 | task需要做什么 |
|---|---|---|
| n=0，不提供受保护开发反馈 | `terminal` | 使用同一task和artifacts；最终由separate verifier执行`test.sh` |
| 正整数n的受控反馈 | `eval-budget`及正数`--n` | 框架自动添加judge，使用task的`tests/Dockerfile`和`test.sh` |
| 按开发时间限制、反馈次数不限 | `time-budget`及`--time` | 内部judge预算0表示unlimited；它不是研究n=0 |

不必为每个task实现submit／result协议或新judge；已有框架负责这些通用调用。研究其他配置时沿用现有CLI和配置，不在本说明里另填模型／资源／时长默认值。

<a id="6-同一个评分入口不自动构成公平数据隔离"></a>

## 6. 同一个评分入口不自动落实评分访问政策

原生in-loop与terminal使用同一个`test.sh`和评分镜像。第一阶段正好要求同case、同完整checker与执行合同，但这不自动证明开发端无法绕过n评分，也不自动证明截止文件已正确冻结。四角色隔离和best-public-selection是旧设计／第二阶段参考，不是第一阶段前置。

按[公平设置C07–C12、C23–C25、C29–C33](fair-ranking.md)核对每个现有task：

- 同task所有n档是否绑定同一固定case、完整checker、目标／容差／资源／算法预算和反馈字段？
- 开发镜像、依赖、共享路径和网络里是否仍可取得完整checker或等价完整目标评分？
- 是否只允许语法、格式和小型示例检查，并禁止搜索原赛测评源码？
- T内最终artifacts是否在截止正确收集并冻结，无修改是否保留starter？终复核是否不回流开发？
- 候选的内部目标计算与向开发agent提供旁路完整评分是否确实分开；目标case哪些输入可见？

同case是本轮研究设计，不因复用case而降为无效实验；结论明确限于该case演化。先用原生配置落实评分通道及artifacts收集，确有缺口才做最小task修改。域名黑名单需结合搜索工具、直连限制、本地副本和数据可见性核验；不能宣称仅开黑名单即封住完整评分旁路。

## 7. 公开GitHub与可信评测数据

`environment/`复制到开发工作区的内容agent可见；separate模式中的`tests/`不出现在该开发工作区，但会进入评测镜像。**公开GitHub中的`tests/`依然公开，目录名不提供保密性。**

本公开仓库可保存获准题面、来源／许可、下载准备说明、case标识及摘要。用于第一阶段的完整checker留在可信评分侧；组织方已经公开的源码不能靠本仓库目录名变成秘密，应禁止开发搜索／下载并验收实际通道。目标case输入是否开发可见尚须确定；公开来源仅在工作区留出的数据不能声称源数据保密。

`feedback`会回传agent；当前judge的`result()`不回传`details`。仍须核对日志和整个可读文件范围；仅采用separate模式不能证明候选在评测环境中无法读到任何测试文件。模板评分样例有把隐藏输入／expected值拼进feedback的写法，**不能照抄这一段**；能源task只输出已约定的安全反馈字段。此处是已发现的task整理检查项，本轮没有修改原模板。

## 8. 五个已有task需要怎么整理

| 家族／已有目录 | 现有提交形式与评测范围 | 按公平设置确定后的最小工作 |
|---|---|---|
| GOC | 原生两阶段及原生输出路线，具体包入口待下一步核对 | 保留Code1→Code2及完整故障，核对artifacts、阶段预算与官方checker；本轮未逐文件验收其包 |
| UC：`pglib-uc-rts-v1` | `/app/submission`；当前评分读取保存的固定实例schedules | 原生包结构可复用；算法benchmark需执行冻结源码产生新排程再validator |
| RTE：`rte-maintenance-2020` | `/app/submission/solver.py`；评分程序实际执行solver | 已初选完整X04；移除开发端checker/public_eval，核计数评分及截止产物，可信端保留原checker |
| L2RPN：`l2rpn-neurips2020-score` | `/app/submission`；`Controller(metadata).act(observation, simulate)` | 先统一动作／forecast／simulate权限和环境，再复用控制器wrapper／原生scorer |
| HEFTCom：`heftcom2024-historical-v2` | `/app/submission/candidate.tar`含代码／模型／CSV，但现有评分只读取bids | 固定因果输入，在现有settlement前实际运行冻结预测交易代码，生成新日报价 |

当前RTE `task.toml`声明verifier 1 CPU／4096 MB；可信runner还通过`prlimit --as=2147483648`限制候选进程地址空间为2 GiB。容器内存与候选进程地址空间不是同一限额，两者都不自动适用于完整X04正式实验；详见[X04配置](../protocol/rte-x04-configuration.md)。

目录和artifacts只是接入形式。UC／HEFTCom的包即便附有源码，评分不执行源码就仍只能说明静态答案质量。后续先填公平设置，再决定这些最小task修改；本轮不把目录示例宣称为五个已交付的稳定运行包。

## 9. 轻量验收与源码依据

一个可交付的第一阶段task至少留下：文件／原生配置检查、baseline或oracle可信执行、固定高难完整case上的算法运行、独立原始评分与失败记录、固定seed重放及评分权限验收。做保护反馈时再核对该模式实际调用及计数；正式比较再满足[公平排行§9](fair-ranking.md#9-排行发布的共同准入门槛)。这些是任务验收记录，不要求建设新的测试／报表平台。

下面路径均相对于核查的`eval-in-loop`源码；其访问权限与本公开仓库不同，不创建虚假的公开链接。

| 核查内容 | 实际依据 |
|---|---|
| 原生目录、两镜像、结果与泄漏要求 | `docs/authoring-a-task.md:17,51,254`；`tasks/_template/README.md:3` |
| 必查文件、oracle与重入检查 | `exp/check.py:65,204` |
| 字段、artifacts、模式、Harbor参数 | `exp/plan.py:106,469,512,604,652,736,785`；`tasks/_template/task.toml:1` |
| task父目录与实际启动 | `exp/cli.py:45`；`exp/launch/local.py:42` |
| 候选打包、评分入口与回传字段 | `runtime/bin/_client.py:57`；`runtime/judge/serve.py:265,472` |
| reward写出及模板反馈问题 | `tasks/_template/tests/reward_io.py:44`；`tasks/_template/tests/score.py:42` |
| 已有题目入口及提交范围 | 上表四个已核查task的`instruction.md`／`task.toml`；RTE的`tests/score.py:43` |

本次核心核查文件均为tracked文件，在工作区和暂存区均无修改。为区分基线源码与其他既有实验适配，保存其SHA-256：

| 文件 | SHA-256 |
|---|---|
| `exp/plan.py` | `2d89fbd554d05f56c882c5dddb26a408549641cce64d211631f3ef574eec66e6` |
| `exp/check.py` | `1d762904e251ae98612f976f66833fb1db633a65e43af8eaf653077e70677309` |
| `exp/cli.py` | `50b3b6f39bf7b7f02764f60147bd7360f6caf9adc810c76177a55381cfc71407` |
| `runtime/judge/serve.py` | `897f717428ae0ec6ef2acf12be2cf5155d344bb9bc60295e1fd9a59aed8668c3` |
| `runtime/bin/_client.py` | `32829ca56d667b217b0cdc8a8e8f37b052db172cb4bc5c09090f121e4eda0d89` |
| `docs/authoring-a-task.md` | `0c2246554ba40e50557c6b75c2d3b6270739b8d6f9cfa459766c855bf02e0d8d` |
| `tasks/_template/task.toml` | `fb2c4bac21535f9ae8979ae760cb9c5584d84003a25c31f3c8ceda3e0b10df2e` |
| `tasks/_template/tests/score.py` | `b893da32034a78bad82c9378b6c5f34e5da877354bd1e8a63e656ecee720da02` |
| `tasks/_template/tests/reward_io.py` | `19200b9cc4688a3985a0eba8831732bf040e50718c486ae5cfa4134d0fbd7b2c` |

上表是原核查基线的只读快照，并非升级后版本的逐文件复核；此次政策同步未据此宣称新task已通过验收。原生包结构已经确认，五任务按所选公平合同的完整实现与运行验收仍是后续工作。
