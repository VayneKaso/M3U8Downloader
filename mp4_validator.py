import subprocess
from pathlib import Path
from typing import Tuple


class MP4Validator:
    """MP4 完整性验证器：精简版，专注结构扫描，无缓存逻辑"""

    def quick_validate(self, mp4_path: Path) -> bool:
        """
        快速验证：通过 ffmpeg 跳转文件尾部进行流检查
        这是目前检测“磁盘满导致合并中断”最有效且最快的方法
        """
        if not mp4_path.exists() or mp4_path.stat().st_size < 1024:
            return False

        # -sseof -3: 跳到最后3秒检查，如果索引缺失（合并没封口）会直接报错
        # -xerror: 遇到流错误立刻退出
        # -map 0:v:0 -c copy: 只查视频轨道封装，不解码，极速响应
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-xerror",
            "-sseof",
            "-3",
            "-i",
            str(mp4_path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "null",
            "-",
        ]
        try:
            # 5秒超时足够处理任何文件的尾部读取
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def verify(self, mp4_path: Path) -> Tuple[bool, str]:
        """对外核心校验函数：保持原有接口不变"""
        if not mp4_path.exists():
            return False, "文件缺失"

        # 执行结构扫描
        if self.quick_validate(mp4_path):
            return True, "验证通过"
        else:
            return False, "结构损坏或不完整"


# 保持对外实例导出不变
_inst = MP4Validator()


def get_validator():
    return _inst
