# PowerGym 原生 task 骨架：尚不可启动

**状态：`design / certification-pending / release_ready=false`。** 此目录提供 eval-in-loop / Harbor 原生布局、可阅读题面和保持当前设备状态的控制器 starter。部署、可信评分与参考解文件使用 `.template` 后缀；没有可直接加载的 `task.toml`、完整 `score.py`、冻结 case 或私有完整运行器，不能直接启动实验。新增扩展不改变原五任务的 75-run 清单。

任务语义见[任务卡](../../docs/task-cards/powergym-volt-var-control.md)，公共基础合同与准备工具见[接入说明](../../docs/framework/distribution-control-integration.md)。

## 已提供

- `instruction.md`：混合动作接口、当前观测、SOC 分轨、严格 n 与提交合同。
- `environment/app/submission/controller.py`：`Controller(metadata).act(observation)`；保持当前电容器和 tap，电池请求 idle。
- `environment/app/public/toy.json` 与 `support/check_interface.py`：合成接口输入和轻量调用检查，不做潮流、SOC 演化或目标评分。
- `task.toml.template` 和两侧 `Dockerfile.template`：资源、镜像与计分参数保留 `${...}`，未渲染不可启动。
- `tests/test.sh.template`：固定私有 verifier 路径和 SHA-256；缺少配置/文件或摘要不符时失败退出，不写默认 reward。
- `solution/solve.sh.template`：尚未实现的参考解入口，明确失败退出，不冒充可用 oracle。

starter 从当前观测读取 caps/taps，不能把初始动作缓存当永久 hold。默认离散电池有 0–32 共 33 档，idle 为 16；`_cbat` 连续电池 idle 为 0。全零动作会改变电容器、tap 和离散电池命令，不能当作 DoNothing。

## 尚未接入的上游接口

1. 锁定 PowerGym/OpenDSS 运行镜像及原始 feeder、负荷文件顺序、设备顺序、实际生成数组和完整 24 小时 profile。
2. `Env.reset/step` 的真实调用、每小时行映射、初末步与尾部环回，`Solution.Converged` 与失败处理。
3. OpenDSS 电容器、调压器与 Generator 电池写入、实际功率、能量账本和动作边界校验。
4. 全电路实际有功损耗积分、电压与操作统计、原生 return；不能以 loss ratio 或 reward 冒充 kWh。
5. 原生轨与物理适配轨选择：原生 vanilla / `_soc` / `_cbat` 的有效权重；或新定义的初末 SOC、容差、效率与 P/Q 关系，分别重跑全部基线。
6. 原生 artifacts 注入、冻结控制器执行、独立验分、受控反馈、严格 n 与最终复核。
7. 独立进程/工作目录隔离与 profile 写入冻结；不能依赖 `worker_idx` 就宣称多环境并发安全。
8. hold/idle、随机、DSS、SOC-aware、受限搜索和可复现 RL 基线，以及 CPU/内存/逐步/完整 case 成本校准。

## 可信准备与发布

完整上游源码准备工具只向可信评测侧复制和核对版本，不把完整环境、目标负荷或完整 checker 放入开发镜像。准备时先冻结网络、完整 case、原生/适配轨、观测、动作、初始能量、终端规则与所有有效权重；模板不自动选择这些内容。

在可信构建目录渲染模板并清除所有 `${...}`，镜像使用不可变 digest。私有构建上下文另需：

```text
tests/private/powergym-volt-var-control/
├── verify.py          # 实际执行冻结候选、独立评分并核验 release/data
├── release.json       # 完整 case、物理/计分/失败/资源/反馈合同及摘要
└── ...                # 冻结目标输入与可信辅助模块
```

公开仓库不提供该 bundle，不要把它提交到公开 GitHub 或开发镜像。`tests/test.sh` 固定入口为 `/opt/powergrid-bench/private/powergym-volt-var-control/verify.py`，摘要为出题侧写入的 `${PRIVATE_VERIFIER_SHA256}`。它不接受候选指定的 scorer 路径、解释器或摘要环境变量；`LOG_DIR` 只能决定 `/logs` 下的结果目录。

私有入口合同为 `--artifact-root /app/submission --log-dir <受限日志目录>`，须实际执行算法并写出框架的 `reward.json`、`reward-details.json`，同时验证自身 release 和全部目标输入。辅助模块应预装可信镜像或通过可信绝对路径加载，不能依赖候选的 Python 搜索路径。入口代码 hash 不替代数据、依赖与实际隔离验收。

候选子进程不可写 `/tests`、私有 bundle 和目标输入；运行网络、共享目录、输出与超时由可信后端控制。缺 runner、依赖或 release 属于基础设施失败，不构造算法零分。完成完整环境 smoke、SOC/时序/损耗核对、强基线和 n=0/n=1 原生 canary 前，保持 pending，不宣称已可运行或已解决能量耗尽优势。
