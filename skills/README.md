# skills 目录约定

```
skills/
├── agent/   # 对话 Agent 的运行时技能（web 后端唯一扫描来源）
│   └── home-profile/
└── dev/     # 项目开发流程技能（供开发助手使用，对话不可见）
    └── web-module-init/
```

- **agent/**：运行时对话技能。每个技能 = 子文件夹 + `SKILL.md`，文件必须以
  YAML frontmatter 开头（首行 `---`），含 `name` 与 `description`。
  后端启动清单只注入 name/description，正文由模型经 `read_skill` 工具按需读取。
- **dev/**：项目开发流程技能（如模块初始化流程固化），供开发助手（ZCode）使用，
  不会被后端扫描，与对话互不干扰。
