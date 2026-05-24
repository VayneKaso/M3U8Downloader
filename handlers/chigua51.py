import subprocess
from pathlib import Path

from handlers.base import BaseSiteHandler, find_aes128_m3u8


class Chigua51Handler(BaseSiteHandler):
    """51 吃瓜网处理器：识别 AES-128 m3u8，并交给 ffmpeg 解密合并。"""

    # 处理器名称，未来日志或调试时可以知道命中了 51 吃瓜网逻辑。
    name = "chigua51"

    def match(self, folder: Path, ts_dir: Path) -> bool:
        # 只要任务里存在 AES-128 m3u8，就认为需要走 51 吃瓜网的解密合并逻辑。
        return find_aes128_m3u8(folder, ts_dir) is not None

    def build_tag(self, base_tag: str) -> str:
        # 输出名里追加 aes，便于区分普通合并结果和解密合并结果。
        return f"{base_tag}_aes"

    def get_start_message(self, output_name: str) -> str:
        # 明确告诉用户当前任务不是普通 concat，而是从 m3u8 入口解密。
        return f"{output_name} 检测到 AES-128 key，使用 m3u8 解密合并"

    def merge(
        self,
        folder: Path,
        ts_dir: Path,
        ts_files: list[Path],
        output_file: Path,
    ) -> subprocess.CompletedProcess:
        # 加密任务必须从 m3u8 入口合并，否则直接 concat 加密 TS 会得到不可播放文件。
        playlist = find_aes128_m3u8(folder, ts_dir)
        if playlist is None:
            raise ValueError("找不到 AES-128 m3u8 文件")

        # 加密 HLS 交给 ffmpeg 按 m3u8 规则处理，这样 key URI、IV、分片顺序都由 ffmpeg 解析。
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            # 下载到本地的 key/ts 可能没有标准扩展名限制，ALL 可以避免被 ffmpeg 拒绝读取。
            "-allowed_extensions",
            "ALL",
            # AES-128 HLS 会用 file 读取 m3u8/key/ts，用 crypto 解密本地分片。
            "-protocol_whitelist",
            "file,crypto,data",
            "-i",
            str(playlist),
            "-c",
            "copy",
            str(output_file),
        ]
        return subprocess.run(
            cmd,
            cwd=playlist.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
