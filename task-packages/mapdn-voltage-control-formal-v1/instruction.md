# MAPDN 33 节点正式固定案例 v1

开发时限 **43200 秒**。修改 `/app/submission/controller.py`，仅提交这一个不超过 1 MiB 的普通 Python 文件；依赖限 Python 标准库，参数也须包含在该文件中。每台 PV 的独立进程运行 `Controller(metadata).act(observation)`，自己的实例历史可保留，各实例不能通信。共同 starter 为已验证的局部松弛 droop，slope=20、relaxation=0.1。

```python
class Controller:
    def __init__(self, metadata):
        self.bound = metadata["action_bound"]

    def act(self, observation):
        return [0.0]
```

每台逆变器返回长度为 1 的列表，元素须为有限数且位于 `[-0.8,0.8]`，布尔值非法。可信侧计算 `Q = action * sqrt(S_max**2-P_now**2)`。metadata 提供 `actor_id`、`pv_count=1`、`pv_bus_id`、`region_bus_ids`、`action_bound=0.8`、本设备 `apparent_power_mva`（列表）、`interval_hours=0.05`、`voltage_bounds_pu=[0.95,1.05]`。

每次 observation 仅含如下字段：

- `interval_index` 与 `timestamp`：当前步与时标。
- `pv_voltage_pu`、`pv_active_mw`、`pv_reactive_mvar`：本设备电压、当前有功、当前测量无功，均为长度 1 的列表。
- `region_bus_ids`：本区域有序母线索引。
- `region_demand_p_mw`、`region_demand_q_mvar`：各区域母线实际负荷。
- `region_voltage_pu`、`region_angle_degree`：同一当前潮流状态的区域电压、角度。

功率单位为 MW/Mvar，角度为度。每步先写入当前外生输入，按上一归一化动作和当前容量计算无功，求解一次潮流形成观测；六个局部控制器各提交一次动作后统一求解、计分。不存在时刻内反复测量权限。初始动作为零、不加噪声，完整一天共 480 步、每步三分钟。容量为完整源 PV CSV 各列最大值的 1.2 倍，不从目标日估计。

评分使用完整 480×33=15840 个母线时间点，电压范围 0.95–1.05 p.u.，数值容差 1e-9 p.u.。只有全部 480 步动作合法且潮流收敛才是完整有效解：

- 非法动作、提前退出、超时或任何一步不收敛：reward=0。
- 有效但至少一个母线时间点电压越界：`reward=0.5*bus_time_compliance`。
- 有效且全部 15840 个点电压合规：`reward=0.5+0.5/(1+actual_loss_mwh)`。

这保证整日安全解优先于任何电压不安全解；安全后只比较真实有功损耗。`bus_time_compliance` 是合规母线时间点的比例，不是全网同时合规的时刻比例；后者另报告 `all_bus_time_compliance`。实际损耗由线路有功损耗积分，并以全网有功平衡核验，不能用无功大小代替。反馈还包含最差过欠压、越界积分、损耗、完成步数、潮流调用数和无功使用量。终止后的未完成时段不会获得部分奖励。

每 actor 单次响应限 1 秒、初始化限 15 秒，累计 CPU 60 秒、地址空间 384 MiB；六个 actor 合计 2304 MiB 地址空间，可信仿真与其共用 verifier 4096 MiB 内存限额。完整运行器限 240 秒，外层 verifier 限 360 秒。网络、子进程、跨单元文件和 IPC、可信 case 和评分器均不可访问。stdout 是协议通道，请勿向其打印。

`python /app/check_interface.py` 仅测试合成局部观测，不提供目标成绩。完整目标反馈只能通过框架的受计数入口获得；具体预算 n 由该次实验配置给出，超过预算的申请拒绝后不运行。n=0 无过程 judge。未使用完预算允许保留；截止时只冻结一个 `controller.py`，未修改则保留 starter。独立终评使用相同固定案例回放，终评不会回流开发；不会按历史反馈选择最优产物。

不得下载目标轨迹、上游环境或评分器重建免费目标评分。沙箱要求 Landlock ABI≥1；ABI1/2 禁止文件截断、`creat`、带 `O_TRUNC` 的打开方式及 `openat2`，自身文件可用 `"x"` 新建或追加，建议将历史存在实例中；所有 ABI 均禁止访问其他控制器和共享临时目录。
