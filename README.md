# SPY Plus 10 Walk-Forward

这是一个 QuantConnect 纯云端策略研究项目，目标是在严格禁止未来数据的历史 walk-forward 模拟中，逐个自然年检验策略是否达到同期 SPY 总回报加 10 个百分点。

当前代码已完成云端基础、三类 Alpha 模块、组合风险控制，以及冻结评价所需的精确证据与独立复算工具。正式 `2015-01-02` 至 `2026-08-28` 结果尚未运行；在结果归档前，不能宣称策略达到目标。

冻结评价只允许以下两个参数组合，并且必须来自同一不可变 Git 提交：

- 基础成本：`evaluation_mode=frozen-evaluation`、`slippage_multiplier=1`、`evaluation_run_label=base`
- 压力测试：`evaluation_mode=frozen-evaluation`、`slippage_multiplier=2`、`evaluation_run_label=double`

算法从 `2012-01-01` 预热，`2015-01-02` 才允许成交，并固定在 `2026-08-28` 结束。算法会在回测结束时一次性把每日权益、SPY 总回报、费用、持仓、保证金、风险和至少十个严格因果时间样本压缩写入 QuantConnect Object Store。Atlas 随后只读下载结果，并用独立代码重新计算逐年门槛和最大回撤。

详细规则见 [设计规范](docs/superpowers/specs/2026-08-30-spy-plus-10-walk-forward-design.md) 和 [冻结评价协议](docs/frozen-evaluation-protocol.md)。项目不包含实盘节点、券商连接或真实下单路径。
