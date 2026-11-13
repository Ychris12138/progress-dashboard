# GitHub Pages：空站部署

生产工作流为 `.github/workflows/pages.yml`，本地与 Actions 统一调用 `scripts/build.py`。正式业务数据尚未启用；`scripts/assert_empty.py` 会阻止任何非空 public 数据进入部署产物。合成 fixtures 只用于测试。

## 部署边界

- PR 运行 Python 3.12／3.14 和前端检查，build/deploy 不运行。
- main push 和选择 main 的 workflow_dispatch 才可构建部署；Environment `github-pages` 配置为只接受 main 分支，不接受标签。
- 各 job 单独授权；检查只读 contents，构建只读 contents/pages。只有 deploy 获得 pages:write、id-token:write，并以 deployments:read 检查成功部署历史。
- 所有官方 Actions 固定完整 SHA。`queue: max` 最多容纳 100 个等待项，不取消运行中的任务；顺序是进入等待队列的顺序，不是提交时间顺序。
- build 依赖所有检查，deploy 依赖检查与 build；没有失败后仍部署的 always 条件。
- 部署前重新读取 main HEAD 和成功部署历史。旧运行、已部署后代和分叉历史不能覆盖站点。查询异常时停止，不跳过保护。
- `fail_build` 手动输入默认为 false；设为 true 会在上传产物之前故意让 build 失败，用于验证旧站保留，不能绕过其他检查。

## 首次初始化顺序

1. 用 `gh api user` 核实当前账户；仓库 owner 必须一致。
2. 检查准备提交的文件白名单、公开空数据、完整测试及无私有文件。使用 GitHub noreply 身份创建唯一根提交。
3. 创建公开空仓库，不生成 README、License 或默认 .gitignore。再次检查 owner、private=false、admin/push 权限及空 refs。
4. 将 origin 设为该仓库 HTTPS 地址。用现有 GitHub CLI credential helper 认证，不把 token 写入 URL、代码、脚本或报告。
5. 将 Actions token 默认权限设为 read，限制允许的 Actions 为 GitHub 官方；配置 `github-pages` 的 main 分支规则，再 push 已审阅的根提交。
6. 设置默认分支 main、Pages build_type=workflow；确认首次成功部署内容为空。
7. 验证 PR、非主分支手动运行、故意 build 失败及旧提交重放不会部署；记录运行链接和线上内容哈希。
8. 检查手机页面，生成包含最终 HTTPS 站点地址的 .webloc。

第三阶段的 publish.py 仍限制本地 bare 目标；本次空站 bootstrap 不将真实数据发布功能启用。后续发布真实记录仍需独立批准批次，并明确启用网络发布，不允许复制本地演练自动批准逻辑。

## 访问与故障定位

站点和仓库均公开。初始站点没有项目或进度；表单只生成本地 JSON，不会上传。Actions 入口显示在网页底部，README 提供工作流徽章。

构建或部署失败时先查看 Actions；失败运行不会调用 deploy-pages，已有站点保留。权限不足时检查 Environment 分支规则、Pages source 和 job permissions；不要提高检查 job 权限来绕过错误。过期运行被 guard 跳过时，在当前 main 上重新运行正常工作流。

## 官方依据

- [自定义 Pages 工作流与部署权限](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [并发队列语义](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

实际运行与浏览器验收记录另见第四阶段交付报告。
