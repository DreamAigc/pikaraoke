import json
import logging
import os
import shlex
import subprocess
import sys
import requests
import time

from pikaraoke.lib.get_platform import get_installed_js_runtime

# yt-dlp command, gets the yt-dlp module from the current python environment
yt_dlp_cmd = [sys.executable, "-m", "yt_dlp"]


def get_youtubedl_version() -> str:
    """Get the installed yt-dlp version.

    Args:
    Returns:
        Version string of the installed yt-dlp or an error message.
    """
    try:
        cmd = yt_dlp_cmd + ["--version"]
        return subprocess.check_output(cmd).strip().decode("utf8")
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as e:
        logging.warning(f"Could not get yt-dlp version: {e}")
        return "Not found"
    except Exception as e:
        logging.error(f"Unexpected error getting yt-dlp version: {e}")
        return "Error"


def get_youtube_id_from_url(url: str) -> str | None:
    """Extract the YouTube video ID from a URL.

    Supports youtube.com/watch?v=, m.youtube.com/?v=, and youtu.be/ formats.

    Args:
        url: YouTube video URL.

    Returns:
        The video ID string, or None if parsing failed.
    """
    if "v=" in url:  # accommodates youtube.com/watch?v= and m.youtube.com/?v=
        s = url.split("watch?v=")
    else:  # accommodates youtu.be/
        s = url.split("u.be/")
    if len(s) == 2:
        if "?" in s[1]:  # Strip unneeded YouTube params
            s[1] = s[1][0 : s[1].index("?")]
        return s[1]
    else:
        logging.error("Error parsing youtube id from url: " + url)
        return None


def upgrade_youtubedl() -> str:
    """Upgrade yt-dlp to the latest version.

    Attempts self-upgrade first, then falls back to pip if needed.

    Args:
    Returns:
        The new version string after upgrade.
    """
    try:
        output = (
            subprocess.check_output(yt_dlp_cmd + ["-U"], stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf8")
    except (FileNotFoundError, PermissionError) as e:
        logging.warning(f"Could not run yt-dlp for upgrade: {e}")
        return get_youtubedl_version()

    # Check if already up to date
    if "is up to date" in output.lower():
        logging.debug("yt-dlp is already up to date")
        return get_youtubedl_version()

    upgrade_success = False
    if "pip" in output.lower():
        if not upgrade_success:
            pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]

            # Outside a venv, pip requires --break-system-packages on modern Python
            if sys.prefix == sys.base_prefix:
                pip_cmd.append("--break-system-packages")

            try:
                logging.info(f"yt-dlp is outdated! Attempting upgrade via {pip_cmd}...")
                subprocess.check_output(pip_cmd, stderr=subprocess.STDOUT)
                upgrade_success = True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.error(f"Failed to upgrade yt-dlp using pip: {e}")

    youtubedl_version = get_youtubedl_version()
    if upgrade_success:
        logging.info("Done. Installed version: %s" % youtubedl_version)
    else:
        logging.error("Failed to upgrade yt-dlp.")
    return youtubedl_version


def build_ytdl_download_command(
    video_url: str,
    download_path: str,
    high_quality: bool = False,
    youtubedl_proxy: str | None = None,
    additional_args: str | None = None,
) -> list[str]:
    """Build the yt-dlp command line for downloading a video.

    Args:
        video_url: URL of the video to download.
        download_path: Directory path where videos will be saved.
        high_quality: If True, download up to 1080p; otherwise download mp4.
        youtubedl_proxy: Optional proxy server URL.
        additional_args: Optional additional command-line arguments as a string.

    Returns:
        List of command-line arguments for subprocess execution.
    """
    dl_path = os.path.join(download_path, "%(title)s---%(id)s.%(ext)s")
    file_quality = (
        "bestvideo[ext!=webm][height<=1080]+bestaudio[ext!=webm]/best[ext!=webm]"
        if high_quality
        else "mp4"
    )
    args = [
        "-f",
        file_quality,
        "-o",
        dl_path,
        "-S",
        "vcodec:h264",
        "--compat-options",
        "filename-sanitization",
    ]
    cmd = yt_dlp_cmd + args
    preferred_js_runtime = get_installed_js_runtime()
    if preferred_js_runtime and preferred_js_runtime != "deno":
        # Deno is automatically assumed by yt-dlp, and does not need specification here
        cmd += ["--js-runtimes", preferred_js_runtime]
    if youtubedl_proxy:
        cmd += ["--proxy", youtubedl_proxy]
    if additional_args:
        cmd += shlex.split(additional_args)
    cmd += [video_url]
    return cmd

def search_bilibili_via_api(query, max_results=5):
    """
       使用 Bilibili 公开搜索 API 获取视频列表
       """
    if not query.strip():
        return []

    # Bilibili 搜索 API（公开，无需登录）
    search_api = "https://api.bilibili.com/x/web-interface/search/type"

    params = {
        "search_type": "video",
        "keyword": query,
        "page": 1,
        "order": "pubdate",  # 按最新发布排序
        "duration": 0,  # 全部时长
        "tids": 0  # 全部分区
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Referer": "https://search.bilibili.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "application/json",
        "Origin": "https://search.bilibili.com"
    }

    try:
        response = requests.get(
            search_api,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            print(f"[Bilibili API] Error: {data.get('message', 'Unknown')}")
            return []

        results = []
        for item in data.get("data", {}).get("result", [])[:max_results]:
            # 构造标准 Bilibili 视频 URL
            if item.get("arcurl"):
                results.append({
                    "id": item.get("bvid"),
                    "title": item.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", ""),  # 移除高亮标签
                    "url": item["arcurl"],
                    "thumbnail": item.get("pic", ""),
                    "duration": self._format_duration(item.get("duration", 0)),
                    "uploader": item.get("author", "Unknown")
                })
        return results

    except Exception as e:
        print(f"[Bilibili Search API Error] {e}")
        return []

def get_search_results(textToSearch: str) -> list[list[str]]:
    """Search YouTube for videos matching the query.

    Args:
        textToSearch: Search query string.

    Returns:
        List of [title, url, video_id] for each result.

    Raises:
        Exception: If the search fails.
    """
    logging.info("Searching BiliBili for: " + textToSearch)

    print('-'*40)
    print(search_bilibili_via_api(textToSearch))
    print('-'*40)

    num_results = 10
    yt_search = 'bilisearch%d:"%s"' % (num_results, textToSearch)

    headers = [
        "--add-header",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "--add-header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "--add-header", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "--add-header", "Accept-Encoding: gzip, deflate",
        "--add-header", "Connection: keep-alive",
        "--add-header", "Upgrade-Insecure-Requests: 1",
    ]

    cmd = yt_dlp_cmd + ["-j", "--no-playlist", "--flat-playlist"] + headers + [yt_search]
    logging.debug("BiliBili search command: " + " ".join(cmd))
    try:
        output = subprocess.check_output(cmd).decode("utf-8", "ignore")
        logging.debug("Search results: " + output)
        rc = []
        for each in output.split("\n"):
            if len(each) > 2:
                j = json.loads(each)
                if (not "title" in j) or (not "url" in j):
                    continue
                # 缩略图
                thumbnail = j['pic'] or f"https://i0.hdslb.com/bfs/archive/{j['id']}_1.jpg"
                rc.append([j["title"], j["url"], j["id"], thumbnail, j['duration']])
        return rc
    except Exception as e:
        logging.debug("Error while executing search: " + str(e))
        raise e
