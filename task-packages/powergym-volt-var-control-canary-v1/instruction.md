# PowerGym 34Bus 因果控制流程试验

修改并提交 `/app/submission/controller.py`，实现
`Controller(metadata).act(observation) -> list[int]`。这是10分钟开发时限的流程
canary，不是12小时正式研究比较；只收集这个单文件，使用Python标准库，所有参数
必须在文件中。不得依赖其他未收集文件、在线服务或保存好的目标动作轨迹。

完整目标是锁定34Bus配电网的24个一小时转移。动作顺序为2个电容器0/1、6个
调压器0..32、2个电池0..32。电池16为空闲，0请求-500kW充电，32请求500kW
放电，每档31.25kW。全零动作不是保持现状。初始化电容器均开，调压器均32，
电池均4000kWh，容量各4000kWh。电池动作按剩余能量投影到合法离散档位。
任意非法类型、布尔值、越界、非有限或错误形状使本次评估无效。

metadata提供设备数量/有序名称、动作上界、24步时域、功率/容量/终SOC。
observation包含 `step`、`capacitor_states`、`regulator_taps`、`battery_soc`、
`battery_actual_kw` 和 `bus_voltages`（bus到各相pu幅值的字典）。第0步电压为
首时段空闲初态测量；后续电压和实际电池功率为上一已执行时段测量。
不提供未来负荷、预测、可交互目标仿真器或完整目标轨迹。可以在controller实例
保留历史；每次独立复核新建实例。受信执行时总进程30秒、每步响应1秒、初始化
5秒，内存512MiB、CPU10秒，不允许网络或启动子进程。

每台电池末能量必须距初值不超过1kWh；否则分数为0。有效完整轨迹评分为

`quality = 1 / (1 + V + L/1000 + (C+R)/33)`。

V为24小时累加的逐bus最坏高相超过1.05pu和最坏低相低于0.95pu幅值，单位pu·h。
L为OpenDSS whole-circuit实际有功网损积分，单位kWh；C为电容器切换次数，R为
tap移动总档数。1000kWh和33档是此轮预先冻结的尺度，用来得到有限、单调且可供
流程反馈的分数，没有依n实验结果调权，不声称已完成正式研究主指标校准。
反馈只给完整日汇总质量、V、L、合规率、操作与末SOC；不会给逐时目标轨迹。
不收敛、异常动作、超时等失败分数为0，受理后的反馈次数照常计数。

这是 `powergym-energy-neutral-canary-v1` 适配轨：使用PowerGym固定DSS feeder和
负荷打包，显式snapshot时序；保留上游Generator电池`Q=P/0.95`及整数kWh能量
账本，固定32个tap间隔，额外施加硬终能量规则。它不等同于原Gym vanilla/_soc
论文成绩。真实loss、相位×时刻合规率、初末SOC另外报告。

可运行 `python /app/support/check_interface.py` 做纯合成接口检查。完整目标评价
只能使用平台提供、计入当前n额度的评价入口。n=0没有过程完整目标反馈；最终
截止收集唯一单文件，在同一完整case独立重执行，不使用免费选模。

执行沙箱要求 Landlock ABI≥1。ABI 1/2 使用额外 seccomp 限制：禁止文件截断、`creat`、带 `O_TRUNC` 的打开方式及 `openat2`；私有工作目录可用 `open(path, "x")` 新建文件，或用追加模式写入，不能用 `"w"` 覆写。建议将历史保存在 Controller 实例中。ABI≥3 由 Landlock 直接保护截断操作；所有版本都禁止访问其他控制器目录、共享临时目录和可信数据。
