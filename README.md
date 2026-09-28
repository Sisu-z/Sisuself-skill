# Sisuself Skill

Sisu 的个人认知与战略上下文：**Stable Core + Dynamic State + Decision History + Cognitive Evolution**。

面向需要理解其学习、科研、工程、职业与商业取舍的 Agent。目标是迅速形成正确的工作假设，不是复制全部人生记录。首次整理：2026-09-28。

## 文件职责

```text
Sisuself-skill/
├── SKILL.md                    # 读取、分类、冲突处理与更新协议
├── AGENTS.md                   # 仓库内 Agent 的短入口
├── README.md                   # 使用与维护说明
├── agents/openai.yaml          # Skill 展示信息
├── context/
│   ├── profile.md              # 稳定背景、资源、约束与协作偏好
│   ├── current_state.md        # 当前主线、近期目标、项目与未决问题
│   ├── principles.md           # 较稳定的判断、学习与行动原则
│   ├── decision_log.md         # 追加决策、依据、放弃项及推翻条件
│   ├── cognitive_model.md      # 假设、冲突、历史观点及认知演化
│   └── sources.md              # 来源索引、覆盖范围和取舍记录
└── .gitignore                  # 排除常见私人/临时文件
```

`profile/principles` 低频更新；`current_state` 按实质变化更新；`decision_log` 只追加；`cognitive_model` 保留冲突和演化。具体事实只在主要文件维护，其他文件用链接引用。

## 让 Agent 读取

可直接给 Agent 这段指令：

> 读取 https://github.com/Sisu-z/Sisuself-skill 的最新默认分支，先读 SKILL.md，再按需读取 context 文件。报告读取的提交与状态日期；将用户事实、当前策略、假设和历史观点分开。结合这些背景回答我的任务，不要仅复述画像。

支持 Git 的环境可克隆到普通工作目录；读取已有副本时，先检查是否有未提交改动，再快进同步：

```sh
git clone https://github.com/Sisu-z/Sisuself-skill.git
cd Sisuself-skill
git status --short
# 仅在工作区干净且无分叉时：
git pull --ff-only
git rev-parse HEAD
```

只支持 HTTP 的 Agent：先通过 GitHub API `https://api.github.com/repos/Sisu-z/Sisuself-skill/commits/main` 取得 `sha`，然后读取 `https://raw.githubusercontent.com/Sisu-z/Sisuself-skill/<sha>/SKILL.md` 及相同 SHA 下的所需文件。这里 `<sha>` 是实际提交，不是字面路径。

**公开可读不等于自动加载或后台实时同步。** Agent 需要网络/文件读取能力；写入另需仓库权限与适用授权。网络不可用、无法解析版本、读到缓存或状态过期时，应明确说明。仓库没有配置后台同步或定时任务。

根目录本身就是完整 Skill。支持本地技能目录的环境可按其规则将整个目录作为 `sisuself-skill` 加载；不要只复制 SKILL.md 而遗漏 context。普通浏览器对话也能按上述链接读取，不需要安装。首次交付仅创建仓库，没有改动本机技能安装目录。

## 更新和版本历史

1. 重大讨论出现明确事实变化、已采纳决策或纠正时更新；普通闲聊和临时情绪不更新。
2. 只改受影响文件，保留来源、事件时间、证据状态；编辑日期与事实核验日期分开。
3. 重大策略改变追加决策条目：决定、依据、放弃项、允许推翻的新证据；尚未决定的方案明确标为候选。
4. 旧事实失效或观点被修订时，保留前后差异、日期和原因。纠正历史决策用追加记录，避免事后改写。
5. 有写入授权和权限的 Agent 审阅最小 diff 后提交、推送、回读远端；多人并行或分叉时用分支/PR，不强推。只读 Agent 输出待应用的 patch，不声称写入成功。

一次提交对应一次有实质变化的更新。提交说明写清“改变什么、来源是什么、为何改变”；Git SHA 是精确版本，`git log -- context/` 可追溯历史。需要撤回时优先追加纠正或 revert 提交，保留演化过程；不要用覆盖文件抹去决策依据。

初版内容已由 Agent 对照来源整理；不代表用户逐条审核通过。用户后续纠正是更新依据。完整规则见 [SKILL.md](SKILL.md)。

## 公开边界

这里公开经整理的背景和认知，不分发原始 Obsidian、完整聊天、第三方全文、私人联系方式、健康/家庭细节、凭据或本地路径。来源索引中的私有笔记名称用于回查，外部读者无法仅凭仓库核验这些原文。

本仓库用于读取个人上下文及维护协作；公开可见不等于已授予通用再分发许可证。未替用户选择 MIT/Apache 等许可证。个人判断不构成他人的投资、职业或健康建议。
