# M3U8Downloader 项目级说明

## 一句话

本项目扫描下载目录中的 m3u8/ts 任务，按任务类型选择合并器，最后用 `ffmpeg` 生成 `mp4`，并在磁盘空间不足时自动限流或停止。

## 先看这里

- 主要入口是 `main.py`。
- 任务识别流程：`find_target_folders()` -> `find_best_ts_dir()` -> `TSAnalyzer.analyze()` -> `pick_handler()` -> `merge()`。
- 处理器优先级由 `handlers/__init__.py` 里的 `HANDLERS` 顺序决定，越靠前越先匹配。
- 当前顺序是：`Chigua51Handler` -> `HsckHandler`，最后一个是兜底处理器。
- 输出文件名由 `output_namer.py` 统一生成，尽量避免同名误判。
- 已有一个回滚点提交：`5deb8f3 兼容51吃瓜网`。

## 主流程

- `main.py` 扫描 `BASE_DIR` 下的一级任务目录。
- `find_best_ts_dir()` 会找出 ts 最多的目录作为合并源。
- `TSAnalyzer.analyze()` 用来判断 ts 编号是否连续，返回 `full_x_y` 或 `sub`，异常直接算失败。
- 合并前会先校验已存在的 `mp4`，通过 `mp4_validator.get_validator().verify()` 复用完整结果。
- 合并前会检查磁盘空间：
  - `3GB`：软停止，不再启动新任务。
  - `1GB`：硬停止，直接终止后续流程。
- `process_folder()` 的返回值固定是 `(status, name, info)`，状态只会是 `success` / `skip` / `fail`。
- `LOGCAT.summary()` 负责最终汇总展示。

## Handler 规则

- 新增网站支持时，优先新增 handler 类，不要把网站专属逻辑继续堆进 `main.py`。
- `handlers/base.py` 的 `BaseSiteHandler` 相当于 Java 里的抽象基类。
- 需要实现的核心方法是：
  - `match(folder, ts_dir)`：判断是否命中当前网站/任务类型。
  - `build_tag(base_tag)`：必要时修改输出标签。
  - `get_start_message(output_name)`：可选，定制开始提示。
  - `merge(...)`：真正执行合并。
- `Chigua51Handler`：
  - 识别 AES-128 的 m3u8。
  - 输出标签会追加 `_aes`。
  - 合并时直接让 `ffmpeg` 读取 m3u8，而不是把加密 ts 当普通 concat 处理。
- `HsckHandler`：
  - 普通 TS concat 合并。
  - 通过临时 `concat_list.txt` 喂给 `ffmpeg`。
  - 作为兜底处理器使用。

## 输出命名

- `get_clean_name()` 负责生成基础英文文件名。
- 中文目录会优先走可读输出名。
- 非中文目录会追加 6 位内容指纹，避免同名任务互相覆盖。
- 错误日志和输出视频会使用同一套命名规则，方便一一对应。

## 已知注意

- 当前 `main.py` 里有一处明显的早退残留：`if len(target_folders) >= 0: return`。
- 如果主流程看起来“找到任务却立刻退出”，先优先检查这行是否已经被修掉。

## 修改原则

- 默认使用中文回答。
- 面向不熟悉 Python/Git、但理解 Java/Android 的用户解释问题。
- 解释代码结构时，优先用 Java 概念类比。
- 动手改文件前，先说明准备改哪些文件、为什么改。
- 完成后说明改动文件、验证方式和验证结果。
- 代码修改尽量小步、少改、可验证。
- 不做与当前任务无关的重构、格式化或目录调整。
- 遇到依赖安装、联网、删除文件、重置 Git、覆盖文件等高风险操作时，先征求确认。
- 新增代码尽量添加中文注释，让不熟悉 Python 但熟悉 Java 的用户能看懂意图。

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
- 提交前先看 `git status --short --branch`，确认有哪些文件会被纳入提交。
