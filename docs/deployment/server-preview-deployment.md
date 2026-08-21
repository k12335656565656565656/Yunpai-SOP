# SOP 服务器部署与预览检查

## 支持范围

首版服务器部署支持 Linux 或 Windows 单机、单应用进程。推荐 Ubuntu/Debian Linux，使用：

- LibreOffice Writer：DOCX 转 PDF。
- PyMuPDF：PDF 转分页 PNG。
- Uvicorn：运行 Web 应用。
- SQLite：保存路线、审核和知识数据。

当前生成锁是进程内锁，SQLite 也使用本地文件，因此必须使用一个 Uvicorn worker。不要通过增加 worker 解决慢请求；多 worker 需要先增加跨进程锁和共享数据库。

## Linux 依赖

```bash
sudo apt-get update
sudo apt-get install -y python3-venv libreoffice-writer fonts-noto-cjk fontconfig
```

中文字体是必需项。缺少字体时转换可能成功，但 PDF/DOCX 会出现替换字体、乱码或分页变化。

## 安装

当前部署必须使用完整源码仓库，不能只上传 Python wheel，因为模板生成器和预览辅助脚本位于 `scripts/`。

```bash
git clone https://github.com/redmaplewww/Yunpai-SOP.git
cd Yunpai-SOP
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

也可以直接使用仓库内的容器配置，LibreOffice、中文字体、单 worker 和健康检查已经固化：

```bash
docker compose up -d --build
docker compose ps
```

容器数据默认保存在仓库同级的 `server-data/`，该目录不会进入 Git，但必须纳入服务器备份。

## 持久化目录

建议使用独立目录，例如：

```text
/var/lib/yunpai-sop/
  sop_knowledge.sqlite3
  sop_media/
  generated_documents/
```

数据库文件及同级的 `sop_media`、`generated_documents` 必须一起备份和持久化。容器重建或代码更新不能删除该目录。

新上传图片在数据库中使用 `sop_media/<文件名>` 相对路径。已有 Windows 绝对路径会在迁移后按文件名从数据库同级的 `sop_media` 自动恢复；仍需确保 SQLite 与整个 `sop_media` 目录一起复制，不能只复制数据库文件。

## 环境变量

```bash
export SOP_DB_PATH=/var/lib/yunpai-sop/sop_knowledge.sqlite3
export SOP_LIBREOFFICE_PATH=/usr/bin/libreoffice
```

AI 服务的 API Key 继续通过服务器环境变量或密钥管理服务提供，不得写入仓库、服务文件或镜像。

## 启动

```bash
.venv/bin/uvicorn cad_ai.sop_knowledge.web:create_server_app \
  --factory \
  --host 127.0.0.1 \
  --port 8787 \
  --workers 1 \
  --timeout-keep-alive 180
```

生产环境应由 systemd、Docker Compose 或其他进程管理器负责自动重启，不要在 SSH 会话里直接长期运行。

## 健康检查

```bash
curl -fsS http://127.0.0.1:8787/api/health
curl -fsS http://127.0.0.1:8787/api/ready
```

- `/api/health`：进程存活检查，返回当前依赖详情。
- `/api/ready`：数据库、模板、DOCX 转换器和 PDF 分页器全部可用时才返回 200；反向代理和容器 readiness 使用该接口。

## Nginx 关键配置

DOCX 生成通常需要几十秒，代理超时不能使用过短的默认值：

```nginx
location / {
    proxy_pass http://127.0.0.1:8787;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 15s;
    proxy_send_timeout 240s;
    proxy_read_timeout 240s;
    client_max_body_size 15m;
}
```

## 发布前验收

1. `/api/ready` 返回 200 且 `status=ready`。
2. 使用真实路线调用一次 `/api/routes/<路线ID>/documents/generate`。
3. `page_count` 等于 `1 + 当前有效工序数量`。
4. `preview_url` 非空且所有 `page_urls` 返回 200。
5. 浏览器刷新后显示最新版本指纹，PNG 失败时能自动切换同版本 PDF。
6. 重启服务后数据库、图片和最新文档仍存在。
7. 确认应用进程只有一个 worker。

详细的代码上传检查继续执行：
`docs/handoff/sop_template_ai_handoff/DOCX_PREVIEW_UPLOAD_CHECKLIST.md`。
