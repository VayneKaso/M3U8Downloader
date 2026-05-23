import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mp4_validator import get_validator
from ts_analyzer import TSAnalyzer

# ===== 配置 =====
BASE_DIR = Path("/Users/jiangliqun/Downloads/output/3")
OUTPUT_DIR = Path("/Users/jiangliqun/Downloads/output/merge_output")
MAX_WORKERS = 4
DISK_THRESHOLD_GB = 1.0  # 剩余空间阈值 (GB)
CHECK_INTERVAL = 2.0  # 磁盘检测间隔 (秒)
DISK_SAFE_SPACE_GB = 3.0  # 磁盘剩余安全容量 (GB)

# 全局停止信号
STOP_EVENT = threading.Event()
SOFT_STOP_FLAG = threading.Event()


def is_disk_space_sufficient(min_gb: float) -> bool:

    try:
        # 写死获取根目录的磁盘情况
        free_gb = getFreeGB()
        return free_gb >= min_gb
    except Exception:  # 其他意外错误
        return False


def getFreeGB():
    usage = shutil.disk_usage(str(OUTPUT_DIR))
    free_gb = usage.free / (1024**3)
    return round(free_gb, 1)


def disk_monitor():
    """后台监控守护线程：检查全盘剩余空间"""
    print(f"🔍 磁盘全局监控已启动 (阈值: {DISK_THRESHOLD_GB}GB)")

    while not STOP_EVENT.is_set():
        # 软限制检查 (3GB)
        if not is_disk_space_sufficient(DISK_SAFE_SPACE_GB):
            if not SOFT_STOP_FLAG.is_set():
                print(
                    f"\n⚠️ 提示：磁盘空间低于 {DISK_SAFE_SPACE_GB}GB，将不再启动新任务。"
                )
                SOFT_STOP_FLAG.set()
        else:
            SOFT_STOP_FLAG.clear()

        # 硬限制检查 (1GB)
        if not is_disk_space_sufficient(DISK_THRESHOLD_GB):
            # 获取当前精确数值用于打印提示
            print("\n🚨 紧急刹车：磁盘全局剩余空间不足")
            STOP_EVENT.set()
            break

        # 每隔指定时间检查一次
        time.sleep(CHECK_INTERVAL)


def natural_sort_key(s):
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", str(s))
    ]


def get_clean_name(folder_name: str):
    # 1. 先把 .m3u8 及其后面的所有杂质切掉 (忽略大小写)
    # 比如 "video.m3u8_cache" -> "video"
    temp_name = re.sub(r"\.m3u8.*", "", folder_name, flags=re.IGNORECASE)

    # 2. 只保留字母和数字
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", temp_name)

    # 3. 返回清洗后的结果，如果洗干了就返回 "output" 兜底
    return clean_name if clean_name else "output"


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


def find_target_folders() -> list[Path]:
    """找出 BASE_DIR 下看起来像 M3U8 下载任务的一级目录。"""
    return [
        p
        for p in BASE_DIR.iterdir()
        if p.is_dir()
        # 目录名命中时直接加入；否则再看目录内部是否存在 m3u8/ts 素材。
        and (any(k in p.name.lower() for k in ["index", "m3u8"]) or has_merge_inputs(p))
    ]


def read_text_safely(path: Path) -> str:
    # 常见 m3u8 是 UTF-8；少数下载工具会带 BOM 或混入异常字符，所以这里做一次兜底读取。
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="ignore")


def is_encrypted_m3u8(path: Path) -> bool:
    # HLS 标准加密通常会写 EXT-X-KEY；当前只识别最常见的 AES-128。
    text = read_text_safely(path)
    return "#EXT-X-KEY" in text and "METHOD=AES-128" in text.upper()


def find_encrypted_m3u8(folder: Path, ts_dir: Path) -> Path | None:
    # 优先检查任务根目录和 TS 目录下的 m3u8，再递归兜底。
    # 你的样例是：xxx.m3u8/index.m3u8 + xxx.m3u8/index/0.key + xxx.m3u8/index/0.ts。
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
        if is_encrypted_m3u8(playlist):
            return playlist
    return None


def get_dir_size_gb(folder: Path) -> float:
    """计算文件夹内所有 .ts 文件的体积总和 (GB)"""
    try:
        total_bytes = sum(f.stat().st_size for f in folder.glob("*.ts") if f.is_file())
        return total_bytes / (1024**3)
    except Exception:
        return 0.0


def get_ffmpeg_stderr(stderr: str) -> str:
    # ffmpeg 报错有时非常长，错误日志截断到前 10000 个字符，避免生成超大 txt。
    if stderr and len(stderr) > 10000:
        return stderr[:10000] + "\n...truncated..."
    return stderr


def merge_plain_ts(ts_dir: Path, ts_files: list[Path], output_file: Path) -> subprocess.CompletedProcess:
    # 未加密 TS 保留原来的 concat 合并方式，速度快，也不会重新编码。
    list_file = ts_dir / "concat_list.txt"
    try:
        # concat demuxer 需要一个文本清单，每行指向一个本地 TS 分片。
        with open(list_file, "w", encoding="utf-8") as f:
            for ts in ts_files:
                safe_name = ts.name.replace("'", "'\\''")
                f.write(f"file '{safe_name}'\n")

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


def merge_encrypted_m3u8(playlist: Path, output_file: Path) -> subprocess.CompletedProcess:
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


def process_folder(folder: Path):
    # 合并前、运行中、合并后都通过 STOP_EVENT 判断
    # 1. 基础状态检查
    if STOP_EVENT.is_set():
        return ("skip", folder.name, "紧急停止")
    if SOFT_STOP_FLAG.is_set():
        return ("skip", folder.name, "触发软停止限制（空间不足）")

    folder_name = folder.name
    output_file = None

    try:
        # 1. 扫描 TS 文件
        ts_dir = find_best_ts_dir(folder)
        ts_files = sorted(
            list(ts_dir.glob("*.ts")), key=lambda x: natural_sort_key(x.name)
        )

        if not ts_files:
            return ("warn", folder_name, "找不到 TS 文件")

        # 2. 基础信息生成
        output_name = f"{get_clean_name(folder_name)}.mp4"
        output_file = OUTPUT_DIR / output_name
        error_log = OUTPUT_DIR / f"{get_clean_name(folder_name)}.txt"

        print(f"{output_name} 扫描完毕，准备校验")
        # 检查ts是否合格。tag是一个标签，区分ts合成的种类，如果不合格，会抛出异常，这个任务算失败了。
        tag = TSAnalyzer.analyze(ts_files)
        # 如果任务里存在 AES-128 m3u8，就在输出名里加 aes，便于区分普通合并结果。
        encrypted_m3u8 = find_encrypted_m3u8(folder, ts_dir)
        if encrypted_m3u8:
            tag = f"{tag}_aes"
        output_name = f"{get_clean_name(folder_name)}_{tag}.mp4"
        output_file = OUTPUT_DIR / output_name
        error_log = OUTPUT_DIR / f"{get_clean_name(folder_name)}_{tag}.txt"

        print(f"{output_name} 校验合格，准备合并")

        # 3. 跳过本地已有的
        if output_file.exists():
            is_ok, _ = get_validator().verify(output_file)
            if is_ok:
                return ("skip", folder_name, f"已存在且完整 ({output_name})")
            else:
                output_file.unlink()

        # 二次检查停止信号
        if STOP_EVENT.is_set():
            return ("skip", folder_name, "任务已取消")

        # 计算真实需要的空间大小，看看磁盘剩余是否符合
        ts_total_size = get_dir_size_gb(ts_dir)
        if not is_disk_space_sufficient(ts_total_size * 1.2):
            # 这里不设置硬退出，因为可能是某个文件特别大，让其他小文件试试。
            return (
                "fail",
                folder_name,
                "预估空间不足",
            )

        if encrypted_m3u8:
            # 加密任务必须从 m3u8 入口合并，否则直接 concat 加密 TS 会得到不可播放文件。
            print(f"{output_name} 检测到 AES-128 key，使用 m3u8 解密合并")
            result = merge_encrypted_m3u8(encrypted_m3u8, output_file)
        else:
            # 普通任务继续按 TS 文件名自然排序后 concat。
            print(f"{output_name} 开始合并")
            result = merge_plain_ts(ts_dir, ts_files, output_file)

        result_stderr = get_ffmpeg_stderr(result.stderr)
        if result.returncode == 0:
            if error_log.exists():
                error_log.unlink(missing_ok=True)
            return ("success", folder_name, output_name)
        else:
            # 失败处理：清理半成品
            if output_file.exists():
                output_file.unlink()
            # FFmpeg层级的报错，空间不足
            if "No space left on device" in result.stderr:
                STOP_EVENT.set()
                return ("fail", folder_name, "❌ 磁盘爆满")
            with open(error_log, "w", encoding="utf-8") as f:
                f.write(result_stderr)
            return ("fail", folder_name, "FFmpeg 报错")

    except Exception as e:
        if isinstance(e, OSError) and e.errno == 28:  # 磁盘空间不足的系统错误码
            STOP_EVENT.set()
            return ("fail", folder_name, "❌ 磁盘空间已满 (写入清单失败)")
        if output_file is not None and output_file.exists():
            output_file.unlink()

        return ("fail", folder_name, f"异常: {e}")
    finally:
        checkDiskSpace()


def checkDiskSpace():
    if not is_disk_space_sufficient(DISK_SAFE_SPACE_GB):
        SOFT_STOP_FLAG.set()
    else:
        SOFT_STOP_FLAG.clear()


def main():

    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"~~~~~ 🎉 还能下{getFreeGB()}个G的 ~~~~~")
    target_folders = find_target_folders()
    print(f"🎬 发现任务: {len(target_folders)} 个\n")

    if len(target_folders) <= 0:
        print("👋🏻 👋🏻  没有可执行的任务，程序退出")
        return

    # if len(target_folders) >= 0:
    #     print("👋🏻 👋🏻  没有可执行的任务，程序退出")
    #     return

    # 启动监控
    monitor_thread = threading.Thread(target=disk_monitor, daemon=True)
    monitor_thread.start()

    results = []
    # 使用 ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务，注意仅仅是提交到等待队列，process_folder不会执行。
        future_to_folder = {
            executor.submit(process_folder, folder): folder for folder in target_folders
        }

        try:
            # 关键：使用 as_completed 实时获取结果
            for future in as_completed(future_to_folder):
                res = future.result()
                results.append(res)
                # 可以在这里根据 res 的内容做实时反馈，比如打印一行简报
                status, name, info = res
                tag = (
                    "✅ 成功"
                    if status == "success"
                    else "⏩ 跳过"
                    if status == "skip"
                    else "❌ 失败"
                )
                print(f"{tag}  name: {name}  info: {info}")

        except KeyboardInterrupt:
            print("\n🛑 用户手动停止，正在等待当前线程收尾...")
            STOP_EVENT.set()

    # 计算各项数据
    total_count = len(target_folders)
    processed_count = len(results)
    success = [r for r in results if r[0] == "success"]
    failed = [r for r in results if r[0] == "fail"]
    skipped = [r for r in results if r[0] == "skip"]

    # 核心逻辑：总数 - 已产出结果的数量 = 没来得及执行的数量
    cancelled_count = total_count - processed_count

    print("\n" + "═" * 50)
    print(f"📊 任务汇总报告 | 进度: {(processed_count / total_count) * 100:.1f}%")
    print(f"  ● 总计任务: {total_count:>3} 个")
    print("  ──────────────────────────────")

    # 成功
    if success:
        print(f"  ✅ 成功完成: {len(success):>3} 个")
        for _, name, info in success:
            print(f"     - {name} -> {info}")

    # 跳过
    if skipped:
        print(f"  ⏩ 自动跳过: {len(skipped):>3} 个")
        for _, name, info in skipped:
            print(f"     - {name}: {info}")

    # 失败
    if failed:
        print(f"  ❌ 执行失败: {len(failed):>3} 个")
        for _, name, info in failed:
            print(f"     - {name}: {info}")

    # 取消
    if cancelled_count > 0:
        print(f"  🚫 已取消: {cancelled_count:>3} 个\n")

    print(f"~~~~~ 🎉 还能下{getFreeGB()}个G的 ~~~~~")
    print("═" * 50)


if __name__ == "__main__":
    main()
