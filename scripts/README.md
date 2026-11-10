# scripts/ — custom 脚本根

这里只放用户/Agent 通过 `save_script` 写入的自定义脚本，目录结构固定为：

```text
scripts/
├── datasource/
├── indicator/
├── strategy/
└── optimizer/
```

- 内置脚本在 `agentkline/resources/scripts/`，只读，不要放这里。
- 测试、生成器、发布、soak 等开发工具在 `../tools/`。
- 服务管理脚本在仓库根 `../service.sh`。
