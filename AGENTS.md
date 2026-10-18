# Repository entry

先读 [SKILL.md](SKILL.md)，再读本次任务涉及的 context 文件。

涉及 Sisu 的实质决策时，执行 [联合决策协议](integration/decision_protocol.md)，以 [manifest](integration/manifest.json) 联合读取个人库与 cognition-kb。入口命令：`python3 scripts/joint_decision.py load --refresh --question '当前问题'`。固定两库 SHA，说明动态日期、命中原文及缺失项；不能只读个人摘要就声称已联动。认知库入口调用同一工具。

- 以当前用户指令和可定位证据为依据，避免把助手建议、模板或旧摘要写成用户决定。
- 对外部事实的核验不等同于核对“用户曾这样表达”；分别注明。
- 维护本仓库不等于获准修改原始 Obsidian、宿主内部记忆或其它项目。
- 不提交原始日志、私人资料和本机绝对路径；只提交最小必要变更，完成后核验远端版本。
- 联合上下文可能包含私有原文，不提交到本公开仓库。反馈队列是待审记录；依据当前授权应用到相应库的正文，个人记录与通用框架分工维护，不复制两份权威正文。
