# RTE ABC／X15任务包：配置、使用与验收

**日期：2026-10-15。当前范围：任务源码、完整本地数据准备和本地测试；集群运行认证待完成。** 本文落实[决定0006](../decisions/0006-rte-abc-open-x15-protected.md)，替代此前X04单例配置，不修改旧任务或旧实验结果。

## 1. 本轮确定的设置

| 项目 | 取值及含义 |
|---|---|
| task ID | `rte-maintenance-abc-x15-v1` |
| 开放数据 | A、B、C各15例，共45例，完整输入与官方checker可自由用于开发 |
| 受保护面板 | X01—15，过程与冻结后均评完整15例 |
| 开发预算 | T=43200秒；n=0／1／3／5／10；每档3次独立开发；累计token不限 |
| n的单位 | 一个完整X15面板申请被框架受理，计一次；分别记录受理／完成／投递 |
| 过程算法时间 | 每例900秒，包括启动、导入、解析、建模、求解与写出 |
| 过程并发 | 15个独立worker，候选各固定一个不同可用CPU；BLAS／OpenMP默认线程数1 |
| 开发资源 | 2 CPU、32GiB内存、32GiB存储、无GPU；内存与存储为初始试配 |
| 评测资源 | 15 CPU、128GiB共享内存、32GiB存储；内存与存储待峰值校准 |
| 候选内存 | 每例8GiB虚拟地址空间上限，不是已测RSS；完整X的充分性待验 |
| 基础设施预算 | 每例数据准备／worker开销预留120秒、checker预留180秒；runner1500秒，verifier1800秒 |
| 最终算法时间 | 截止冻结后，独立启动每例5400秒、15路并行；runner6300秒 |
| 随机化 | 当前task固定seed=2020；每档三次是独立开发，不是只换solver seed |
| 算法提交 | `/app/submission/solver.py`，不超过1MiB；输出排程上限4MiB |
| 依赖 | Python3.12、NumPy2.2.6、SciPy1.15.3，BLAS／OpenMP默认线程数1；允许候选线程共享该例唯一CPU |
| starter | 继承既有RTE先导算法，SHA256 `ed51f16524846e40ba7f6b51ef3158a2081e41fa1def51b2fd21fcbbf4b7f86d` |

15 CPU是容器计算额度，不等于独占15颗物理核。外层作业必须容纳开发2＋评测15及系统开销；包内示例预留4 CPU和8GiB，合计21 CPU／168GiB，不是用户已获批资源，也不是原赛平台复现。并行能力不降低总CPU工作量；不同自适应反馈轮次仍需等待上一轮结果后再修改算法。

内存初始配额是为了提供可审查的启动设置，不把未测数据填写成已验证参数。B15原JSON接近4GB，开发算法应按需读取；starter大例解析／建模可能超限。若验收发现配额不足，须在正式n比较前统一调整并锁版本，不能只为某个候选或n档放宽。

## 2. 数据准备与来源

[公开源码包](../../task-packages/rte-maintenance-abc-x15-v1/README.md)不携带大型实例。原始源固定官方commit `052def4d47271f913f89a68169083059732360f3`，五个原包的URL、字节、SHA256和Git blob见[归档锁](../../task-packages/rte-maintenance-abc-x15-v1/data-archives-lock.json)。官方B包内部目录为`B_set_rounded`，C／X来自compact包；保留原始数值与字节，不自行再舍入。[官方仓库](https://github.com/rte-france/challenge-roadef-2020)

本轮本地准备得到：ABC共16,139,351,422字节，X共7,174,022,647字节，总计23,313,374,069字节。60例已完成原包对应、逐文件SHA256、流式JSON结构和风险向量长度检查。逐例输入归一化常数以低内存计算；A09、B05、X04与原先函数结果位级一致。它们是数据准备证据，不是算法完整运行或checker性能测量。

操作者取得固定五个原包后，在本task目录执行：

```sh
python prepare.py --archives-dir /data/official-archives
```

也可指定四组已解压目录，X目录需包含两个分包的全部15例：

```sh
python prepare.py --a /data/A_set --b /data/B_set --c /data/C_set --x /data/X_set
```

准备阶段需要`py7zr`和`ijson`；脚本先核验归档／实例，再重建两个独立上下文：`environment/app/public/`仅ABC，`tests/data/`仅X。不要把整个任务目录、数据库存、旧实验或操作者工作区挂载给agent。流式准备避免一次读入完整数GB JSON；运行算法是否流式由候选决定。

## 3. 提交接口和ABC自测

候选使用以下命令行接口，评测器为每个实例分别启动：

```sh
python solver.py --instance instance.json --output schedule.txt --time-limit 898 --seed 2020
```

`--time-limit`为候选内部主动停止预留约2秒；权威外部候选墙钟仍是900秒。每项干预恰好输出一次合法整数开始时段，最终有效性和风险目标均由固定官方checker计算。solver自报objective不被采信。

ABC可在开发端自由自测，例如仅选一例，避免默认跑全部45例：

```sh
python /app/support/public_eval.py --case A_01 --seconds 60 --workers 1
```

ABC本地评分不计n，但计入开发T与资源。受保护X只能走框架正式提交接口；一次受理运行全部X15，等完整面板完成才返回汇总。不能把某例先完成的结果当作额外过程反馈。

## 4. 反馈与分数

过程返回：normalized_score、feasible_fraction、verdict计数、constraint_errors计数。全部15例有效时再返回mean_official_objective、mean_risk、mean_excess；mean_excess是原目标使用的正向分位超额，不是CVaR。candidate可行性与评分器成功完成分别保存。

原始F越低越好；反馈质量为`q_i=0.5-atan(F_i/s_i)/pi`。各s_i仅由原输入计算并锁定，全部15例有效才等权平均，否则面板质量0；有效比例和失败类型仍报告。保留逐例F、状态与资源记录供操作者审计，不向agent返回X原数据、逐例分数、候选日志、排程或风险向量。详见[数据锁](../../task-packages/rte-maintenance-abc-x15-v1/data-lock.json)。

本方案未修改原生框架的受理计数。缺输入、checker失败、资源不足等基础设施错误须作为错误报告，不解释成算法低分；是否重跑由原协议记录，不能无记录提供额外开发反馈。

## 5. 截止冻结与90分钟评测

截止由原框架停止开发并收集最终artifacts，操作者对这一源码生成冻结副本和摘要；没有修改时保留starter。最终工具核验摘要，使用同一X15每例5400秒，结果仅供操作者保存，不调用过程反馈账本。不能在开发仍运行时挂载最终报告或借此选优。

```sh
python tools/freeze_candidate.py --candidate /private/final-artifact/solver.py --output-dir /private/frozen
```

随后按[任务README](../../task-packages/rte-maintenance-abc-x15-v1/README.md)中的Docker命令运行`final_evaluate.py`。工具检查完整X15与冻结摘要、拒绝覆盖已有报告，保留5400秒结果。该工具证明的是源码一致性；开发停止、截止产物来源仍由操作者和原框架记录保证。


原生Harbor终验仍调用本task的900秒入口，形成截止源码的不回流900秒记录；5400秒档由独立工具随后运行，不会因改变过程反馈时限而自动执行。两者都必须绑定同一截止产物。

过程900秒与最终5400秒均独立启动，不是同轨迹快照。最终90分钟评估不消耗过程n，也不回流。若要对冻结算法计算历史双档加权值，应采用同一冻结源码的原生不回流900秒记录（或按同条件补做），披露两档独立执行，不能拼接开发历史最佳分。

## 6. 启动前仍要核验什么

直接沿用eval-in-loop／Harbor，不新增平台。操作顺序为准备数据 → 构建runtime／developer／verifier镜像 → 解析并检查原生计划 → Linux小例隔离验收 → 整X15资源与超时实测 → n=0／正n小规模端到端 → 冻结配置后正式15个RTE开发run。

Codex采用当前已核查的Harbor时需在镜像中预装CLI，避免默认NVM安装被GitHub域名封禁阻断；正式启动前核验版本。PersistentAgent仍沿用1800秒续跑余量，各n档需统一persist／max_resumes并记录实际开发时长。

启动时必须启用egress，禁用agent内置搜索，确认任务域名规则确实作用于实际客户端；关闭额外snapshot评分。原生runtime会从task读取1800秒评测超时，不能沿用旧A4的300秒设置。完整计划须核对T=43200、n语义、模型profile、资源不被站点封顶及镜像标识。

尚未完成的实际验收包括：15CPU可调度性、Linux seccomp／权限与扩核EPERM、完整X15解析／求解／checker峰值、实测吞吐和反馈延迟、网络绕过／镜像取回X、真实模型截止冻结、starter全X可行性和强基线同条件重跑。基础镜像标签与apt依赖仍须在正式批次前记录实际digest。

X已经公开，旧结果曾被研究者使用；域名黑名单不覆盖所有镜像、直接网络或模型记忆。不同UID和scratch权限也不等于完整文件系统隔离，共享临时目录存在残余通道。当前代码与本地测试不冒充部署认证；`release_ready=false`。
