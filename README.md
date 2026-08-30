# SPY Plus 10 Walk-Forward

这是一个 QuantConnect 纯云端策略研究项目，目标是在严格禁止未来数据的历史 walk-forward 模拟中，逐个自然年检验策略是否达到同期 SPY 总回报加 10 个百分点。

当前代码已完成云端基础、三类 Alpha 模块、组合风险控制和两次冻结评价。正式证据结论为 `UNVERIFIED`：QuantConnect 的结构化年度统计显示所有评价期均未达到目标，但每日权益证据对象保存失败，无法完成独立权益曲线与最大回撤复算。完整结果见 [冻结评价报告](docs/frozen-evaluation.md)。

冻结评价只允许以下两个参数组合，并且必须来自同一不可变 Git 提交：

- 基础成本：`evaluation_mode=frozen-evaluation`、`slippage_multiplier=1`、`evaluation_run_label=base`
- 压力测试：`evaluation_mode=frozen-evaluation`、`slippage_multiplier=2`、`evaluation_run_label=double`

算法从 `2012-01-01` 预热，`2015-01-02` 才允许成交，并固定在 `2026-08-28` 结束。两次正式回测均由冻结提交 `66b630342c3171cb30c8f05faa7cac69706e35f6` 运行。Atlas 已只读归档回测响应、全部订单和全部已平仓交易；Object Store 每日证据未成功保存，因此独立复算器按协议失败关闭，没有发布未经验证的通过结论。

详细规则见 [设计规范](docs/superpowers/specs/2026-08-30-spy-plus-10-walk-forward-design.md) 和 [冻结评价协议](docs/frozen-evaluation-protocol.md)。项目不包含实盘节点、券商连接或真实下单路径。
