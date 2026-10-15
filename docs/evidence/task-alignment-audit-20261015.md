# 五任务原题差异、数据实物与成本证据审计

**核查日期：2026-10-15。** 本轮只读检查已有源码、实际数据、历史记录与一手规则，未启动新算法开发、基线重跑或75次正式实验。本文支持[原题对齐与参数决定](../protocol/task-alignment-and-calibration.md)，不构成五任务新协议的运行认证。

公开仓库核查起点为`58af3ccffe54abce1bbc02d25cf408b8a88533b0`；私有eval-in-loop基础提交为`2f998fee5ee4229c02271941e804c17f7a8e6eb5`。任务包及大量实验材料是该工作区的未跟踪文件，**仅有Git提交号不足以复原此次核查对象**。下文路径相对私有工作区，摘录事实及必要摘要；不发布源码、原始数据、保护成员映射、模型轨迹或部署配置。已有无关工作区改动未处理。

## 1. 源码中实际存在的差异

| task／检查对象 | 已核实的行为 | 对本轮的影响 |
|---|---|---|
| GOC完整793路径 | 后续实验实际执行Code1和Code2、保持同一基态并输出全部86故障；官方原始J保留，显示reward是其单调映射 | 完整数值逻辑已有，优先接回复用；早期固定响应不能代表完整原题 |
| GOC旧提交入口 | 旧`run_options.py`只接受n=0/1/3及28800秒；任务仍依赖实验目录评分、socket和终评回执 | “原生框架支持任意正n”不等于旧脚本接受n10和12小时；收齐依赖并最小修补入口 |
| UC原生grader | 检查附带源码存在，但读取预先写出的schedule，没有执行源码生成新解 | 旧结果可说明这两份排程质量，不能说明冻结算法处理新日期的能力 |
| UC／SCUC | 原UC两例保持完整48期、73热机／81新能源；派生SCUC另加100/120MW线路限额与19/38个非孤岛线路故障 | 本轮以原铜板UC为核心，派生DC SCUC另列，不赋予原库没有的安全约束或竞赛名次 |
| RTE原生pilot | 实际调用solver并按原风险评分；公开A07／A09，A08／A12兼作反馈和终评 | 可复用执行链与确定性证据；新比较仍需不同角色的实际输入绑定 |
| L2RPN旧小任务 | 只允许set_bus／set_line_status；16次simulate／步、2048次／episode等为本地限制 | 原Starting Kit实际为`TopologyAndDispatchAction`；用户已选恢复含redispatch的原动作能力，需要同权限重跑 |
| L2RPN较大先导 | 375离散动作含裁剪拓扑；n0 launcher拒绝正n、没有自动终评，网关仍有累计token cap | 三次12小时PPO运行不是正n／无限累计token的完整实验入口认证 |
| L2RPN评分 | 小任务使用现代native经济scorer，较大协议还有归档公式路线；生存率先导另有版本 | 必须选一套主scorer与同环境reference重跑，不能拼接已有分数 |
| HEFT原生grader | 只读静态bids；允许±5000MWh；题面还有旧1800秒／100万token／恰好一次反馈 | 新协议需要实际执行预测交易流水线；恢复原报价0–1800及新研究预算，旧CSV评分不证明算法执行 |
| HEFT时间处理 | 旧准备按UTC日期分组，过滤非48行UTC日；NWP issue按目标UTC日期选择 | 原题是英国本地23:00—23:00市场日，2024-03-31为46period；必须重建period与cutoff，不能只改一条时区标签 |
| HEFT训练政策 | 旧允许train+validation拟合最终模型，且整段test特征一次可见 | 本轮固定权重、selection只选择、逐市场日执行是明确的本地学习变体；恢复原结算不等于恢复原实时参赛过程 |

关键源码定位：

- GOC：`experiments/goc793-s195-n3-r1-8h-20261009/grid-tasks/goc1-793-development-v1/instruction.md`及同实验的`grading.py`、`evaluate.py`、`run_options.py`。
- UC：`tasks/pglib-uc-rts-v1/tests/grade.py`、`environment/app/data/manifest.json`；派生扩展见`tasks/`中独立DC SCUC包，不能把其常数带入原UC。
- RTE：`tasks/rte-maintenance-2020/{task.toml,tests/score.py}`及评分侧manifest；[已公开的真实接入报告](../completion-step3-cluster-20261015.md)说明独立接桥验收范围。
- L2RPN：`tasks/l2rpn-neurips2020-score/`；`experiments/l2rpn-formal-n0-20261012/code/{famou_runner.py,model_gateway.py}`；原动作定义位于`experiments/l2rpn-public24-reevaluation-20261011/upstream/starting-kit/L2RPN_neurips2020_track1_starting_kit/input_data_local/config.py`。
- HEFT：`tasks/heftcom2024-historical-v2/{instruction.md,tests/grade.py,tests/score_public.py}`；`experiments/heftcom2024-time-only-20261013/verification.json`只证明24项本地检查、0次提交，没有完整容器／正式执行证据。

## 2. 数据文件实际具备什么条件

| task | 本地／上游实物核查 | 当前可以声明什么 | 仍缺什么 |
|---|---|---|---|
| GOC | 已有793/195、500/67、2000/25、2312/21等公开合成场景；没有找到已完成的新四角色manifest | 旧场景可用作开发／校准；完整793有全部故障运行证据 | 新面板具体成员、历史暴露和分组审计；工业终赛输入不可恢复 |
| UC | 原task仅2020-01-27和07-06，均已公开；只读核对固定上游归档确认CA20／FERC24／RTS12共56例 | 可从完整RTS日期建立同系统比较，不需要先实现SCUC | 新日期下载入task、摘要、暴露与基线可行性；4/2/2/4只是待核候选 |
| RTE | 本地`experiments/rte2020-adapter-20261012/data/A_set/`确有A_01至A_15及原压缩包；已暴露A4 | 小规模A组问题可直接继续盘点 | 新角色映射、规模范围；不能由A组实物推断C+X30例已就绪 |
| L2RPN | 候选144／48／24／96周分别来自12／4／2／8个来源组件；共312周，3154文件，既有3151文件清单核对无差异 | 不是纸面比例，已有真实四角色资产、精确重叠审计和隔离旧暴露组件 | 本轮再核后续暴露；近重复与原生成谱系统计独立性未证明；完整动作新接口未验 |
| HEFT | energy／prices各59902行，覆盖2020-09-20至2024-02-19 22:30UTC；NWP issue至05-19、valid_time至05-21 | 历史标签可用于校准；天气覆盖原正式期 | 2024-02-20至05-19的实际发电／价格标签本地缺失；官方归档、修订和到达时点需核对 |

L2RPN证据在`experiments/l2rpn-benchmark-protocol-20261011/v1/private/`的dataset／split／overlap／frozen-files清单及`experiments/l2rpn-benchmark-audit-20261011/三步验收报告.md`。旧12份任务数据、Starting Kit24份和48周先导的暴露来源已做隔离。冻结快照记录feedback／test策略rollout为0，**不表示管理员没读过原始数据，也不证明快照之后没有使用**。本轮公开计数和方法，不发布保护成员及来源映射。

HEFT本地旧DWD空间聚合只包含天气与日历，不含GFS完整格点。旧791／168／201天来自UTC48行过滤，必须按正确市场日重算，不能沿用作新split计数。天气4小时滞后是release假设；energy／prices的1日滞后声明没有实际到达日志支持。原队第一手记录中价格可能延迟4–5天，故不能把1日声明视为已证因果性。原始来源分别见[官方v4](https://zenodo.org/api/records/13950764/files/Competition%20Documentation%20v4.0.pdf/content)、[组织方赛后回顾](https://arxiv.org/html/2507.01579v2)、[GEB方法论文](https://arxiv.org/html/2505.10367v1)。

## 3. 已有成本证据能支持什么

以下为历史实测，不是本轮新生成的校准报告。CPU／内存／时间单位按记录保留；声明配额不等于实际使用量，采样最大值不等于真实峰值。

| task／记录 | 核实的测量 | 可继承的结论 | 不能据此决定什么 |
|---|---|---|---|
| GOC793阶段timing | 42条阶段记录、21组Code1／Code2；Code1=15.83–216.33秒，Code2=0.69–69.54秒；记录未见OOM | 已测793路径可在原600／172秒档完成；可作同平台校准起点 | 多网络尾部成本、固定参考重复性、内存峰值；memory字段是限制值 |
| UC两日期baseline | 1月求解60.037秒、总62.403秒，`TIME_LIMIT`；7月求解26.988秒、总27.663秒，`OPTIMAL`（记录容差内） | 完整MILP可运行；60秒是有记录的成本起点，可信bound应单列 | 全RTS成本／最优性；不能把1月60秒参考说成最优解 |
| RTE A08／A12重复verifier | 固定starter两次原目标一致；完整两例分别4.945／5.355秒 | 小面板执行与原风险计分可重入 | 原赛15／90分钟预算或C+X30例成本 |
| L2RPN formal-v2 PPO | seed101／202／303，三次wall约43201秒；开发CPU时间下界39447–40304秒；评测CPU2528–3426秒、wall2729–3608秒 | 受限动作PPO训练／导出在合计4CPU／16GiB运行有实证 | 完整动作、LLM开发或n10反馈成本；也不把43201秒当严格截止已通过 |
| 同PPO内存 | 采样峰值下界约511–529MB | 提供内存需求量级的下界 | 不据此选512MB上限；没有真实峰值／OOM边界证据 |
| L2RPN公开校准 | 36项reference；记录`final_holdout_accessed=false`，训练／重载／模拟接口有验收 | 可复用校准资产和重放程序 | 不认证所有新动作／scorer／面板／预算组合 |
| HEFT constant／ridge | 8064个结算period的收益和RMSE | 旧settlement数值可作回归线索 | 因果训练／加载／逐日执行成本；输入、报价和市场日改变后须重跑 |
| HEFT n3静态评测 | 两条eval记录各0.1秒 | CSV读取与settlement很便宜 | 不能给模型流水线分配0.1秒执行预算 |
| HEFT旧token策略 | `charged_tokens=691953`，`token_cap_reached=true`，25次complete | 旧预留策略在名义100万前实际阻断；本轮必须清理该限制 | 不能把旧run标为累计token不限 |

路径索引：

- GOC：`experiments/goc793-s195-n013-three-repeats-20261009/analysis-evidence/`下阶段`timing.json`。九次终评子集的Code2最大值约44秒；本表使用更宽的21组记录，二者不是同一统计集合。
- UC：`experiments/uc-scuc-adaptation-20261012/validation-baselines.json`。
- RTE：`experiments/rte2020-adapter-20261012/cluster-acceptance-2/acceptance/repeated-verifier.json`。
- L2RPN：`experiments/l2rpn-formal-n0-20261012/preparations/formal-v2/outputs/acceptance.json`，以及`experiments/l2rpn-benchmark-pilots-20261011/{calibration-complete.json,runtime-validation.json}`。
- HEFT：`experiments/heftcom2024-n3-20261013/validation-baselines.json`及同实验运行记录中的`record/evals.jsonl`、`model-usage.json`。

## 4. 原生框架与旧实验脚本不要混为一谈

源码核查表明原生入口可以表达43200秒和任意正n，n0有terminal路径；并非需要新建一套框架才能做本批实验。但旧GOC／L2RPN／HEFT专用脚本保留n白名单、短时间、累计token cap或n0限定，必须逐一清理实际采用入口。

已有persistence默认未必开启；n用尽后是否继续开发取决于实际配置。三次独立开发需要不同run身份，不能把同模型一次开发的三个环境seed写成三次开发。原生CLI没有可任意假设存在的开发seed／repetition开关，需按实际能力保存重复映射；模型端不支持seed时如实记不可控。

此前RTE桥接canary已经验证一条真实Harbor／模型路径上的n0／n1、共同截止、冻结和独立终评，见[验收报告](../completion-step3-cluster-20261015.md)。这不证明所有旧task脚本自动获得相同保证。本轮本地未运行完整容器或新基线；后续只测试采用的实际入口，不扩建后端保障平台。

## 5. 核查文件摘要

SHA-256用于识别本次只读看到的文件，不代替受许可的原文件发布或完整task release摘要。

| 对象 | SHA-256 |
|---|---|
| UC `tests/grade.py` | `237f7dc3e5f56cb77c3ea0aad62c941300f5c16df96c85dd2b6915fbfed5d7e6` |
| UC输入manifest | `3b196547117c25333ca18c31eea078968c045d197c5a8b64a59ef0dc07e7ab68` |
| HEFT `tests/score_public.py` | `847f441bef81b7287ce0c2c386abf03a8365f04732a8d1518b715e5c4ffc73f5` |
| HEFT `tests/grade.py` | `4eca04a07fd333951303ab65fc7a5d062e793028562a470cdf606f0b4a77716f` |
| RTE `tests/score.py` | `7143baba245f45485f62da4b5073703e8bfda4807ee2e91ea76133066269135c` |
| UC baseline记录 | `c82ddfe17a924e01b87e5ae77018c3daf691d79691538b60a0ef7983b11a1bad` |
| RTE repeated-verifier记录 | `59205b48fed811639965f78faf88e6a496ab4fd98c308ec76f99fdd805f1ca81` |
| L2RPN formal-v2 acceptance | `e20f713cfa2b6994dd88dd92d0c84ad2a5622b45aab65260c4c59e8d533d11d2` |
| L2RPN候选frozen-files清单 | `af553679d1b0e02e2078ee09b6af282431792c7de5a1a6a6307dac5b10e09024` |
| 原Starting Kit动作配置 | `363eb30b4c5a26e45a278bd7537ce38b526a175e3af6c3702a478215067a275a` |
| HEFT baseline记录 | `2b7eefa48840a9e6fe02504b8b41feea93e6f5d4a07aeeb9c367e7ef5ee1fc7b` |

原题定义来源另见[GOC组织者综述](https://molzahn.github.io/pubs/aravena_molzahn_zhang_et_al-go_intro.pdf)、[GOC官方数据归档](https://data.openei.org/submissions/6153)、[固定PGLib-UC版本](https://github.com/power-grid-lib/pglib-uc/tree/39a7f38cf4703de92f0291f0c873c2e98c789301)、[RTE原题与checker](https://github.com/rte-france/challenge-roadef-2020)、[L2RPN组织方论文](https://proceedings.mlr.press/v133/marot21a.html)。本轮未复制这些第三方代码或数据。
