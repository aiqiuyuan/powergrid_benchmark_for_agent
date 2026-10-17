# 配电网选例基础实验

这些工具只用于可信侧准备和已知基线数值实验。它们不提供 agent 开发端的免费目标评分入口，也不替代正式任务隔离。原 canary 包、源数据与历史 run 保持原样。

协议和完整结果见[实验报告](../../docs/experiments/distribution-case-selection-20261016.md)。MAPDN 和 PowerGym 使用各自运行包的模拟器依赖锁及独立 Python 环境；核心仓库的无依赖安装不包含这些后端。需要预先按锁定来源准备 raw/source receipt，不在评测中自动下载。

## MAPDN

每个网络使用一个新的输出目录。`RAW` 包含经过 CRC32/SHA256 核验的 `model.p`、三个 CSV 和 `preparation-receipt.json`；33节点准备入口保留在原包，141节点使用本目录 `runtime_fetch_mapdn141.py`。候选池按外生规则冻结，控制器运行不会重新选择日期。

```sh
python tools/distribution_selection/mapdn_selection.py \
  --stage freeze --network 33 --raw-dir RAW --output OUTPUT

python tools/distribution_selection/mapdn_selection.py \
  --stage screen --network 33 --output OUTPUT

# 首轮稳定性检查后单独登记的补充实验，原结果继续保留。
python tools/distribution_selection/mapdn_selection.py \
  --stage screen --network 33 --output OUTPUT --baseline grid_droop \
  --droop-gains 0.25 0.5 1.5 2.5

# 必须指定完整候选日；可重复 --case-id，对所列每一天都执行480步。
python tools/distribution_selection/mapdn_selection.py \
  --stage reference --network 33 --output OUTPUT \
  --case-id mapdn33-2012-02-03
```

141节点使用 `--network 141` 和独立 `RAW`、`OUTPUT`。原始池 SHA、结果 SHA、实际实现、starter 和运行依赖都必须匹配才允许复用。旧结果不匹配时使用新输出目录并保留旧记录，不删除或修改哈希以强行续跑。局部策略仅取得区域当前观测；AC OPF额外使用当前全网快照，不作为同信息主比较。OPF固定有功和源端电压、保留无功边界，并用新AC潮流校验；没有全局最优证书。

## PowerGym

`SOURCE` 是已有固定提交与逐文件 `source-receipt.json` 的可信准备副本。冻结含标准组与独立压力组的完整池后，运行四类基线：

```sh
python tools/distribution_selection/powergym_selection.py \
  --source-dir SOURCE --output OUTPUT --prepare-only

python tools/distribution_selection/powergym_selection.py \
  --source-dir SOURCE --output OUTPUT --resume
```

`--case-ids` 可选测试子集；`--baselines` 可指定策略，`--search-passes` 默认2。首次运行写入运行锁，此后参数、代码或模拟器版本变化需新输出目录。保持动作与原始电压滞环已和历史34Bus数据交叉验证。当前快照搜索拥有完整模型及当前外生负荷，只把它列为额外参照；所有基线的电池为空闲，因此无法单凭此批次声称跨期储能控制已验证。

## 产物与验证

完整目标资产和逐时轨迹仅保存在本地忽略目录。公开证据含池清单、物理指标、参数、运行环境及原始结果 SHA，不含完整轨迹。失败和部分轨迹原样保留，不计算不等电压合规条件下的纯损耗差距。

`runtime_tests.py` 验证可选集群入口的冻结闭包、离线镜像身份、只读输入和输出副本。`runtime_cluster.py` 尚未在本批次实际运行新 Linux DinD 作业，不能凭单元测试宣称新增集群验收通过。
