import subprocess
from pathlib import Path


class BaseSiteHandler:
    """网站处理器基类：作用类似 Java 里的 interface/abstract class。"""

    # 给处理器起一个名字，后续打印日志或排查问题时可以直接看出走了哪个处理器。
    name = "base"

    def match(self, folder: Path, ts_dir: Path) -> bool:
        # 子类负责判断自己能不能处理当前目录。
        return False

    def build_tag(self, base_tag: str) -> str:
        # 默认不改 TSAnalyzer 算出来的标签，特殊网站可以在子类里追加后缀。
        return base_tag

    def get_start_message(self, output_name: str) -> str:
        # 默认合并提示，特殊网站可以在子类里改成更明确的提示。
        return f"{output_name} 开始合并"

    def merge(
        self,
        folder: Path,
        ts_dir: Path,
        ts_files: list[Path],
        output_file: Path,
    ) -> subprocess.CompletedProcess:
        # 这里故意抛异常，提醒新网站子类必须实现真正的合并逻辑。
        raise NotImplementedError("子类必须实现 merge 方法")


def read_text_safely(path: Path) -> str:
    # 常见 m3u8 是 UTF-8；少数下载工具会带 BOM 或混入异常字符，所以这里做一次兜底读取。
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="ignore")


def is_aes128_m3u8(path: Path) -> bool:
    # HLS 标准加密通常会写 EXT-X-KEY；当前只识别最常见的 AES-128。
    text = read_text_safely(path)
    return "#EXT-X-KEY" in text and "METHOD=AES-128" in text.upper()


def find_aes128_m3u8(folder: Path, ts_dir: Path) -> Path | None:
    # 优先检查任务根目录和 TS 目录下的 m3u8，再递归兜底。
    candidates = []
    candidates.extend(folder.glob("*.m3u8"))
    candidates.extend(ts_dir.glob("*.m3u8"))
    candidates.extend(folder.rglob("*.m3u8"))

    # folder 和 ts_dir 可能相同，去重可以避免重复读取同一个 playlist。
    seen = set()
    for playlist in candidates:
        if playlist in seen:
            continue
        seen.add(playlist)
        if is_aes128_m3u8(playlist):
            return playlist
    return None
