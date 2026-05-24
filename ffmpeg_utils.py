def get_ffmpeg_stderr(stderr: str) -> str:
    # ffmpeg 报错有时非常长，错误日志截断到前 10000 个字符，避免生成超大 txt。
    if stderr and len(stderr) > 10000:
        return stderr[:10000] + "\n...truncated..."
    return stderr
