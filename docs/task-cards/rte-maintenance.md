# RTE 检修排程

> 状态：旧版4实例接入先导可运行；新增批暴露任务包缺失，修复验收未在快照中完成。v0.1的独立四角色数据划分为拟定。历史证据截止北京时间 2026-10-13 23:32；修复准备核对至 23:38。

## 1. 家族定位与研究能力

**家族 ID：`rte-maintenance`。** 基于ROADEF/EURO 2020 RTE公开问题，选择检修开始时段，满足资源、持续时间、季节与互斥等约束，最小化均值风险与分位超额风险组合。它测试随机情景下的组合优化、MILP与局部搜索混合、可行性修复和风险目标求解；不是在线潮流或RL任务。

## 2. 演化对象与执行合同

- 演化通用实例解析、建模、构造、改进和风险计算策略；不得把目标换成CVaR或均值风险的近似后仍按原任务声称优化。
- 提交算法源码、固定依赖、参数及随机种子。评测端提供原始实例，候选输出每个干预作业的整数开始时段。
- 终评重新执行冻结求解器；独立官方checker验证全部约束，并计算原始风险目标及分项。
- 主报告保留逐实例原始目标 `F`、可行率、相对固定参考算法的gap、耗时和内存。先导reward是单调归一化，不是历史竞赛排行榜分数。
- 接口与沙箱需支持选定求解器合法使用的线程/进程模式；先导“禁止子进程/线程”属于已有合同，是否保留需校准后声明，不能隐性改变方法能力。

## 3. 已有预实验与限制

旧 `rte2020-a4-pilot-v1`：公开A_07/A_09，反馈及终评共用A_08/A_12，实例保持完整规模；每例60秒总求解墙钟、1 CPU、2 GiB地址空间；开发12小时，无累计token cap，单响应输出8192。

| 原有效运行 | 最终reward |
|---|---:|
| starter | 0.37303000350813975 |
| n0-r1 | 0.37305086787489783 |
| n1-r1 | 0.3732618178335546 |
| n3-r1 | 0.3732712577690902 |

各条件仅一次，小幅改善只说明当前面板的算法变化。n0/n1有开发到时的timeout字段，但冻结后终评有效，不能只因字段名判为实验失败。旧任务曾通过无模型容器与反馈接口验收；该验收不代表每个后来重新冻结的包完整。

新增12次截至快照11次Failed、1次Running，尚不能计为有效重复。包遗漏3份嵌套清单，使过程反馈与终评缺输入；对“清单中已列文件”做哈希检查不能验证所有必需文件存在。另有模型接口HTTP400需精确分类与有限重试，上游内部原因未确定。

补齐版本已进行本地检查并启动无模型验收，但快照未确认真实终评、n=1反馈及模型工具往返全通过；替代正式重复也未完成。救回旧源码补评应单列，不能替换无效过程反馈的因果证据。

## 4. v0.1 数据与反馈协议（拟定）

| 数据角色 | 拟定安排 |
|---|---|
| Public development | 公开开发实例、完整目标与checker，可自由调试 |
| Public selection | 独立公开实例，按预定可行性与风险指标选候选 |
| Protected feedback | 与公开两组及终评分离的实例；服务端执行候选，仅返回规定信息 |
| Final test | 未用于反馈的留出实例，运行冻结算法；保留全作业、时段和风险情景 |

A/B/C/X等来源组是否同分布、规模是否合适，先做来源与难度统计，再决定分组。**不在本卡预先编造正式实例名单或假定B/C/X已被冻结。** A_08/A_12已经用于反馈，只可作为先导/开发校准，不属于未触碰测试。

原始竞赛数据公开，开发端网络可检索，因此当前只证明镜像与进程隔离。v0.1需声明网络白名单与实例访问边界；无法完全排除历史知识和预训练污染，需披露而非承诺。n仅控制受保护实例聚合反馈；公开checker和优化目标合法。

## 5. 基线、预算与校准

当前可信starter是HiGHS均值风险MILP加原风险目标可行局部搜索，已显示部分实例比纯均值风险MILP改善。两者可构成最小校准基线。后续选取公开、许可允许的较强求解方法，按统一预算重新执行；不能引用历史15/90分钟赛事结果当作60秒同条件对照。

先导每例60秒含启动、导入、解析、求解与写出；开发环境外层4 CPU/12 GiB。最终v0.1应根据原始实例规模校准评测成本、超时率与改善空间，再锁定开发预算和每例限额。目标继续**无累计token cap**，单响应上限与用量统计独立记录。12小时和8192是已有先导值，不是已完成校准的最终发布值。

## 6. 核心验收门槛

- 从清洁包发现并加载所有嵌套输入；来源与文件清单必须包含“必需文件”契约检查。
- 原目标、风险分位、约束和checker语义一致；有可行/不可行/缺输出/超时测试。
- 真实无模型终评与n=1反馈往返通过，第二次超额调用被拒绝；再通过真实模型最小工具往返。
- 失败不把缺输入降级为算法零分；受控开发到时与无效最终解明确区分。
- 原先修复与新冻结包均通过清洁环境验收；开发反馈集与独立终评组互不重合。

## 7. 待定与阻塞项

**阻塞：** 修复版本完整运行验收和替代重复。**待定：** 核心实例范围、风险归一化、反馈粒度、求解器能力边界、线程/进程限制、发布数据许可与独立划分。先修任务包完整性，再扩大实验矩阵。

## 8. 原始竞赛排行榜与开发／测试数据

**公开资料核查日期：北京时间 2026-10-14。** 本节描述的是ROADEF/EURO 2020 RTE竞赛；赛事名称含2020，算法决赛结果实际在2021年公布，科学奖在2022年公布。原赛程、原排行榜和本卡§3的先导reward属于不同记录。[官方赛程](https://roadef.org/challenge/2020/en/calendrier.php)

### 8.1 原始排行榜、计分与参赛类别

原赛设Sprint、资格赛、半决赛和决赛。决赛合并 **C、X共30个实例** 排名：对每个实例，把15分钟与90分钟的原始目标值按 `V = 0.8 × F_15 + 0.2 × F_90` 加权，`V`越小越好；对于可行结果，该实例积分为 `max(0, 10 − 严格优于该队的队伍数)`，再求实例积分之和，总积分越大越好，理论上限300。官方规则的计算环境为Linux、2 CPU、16 GB RAM，按指定种子评测，不按多次随机重复的平均值排序。因此，下面的291等数字是**名次积分**，不是原始风险目标，也不是我们先导的0.373…归一化reward。[官方规则§2.3—2.6](https://github.com/rte-france/challenge-roadef-2020/blob/master/Challenge_Rules.pdf)

以下保留官方决赛页的全部13支队伍与并列名次；字母`S`、`J`分别表示Senior、Junior，表格本身是两类队伍合并的总榜。[官方决赛排行榜及逐实例结果](https://roadef.org/challenge/2020/en/finalresult.php)

| 决赛总排名 | Team ID／类别 | 队员 | 总积分 |
|---|---|---|---:|
| 1 | S34／Senior | Mirsad Buljubasic、Michel Vasquez | 291 |
| 2 | S66／Senior | Hue Chi Lam、Hanyu Gu、Thi Thanh Thu Pham | 236 |
| 3 | S56／Senior | Francisco Parreno、Ramon Álvarez-Valdés、Consuelo Parreno-Torres | 225 |
| 4 | S19／Senior | Luc Libralesso、Florian Fontan | 187 |
| 并列5 | J73／Junior | Marco Langiu | 139 |
| 并列5 | S68／Senior | David Torre Sanchez、Matthew Bold | 139 |
| 7 | S58／Senior | Marius Roland、Matteo Petris、Diego Cattaruzza、Martine Labbé、Martin Schmidt | 138 |
| 并列8 | J43／Junior | Hyunwoo Park、Jaegwan Joo、Youngjoo Roh、Lee Jerimi | 77 |
| 并列8 | J49／Junior | David Woller、Jakub Rada | 77 |
| 10 | J24／Junior | Maximiliano Frungillo | 49 |
| 11 | J3／Junior | Gabriel Gouvine | 48 |
| 12 | S14／Senior | Hugo Chareyre | 40 |
| 13 | S28／Senior | Lijun Wei、Jiawei Lin、Zhaohan Zhan、Lihui Huang、Jiawei Zeng、Jiadong Bu | 13 |

S34是官方明确宣布的总冠军；J73是上述总榜中排名最高的Junior队伍。原赛另外设最佳Junior、最佳Open Source和科学贡献奖，**奖项类别不等同于一张独立的算法积分榜**。决赛页的`SOURCE`列是部分团队的代码入口，例如[S34源码](https://github.com/mbmv7/rc)、[S56源码](https://github.com/FranciscoParrenoTorres/Roadef2020)和[S19源码](https://github.com/fontanf/localsearchsolver)，不能只因存在代码链接就宣称某队获得Open Source奖；本次查到的决赛页未单独列出该奖授奖结果。科学奖的官方获奖队伍为 **S58**，与其决赛总排名第7是两项不同信息。[官方奖项设置](https://roadef.org/challenge/2020/en/prix.php)、[科学奖获奖结果](https://roadef.org/challenge/2020/en/scientificprizeresults.php)

历史阶段榜也公开：[资格赛A榜](https://roadef.org/challenge/2020/en/qualifresult.php)、[半决赛B榜](https://roadef.org/challenge/2020/en/semifinalfresult.php)。需要重建逐实例对照时，决赛页提供完整汇总工作簿[compiler_final.xlsx](https://roadef.org/challenge/2020/en/compiler_final.xlsx)以及[C组结果](https://roadef.org/challenge/2020/en/compiler_C.xlsx)、[X组结果](https://roadef.org/challenge/2020/en/compiler_X.xlsx)。这些是历史性能参照；要成为本benchmark基线，仍需检查代码许可、依赖与求解器许可，并在本benchmark的统一资源和时限下重跑。

### 8.2 原赛开发、阶段评测与隐藏测试

原赛是组合优化算法竞赛，没有监督学习意义上的标签训练集。开发者取得完整实例输入、问题定义与checker，开发能处理新实例的求解程序。官方规则列出四组、每组15个实例，共60个；A是小／中规模，B、C、X是常规工业规模。规则给出的规模上限包括1000项干预、365个时间段和15类资源，不能据此假定每个实例都达到上限。[官方规则§2.3](https://github.com/rte-france/challenge-roadef-2020/blob/master/Challenge_Rules.pdf)

| 原赛数据组 | 实例数／编号 | 比赛进行期间的角色与可见性 | 当前公开状态与入口 |
|---|---|---|---|
| A | 15，A01—A15 | 初始公开开发数据；用于Sprint和资格赛。官方赛历记录2020-04-01提供题面、checker和A组 | 公开：[A_set.7z](https://github.com/rte-france/challenge-roadef-2020/raw/master/A_set.7z) |
| B | 15，B01—B15 | 资格赛后提供的公开数据；用于半决赛。官方赛历记录2021-01-05开放B组 | 公开：[B_set.7z](https://github.com/rte-france/challenge-roadef-2020/raw/master/B_set.7z) |
| C | 15，C01—C15 | 决赛前公开，供最终程序开发和提交解；同时计入决赛。因此它不是比赛期间始终隐藏的测试组。官方赛历记录2021-03-16开放C组 | 公开：[C_compact.7z](https://github.com/rte-france/challenge-roadef-2020/raw/master/C_compact.7z) |
| X | 15，X01—X15 | 比赛期间隐藏，由组织者运行提交程序，和C联合形成决赛总榜；规则说明比赛结束后公开 | 当前公开，分成两个下载包：[X_compact_1_1.7z](https://github.com/rte-france/challenge-roadef-2020/raw/master/X_compact_1_1.7z)、[X_compact_1_2.7z](https://github.com/rte-france/challenge-roadef-2020/raw/master/X_compact_1_2.7z)。X1/X2是X组的分包，不是额外两组各15例 |

数量与阶段用途依据[官方规则§2.3—2.4](https://github.com/rte-france/challenge-roadef-2020/blob/master/Challenge_Rules.pdf)，发布日期依据[实际赛历](https://roadef.org/challenge/2020/en/calendrier.php)，现有下载入口依据[官方实例页](https://roadef.org/challenge/2020/en/instances.php)。需要注意，规则概述称C在半决赛后开放，但更新后的赛历把C开放时间列为2021-03-16、半决赛提交期限列为2021-04-02；实际复原可见性时应采用具体赛历，不把“C曾提前公开”改写为隐藏测试。RTE仓库另提供`exemple1.json`、`exemple2.json`两个功能示例及checker，不应把示例再计入上述60个工业实例。[RTE官方checker说明](https://github.com/rte-france/challenge-roadef-2020)

### 8.3 与本项目先导及v0.1划分的关系

本卡§3的4实例先导全部取自A组：A_07/A_09作公开开发，A_08/A_12作过程反馈与终评。它不是对原赛全部A组、原赛C/X决赛面板或隐藏X组的复现；每例60秒、1 CPU、2 GiB也不同于原赛15／90分钟的预算。

v0.1的`Public development / Public selection / Protected feedback / Final test`是本项目拟建立的四种用途，**不能把原赛A/B/C/X四个字母一一机械对应过去**：原赛C在决赛前可见，X现在也已公开且有最佳值表。若后续使用C或X作服务端留出，需要冻结具体版本与实例清单，并披露“当前执行隔离的公开历史实例”及潜在历史知识污染；它们不会因此恢复成原赛当年的未公开测试。四组的难度、规模与历史暴露程度需要先统计，再确定独立划分；本次补充原赛信息并不代表这些v0.1划分已经落盘或完成验收。

## 9. 公开来源

- [RTE官方ROADEF 2020问题仓库](https://github.com/rte-france/challenge-roadef-2020)：问题、checker与数据来源入口。
- [原赛规则](https://github.com/rte-france/challenge-roadef-2020/blob/master/Challenge_Rules.pdf)、[原赛实例与checker入口](https://roadef.org/challenge/2020/en/instances.php)、[原赛最终排行榜](https://roadef.org/challenge/2020/en/finalresult.php)：用于核对原赛数据角色、规模、计算预算与历史成绩。
- 正式发布需逐项锁定原始数据、checker及适配版本，并核验各自许可；当前只发布协议与先导摘要。

## 10. 本次选定的可执行Adapter与公平排行路线

**2026-10-14设计决定：先在原C+X面板按15/90分钟结构做冻结算法历史参照；智能体泛化另设独立面板。** C、X现在公开，不能重称未触碰测试；硬件、种子与checkpoint执行语义的差异必须记录。原积分依赖对手，新增方法时重算固定集合的全部受影响方法，不把原冠军291积分直接插入新榜。[公平路线](../framework/fair-ranking.md#6-rtecx历史参照先行)。

| 合同项 | 本家族的选择 |
|---|---|
| 提交 | 通用求解器源码、dependency lock、参数与种子；运行时读取完整官方实例 |
| 输入/输出 | 完整Interventions/Resources/Exclusions/Seasons及风险情景；每项作业恰好一个1-based整数开始时段 |
| 权威评分 | 官方checker验全部约束与原风险目标，保存`F_15/F_90/V`、分项和成本；均值或CVaR近似不能替代原评分 |
| 公平性 | 同面板/目标/checker、同随机化与执行合同；商业与开源solver许可、线程和资源显式分赛道 |
| 基线覆盖 | 当前HiGHS+原目标局部搜索已有；[S34](https://github.com/mbmv7/rc)、[S56](https://github.com/FranciscoParrenoTorres/Roadef2020)源码公开，Gurobi依赖与构建/重放认证仍待完成 |
| 发布条件 | 必需嵌套文件完备性、原checker parity、30例完整重评、15/90快照及seed语义、许可审计与独立泛化面板 |

**就绪状态：`design / certification-pending / release_ready=false`。** 已准备/启动的重评不等于完成；旧A4验收也不替新冻结包签证。15/90分钟和原2 CPU/16 GB是历史协议参照，开发`T/n/资源/重复`仍不定值。详见[Adapter执行合同](../framework/task-adapters.md#5-rte风险目标求解与cx历史记录)与[机器声明](../../manifests/task-adapters/rte-maintenance.json)。

**2026-10-15集成证据更新：** A07／A09／A08／A12校准面板已通过真实Harbor与模型的n=0、n=1配对canary，验证公共选择、受保护反馈／显式ACK、共同截止前容器停止、算法冻结与独立原checker终评。两组均选择未修改starter；T=180秒与每例10秒只用于接口验收，不是原赛15／90分钟复现或正式研究配置。完整C+X、强基线同平台重评、许可／随机化审计与新泛化面板仍待验收，任务认证状态保持不变。[中文结果与修复说明](../completion-step3-cluster-20261015.md)、[脱敏机器证据](../evidence/harbor-cluster-acceptance-20261015.json)。


## 11. 原题对齐与参数依据（2026-10-15）

本节更新第1—10节保留的历史设置状态；下列是本轮设计决定，**不表示新面板已认证、基线已重跑或新分数已生成**。已有A4 canary仅证明此前列出的接入路径。共同研究设计已定为T=43200秒、n=0／1／3／5／10、每档3次独立开发、累计token不限；模型、实际资源及其余执行限额仍须锁定或校准，详见[共同政策与取值依据](../protocol/task-alignment-and-calibration.md#2-四类取值依据与本轮已定设置)。

| 旧差异／待明确项 | 本轮决定与依据 | 实际剩余工作 |
|---|---|---|
| A4接入规模小；均值MILP仅近似搜索目标 | 保留完整干预、资源、时段、风险情景和原Alpha／Quantile语义，由原checker计算权威风险 | 核对完整输入及checker；不能用均值或CVaR替换原评分 |
| 先导60秒、canary 10秒与原赛15／90分钟并存 | agent主线逐例预算另做成本校准；C+X历史参照保留F15／F90及V=0.8F15+0.2F90，两者分开 | 锁定agent预算与计时边界；完整C+X重评不作为75次agent实验的先决条件 |
| A07／A09／A08／A12已暴露且复用终评 | A4保留校准；本地实际有A组15例，须另定角色；只用A组不主张C+X或常规工业规模泛化 | 盘点来源／难度，绑定不同成员及访问权限，避免把旧反馈重新命名为全新final |
| 原榜积分依赖对手；强方法有许可／构建条件 | 同预算重跑HiGHS均值MILP与原风险局部搜索；S34／S56为待核验参考，历史积分独立列示 | 核许可、依赖、seed与checkpoint语义；重算历史积分时固定对手集合，不能直接减原冠军积分 |

详见[RTE逐项决定](../protocol/task-alignment-and-calibration.md#6-rte保留原风险分开agent实验与历史时间档)及[校准和进入正式实验的条件](../protocol/task-alignment-and-calibration.md#10-怎样消除参数随意)。任务仍为`certification-pending / release_ready=false`。


## 12. 第一阶段：固定X04算法演化（2026-10-15）

**用户已初选完整工业实例X04（`X_04.json`）。** 第一阶段研究同case算法演化，开发、计数反馈和截止冻结后的重新执行复核均用此case；其他case泛化留下一阶段。本节覆盖第1—11节中与此冲突的四角色划分、免费完整自测和public-selection选择设计，保留历史内容供追溯。

选例依据已做只读独立核查：组织方归档13支队伍在X04的15分钟／90分钟有效记录分别为**6／13、7／13**。按15分钟有效队数、90分钟有效队数依次升序，前五为X04(6,7)、X15(8,12)、X10(9,9)、X09(9,10)、X02(9,11)，第六X12(9,12)。这是历史可行性难度指标，不证明所有意义上的绝对最难；还须测完整实例成本和改进空间。自有旧候选在X04两档均AC，F15=11560.512、F90=11494.032；加权V=11547.216的**单例历史插入积分为7分**，不是每档各7分，不是新官方名次。自有C15／X06两档RE不能直接作为更难依据：原赛15分钟档两例均有11／13队有效。

共同研究设计已定：T=43200秒，n=0／1／3／5／10各3次独立开发，累计token不限且不做累计预留截断。**禁止开发agent获得完整checker／public_eval，禁止完整目标本地算分及搜索原赛测评源码。** 完整目标反馈只能调用框架评分器并计入n；允许语法、格式及小型示例检查。solver在可信执行中计算内部目标不因此被禁止。完整X04输入的开发可见范围及有效隔离方案尚未确定，不能据同case设计擅自默认全部可见或全部隐藏。

无免费public-selection完整评分。agent在T内把最终版本放进原生artifacts路径，截止收集并冻结；无修改保留共同starter。冻结后按同case、同checker、同seed政策、同算法预算和资源重新运行，结果不回流开发且不占过程n。n=0没有过程完整目标评分。单case原始指标可以与原榜该例比较；条件不同标历史参照，不能推导原赛总榜或跨case泛化。

| 当前状态 | 内容 |
|---|---|
| 已定 | 第一阶段固定case研究、优先高难完整实例、X04初选、n／T／重复／token政策及禁止本地完整评分 |
| 待校准 | X04完整输入／checker版本、实际可见边界、每次算法时限、资源、seed、反馈schema和失败政策 |
| 待确认 | 模型／agent版本、共同starter及开发资源；15／90分钟仅为历史参照和成本测量候选，非已定正式值 |
| 尚未完成 | RTE运行代码修复、新X04成本测量、升级框架上的评分通道／截止冻结验收、15次正式RTE实验 |

较新eval-in-loop `chufan_dev`已安全切换到本地；单测及真实任务验收仍须核对，不能把黑名单功能存在当作封住所有评分旁路。最短顺序是：**锁完整X04和可见边界 → 无模型可信成本测量 → 冻结剩余配置 → 只修原生task必要缺口 → n=0／正n及冻结复核验收 → 正式批次。** 原题全部干预、风险情景和原Alpha／Quantile目标不裁减，不额外建设平台。

完整依据、资源差异和待定项见[X04配置确认与最小验收](../protocol/rte-x04-configuration.md)，政策见[固定case算法演化决定](../decisions/0005-fixed-case-evolution-first.md)。本次没有运行新基线或产生新分数，状态仍为`certification-pending / release_ready=false`。

## 13. 当前任务包：ABC开放、X15受保护反馈（2026-10-15）

**本节覆盖§12及此前与新划分冲突的研究政策；原赛资料与历史实验记录保留。** A／B／C共45个完整实例开放开发，允许官方checker本地评分；X15仅放在评测端，过程每例900秒、15路并行，完整面板每次受理计一次n。开发T=12小时、n=0／1／3／5／10、各三次独立开发，累计token不限。

提交通用`solver.py`。截止冻结唯一最终源码，随后在同一X15上独立运行每例5400秒档，不回流、不占过程n。X是有限反馈的自适应评测面板；不称独立未见测试。该版本不再以X04单例作为开发／反馈／终评全集，也不再禁止ABC完整自测。

资源为开发端2 CPU、评测端15 CPU，内存／存储采用显式初始配额待实测。完整原始输入、官方checker及逐例哈希固定；n只改变受保护反馈机会，不能随n改变实例或资源。过程reward保留严格全15例有效规则与输入归一化；原始F、有效率与失败结果均保存，不直接宣称原赛完整榜。

来源与数据准备、命令、反馈字段、最终评测和验收边界见[新版配置](../protocol/rte-abc-x15-configuration.md)，政策见[决定0006](../decisions/0006-rte-abc-open-x15-protected.md)。新源码包见[原生task目录](../../task-packages/rte-maintenance-abc-x15-v1/README.md)。正式认证仍待Linux／Harbor、整套X并行资源与网络隔离验收，`release_ready=false`。
