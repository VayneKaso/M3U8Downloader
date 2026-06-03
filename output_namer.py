import hashlib
import re
from pathlib import Path

CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
# 【修改 1】在正则表达式末尾加上了 \-，允许并保留连字符，不再把连字符替换成下划线
OUTPUT_ALLOWED_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9,，.。!！?？\-]+")
CONTENT_SUFFIX_PATTERN = re.compile(r"_(\d{6})\.mp4$", re.IGNORECASE)


def get_clean_name(folder_name: str):
    temp_name = re.sub(r"\.m3u8.*", "", folder_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", temp_name)
    return clean_name if clean_name else "output"


def has_chinese(value: str) -> bool:
    return CHINESE_PATTERN.search(value) is not None


def clean_readable_name(value: str) -> str:
    # 1. 去掉 .m3u8 及后面的缓存杂质
    temp_name = re.sub(r"\.m3u8.*", "", value, flags=re.IGNORECASE)

    # 【修改 2】强制干掉末尾的 "-index" 或 "_index" 或 "index"
    temp_name = re.sub(r"[-_]?index$", "", temp_name, flags=re.IGNORECASE)

    # 2. 提取合法字符
    parts = OUTPUT_ALLOWED_PATTERN.findall(temp_name)
    readable_name = "_".join(part for part in parts if part)

    # 3. 去掉首尾多余符号，加入了对连字符 "-" 的剔除
    readable_name = readable_name.strip("._-。 ")
    return readable_name or "output"


def find_readable_m3u8_stem(folder: Path) -> str | None:
    candidates = list(folder.glob("*.m3u8"))
    candidates.extend(folder.rglob("*.m3u8"))
    unique_candidates = sorted(set(candidates), key=lambda path: str(path))
    if not unique_candidates:
        return None
    for playlist in unique_candidates:
        if has_chinese(playlist.name):
            return clean_readable_name(playlist.name)
    return clean_readable_name(unique_candidates[0].name)


def build_readable_output_stem(folder: Path) -> str:
    folder_part = clean_readable_name(folder.name)
    playlist_part = find_readable_m3u8_stem(folder)

    if not playlist_part:
        return folder_part
    if playlist_part == folder_part:
        return folder_part

    # 【修改 3】坚决不要多级路径。如果名字不一样，我们只挑一个最优的。
    # 优先用 m3u8 的名字（如果它里面有中文，说明它大概率是真实片名）
    if has_chinese(playlist_part):
        return playlist_part

    # 否则兜底使用文件夹的名字
    return folder_part


def pick_fingerprint_ts_files(ts_files: list[Path]) -> list[Path]:
    if len(ts_files) == 1:
        return [ts_files[0]]
    if len(ts_files) == 2:
        return [ts_files[0], ts_files[-1]]
    return [ts_files[0], ts_files[len(ts_files) // 2], ts_files[-1]]


def build_content_suffix(folder: Path, ts_files: list[Path]) -> str:
    # folder 保留在参数里，是为了不破坏 main.py 和测试入口现有调用方式。
    digest = hashlib.sha1()

    for ts_file in pick_fingerprint_ts_files(ts_files):
        # 只用 TS 文件自身信息生成指纹，不混入目录路径，这样同一视频换目录也能识别为同一个内容。
        digest.update(ts_file.name.encode("utf-8", errors="ignore"))
        try:
            # 文件大小是廉价且稳定的特征，类似 Java 里先用 metadata 做快速区分。
            digest.update(str(ts_file.stat().st_size).encode("utf-8"))
            # 每个采样 TS 只读前 4KB，避免为了去重把大文件完整读一遍。
            with open(ts_file, "rb") as f:
                digest.update(f.read(4096))
        except Exception:
            # 某个 TS 被占用或读取失败时跳过它，避免命名阶段直接中断整个任务。
            continue

    return f"{int(digest.hexdigest(), 16) % 1000000:06d}"


def extract_content_suffix(mp4_name: str) -> str | None:
    # 从 xxx_full_0_9_232323.mp4 里取最后 6 位内容标识。
    match = CONTENT_SUFFIX_PATTERN.search(mp4_name)
    # 没有匹配说明这是旧命名或无效文件名，返回 None 让调用方忽略。
    return match.group(1) if match else None


def find_outputs_by_content_suffix(
    output_dir: Path, content_suffix: str, exclude: Path
) -> list[Path]:
    # 用 glob 精确匹配尾部标识，几百个文件时也只遍历命中的候选，避免全目录逐个正则扫描。
    candidates = sorted(
        output_dir.glob(f"*_{content_suffix}.mp4"), key=lambda path: path.name
    )
    # 只返回普通文件，并排除当前目标文件，因为同名检查在调用方会先处理。
    return [
        candidate
        for candidate in candidates
        if candidate.is_file() and candidate != exclude
    ]


def find_existing_valid_output(output_file: Path, content_suffix: str, validator) -> Path | None:
    # 第一优先级：完全同名文件存在且完整，直接复用。
    if output_file.exists():
        # 复用现有 MP4Validator.verify()，保持和旧逻辑一样的快速尾部校验。
        is_ok, _ = validator.verify(output_file)
        if is_ok:
            return output_file
        # 同名但不完整时删除半成品，后面允许重新合并生成。
        output_file.unlink()

    # 第二优先级：没有同名文件时，再查是否已有相同 6 位内容标识的视频。
    for existing_file in find_outputs_by_content_suffix(
        output_file.parent, content_suffix, output_file
    ):
        # 同标识文件也必须通过完整性校验，避免把坏文件当成已下载。
        is_ok, _ = validator.verify(existing_file)
        if is_ok:
            return existing_file
    # 同标识但不完整的其他文件不删除，避免误动用户可能还想保留的旧结果。
    return None


def build_unique_output_paths(
    output_dir: Path, folder: Path, clean_name: str, tag: str, ts_files: list[Path]
) -> tuple[str, Path, Path, str]:

    content_suffix = build_content_suffix(folder, ts_files)
    if has_chinese(folder.name):
        # 此时 build_readable_output_stem 出来的就是一层干净的名字
        output_name = f"{build_readable_output_stem(folder)}_{tag}_{content_suffix}.mp4"
        output_file = output_dir / output_name
        output_file.parent.mkdir(parents=True, exist_ok=True)
        error_log = output_file.with_suffix(".txt")
        return output_name, output_file, error_log, content_suffix

    output_name = f"{clean_name}_{tag}_{content_suffix}.mp4"
    output_file = output_dir / output_name
    error_log = output_dir / f"{clean_name}_{tag}_{content_suffix}.txt"

    return output_name, output_file, error_log, content_suffix


# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    print("=== 输出路径生成测试工具 ===")

    while True:
        test_folder_name = input("\n请输入测试文件夹名称 (输入 exit 退出): ").strip()
        if test_folder_name.lower() == "exit":
            break
        if not test_folder_name:
            continue

        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            test_folder = base_path / test_folder_name
            test_folder.mkdir()

            # 模拟 m3u8 文件（优先取用户输入主体加上.m3u8）
            simulated_m3u8_name = re.sub(
                r"\.m3u8.*", "", test_folder_name, flags=re.IGNORECASE
            )
            m3u8_file = test_folder / f"{simulated_m3u8_name}.m3u8"
            m3u8_file.write_text("#EXTM3U\n0.ts", encoding="utf-8")

            # 模拟 ts 文件
            ts_file1 = test_folder / "0.ts"
            ts_file1.write_bytes(b"dummy")
            ts_files_list = [ts_file1]

            output_dir = base_path / "Merge_Output"
            output_dir.mkdir()

            clean_name = get_clean_name(test_folder.name)
            tag = "full_0_99"

            output_name, output_file, error_log, content_suffix = build_unique_output_paths(
                output_dir=output_dir,
                folder=test_folder,
                clean_name=clean_name,
                tag=tag,
                ts_files=ts_files_list,
            )

            print("-" * 50)
            print(f"输入目录名: {test_folder.name}")
            print(f"★ 相对文件名 (output_name) : {output_name}")
            print(f"★ 6位内容标识 (content_suffix): {content_suffix}")
            try:
                print(
                    f"★ 最终 MP4 路径 (output_file): {output_file.relative_to(base_path)}"
                )
                print(
                    f"★ 最终 TXT 路径 (error_log)  : {error_log.relative_to(base_path)}"
                )
            except ValueError:
                print(f"★ 最终 MP4 路径 (output_file): {output_file}")
                print(f"★ 最终 TXT 路径 (error_log)  : {error_log}")
