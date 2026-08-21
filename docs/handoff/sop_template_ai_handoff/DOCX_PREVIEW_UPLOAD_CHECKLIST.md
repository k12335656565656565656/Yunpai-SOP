# DOCX 预览上传前检查清单

## 2026-08-20 故障记录

### 表现

- 网页显示“预览暂时不可用”，但 DOCX 仍可下载。
- `/api/routes/1/documents/latest` 返回 `preview_status=failed`、`page_count=0`。
- 同一台电脑上可能偶尔正常、偶尔失败。

### 根因

1. `scripts/render_docx_preview.ps1` 依赖的 `scripts/render_pdf_pages.py` 没有进入仓库，导致 PDF 已生成但无法转换成分页 PNG。
2. Edge 正在读取旧预览时，Windows 会拒绝移动 `preview-current` 目录。发布逻辑必须保留 `preview-version-*` 兜底，不能退回到只移动固定目录的实现。
3. 本地 8787 端口曾同时存在两个监听进程，请求随机进入旧代码，造成“修改后仍偶尔报旧错误”的假象。

## 上传或发 PR 前必须检查

### 1. 确认分页脚本已被 Git 跟踪

```powershell
git status --short
git ls-files --error-unmatch scripts/render_pdf_pages.py
```

第二条命令必须成功，并输出 `scripts/render_pdf_pages.py`。只看 `git diff` 不够，因为它不会显示未跟踪文件的内容。

### 2. 确认 8787 只有一个监听服务

```powershell
& 'C:\Windows\System32\netstat.exe' -ano -p TCP | Select-String 'LISTENING' | Select-String ':8787'
```

只能出现一条 `LISTENING`。如有两条，先核对 PID 确实属于本项目，再停止旧服务并重新启动，不能让新旧代码同时监听。

### 3. 运行预览专项回归

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_sop_conversational_docx.SopConversationalDocxTests.test_pdf_page_renderer_supports_chinese_paths `
  tests.test_sop_conversational_docx.SopConversationalDocxTests.test_preview_publish_uses_versioned_directory_when_current_preview_is_locked `
  -v
```

这两项必须全部通过，分别防止“分页脚本/中文路径失效”和“Edge 占用旧预览后无法发布”。

### 4. 用真实路线重新生成一次

```powershell
$document = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8787/api/routes/1/documents/generate' `
  -TimeoutSec 180
$document | Select-Object preview_status,page_count,preview_url,page_urls,version_token
```

验收条件：

- `preview_status` 不能是 `failed`。
- `page_count` 必须等于 `1 + 当前有效工序数量`。
- `preview_url` 非空。
- `page_urls.Count` 必须等于 `page_count`。
- 浏览器刷新后能显示第一页，Console 和 Network 没有预览相关错误。

### 5. 运行完整 SOP 回归

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_sop_*.py" -v
```

## 再次出现时的排查入口

先查看：

```text
outputs/sop_process_knowledge/generated_documents/route_<路线ID>/preview_failure.json
```

不要只根据页面提示重装 Word。重点查看 `preview_error_detail`，区分 DOCX 转 PDF、PDF 转 PNG、预览目录占用和旧服务进程四类问题。

## 上传服务器时

服务器发布还必须执行
`docs/deployment/server-preview-deployment.md`。Linux 使用 LibreOffice，不依赖 Microsoft Word；
部署后 `/api/ready` 必须返回 200，并且 Uvicorn 必须保持 `--workers 1`。
