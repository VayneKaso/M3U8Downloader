import subprocess
from pathlib import Path

from handlers.base import BaseSiteHandler


class HsckHandler(BaseSiteHandler):
    """普通 TS 合并处理器：当前作为 hsck 和默认普通下载任务的兜底处理器。"""

    # 处理器名称，方便未来日志里区分“普通合并”和“特殊网站合并”。
    name = "hsck"

    def match(self, folder: Path, ts_dir: Path) -> bool:
        # 普通 TS 合并是兜底策略，所以只要前面的特殊处理器不匹配，就由它处理。
        return True

    def merge(
        self,
        folder: Path,
        ts_dir: Path,
        ts_files: list[Path],
        output_file: Path,
    ) -> subprocess.CompletedProcess:
        # 未加密 TS 保留原来的 concat 合并方式，速度快，也不会重新编码。
        list_file = ts_dir / "concat_list.txt"
        try:
            # concat demuxer 需要一个文本清单，每行指向一个本地 TS 分片。
            with open(list_file, "w", encoding="utf-8") as f:
                for ts in ts_files:
                    safe_name = ts.name.replace("'", "'\\''")
                    f.write(f"file '{safe_name}'\n")

            # ffmpeg 命令保持原逻辑：读取清单，然后直接 copy 封装为 mp4。
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_file),
            ]
            return subprocess.run(
                cmd,
                cwd=ts_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        finally:
            # 清单文件只是临时输入，合并结束后无论成功失败都清掉。
            if list_file.exists():
                list_file.unlink(missing_ok=True)
