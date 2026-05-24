import re
from pathlib import Path


def natural_sort_key(s):
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", str(s))
    ]


def find_best_ts_dir(folder: Path) -> Path:
    # 找出所有包含 .ts 的目录（递归）
    dirs_with_ts = [
        d
        for d in [folder] + list(folder.rglob("*"))
        if d.is_dir() and any(d.glob("*.ts"))
    ]

    if not dirs_with_ts:
        return folder

    # 按直接包含的 .ts 数量排序
    return max(dirs_with_ts, key=lambda d: len(list(d.glob("*.ts"))))


def has_merge_inputs(folder: Path) -> bool:
    # 判断一个一级任务目录里是否有可合并的素材。
    # 例如：目录名不含 index/m3u8，但里面有 index.m3u8 或若干 .ts，也应该被扫描到。
    return any(folder.glob("*.m3u8")) or any(folder.rglob("*.ts"))


def find_target_folders(base_dir: Path) -> list[Path]:
    """找出 BASE_DIR 下看起来像 M3U8 下载任务的一级目录。"""
    return [
        p
        for p in base_dir.iterdir()
        if p.is_dir()
        # 目录名命中时直接加入；否则再看目录内部是否存在 m3u8/ts 素材。
        and (any(k in p.name.lower() for k in ["index", "m3u8"]) or has_merge_inputs(p))
    ]


def get_dir_size_gb(folder: Path) -> float:
    """计算文件夹内所有 .ts 文件的体积总和 (GB)"""
    try:
        total_bytes = sum(f.stat().st_size for f in folder.glob("*.ts") if f.is_file())
        return total_bytes / (1024**3)
    except Exception:
        return 0.0
