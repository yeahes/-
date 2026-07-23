# runtime/python311._pth 变更说明

## 变更

在 `runtime/python311._pth` 中新增一行：

```text
..
```

## 目的

项目内置的 `runtime/python.exe` 默认只把 `runtime` 目录加入 `sys.path`，不会自动包含项目根目录。
因此以下命令无法找到 `tests` 包：

```powershell
runtime\python.exe -m tests.caption_audit.run_all
```

加入 `..` 后，内置 Python 可以从项目根目录导入 `tests`、`app` 等项目包。

## 影响

收益：

- 支持 `python -m tests.caption_audit.run_all` 形式的稳定回归入口。
- 回归测试和项目代码使用同一个内置 Python 环境。

风险：

- 项目根目录会参与模块解析。如果根目录存在与第三方库同名的文件或目录，可能改变导入优先级。
- 当前已通过 `tests.test_stable_caption_rules.test_runtime_module_import_path_is_available` 验证 `-m` 入口可用。

## 约束

不要继续向 `python311._pth` 加入宽泛路径，例如用户目录、桌面目录或系统 Python 路径。
