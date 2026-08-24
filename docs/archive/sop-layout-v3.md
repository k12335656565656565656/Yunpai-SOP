# SOP 版式 v3 归档

v3 模板 ID：`yunpai.sop.hdmi-cable.multi-page.v3`。

归档基线：Git 标签 `archive/sop-layout-v3-before-xlsx-reference`，对应实施前提交 `c4a4c18`。

v3 使用固定图片区、右侧六段信息和独立大 IE 表。它从 v4 起退出生产生成入口，但相关渲染代码继续保留，便于排查旧文件或紧急回退。

回退时应先创建当前工作的临时分支或提交，再从该标签建立恢复分支，不要覆盖现有未提交内容：

```powershell
git switch -c restore/sop-layout-v3 archive/sop-layout-v3-before-xlsx-reference
```

退出原因：客户参考格式要求每道工序成为一张完整详细页，同时必须保留 1–6 图、人工 IE、局部编辑和真实 DOCX 预览能力。v4 只替换纸张内部版式，不改网站工作台框架。
