from hitl_pythonic import TerminalHitlHandler, with_hitl
from tool_registry import ToolRegistry
from tools import WriteFileTool


base = ToolRegistry()
base.register(WriteFileTool())

gate = with_hitl(base, TerminalHitlHandler(enabled=True))
result = gate.execute("write_file", {"path": "/tmp/hello.txt", "content": "hello,world"})

print(result)
