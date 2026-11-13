# Git 初始化、发布与恢复

第三阶段仅支持本地 bare 仓库。HTTP、SSH、file URL 和相对远程路径均拒绝；不调用 gh、不创建 GitHub 仓库、不部署。所有示例用合成数据。现有正式项目保持空公开数据，并未初始化 Git。

## 一键保留验证现场

```sh
python3.12 scripts/demo_git.py --output /private/tmp/progress-dashboard-git-demo
```

输出目录必须不存在。脚本创建最小合成代码仓库、空数据初始提交和独立 bare 仓库，自动批准的仅是脚本中固定的合成候选。依次验证提交前恢复、接收端 hook 拒收、重试不重复提交、远程冲突不覆盖任何一方。proof.json 给出提交与批次，private/ 保存完整审批和事务证据。最终的本地分叉是刻意保留的测试现场。

## 独立初始化

在已经准备好代码、合成测试及空 public 的独立演练目录中，按顺序执行。以下 REPO、LOCAL、REMOTE 均需替换为真实的绝对路径，三者彼此分离；不得把真实草稿复制进 REPO。

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/initialize.py --repo REPO --local-root LOCAL local-init --email '12345+synthetic@users.noreply.github.com'
git init --bare --initial-branch=main REMOTE
git -C REPO remote add origin REMOTE
python3.12 scripts/initialize.py --repo REPO --local-root LOCAL prepare --remote REMOTE --email '12345+synthetic@users.noreply.github.com'
```

local-init 只建立本地 Git，显式暂存代码白名单并提交一次，不添加远程。遇到已有 Git 工作树会停止，不重置它。prepare 要求 main、干净工作区、唯一根提交、空业务数据、完全空的 bare 远程及远程默认分支 main，输出 bootstrap.json 和摘要。

审阅清单中的全部文件、哈希、身份、仓库和基准提交后，将返回摘要作为确认参数：

```sh
python3.12 scripts/initialize.py --repo REPO --local-root LOCAL bootstrap --digest REVIEWED_SHA256
```

工具只推送原冻结根提交；确认远程只包含这个 main 后，写入本地演练启用凭据。推送成功但写回执前中断时，重复相同命令可确认远程已有该提交。远程已经自带 README、其他分支或独立历史时停止，不合并、不覆盖。

初始化扫描检查代码路径白名单、文件模式、典型凭据和空业务数据；不能替代对代码、文档及 fixtures 是否含真实私有内容的人工审阅。bootstrap digest 是这次完整文件清单的确认。尚未实现的 GitHub 账户/所有者/公开属性验证及 Pages 空站验证属于第四阶段；当前启用凭据不适用于网络发布。

## 发布批准的批次

先使用原有 import/project/preview 命令形成批次，阅读本地完整预览；用户确认摘要后再 approve。初始化之前生成的批次因 HEAD/target 变化不可继续使用，需要重做预览。

```sh
python3.12 scripts/preview.py --repo REPO --local-root LOCAL --approve BATCH_ID --digest REVIEWED_SHA256
python3.12 scripts/publish.py --repo REPO --local-root LOCAL --batch BATCH_ID
```

工具要求工作区和暂存区干净、main 分支、单一且相同的 origin fetch/push 地址、远程 HEAD 等于审批基准。拒绝 assume-unchanged/skip-worktree 等可能隐藏修改的索引标志，以及进行中的 merge/rebase。不会自动 stash、pull、rebase、强推或将无关文件一起提交。

发布只使用冻结候选，不重新从草稿生成。提交前和推送前再次核验审批内容。提交包含 `Progress-Batch: BATCH_ID`，作者及提交者邮箱强制为配置的 GitHub noreply；记录时间不会因重试改变。

## 恢复决策

| 观察到的结果 | 操作和边界 |
|---|---|
| 候选写入前、部分文件写入、暂存后中断 | 用 --recover-only 校验全批次后恢复，返回 rolled_back；再执行普通 publish |
| 备份、工作文件或暂存被其他操作改变 | 停止并保留现场，不覆盖、不清理其他暂存 |
| commit_ready，提交对象已生成但分支未更新 | 验证对象、暂存、文件和父提交后，用原 HEAD 条件更新分支，复用同一对象 |
| 分支已更新但 committed 日志未写入 | 核对父提交、标记、文件集合、blob 和模式，找回已有提交 |
| push 失败或返回结果不明 | 重复普通 publish；先查询远程，再决定是否安全重试 |
| push 成功但日志未更新 | 识别远程包含该提交，不再推送，也不新增提交 |
| 远程已快进到包含本批次的后代 | 记录本批次已送达，不倒退远程 |
| 远程分叉、其他本地提交插入、目标改变 | 停止；保留本地提交、草稿、批准和事务证据，人工决定后续处理 |

```sh
python3.12 scripts/publish.py --repo REPO --local-root LOCAL --batch BATCH_ID --recover-only
```

--recover-only 不推送；即使 bare 目录暂时不可用也可完成本地恢复。普通 publish 遇到 prepared 状态也只返回恢复结果，不在同一次调用中顺便重新发布。提交后绝不自动 reset 或撤销提交。日志损坏或批准改变时保留现场，不能通过删除日志绕过校验。

仓库和私有目录各有一把本工具锁；不能阻止用户的其他 Git 进程写入。检测到外部变化即停止，不承诺能协调任意不遵守锁的进程，也不将哈希机制描述成对恶意本地篡改的防御。

## 验证范围

Python 标准库和 Git CLI；macOS 本地实测，CI 保留 Python 3.12/3.14 检查配置。注入错误只通过 Python 测试回调，发布 CLI 没有故障注入开关。测试含一个子进程 os._exit 模拟突然终止；文件系统断电损坏、真实 GitHub 网络故障和 Pages 不在本阶段实测范围。
