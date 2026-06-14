import tempfile
import unittest
from pathlib import Path

from tooling import EditTool, FindTool, GrepTool, LsTool, ReadTool, WriteTool


class WriteToolTests(unittest.TestCase):
    def test_create_reports_created_with_line_and_byte_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"

            out = WriteTool().execute({"path": str(p), "content": "hello\nworld\n"})

        self.assertIn("已创建", out)
        self.assertIn("2 行", out)

    def test_overwrite_reports_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("old", encoding="utf-8")

            out = WriteTool().execute({"path": str(p), "content": "new"})

        self.assertIn("已覆盖", out)

    def test_write_to_directory_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = WriteTool().execute({"path": tmp, "content": "x"})

        self.assertIn("目标是目录", out)

    def test_write_creates_missing_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "deep" / "a.txt"

            out = WriteTool().execute({"path": str(p), "content": "x"})

            self.assertIn("已创建", out)
            self.assertTrue(p.exists())


class EditToolTests(unittest.TestCase):
    def test_edit_reports_first_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("l1\nl2\ntarget\nl4\n", encoding="utf-8")

            out = EditTool().execute({"path": str(p), "old_text": "target", "new_text": "x"})

        self.assertIn("编辑成功", out)
        self.assertIn("第 3 行", out)

    def test_edit_same_old_and_new_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("abc", encoding="utf-8")

            out = EditTool().execute({"path": str(p), "old_text": "abc", "new_text": "abc"})

        self.assertIn("相同", out)

    def test_edit_missing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nope.txt"

            out = EditTool().execute({"path": str(p), "old_text": "a", "new_text": "b"})

        self.assertIn("文件不存在", out)


class LsToolTests(unittest.TestCase):
    def test_dirs_first_with_slash_files_with_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "f.txt").write_text("12345", encoding="utf-8")

            out = LsTool().execute({"path": str(root)})

        lines = out.splitlines()
        self.assertEqual(lines[0], "sub/")
        self.assertIn("f.txt", lines[1])
        self.assertIn("5 B", lines[1])

    def test_missing_path(self):
        out = LsTool().execute({"path": "no_such_dir_xyz"})

        self.assertIn("路径不存在", out)

    def test_file_path_shows_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.txt"
            p.write_text("abc", encoding="utf-8")

            out = LsTool().execute({"path": str(p)})

        self.assertIn("f.txt", out)
        self.assertIn("3 B", out)


class ReadToolCacheTests(unittest.TestCase):
    def setUp(self):
        from tooling.file_cache import get_read_state_cache

        get_read_state_cache().clear()

    def test_repeated_read_of_same_shown_range_returns_cache_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("\n".join(f"line {i}" for i in range(1, 7)), encoding="utf-8")
            tool = ReadTool()

            first = tool.execute({"path": str(p), "offset": 1, "limit": 3})
            second = tool.execute({"path": str(p), "offset": 1, "limit": 3})

        self.assertIn("line 1", first)
        self.assertIn("[CACHED]", second)
        self.assertIn("lines 1-3 already shown", second)

    def test_unseen_range_is_read_even_when_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("\n".join(f"line {i}" for i in range(1, 9)), encoding="utf-8")
            tool = ReadTool()

            first = tool.execute({"path": str(p), "offset": 1, "limit": 3})
            second = tool.execute({"path": str(p), "offset": 4, "limit": 3})

        self.assertIn("line 1", first)
        self.assertNotIn("[CACHED]", second)
        self.assertIn("line 4", second)
        self.assertIn("line 6", second)

    def test_cache_is_scoped(self):
        from tooling.file_cache import get_read_state_cache

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("one\ntwo\nthree\n", encoding="utf-8")
            cache = get_read_state_cache()

            first = cache.lookup(p, scope_id="session-a", offset=1, limit=2)
            content = p.read_text(encoding="utf-8")
            cache.store(p, content=content, total_lines=3, shown_range=(1, 2), scope_id="session-a")
            second = cache.lookup(p, scope_id="session-a", offset=1, limit=2)
            other_scope = cache.lookup(p, scope_id="session-b", offset=1, limit=2)

        self.assertTrue(first.should_read)
        self.assertFalse(second.should_read)
        self.assertTrue(other_scope.should_read)

    def test_modified_file_invalidates_cache_and_reads_new_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("old\nsame\n", encoding="utf-8")
            tool = ReadTool()

            first = tool.execute({"path": str(p), "offset": 1, "limit": 2})
            p.write_text("new\nsame\n", encoding="utf-8")
            second = tool.execute({"path": str(p), "offset": 1, "limit": 2})

        self.assertIn("old", first)
        self.assertNotIn("[CACHED]", second)
        self.assertIn("new", second)


class GrepToolTests(unittest.TestCase):
    def test_include_filter_and_match_count_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("needle here\n", encoding="utf-8")
            (root / "b.md").write_text("needle there\n", encoding="utf-8")

            out = GrepTool().execute({"path": str(root), "pattern": "needle", "include": "*.py"})

        self.assertIn("找到 1 处", out)
        self.assertIn("a.py", out)
        self.assertNotIn("b.md", out)

    def test_ignore_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("HELLO\n", encoding="utf-8")

            out = GrepTool().execute({"path": str(root), "pattern": "hello", "ignore_case": True})

        self.assertIn("a.txt", out)

    def test_skips_git_dir_and_binary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("needle in git\n", encoding="utf-8")
            (root / "bin.dat").write_bytes(b"needle\x00binary\n")
            (root / "ok.txt").write_text("needle ok\n", encoding="utf-8")

            out = GrepTool().execute({"path": str(root), "pattern": "needle"})

        self.assertIn("ok.txt", out)
        self.assertNotIn(".git", out)
        self.assertNotIn("bin.dat", out)

    def test_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("xxx\n", encoding="utf-8")

            out = GrepTool().execute({"path": tmp, "pattern": "zzz"})

        self.assertIn("未找到匹配项", out)

    def test_invalid_regex(self):
        out = GrepTool().execute({"path": ".", "pattern": "("})

        self.assertIn("正则表达式无效", out)


class FindToolTests(unittest.TestCase):
    def test_type_filter_dir_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg.py").write_text("x", encoding="utf-8")

            out = FindTool().execute({"path": str(root), "name": "pkg*", "type": "dir"})

        self.assertIn("pkg/", out)
        self.assertNotIn("pkg.py", out)

    def test_skips_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "x.py").write_text("x", encoding="utf-8")
            (root / "real.py").write_text("x", encoding="utf-8")

            out = FindTool().execute({"path": str(root), "name": "*.py"})

        self.assertIn("real.py", out)
        self.assertNotIn(".git", out)

    def test_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = FindTool().execute({"path": tmp, "name": "*.nonexist"})

        self.assertIn("未找到文件", out)

    def test_missing_path(self):
        out = FindTool().execute({"path": "no_such_dir_xyz", "name": "*.py"})

        self.assertIn("路径不存在", out)


if __name__ == "__main__":
    unittest.main()
