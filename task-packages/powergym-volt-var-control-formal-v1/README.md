# PowerGym 123Bus formal v1

独立正式任务包，案例为 `123Bus-stress-p000-s2.5`，完整24小时。
评分、观测、双终能量约束与资源限制见 [instruction.md](instruction.md)，选择与
传统参照的信息权限边界见 [problem.md](problem.md)。所有 n 使用相同的既有
`coordinated_voltage` 初始控制器（当前已有同观测策略中的最佳参照），电池空闲；
旧 hysteresis 保留为历史参考，canary 未修改。

```sh
python prepare.py --pool /trusted/frozen-powergym-pool --output tests/data
python stage.py --wheelhouse /trusted/powergym-wheels-linux-amd64
docker build -f images/Dockerfile -t powergym-formal-runtime:1 .
docker build -f tests/Dockerfile -t powergym-formal-verifier:1 tests
docker build -t powergym-formal-development:1 environment
```

准备入口逐项验证 frozen pool/case/assets 哈希，拒绝覆盖。数据目录被 Git 忽略，
只进入 verifier；开发镜像不包含源模型、负荷数组、可信计划或 checker。依赖与
安全 launcher 继承已部署的版本，Linux 构建需记录实际镜像 digest、wheel 哈希
及 sandbox 验收证据；正式矩阵和部署由外部冻结协议统一管理。

```sh
python verification/validate_runtime.py --data tests/data --output /trusted/numerical.json
python verification/validate_runtime.py --data tests/data --secure --output /trusted/linux.json
python verification/replay_references.py --data tests/data \
  --references /trusted/powergym-final/cases/123Bus-stress-p000-s2.5 \
  --output /trusted/formal-reference-parity.json
```

最后一个入口仅供可信验收，用临时候选重放既有9种参照的动作，不向参与者发布
轨迹；数值与 quality 逐项精确核对。参考控制器的 current-load/day oracle 权限
另列，不当作正式观察策略的公平强基线。`--secure` 才测试真实 Linux 受限候选
进程，本地数值通过不能代替沙箱验收。平台计 n、拒绝超额、截止唯一单文件收集
及最终结果隔离须由启动记录另外验证。
