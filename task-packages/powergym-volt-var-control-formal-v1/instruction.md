# PowerGym 123Bus 配电网控制正式实验 v1

修改并提交 `/app/submission/controller.py`，实现
`Controller(metadata).act(observation) -> list[int]`。只收集这个单文件，使用
Python 标准库，参数应保存在文件中。不得依赖其他未收集文件、在线服务或保存好的目标动作轨迹。
各 n 条件共享本合同、初始文件和完整目标；开发时长与反馈额度由外部冻结实验配置规定。

目标是锁定 123Bus、profile 0、负荷倍数 2.5 的24个一小时转移。动作依次为4个
电容器 0/1、7个调压器 0..32、4个电池 0..32。电池16为空闲，0请求充电
100kW，32请求放电100kW，每档6.25kW。全零动作不是保持现状。初始化电容器
均开、tap 均32、电池各1000kWh，容量各1000kWh。请求按每台剩余能量投影到
合法离散功率档位；实际积分使用 OpenDSS Generator 端口有功，不以请求功率代替。
能量账本在每小时 clip 到容量后用 Python `round` 舍入到整数 kWh，保留原物理
及舍入语义。Generator 无功采用原 `Q=P/0.95` 约定。

metadata 提供设备数量、有序名称、动作上界、容量、最大功率、时域与初末 SOC。
observation 包含 `step`、`capacitor_states`、`regulator_taps`、`battery_soc`、
`battery_actual_kw` 和 `bus_voltages`（bus 到各相 pu 幅值的字典）。第0步电压
为首时段空闲初态测量；之后电压和实际电池功率为上一已执行时段测量，当前 SOC
为已更新账本值。不提供负荷矩阵、当前或未来负荷查询、预测、DSS 模型或仿真接口。
可以在 Controller 实例中保留历史；每次评价创建新实例。受信执行时总进程30秒、
每次动作响应1秒、初始化5秒，CPU10秒、内存512MiB；不允许网络和子进程。
源码上限1,000,000 bytes，输出动作必须是15个范围内的 Python int（不接受 bool）。

硬约束为动作合法、全部24步潮流收敛与物理测量有限、每台末端账本能量距初值
不超过1kWh，并且每台 `abs(sum(actual_battery_kw)*1h) <= 1kWh`。
任一不满足，分数为0。电压越限作为软成本，允许有效轨迹仍有电压违规。
有效完整轨迹评分：

`quality = 1 / (1 + V + L/1000 + (C+R)/33)`。

V 是24小时逐 bus 的最高相超过1.05pu及最低相低于0.95pu的幅值积分，单位 pu·h。
L 是 whole-circuit 实际有功网损积分，单位 kWh；C 为电容器切换次数，R 为 tap
移动档数之和。`1000` 和 `33` 是本 benchmark 的冻结成本尺度；它们不是论文
原始评分，也未依本轮 n 实验结果调整。反馈只给完整日汇总质量、V、L、合规率、
操作、吞吐与初末能量等声明指标；不给完整目标轨迹或动作序列。受理后的异常、
超时、非法动作和终能量失败是有效计数的零分反馈。

数值求解与已完成强基线保持一致：snapshot/controlmode=off、每次显式设置当小时
负荷，tolerance=1e-10、BuildYMatrix(2,True)，并将 SolutionInitialized 设 False。
每次完整评价隔离可写目录。此合同是固定单案例控制研究，开发反馈与终评使用
同一完整案例；不声称跨日期独立性或原论文曲线复现。完整数据和 checker 只在
独立受信 verifier 中。可用 `python /app/support/check_interface.py` 做合成接口
检查；完整目标评价必须使用平台计 n 入口，n=0 不提供过程目标反馈。

候选沙箱要求 Landlock ABI≥1。ABI1/2 下额外禁止文件截断、creat、带 O_TRUNC
的打开方式及 openat2；私有目录可独占新建或追加文件，不能使用 `open(...,"w")`
覆写。建议将历史保存在实例内存。ABI≥3 由 Landlock 保护截断操作；所有版本
均禁止访问其他控制器目录、共享临时目录和可信数据。
