import hashlib
import re
from pathlib import Path

CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
# 【修改 1】在正则表达式末尾加上了 \-，允许并保留连字符，不再把连字符替换成下划线
OUTPUT_ALLOWED_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9,，.。!！?？\-]+")


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
    digest = hashlib.sha1()
    digest.update(str(folder.resolve()).encode("utf-8", errors="ignore"))

    for ts_file in pick_fingerprint_ts_files(ts_files):
        digest.update(ts_file.name.encode("utf-8", errors="ignore"))
        try:
            digest.update(str(ts_file.stat().st_size).encode("utf-8"))
            with open(ts_file, "rb") as f:
                digest.update(f.read(4096))
        except Exception:
            continue

    return f"{int(digest.hexdigest(), 16) % 1000000:06d}"


def build_unique_output_paths(
    output_dir: Path, folder: Path, clean_name: str, tag: str, ts_files: list[Path]
) -> tuple[str, Path, Path]:

    if has_chinese(folder.name):
        # 此时 build_readable_output_stem 出来的就是一层干净的名字
        output_name = f"{build_readable_output_stem(folder)}_{tag}.mp4"
        output_file = output_dir / output_name
        output_file.parent.mkdir(parents=True, exist_ok=True)
        error_log = output_file.with_suffix(".txt")
        return output_name, output_file, error_log

    content_suffix = build_content_suffix(folder, ts_files)
    output_name = f"{clean_name}_{content_suffix}_{tag}.mp4"
    output_file = output_dir / output_name
    error_log = output_dir / f"{clean_name}_{content_suffix}_{tag}.txt"

    return output_name, output_file, error_log


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

            output_name, output_file, error_log = build_unique_output_paths(
                output_dir=output_dir,
                folder=test_folder,
                clean_name=clean_name,
                tag=tag,
                ts_files=ts_files_list,
            )

            print("-" * 50)
            print(f"输入目录名: {test_folder.name}")
            print(f"★ 相对文件名 (output_name) : {output_name}")
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
