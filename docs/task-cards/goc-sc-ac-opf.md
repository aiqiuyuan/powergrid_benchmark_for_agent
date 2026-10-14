# GOC 安全约束交流最优潮流

> 状态：已完成多规模先导实验；本卡定义拟定的 v0.1 研究协议，尚未完成独立数据划分与验收。历史证据截止北京时间 2026-10-13 23:32；修复准备核对至 23:38。卡片不表示已发布可运行的 benchmark。

## 1. 家族定位与研究能力

**家族 ID：`goc-sc-ac-opf`。** 以 GOC Challenge 1 的安全约束交流最优潮流为基础，覆盖非凸连续优化、物理可行性、故障批量处理、分解求解和工程实现。GOC500、793、2000、2312是同一家族的规模或难度分层，不计为四个独立任务家族。

核心版本优先选择能在常规实验预算内完成完整评分的中等规模实例。GOC30000保留为规模与可靠性扩展；其长评测时间不适合作为 v0.1 常规反馈矩阵的必测项。

## 2. 演化对象与执行合同

- 演化对象：通用基态与故障求解算法、初始化、数值策略、故障分解和调度代码；不得修改物理问题、官方评分语义或指定故障集。
- 提交产物：可执行求解器源码、依赖锁定、参数和随机种子。参数可学习，但必须披露训练来源；每实例预先存好的答案不能替代通用算法。
- 目标终评：冻结后在评测端读入留出实例，执行 Code1/Code2 等规定接口，检查输出完整性、官方有效性/可行性与目标值。完整指定故障覆盖是验收条件。
- 指标：保留原始 `J`、硬约束可行性、软惩罚分项、故障覆盖、求解时间及峰值内存。不同网络的 `J` 不直接相加；跨实例比较需按固定参考算法归一化并同时保留原值。
- 求解器许可、CPU线程与子进程、GPU、外部服务、预训练权重以及商业求解器使用须随版本声明；不能把商用求解器能力混入未标注的演化效果。

## 3. 已有预实验与能支持的结论

| 先导设置 | 结果与限制 |
|---|---|
| GOC500 / scenario_67，n=5，3次，48小时开发 | 3次正式有效可行；最好 `J=297,568.566878`，693个故障完整覆盖 |
| GOC2000 / scenario_25，n=5，3次，48小时开发 | 3次正式有效可行；最好 `J=988,323.296509`，2421个故障完整覆盖；有开发内存与产物导出风险 |
| GOC2312 / scenario_21，n=5，3次，48小时开发 | 镜像拉取修复并替代补跑后3次有效；最好 `J=373,758.650134`，982个故障完整覆盖 |
| GOC793 / scenario_195，n=0/1/3/5/20，各3次，8小时开发 | 14/15有正式分数；n5-r1收尾失败。各n有效样本均值依次为203,823.242399、201,787.868551、201,787.696113、201,791.434421（仅2次）、201,782.241176 |
| GOC793 n=20 | 实际计数17/15/20；最好 `J=201,771.320653`。不能把允许20次写成三次都使用20次 |
| GOC30000 新批，12槽位 | 1次正式有效、2次实际运行、2次失败、7次未启动或恢复排队；不作为核心可批量运行已经稳定的证据 |

以上是各冻结场景上的优化成绩，不是独立跨场景泛化测试。GOC793已有轨迹显示读取官方 evaluator 与构建全量本地估分器；**公开目标、可行性检查与 evaluator 知识本身是合法的优化信息**。真正需要厘清的是是否能访问受保护实例、受保护结果或等价的非公开信息。因此旧批不足以证明严格受控的 protected-feedback 因果比较，也不能仅凭下载 checker 就判定作弊。

## 4. v0.1 数据与反馈协议（拟定）

| 数据角色 | 拟定安排 | 与先导的差异 |
|---|---|---|
| Public development | 公开训练网络/场景，允许完整目标、约束、自测和局部代理估分 | 明确允许信息，避免把求解器内部迭代误计为反馈 |
| Public selection | 独立公开选择场景，按发布的聚合指标选唯一候选 | 当前多批只围绕固定场景开发，需要增加选模规则 |
| Protected feedback | 独立且不挂载于开发端的网络/场景，由服务执行候选并返回固定聚合结果 | n控制该面板的信息访问，而不是已知实例上的本地目标计算 |
| Final test | 开发、反馈、选模均未使用的留出网络/场景；冻结后仅终评 | 原先已反复优化的场景只能进入开发/校准，不声称未触碰 |

按基础网络或场景来源分组再划分，防止同一网络的近似场景跨组泄漏。确切实例、数量、场景关系、许可与数据再分发方式均**待校准与来源核验后冻结**。公开历史数据的访问隔离不等于排除了模型预训练污染；声明其公开性并记录额外信息暴露。不能通过更改样本 ID 把已使用的数据重新包装成未使用的测试。

## 5. 基线、预算与校准

可信起点是当前可行 starter 和固定完整数值求解器；应重跑同一参考求解器并保存失败率、目标、容差与资源。另设可行初始化/简单故障修复基线，用于验证评分能辨别改进；不得人为削弱完整求解器。基线最终配置与结果仍需统一校准。

| 已测资源/时间 | v0.1处理 |
|---|---|
| GOC793：开发8 CPU/16 GiB，数值24 CPU/56 GiB；Code1 600秒、全部Code2合计172秒；开发8小时 | 作为校准起点；不自动成为所有场景的最终预算 |
| GOC500：开发2 CPU/16 GiB；GOC2000：8 CPU/16 GiB；GOC2312：8 CPU/32 GiB；数值均24 CPU/56 GiB | 资源差异须显式分层；先测单次完整反馈成本与成功率 |
| GOC500/2000/2312的Code2预算分别1386/38736/15712秒 | 长评测会减少可取回反馈，需据评测成本确定主实验难度和截止策略 |

目标采用开发墙钟上限、**无累计 token cap**、独立单响应输出上限与用量统计；不改写历史记录。开发截止后的结果可归档，不能让代理继续修改。开发、公开选择、反馈等待和终评的计时边界按统一协议执行；具体开发时间及响应上限待统一冻结。

## 6. 核心验收门槛

- 清洁环境能重建任务，并完整执行参考求解器；数据、代码、依赖与评分版本有锁定记录。
- grader能识别缺故障、无效输出、硬约束违规；软惩罚按官方语义计入，不能混同于硬不可行。
- 反馈与终评对同一冻结算法使用同一物理定义、容差及资源语义。
- 候选、基态、输入和分片哈希一致；恢复不跨候选拼接结果；反馈完成、送达和冻结均可追溯。
- 修复收尾、内存与导出路径后，在目标并发下稳定完成中等规模矩阵；GOC30000另外接受规模测试。

## 7. 待定与阻塞项

**尚未冻结：** 核心规模范围、留出网络分组、每实例求解限额、跨实例聚合、允许求解器清单、反馈信息粒度、独立测试面板和基线参考值。先解决固定场景自适应优化与通用算法评测的区别，再解释预算消融。

## 8. 原始竞赛排行榜与开发 / 测试数据

### 8.1 原赛身份与最终排行榜

**原始赛事：ARPA-E Grid Optimization Competition，Challenge 1（2018—2019）；Final Event 4于2019年10月31日截止，获奖结果于2020年2月12日公布。以下为2026-10-14核验的历史榜单，不是当前实时排名。** 原赛有四个独立 division：Division 1/3为Real-Time，Code1限10分钟；Division 2/4为Offline，Code1限45分钟。Division 1/2按网络内、网络间两层几何均值比较目标值，越小越好；Division 3/4按performance profile排序，不能把一项场景的`J`写成总榜分数。[官方补充说明](https://data.openei.org/files/6153/Challenge%201%20Additional%20Info.pdf)、[原赛评分规则](https://data.openei.org/files/6153/Challenge_1_Scoring.pdf)。

下表直接读取[官方Final Event结果工作簿](https://data.openei.org/files/6153/C1_E4_scenario_results_20200106.xlsx)的`Division 1`、`Division 2`页，第415行`Synthetic Dataset Geomean Rank`与第419行`Full Dataset Geomean Rank`，未根据列顺序推断排名：

| 榜单范围 | 第1名 | 第2名 | 第3名 |
|---|---|---|---|
| Division 1，全量终赛（含工业实例） | Lawrence Livermore National Laboratory | Georgia Institute of Technology (Sun) | University of Colorado Boulder |
| Division 2，全量终赛（含工业实例） | Lawrence Livermore National Laboratory | BAT | Lehigh University |
| Division 1，仅合成数据 | Lawrence Livermore National Laboratory | Lehigh University | Georgia Institute of Technology (Sun) |
| Division 2，仅合成数据 | Lawrence Livermore National Laboratory | Lehigh University | Georgia Institute of Technology (Sun) |

**榜单缺口：** 当前归档工作簿实际只有上述两个页签，保留了目标值与聚合名次；没有可直接读取的全量终赛总分及Division 3/4最终排名。因此本卡不补造这两项排名、也不以工业实例的公开名次反推保密目标值。归档网页对工作簿的“含完整Results与Rankings页签”描述与实际下载内容不一致，应锁定实物文件后引用。官方历史[leaderboard入口](https://gocompetition.energy.gov/challenges/challenge-1/trial-event-leaderboards)本次未能正常访问；上述核验依据为仍可下载的官方结果归档。

为对应当前五个规模，官方`Division 1`页中相同网络/场景的历史最低场景目标如下；这些是**单场景参考值**，不是队伍总榜分数，也不能据此宣称我们的算法取得原赛名次。[官方场景结果工作簿](https://data.openei.org/files/6153/C1_E4_scenario_results_20200106.xlsx)。

| 对应预实验 | 原赛网络 / 场景 | 官方历史最低`J` | 该场景最低值队伍 |
|---|---|---:|---|
| GOC500 | Network_02R-173 / 67 | 296,489.189505 | BAT |
| GOC793 | Network_03R-200 / 195 | 201,790.245975 | Lawrence Livermore National Laboratory |
| GOC2000 | Network_06R-124 / 25 | 988,356.792003 | Lawrence Livermore National Laboratory |
| GOC2312 | Network_70R-422 / 21 | 374,222.320075 | Lawrence Livermore National Laboratory |
| GOC30000 | Network_30R-048 / 15 | 1,123,319.661123 | Lawrence Livermore National Laboratory |

原赛统一平台可用144 CPU cores、6个节点各64 GB内存；当前预实验的资源、开发时间和部分Code2限额不同。历史最低值用于核验目标量级和建立参考算法，正式性能结论仍需在同一资源/时限/容差下重跑。[竞赛组织者与参赛者的Challenge 1综述，§4.2](https://arxiv.org/abs/2206.07843)。

### 8.2 原始开发集与测试集

原赛是**提交算法、由主办方运行的优化竞赛**。公开Sandbox实例相当于算法开发数据，Trial/Final事件数据承担当时的竞赛测试；原赛没有标准的监督学习`train.csv / validation.csv / test.csv`三分文件。网络描述、负荷/机组场景和故障集合构成一个实例，主要输入为`case.raw / case.rop / case.inl / case.con`。[官方数据格式说明](https://data.openei.org/files/6153/Challenge_1_Dataset_Format.pdf)。

| 原始阶段 / 数据包 | 原始规模与用途 | 当时与当前的可访问性 |
|---|---|---|
| Sandbox / Original Dataset 1 | 5个网络，每网络10场景；Real-Time与Offline各50，共100条网络-场景-模式记录；网络规模500/793/2000/2312/7977 buses | 公开开发数据；当前[Dataset 1归档](https://data.openei.org/files/6153/Challenge_1_Original_Dataset_1_Scenarios.zip)可下载 |
| Sandbox / Original Dataset 2，当前归档版本 | 4个网络；每种模式500/793/2312 buses各20场景、2000 buses有10场景；Real-Time与Offline各70，共140条记录 | 公开开发数据；本次核对[Dataset 2压缩包](https://data.openei.org/files/6153/Challenge_1_Original_Dataset_2_Scenarios.zip)共有140个`case.raw`；历史补充说明曾写80，与当前归档不一致，引用需明确版本 |
| Trial Event 1，实际计分子集 | 13网络×3场景=39/模式，共78；区别于为Trial 1准备的718场景大集合 | 当轮新测试数据；事后公开，[实际计分子集归档](https://data.openei.org/files/6153/Challenge_1_Trial_Event_1_Used_Scenarios.zip)；不得把准备量当作正式计分量 |
| Trial Event 2，实际计分子集 | 14网络×10场景=140/模式，共280；包含30000 buses网络 | 当轮测试，事后公开；[Trial 2归档](https://data.openei.org/files/6153/Challenge_1_Trial_Event_2_Used_Scenarios.zip) |
| Trial Event 3，实际计分子集 | 6网络×5场景=30/模式，共60 | 当轮测试，事后公开；[Trial 3归档](https://data.openei.org/files/6153/Challenge_1_Trial_Event_3_Scenarios.zip) |
| Final Event 4，合成测试数据 | 17网络×20场景=340/模式；Real-Time与Offline各340，共680条记录，规模500—30000 buses | 最终评测使用既有与未见网络/场景；合成数据于2019年12月3日公开，当前可下载[Real-Time包](https://data.openei.org/files/6153/Challenge_1_Final_Event_Real-Time_Synthetic_Scenarios.zip)与[Offline包](https://data.openei.org/files/6153/Challenge_1_Final_Event_Offline_Synthetic_Scenarios.zip) |
| Final Event 4，工业测试数据 | 3个实际工业网络×4场景=12/模式；与合成数据合计352个问题/模式 | 工业输入未公开；原参赛队伍仅获其聚合成绩，不具备重建完整原赛隐私测试集的公开数据条件 |

阶段与公开状态依据[官方归档](https://data.openei.org/submissions/6153)、[官方补充说明](https://data.openei.org/files/6153/Challenge%201%20Additional%20Info.pdf)及[Challenge 1综述§4.1](https://arxiv.org/abs/2206.07843)。Real-Time提供起始运行点，Offline不提供同样的起始信息；一对模式记录不能当作两个独立电网样本。归档还提供部分Week-Ahead场景，但其未用于Challenge 1竞赛评分。[官方归档的模式说明](https://data.openei.org/submissions/6153)。

**对本benchmark的直接约束：** 当前GOC500/793/2000/2312/30000固定场景来自已经公开的原赛Final合成数据，且已用于预实验优化，只能作为我们的开发/校准实例。原赛的“Final”文件名不能赋予其本研究未触碰测试集的身份。后续需按基础网络与场景来源关系重新划分四个数据角色，并记录公开数据暴露与既有使用；工业终赛数据不可获取，不能宣称完整复现原赛全量榜单。以上为本项目基于原赛数据状态制定的设计要求，独立终评划分仍待冻结。

## 9. 公开来源

- [ARPA-E GOC Challenge 1 数据目录](https://catalog.data.gov/dataset/arpa-e-grid-optimization-go-competition-challenge-1)：问题与数据来源入口。
- 原始评分器、数据版本与适配应在正式实现中附来源锁定及许可记录；本仓库当前不再分发未核验的原始数据或上游代码。
