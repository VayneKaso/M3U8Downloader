# M3U8Downloader 项目级说明

## 默认沟通方式

- 默认使用中文回答。
- 面向不熟悉 Python/Git、但理解 Java/Android 的用户解释问题。
- 解释代码结构时，优先用 Java 的接口、实现类、策略模式、简单工厂、注册表等概念类比。
- 动手改文件前，先说明准备改哪些文件、为什么改。
- 完成后说明改动文件、验证方式和验证结果。

## 修改原则

- 代码修改遵循现有项目风格，尽量小步、少改、可验证。
- 不做与当前任务无关的重构、格式化或目录调整。
- 不回退用户已有改动，除非用户明确要求。
- 遇到依赖安装、联网、删除文件、重置 Git、覆盖文件等高风险操作时，先征求确认。
- 新增代码尽量添加中文注释，让不熟悉 Python 但熟悉 Java 的用户能看懂意图。

## VS Code 快捷键速查约定

- 用户询问 VS Code 快捷键时，先查看 `.vscode/codex-notes.md` 中已有的快捷键速查表。
- 如果速查表里没有对应快捷键，按 Codex 默认文件访问规则查询；查到后把该快捷键补充进 `.vscode/codex-notes.md`。
- `.vscode/codex-notes.md` 只保存快捷键速查内容，不保存无关的个人配置内容。

## 项目背景

- 这是一个 Python m3u8/ts 合并工具。
- 主要入口是 `main.py`。
- 工具会扫描下载目录，找到 m3u8/ts 任务目录，然后用 `ffmpeg` 合并为 mp4。
- 当前分支 `codex/aes-key-ts-support` 在旧版普通 TS 合并基础上，新增了 51 吃瓜网 AES-128 m3u8 解密合并支持。
- 已有一个回滚点提交：`5deb8f3 兼容51吃瓜网`。

## 当前主要文件职责

- `main.py`：主流程入口，负责扫描任务、磁盘空间检查、并发处理、结果汇总。
- `ts_analyzer.py`：分析 ts 文件编号是否连续，并生成类似 `full_0_100` 或 `sub` 的标签。
- `mp4_validator.py`：用 ffmpeg 快速检查已有 mp4 是否完整。
- `handlers/`：不同网站或不同合并方式的处理器目录。

## Handler 架构约定

- 新增网站支持时，优先新增一个 handler 类，不要继续把网站专属逻辑塞进 `main.py`。
- `handlers/base.py` 定义处理器基类，作用类似 Java 里的接口或抽象类。
- `handlers/hsck.py` 是普通 TS concat 合并处理器，目前也是默认兜底处理器。
- `handlers/chigua51.py` 是 51 吃瓜网 AES-128 m3u8 解密合并处理器。
- `handlers/__init__.py` 当前承担注册表职责，集中维护 `HANDLERS` 列表和 `pick_handler()`。
- 注册表顺序有优先级：越靠前越先匹配，兜底处理器应放最后。

## 新增网站处理器的推荐步骤

1. 在 `handlers/` 下新增一个网站文件，例如 `new_site.py`。
2. 新建一个继承 `BaseSiteHandler` 的类，例如 `NewSiteHandler`。
3. 实现 `match()`，判断当前任务目录是否属于这个网站。
4. 如需修改输出标签，实现 `build_tag()`。
5. 如需自定义开始提示，实现 `get_start_message()`。
6. 实现 `merge()`，只放这个网站自己的合并逻辑。
7. 在 `handlers/__init__.py` 的 `HANDLERS` 中注册新处理器，并放在兜底处理器之前。

## 验证方式

- 修改 Python 代码后，至少运行语法检查：

```bash
python3 -m compileall main.py handlers
```

- 如果只改 handler 选择逻辑，可以构造临时目录测试 `pick_handler()` 是否选中预期处理器。
- 真实合并会读写用户下载目录和输出目录，除非用户明确要求，否则不要随便跑完整合并。

## Git 注意事项

- 当前分支通常是 `codex/aes-key-ts-support`。
- `main` 是初始老版本。
- 用户可能会要求先提交一个回滚点，再继续改造。
- 提交前先看 `git status --short --branch`，确认有哪些文件会被纳入提交。
