# Artifact Protocol

## Artifact 类型

| 类型 | 说明 |
|---|---|
| `code_file` | 代码文件 |
| `markdown_doc` | Markdown 文档 |
| `web_preview` | 可 iframe 预览的网页产物 |
| `source_diff` | 真实源码 diff |
| `deployment_release` | 部署结果 |

## Artifact 字段

```json
{
  "id": "string",
  "conversation_id": "string",
  "run_id": "string",
  "created_by_agent_id": "string",
  "type": "web_preview",
  "title": "string",
  "status": "available | failed | pending",
  "uri": "string | null",
  "preview_url": "string | null",
  "version": 1,
  "created_at": "ISO-8601"
}
```

## 创建规则

1. 只有真实文件、真实内容或真实 diff 存在时，才能创建 Artifact。
2. 空输出不得生成 Artifact。
3. DiffCard 只能由真实 diff 生成。
4. WebPreviewCard 只能由真实 HTML 或构建产物生成。
5. DeploymentCard 只有 URL 可访问时才能显示 `published`。

## Preview

- HTML：iframe sandbox。
- Markdown：文档渲染。
- Code：代码块或编辑器。
- Diff：逐文件 diff 展示。
