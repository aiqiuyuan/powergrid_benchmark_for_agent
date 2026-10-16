# MAPDN 33 节点局部无功控制：流程 canary v1

本轮用于验证真实仿真、n 次过程反馈、冻结产物与独立终评的流程，开发时限为 **600 秒**。它是 MAPDN 数据与网络上的因果运行器适配轨，不是上游训练环境的逐步复现，也不是已认证的研究难例。

修改 `/app/submission/controller.py`，只提交这一个不超过 1 MiB 的普通 Python 文件；依赖限 Python 标准库，辅助参数也必须包含在此文件中。不要提交单独 helper、模型权重、symlink 或数据文件。每台 PV 由一个独立进程执行 `Controller(metadata).act(observation)`，进程之间不能通信。初始 starter 为增益 1 的局部 droop。

```python
class Controller:
    def __init__(self, metadata):
        self.bound = metadata["action_bound"]

    def act(self, observation):
        return [0.0]
```

每个控制单元只控制一台逆变器。返回长度为 1 的列表，元素必须为有限数且位于 `[-0.8, 0.8]`；禁止布尔值。可信运行器计算 `Q = action * sqrt(S_max**2 - P_now**2)`。metadata 提供 `actor_id`、`pv_count=1`、`pv_bus_id`、`region_bus_ids`、`action_bound=0.8`、本设备 `apparent_power_mva`（列表）、`interval_hours=0.05` 与 `voltage_bounds_pu=[0.95, 1.05]`。

observation 字段如下，功率单位为 MW/Mvar，角度为度：

- `interval_index` 与当前 `timestamp`：从 0 起的当前间隔和原始时标。
- `pv_voltage_pu`、`pv_active_mw`、`pv_reactive_mvar`：本逆变器当前母线电压、有功、无功，均为长度 1 的列表。
- `region_bus_ids`：本区域有序母线索引。
- `region_demand_p_mw`、`region_demand_q_mvar`：对应母线的实际负荷总和。
- `region_voltage_pu`、`region_angle_degree`：同一当前潮流状态下的区域电压和相角。

每个间隔先写入该时刻外生输入，用上一间隔归一化动作按当前容量重新映射无功并求解潮流，产生当前观测；随后并行含义下采集各局部动作，再统一应用并求解与计分。观测和计分使用相同外生时刻。历史只来自自己的实例；无全网观测、未来轨迹或共享运行状态。初始动作全部为 0，无随机噪声。完整 episode 为一个自然日的 480 个三分钟间隔。

可信侧独立计算真实有功损耗电量和电压指标；仅当全部 480 个间隔均合法且潮流收敛时，流程测试 reward 为：

`0.8 * 母线×时间合规率 + 0.2 / (1 + 实际损耗MWh)`。

这是本轮固定的流程校准映射，没有正式研究排序意义。所有母线电压范围为 0.95–1.05 p.u.，容差 1e-9。真实损耗由全部线路求和，并以全网有功平衡交叉校验；本网络没有变压器等其他有损设备。反馈另外报告全母线同时合规时间比例、最大过欠压、越界积分、真实损耗、完成步数及 Q 使用量。非法动作、退出、超时或不收敛导致完整 episode reward 为 0，不能靠提前结束获得部分分数。

每 actor 单次响应限 1 秒（首次初始化 15 秒），累计 CPU 60 秒、地址空间 384 MiB。六个 actor 合计最多 2.25 GiB 地址空间，可信潮流进程与其共同使用 verifier 的 4 GiB 内存限额。完整运行器总时限 240 秒，外层 verifier 360 秒。禁止网络、子进程、跨单元读写以及读取可信数据。候选的 `stdout` 用于协议，不要直接打印到 stdout。

`python /app/check_interface.py` 仅测试合成局部观测，不能提供目标成绩。n=0 没有完整目标过程反馈；n=1 只可通过框架申请一次完整反馈，候选错误同样消耗次数。截止时冻结唯一的 `controller.py`，未修改即保留 starter；随后在同 case 独立终评，终评分数不回流开发，也不计过程 n。不要下载原始目标数据、上游环境或 checker 重建免费评分。

执行沙箱要求 Landlock ABI≥1。ABI 1/2 使用额外 seccomp 限制：禁止文件截断、`creat`、带 `O_TRUNC` 的打开方式及 `openat2`；私有工作目录可用 `open(path, "x")` 新建文件，或用追加模式写入，不能用 `"w"` 覆写。建议将历史保存在 Controller 实例中。ABI≥3 由 Landlock 直接保护截断操作；所有版本都禁止访问其他控制器目录、共享临时目录和可信数据。
