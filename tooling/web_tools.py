from typing import Dict

from .base import Tool
import requests

class WebSearchTool(Tool):
    @property
    def name(self):
        return "Web Search"

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

    def execute(self, arguments):
        query = arguments["query"]

        try:
            from ddgs import DDGS

            results = DDGS().text(query, max_results=5)
        except ImportError:
            return "搜索失败: 未安装 ddgs 依赖"
        except Exception as e:
            return f"搜索失败: {e}"

        if not results:
            return f"🔍 {query}\n\n未找到结果"

        lines = [f"🔍 搜索: {query}\n"]
        for i, item in enumerate(results, start=1):
            lines.append(f"{i}. {item.get('title', '')}")
            lines.append(f"   {item.get('body', '')}")
            lines.append(f"   🔗 {item.get('href', '')}\n")

        return "\n".join(lines)

class WebFetchTool(Tool):
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
                headers={"User-Agent": "Mozilla/5.0 (paicli)"},
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