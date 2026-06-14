from typing import Dict
import ipaddress
from urllib.parse import urlparse
from .base import Tool
import requests
import logging
log = logging.getLogger(__name__)
class WebSearchTool(Tool):
    category = "web"
    effect = "read"
    concurrency_safe = True
    result_kind = "search_hits"
    guidance = "ShadowCLI web_search 工具，用于搜索互联网并返回标题、摘要和链接；需要读取具体网页正文时再用 web_fetch。"

    @property
    def name(self):
        return "web_search"

    @property
    def description(self):
        return "搜索互联网，返回相应网页的标题，摘要，链接"

    @property
    def parameters(self):
        return {
            "type":"object",
            "properties":{
                "query":{"type":"string","description":"搜索关键词"}
            },
            "required":["query"]
        }
    def is_safe_url(self,url:str)->bool:
        """检查URL是否正确"""
        try:
            #先解析url
            parsed=urlparse(url)
            #只允许http和https访问
            if parsed.scheme not in("http","https"):
                return False
            #闹到主机名
            hostname=parsed.hostname
            if not hostname:
                return False
            try:
                #解析ip
                ip=ipaddress.ip_address(hostname)
                #禁止私有ip,本地回环,链路本地地址
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            except ValueError:
                #如果是本地域名，同样禁止
                if hostname.lower() in ("localhost","127.0.0.1","0.0.0.0"):
                    return False
                if hostname.endswith(".local") or hostname.endswith(".internal"):
                    return False
            return True
        except Exception:
            return False
    def execute(self, arguments):
        query = arguments["query"]

        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=5)
            safe_results=[]
            for result in results:
                url=result.get("href","")
                if self.is_safe_url(url):
                    safe_results.append(result)
                else:
                    log.warning(f"[WebSearch] 过滤不安全的 URL: {url}")
        except ImportError:
            return "搜索失败: 未安装 ddgs 依赖"
        except Exception as e:
            return f"搜索失败: {e}"

        if not safe_results:
            return f"🔍 {query}\n\n未找到结果"

        lines = [f"🔍 搜索: {query}\n"]
        for i, item in enumerate(safe_results, start=1):
            lines.append(f"{i}. {item.get('title', '')}")
            lines.append(f"   {item.get('body', '')}")
            lines.append(f"   🔗 {item.get('href', '')}\n")

        return "\n".join(lines)

class WebFetchTool(Tool):
    category = "web"
    effect = "read"
    concurrency_safe = True
    result_kind = "web_text"
    guidance = "ShadowCLI web_fetch 工具，用于抓取指定 URL 的网页正文；适合读官方文档、博客和技术文章。"

    @property
    def name(self) -> str:

        return "web_fetch"

    @property
    def description(self):

        return "抓取指定 URL 的网页正文，返回纯文本。适合读官方文档、博客、技术文章。"
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整 URL（http 或 https）"},
                "max_chars": {"type": "integer", "description": "返回最大字符数，默认 8000"}
            },
            "required": ["url"]
        }


    def execute(self, arguments: Dict):
        url = arguments["url"]
        max_chars = arguments.get("max_chars", 8000)

        # 抓取
        try:
            resp = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (shadowcli)"},
            )
            resp.raise_for_status()
        except Exception as e:
            return f"抓取失败: {e}"

        # HTML → 纯文本
        text = self._strip_html(resp.text)

        # 截断
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...(已截断)"

        return f"🌐 {url}\n\n{text}"
    @staticmethod
    def _strip_html(html: str) -> str:
        import re
        from html import unescape

        # 去 script/style 整块
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # 去所有标签
        text = re.sub(r"<[^>]+>", " ", html)
        # 解码 HTML 实体（&amp; → &）
        text = unescape(text)
        # 压缩多余空白
        text = re.sub(r"\s+", " ", text)
        return text.strip()
