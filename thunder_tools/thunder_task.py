#!/usr/bin/env python3
"""生成迅雷 JS-SDK 下载任务页面。"""

import argparse
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

INVALID_FILENAME_CHARS = r'\/:*?"<>|'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HTML_PATH = PROJECT_ROOT / "thunder_tools" / "thunder_task.html"
DEFAULT_DOWNLOAD_DIR = "output/3"
ABSOLUTE_M3U8_PATTERN = re.compile(
    r"""(?P<url>(?:https?:)?//[^"'<>\s]+?\.m3u8(?:\?[^"'<>\s]*)?)""", re.IGNORECASE
)
RELATIVE_M3U8_PATTERN = re.compile(
    r"""["'](?P<url>[^"']+?\.m3u8(?:\?[^"']*)?)["']""", re.IGNORECASE
)


def sanitize_filename(value):
    """把网页标题清理成 macOS/迅雷更容易接受的文件名片段。"""
    # 类似 Java 里先 trim，避免标题前后的空格变成文件名的一部分。
    cleaned = value.strip()
    # 把 macOS/Windows 常见非法文件名字符替换成空格，避免迅雷创建任务失败。
    cleaned = re.sub(f"[{re.escape(INVALID_FILENAME_CHARS)}]", " ", cleaned)
    # 把连续空白压成一个空格，让文件名更紧凑也更容易阅读。
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 去掉文件名末尾的点和空格，避免某些下载器或文件系统处理异常。
    cleaned = cleaned.strip(" .")
    # 如果标题清理后为空，就给一个兜底名字，类似 Java 里给默认值避免 null/空串。
    return cleaned or "未命名视频"


def guess_source_name(url):
    """从 m3u8 地址里取最后一段文件名，通常是 index.m3u8。"""
    # urlparse 类似 Java URI，可以把 URL 拆成 path/query 等结构化字段。
    parsed = urlparse(url)
    # Path(...).name 只取路径最后一段，避免手写 split 时漏掉边界情况。
    name = Path(parsed.path).name
    # 如果 URL 没有文件名，就沿用 m3u8 场景下最常见的 index.m3u8。
    return name or "index.m3u8"


def is_m3u8_url(url):
    """判断用户输入是否已经是 m3u8 地址。"""
    # 只看 URL path，避免 query 里碰巧出现 m3u8 字样导致误判。
    parsed = urlparse(url)
    # 路径统一转小写，兼容 INDEX.M3U8 这类大小写变体。
    return parsed.path.lower().endswith(".m3u8")


def fetch_text(url):
    """用标准库抓取网页文本。"""
    # 伪装成普通浏览器，减少网站因为默认 Python UA 而拒绝访问的概率。
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    # 设置超时，避免网络卡住时脚本一直不返回。
    with urlopen(request, timeout=20) as response:
        # 先读 bytes，因为网页编码需要从响应头里判断。
        data = response.read()
        # 从 Content-Type 里提取 charset，类似 Java 里根据响应头选择解码器。
        content_type = response.headers.get("Content-Type", "")
    # 正则只找 charset=xxx 这一段，找不到就用 UTF-8 兜底。
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    # errors="replace" 可以避免个别坏字符让整个页面解析失败。
    return data.decode(match.group(1) if match else "utf-8", errors="replace")


def normalize_page_text(page_text):
    """把网页里常见的转义形式还原，方便正则找 m3u8。"""
    # html.unescape 处理 &amp; 这类 HTML 实体，避免 URL query 被截断。
    normalized = html.unescape(page_text)
    # 很多站点会把 URL 写成 https:\/\/xxx，先还原斜杠。
    normalized = normalized.replace("\\/", "/")
    # 有些 JS 会把 URL 写成 \u002F 这种形式，这里只还原 URL 常见字符。
    normalized = normalized.replace("\\u002F", "/").replace("\\u002f", "/")
    # 冒号和 & 也可能被 Unicode 转义，顺手还原成 URL 原样。
    normalized = normalized.replace("\\u003A", ":").replace("\\u003a", ":")
    # query 参数里的 & 被转义时也要还原，否则迅雷拿到的链接可能不完整。
    return normalized.replace("\\u0026", "&")


def strip_tags(value):
    """去掉标题里可能混进来的 HTML 标签。"""
    # 标题通常来自 meta 或 title，简单标签清理已经足够。
    return re.sub(r"<[^>]+>", "", value)


def extract_title(page_text):
    """从网页 HTML 里提取视频标题。"""
    # 优先读 og:title，很多视频网站会把真实标题放在这里。
    meta_match = re.search(
        r"""<meta[^>]+(?:property|name)=["']og:title["'][^>]+content=["']([^"']+)["']""",
        page_text,
        re.IGNORECASE,
    )
    # 如果属性顺序反过来，再用另一条正则补一次。
    if not meta_match:
        meta_match = re.search(
            r"""<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']og:title["']""",
            page_text,
            re.IGNORECASE,
        )
    # 找到 og:title 就直接清理并返回。
    if meta_match:
        return sanitize_filename(html.unescape(strip_tags(meta_match.group(1))))
    # 兜底读取浏览器标签页标题。
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", page_text, re.IGNORECASE | re.DOTALL
    )
    # 找不到标题时返回 None，让调用方决定默认值。
    if not title_match:
        return None
    # title 标签可能跨行，所以先去标签再压缩空白。
    return sanitize_filename(html.unescape(strip_tags(title_match.group(1))))


def extract_m3u8_url(page_url, page_text):
    """从网页 HTML 里提取第一个 m3u8 地址。"""
    # 先还原常见转义，再用统一正则查找 m3u8。
    normalized = normalize_page_text(page_text)
    # 优先找绝对地址，避免把页面展示文字里的“文件名xxx.m3u8”误当成链接。
    for match in ABSOLUTE_M3U8_PATTERN.finditer(normalized):
        # 去掉末尾可能跟着的转义或标点，避免把 JS 语法带进 URL。
        candidate = match.group("url").rstrip("\\),.;")
        # 协议相对地址 //cdn.xxx/index.m3u8 要继承页面协议。
        if candidate.startswith("//"):
            return f"{urlparse(page_url).scheme}:{candidate}"
        # 绝对地址可以直接返回。
        return candidate
    # 找不到绝对地址时，再尝试引号包裹的相对地址。
    for match in RELATIVE_M3U8_PATTERN.finditer(normalized):
        # 只从引号内取值，避免把中文说明文字拼进链接。
        candidate = match.group("url").rstrip("\\),.;")
        # 相对地址用 urljoin 变成绝对地址，类似 Java URI.resolve。
        return urljoin(page_url, candidate)
    # 找不到就明确抛错，避免生成一个空任务让迅雷弹出奇怪结果。
    raise ValueError("没有在网页里找到 .m3u8 地址")


def resolve_task_info(source_url, explicit_title):
    """把用户输入解析成迅雷需要的 title 和 m3u8。"""
    # 如果用户直接传 m3u8，就不抓网页，保持第一版的快速路径。
    if is_m3u8_url(source_url):
        # 直接 m3u8 模式下没有网页标题，所以允许用户 title 为空时用默认值。
        return explicit_title or "未命名视频", source_url
    # 网页模式需要先抓 HTML，再从里面提取标题和 m3u8。
    page_text = fetch_text(source_url)
    # 命令行传入的标题优先级最高，方便用户覆盖网页标题。
    title = explicit_title or extract_title(page_text) or "未命名视频"
    # m3u8 必须从网页里找到，找不到就让异常提示用户。
    m3u8_url = extract_m3u8_url(source_url, page_text)
    # 返回结构保持简单，类似 Java 里返回一个二元 DTO。
    return title, m3u8_url


def build_download_name(title, url, explicit_name=None):
    """根据标题和原始 URL 生成迅雷里显示的下载文件名。"""
    # 如果用户直接指定完整文件名，就尊重用户输入，只做非法字符清理。
    if explicit_name:
        return sanitize_filename(explicit_name)
    # 标题只作为前缀，保留原始 URL 的 index.m3u8 这类后缀，贴合迅雷当前识别习惯。
    safe_title = sanitize_filename(title)
    # 保留原始 m3u8 文件名，方便看到它仍然是一个 m3u8 下载任务。
    source_name = sanitize_filename(guess_source_name(url))
    # 和你验证成功的“我的标题index.m3u8”保持一致，不额外加分隔符。
    return f"{safe_title}{source_name}"


def build_html(url, download_name, download_dir):
    """生成一个本地 HTML，通过迅雷官方 JS-SDK 创建下载任务。"""
    # 用 json.dumps 生成 JS 字面量，避免标题里有引号时破坏脚本语法。
    task_json = json.dumps(
        {
            "downloadDir": download_dir,
            "tasks": [
                {
                    "url": url,
                    "name": download_name,
                }
            ],
        },
        ensure_ascii=False,
        indent=12,
    )
    # 页面展示用 HTML 转义，避免特殊字符影响本地页面结构。
    escaped_url = html.escape(url)
    # 文件名展示也单独转义；真正传给迅雷的值仍然来自上面的 JSON。
    escaped_download_name = html.escape(download_name)
    # 页面保留按钮作为兜底：如果浏览器拦截自动拉起，用户可以手动点一下。
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>迅雷下载任务</title>
</head>
<body>
  <button id="download">拉起迅雷下载</button>
  <p>文件名：{escaped_download_name}</p>
  <p>链接：{escaped_url}</p>

  <script src="https://open.thunderurl.com/thunder-link.js"></script>
  <script>
    const task = {task_json};

    function startThunderTask() {{
      thunderLink.newTask(task);
    }}

    document.getElementById('download').onclick = startThunderTask;
    window.onload = startThunderTask;
  </script>
</body>
</html>
"""


def write_task_html(url, download_name, download_dir, output_path):
    """把迅雷任务页面写入固定 HTML 文件，并返回文件路径。"""
    # expanduser 支持用户传 ~/Desktop/xxx.html 这种路径。
    output_path = Path(output_path).expanduser()
    # resolve 让打印出来的路径是绝对路径，方便用户定位文件。
    output_path = output_path.resolve()
    # 确保父目录存在，避免自定义输出路径时因为目录不存在而失败。
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 写入 UTF-8，确保中文标题在浏览器和迅雷里都能正常显示。
    output_path.write_text(
        build_html(url, download_name, download_dir), encoding="utf-8"
    )
    # 返回 Path 对象，调用方可以选择打印或用 open 打开。
    return output_path


def parse_args(argv=None):
    """解析命令行参数，保持脚本入口清晰。"""
    # argparse 类似 Java CLI 库里的参数定义器，集中声明参数和帮助文案。
    parser = argparse.ArgumentParser(description="生成并打开迅雷 m3u8 下载任务")
    # 现在既支持网页 URL，也支持直接传真实 m3u8 地址。
    parser.add_argument("url", help="网页 URL 或真实 m3u8 地址")
    # 标题可选：网页模式会自动抓，直接 m3u8 模式建议手动传。
    parser.add_argument("--title", help="手动指定视频标题，优先级高于网页标题")
    # 允许用户绕过默认拼接规则，直接指定迅雷显示的完整文件名。
    parser.add_argument("--name", help="直接指定迅雷下载文件名")
    # 对应迅雷 JS-SDK 的 downloadDir，默认使用你测试过的目录名 output/3。
    parser.add_argument(
        "--download-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help="迅雷下载目录名，默认是 output/3",
    )
    # 默认复用 thunder_tools/thunder_task.html，避免每次生成新的临时文件。
    parser.add_argument(
        "--html-path", default=DEFAULT_HTML_PATH, help="生成的 HTML 文件路径"
    )
    # 验证脚本时可以只生成 HTML，不打开浏览器、不拉起迅雷。
    parser.add_argument(
        "--no-open", action="store_true", help="只生成 HTML，不自动打开"
    )
    # 返回解析后的参数对象，类似 Java 里返回一个配置 DTO。
    return parser.parse_args(argv)


def main(argv=None):
    """脚本主入口：生成任务页面，并按需打开它。"""
    # 先解析命令行参数，后续逻辑都从 args 读取配置。
    args = parse_args(argv)
    # 把网页 URL 或 m3u8 URL 统一解析成 title + 真实 m3u8。
    title, m3u8_url = resolve_task_info(args.url, args.title)
    # 生成迅雷要显示的文件名，把 title 和原始 index.m3u8 拼起来。
    download_name = build_download_name(title, m3u8_url, args.name)
    # 写出固定 HTML，让浏览器加载迅雷 JS-SDK。
    html_path = write_task_html(
        m3u8_url, download_name, args.download_dir, args.html_path
    )
    # 打印关键信息，方便用户确认脚本生成的任务是否符合预期。
    print(f"标题：{title}")
    print(f"文件名：{download_name}")
    print(f"链接：{m3u8_url}")
    print(f"HTML：{html_path}")
    # --no-open 用于测试和排查，不触发任何 GUI 动作。
    if args.no_open:
        return
    # macOS 的 open 会用默认浏览器打开本地 HTML，再由 JS-SDK 拉起迅雷。
    subprocess.run(["open", str(html_path)], check=True)


if __name__ == "__main__":
    main()
