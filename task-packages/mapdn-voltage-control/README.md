# MAPDN 原生 task 骨架：尚不可启动

**状态：`design / certification-pending / release_ready=false`。** 此目录保留 eval-in-loop / Harbor 原生布局，提供可阅读题面和独立控制器 starter；所有部署、评分与参考解入口使用 `.template` 后缀。没有可直接加载的 `task.toml`，没有完整 `score.py`，没有私有目标数据或已完成的真实 MAPDN 运行器，不能直接启动实验。

本扩展不修改原五任务 75-run 清单。任务语义见[任务卡](../../docs/task-cards/mapdn-voltage-control.md)，公共合同模块和准备工具见[接入说明](../../docs/framework/distribution-control-integration.md)。

## 已提供

- `instruction.md`：候选算法接口、局部信息、严格 n 与产物要求。
- `environment/app/submission/controller.py`：`Controller(metadata).act(observation)` 局部 droop starter。
- `environment/app/public/toy.json`：合成接口输入，只检查调用与动作形状，不是目标 case、潮流或评分。
- `environment/app/support/check_interface.py`：只做合成输入的导入和接口检查；开发镜像可复制该轻量支持目录，不包含完整 checker。
- `task.toml.template`：原生字段位置与待冻结资源；`${...}` 未填数值使其不可作为可执行配置使用。
- 两侧 `Dockerfile.template`：开发侧只复制 starter、toy 和轻量接口检查，可信侧另需不公开的 verifier bundle。
- `tests/test.sh.template`：固定私有 verifier 路径和内容 SHA-256；未填写摘要、缺文件、链接替换或摘要不符均失败退出，不生成默认 reward。
- `solution/solve.sh.template`：明确未实现的参考解入口，失败退出，不冒充可用 oracle。

## 尚未接入的上游接口

1. 数据获取与实际归档 SHA-256 校验、许可及网络资产来源确认，`model.p` 的真实导入/格式迁移。
2. `VoltageControl` 的网络、负荷、PV、区域与设备映射，完整固定时域与初始 Q 的可信准备。
3. 修正后的观测→决策→潮流→计分→前进顺序、首末间隔与历史更新；不能直接复用上游 239/479 次有奖转移。
4. 逐控制单元 worker 和私有状态传输；基础字段投影不是进程隔离。
5. 可信动作检查、真实总有功损耗、变压器损耗与能量平衡核对，固定失败与超时规则。
6. 原生 artifacts 注入、候选实际运行、reward 输出、安全反馈、严格 n 计数和独立终评。
7. 同容量、同观测、同仿真机会的 droop/MARL/OPF 基线与运行成本测量。

## 从骨架到可验收 task

先由出题侧固定完整 case、观测字段、动作界、外生实现、初始化、实际运行环境和资源，再生成私有可信运行器及完整 release manifest。该 manifest 应锁定数据、代码、依赖、时域、计分、反馈 schema 与失败规则；仅锁定一个 verifier 文件的 hash 不等于完整 release 验收。

在可信准备目录渲染 `.template` 为原生文件；检查所有 `${...}` 均已替换、镜像使用不可变 digest。不要向公开仓库或开发镜像复制 `tests/private/`。可信构建上下文需包含：

```text
tests/private/mapdn-voltage-control/
├── verify.py          # 私有完整运行/独立验分入口，须校验其 release 与数据
├── release.json       # 冻结输入、计分、失败、资源和反馈合同及摘要
└── ...                # 获准的依赖、完整目标输入与必要可信模块
```

`tests/test.sh` 固定调用 `/opt/powergrid-bench/private/mapdn-voltage-control/verify.py`。出题侧将 `${PRIVATE_VERIFIER_SHA256}` 写为该文件的真实 64 位十六进制 SHA-256；评分程序不读取候选指定的路径或 scorer 环境变量。私有入口接受 `--artifact-root /app/submission --log-dir <受限日志目录>`，必须执行冻结候选并独立计算原始指标，按框架合同写出 `reward.json` 和 `reward-details.json`。其辅助模块须预装在可信镜像或由该入口以可信绝对路径加载；启动器不把候选目录加入 Python 搜索路径。本骨架没有实现该程序。

运行镜像中的 `/tests`、私有 bundle、数据与解释器须由可信镜像提供且对候选只读；隔离候选环境、网络、日志权限与子进程资源。模板中的 `LOG_DIR` 仅控制 `/logs` 下的结果目录，不能改变 verifier、摘要、解释器或 artifact 根目录。缺少可信 bundle/配置属于基础设施失败，不能伪装成候选零分。

资源、逐步/整例时限、目标 case、排名映射与正式扩展 run 均待校准。完成真实环境 smoke、强基线、物理/因果校验、评分旁路检查和 n=0/n=1 原生 canary 前，不移除 pending 标识，不宣称 task 已可运行。
