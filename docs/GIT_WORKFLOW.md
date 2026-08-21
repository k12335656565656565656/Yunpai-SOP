# 本地 Git 管理与安全回退

本项目使用 Git 保存每一个可工作的检查点。日常修改应在当前功能分支完成，确认功能可运行后再提交。提交只在本地创建，不会自动上传 GitHub 或 GitLab。

## 每次修改前

```powershell
git status --short --branch
git timeline
```

`git status` 用于确认改了哪些文件；`git timeline` 用于查看所有本地分支和标签。每次开始一项独立功能前，先建立功能分支：

```powershell
git switch -c feature/功能简述
```

## 建立检查点

确认页面或功能可用后，先查看差异，再提交：

```powershell
git diff --stat
git add 路径1 路径2
git commit -m "说明本次完成的功能"
```

每个完成阶段还应打一个本地标签，便于一眼找到可回退版本：

```powershell
git tag -a local-checkpoint-YYYYMMDD-说明 -m "本地可用检查点"
```

提交前钩子会阻止浏览器缓存、DOCX 临时预览、截图、`.env` 和私钥进入版本库。

## 安全回退

先找到目标版本：

```powershell
git timeline
```

需要撤销一个已提交的错误时，使用下面的命令创建一条反向提交，历史仍然完整：

```powershell
git revert 提交编号
```

只需要拿回某个旧文件时，使用：

```powershell
git restore --source 提交编号 -- 路径/文件名
```

不要使用 `git reset --hard`、`git clean -f` 或强制推送。它们会丢失尚未提交的内容，且不适合本项目的日常回退。

## 常用命令

```powershell
git changes                 # 查看当前状态
git diff                    # 查看未暂存的具体改动
git show 提交编号 --stat     # 查看某次提交修改了什么
git switch 分支名            # 切换到已有分支
git switch -                 # 回到刚才所在分支
```

远程上传或创建 Pull Request 前，必须先确认本地检查点、测试结果和待上传文件清单。
