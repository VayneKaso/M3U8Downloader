import hashlib
import re
from pathlib import Path


def get_clean_name(folder_name: str):
    # 1. 先把 .m3u8 及其后面的所有杂质切掉 (忽略大小写)
    # 比如 "video.m3u8_cache" -> "video"
    temp_name = re.sub(r"\.m3u8.*", "", folder_name, flags=re.IGNORECASE)

    # 2. 只保留字母和数字
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", temp_name)

    # 3. 返回清洗后的结果，如果洗干了就返回 "output" 兜底
    return clean_name if clean_name else "output"


def pick_fingerprint_ts_files(ts_files: list[Path]) -> list[Path]:
    # 只有 1 个 ts 时，只取它自己，避免访问不存在的中间或结尾元素。
    if len(ts_files) == 1:
        return [ts_files[0]]

    # 只有 2 个 ts 时，取首尾两个，覆盖短视频常见边界情况。
    if len(ts_files) == 2:
        return [ts_files[0], ts_files[-1]]

    # 3 个及以上时，取首、中、尾三个样本，尽量用很小 IO 区分不同视频。
    return [ts_files[0], ts_files[len(ts_files) // 2], ts_files[-1]]


def build_content_suffix(folder: Path, ts_files: list[Path]) -> str:
    # 创建 SHA1 摘要对象，作用类似 Java 里的 MessageDigest。
    digest = hashlib.sha1()
    # 写入任务目录路径作为兜底特征，读取 TS 字节失败时也能得到稳定编号。
    digest.update(str(folder.resolve()).encode("utf-8", errors="ignore"))

    # 从首/中/尾 TS 中抽样读取少量字节，避免为了起名而扫描整个视频。
    for ts_file in pick_fingerprint_ts_files(ts_files):
        # 写入文件名，避免两个样本内容开头相同但分片命名不同导致过度相似。
        digest.update(ts_file.name.encode("utf-8", errors="ignore"))
        try:
            # 写入文件大小，几乎不产生 IO，但能提供很有用的区分信息。
            digest.update(str(ts_file.stat().st_size).encode("utf-8"))
            # 只读取每个样本 TS 的前 4096 字节，整体通常最多 12KB，性能影响很小。
            with open(ts_file, "rb") as f:
                digest.update(f.read(4096))
        except Exception:
            # 单个 TS 读取失败时跳过内容读取，保留前面已经写入的路径/文件名等稳定特征。
            continue

    # 把 SHA1 十六进制结果转成整数，再压缩成 000000-999999 的 6 位数字。
    return f"{int(digest.hexdigest(), 16) % 1000000:06d}"


def build_unique_output_paths(
    output_dir: Path, folder: Path, clean_name: str, tag: str, ts_files: list[Path]
) -> tuple[str, Path, Path]:
    # 根据 TS 内容生成稳定 6 位编号，同一个任务重复运行会得到同一个编号。
    content_suffix = build_content_suffix(folder, ts_files)
    # 按“index_12345_full...”这种格式拼接最终 mp4 文件名。
    output_name = f"{clean_name}_{content_suffix}_{tag}.mp4"
    # 根据最终 mp4 文件名拼出完整输出路径。
    output_file = output_dir / output_name
    # 根据同一个编号和 tag 拼出错误日志路径，方便 mp4 和 txt 一一对应。
    error_log = output_dir / f"{clean_name}_{content_suffix}_{tag}.txt"

    # 返回给主流程使用，类似 Java 方法一次返回文件名、mp4 File、日志 File。
    return output_name, output_file, error_log
