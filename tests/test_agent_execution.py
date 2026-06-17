import contextlib
import inspect
import io
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cli_app as cli
from agent.agent_loop import AgentLoop
from agent.prompts import react_agent_prompt
from agent.react_agent import ReactAgent
from app_runtime import AppRuntime, build_skill_roots
from llm import ChatResponse, FunctionCall, Message, ToolCall
from llm.client import StreamEvent
from memory import MemoryProposal, TextLongTermMemory, build_long_term_memory
from sessions import (
    BranchSummaryEntry,
    CompactionEntry,
    CompactionResult,
    RuntimeContextBuilder,
    SessionStore,
)
from skills import (
    SkillDefinition,
    SkillRegistry,
    SkillRoot,
    SkillSelection,
    SkillSelector,
    auto_skill_candidates,
)
from plugin_runtime import PluginContributions, PluginManager, PluginStateStore
from tooling import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    Tool,
    ToolRegistry,
    WebFetchTool,
    WebSearchTool,
    WriteTool,
)
from tooling.runtime import ToolExecutionBlocked, ToolRuntime
from tooling.defaults import build_default_tool_runtime
from ui import BranchNavigationChoice, ask_branch_navigation_choice


class CaptureRegistry:
    def __init__(self):
        self.tools = {}
        self.executed = []

    def get(self, name):
        return self.tools[name]

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return self.tools[name].execute(arguments)

    def get_all_definitions(self):
        return []


class _SchemaTool(Tool):
    def __init__(self, name: str, parameters: dict):
        self._name = name
        self._parameters = parameters

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict:
        return self._parameters

    def execute(self, arguments: dict) -> str:
        return "ok"


class ModuleLayoutTests(unittest.TestCase):
    def test_legacy_root_modules_are_removed(self):
        root = Path(__file__).resolve().parents[1]

        for filename in [
            "cli.py",
            "tools.py",
            "tool_registry.py",
            "config.py",
            "model.py",
            "llm_client.py",
        ]:
            self.assertFalse((root / filename).exists(), filename)

    def test_agent_package_does_not_depend_on_multi_agent(self):
        root = Path(__file__).resolve().parents[1]

        for path in (root / "agent").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("multi_agent", source, path.name)

    def test_memory_pythonic_python_modules_are_removed(self):
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(list((root / "memory_pythonic").glob("*.py")), [])

    def test_memory_is_split_out_of_sessions_package(self):
        root = Path(__file__).resolve().parents[1]

        self.assertTrue((root / "memory" / "__init__.py").exists())
        self.assertFalse((root / "memory" / "suggestions.py").exists())
        sessions_init = (root / "sessions" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("TextLongTermMemory", sessions_init)
        self.assertFalse((root / "sessions" / "long_term.py").exists())
        self.assertFalse((root / "sessions" / "memory_suggestions.py").exists())

    def test_source_and_docs_use_shadowcli_name(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = [
            "Pai" + "CLI",
            "PAI" + "CLI",
            "pai" + "cli",
            "pai" + "_cli",
        ]
        checked_suffixes = {".md", ".py"}
        ignored_dirs = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            "agent_memory",
            "logs",
        }

        offenders = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in checked_suffixes:
                continue
            if any(part in ignored_dirs for part in path.relative_to(root).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(term in text for term in forbidden):
                offenders.append(str(path.relative_to(root)))

        self.assertEqual(offenders, [])


class SkillRegistryTests(unittest.TestCase):
    def test_registry_without_roots_does_not_discover_skill_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes.",
                    "---",
                    "",
                    "Review code.",
                ]),
                encoding="utf-8",
            )

            skills = SkillRegistry(root).list()

        self.assertEqual(skills, [])

    def test_scan_discovers_skill_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes for bugs and risky behavior.",
                    "when_to_use: Use when the user asks for a code review.",
                    "disable-model-invocation: true",
                    "argument-hint: [scope]",
                    "---",
                    "",
                    "Review the current diff and report concrete risks.",
                ]),
                encoding="utf-8",
            )

            registry = SkillRegistry(
                root,
                roots=[SkillRoot(source="project", path=root / ".agents" / "skills")],
            )

            skills = registry.list()

        self.assertEqual(len(skills), 1)
        skill = skills[0]
        self.assertEqual(skill.name, "code-review")
        self.assertEqual(skill.directory_name, "code-review")
        self.assertEqual(skill.source, "project")
        self.assertEqual(skill.description, "Review code changes for bugs and risky behavior.")
        self.assertEqual(skill.when_to_use, "Use when the user asks for a code review.")
        self.assertTrue(skill.disable_model_invocation)
        self.assertEqual(skill.argument_hint, "[scope]")
        self.assertEqual(skill.path.name, "SKILL.md")

    def test_scan_skips_bad_skill_file_and_records_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / ".agents" / "skills" / "good"
            bad = root / ".agents" / "skills" / "bad"
            good.mkdir(parents=True)
            bad.mkdir(parents=True)
            (good / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: good",
                    "description: Valid skill.",
                    "---",
                    "",
                    "Run safely.",
                ]),
                encoding="utf-8",
            )
            (bad / "SKILL.md").write_bytes(b"\xff\xfe\xff")

            registry = SkillRegistry(root, roots=[SkillRoot(source="project", path=root / ".agents" / "skills")])
            skills = registry.list()

        self.assertEqual([skill.name for skill in skills], ["good"])
        self.assertTrue(any("failed to read skill" in diagnostic.message for diagnostic in registry.diagnostics()))

    def test_scan_supports_bom_and_yaml_folded_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: >-",
                    "  Use when: starting creative work",
                    "  or changing product behavior.",
                    "---",
                    "",
                    "Ask questions first.",
                ]),
                encoding="utf-8-sig",
            )

            skills = SkillRegistry(
                root,
                roots=[SkillRoot(source="project", path=root / ".agents" / "skills")],
            ).list()

        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].description, "Use when: starting creative work or changing product behavior.")

    def test_load_returns_skill_body_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "explain-code"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: explain-code",
                    "description: Explain code in plain language.",
                    "---",
                    "",
                    "Explain `$ARGUMENTS` using a process-first mental model.",
                ]),
                encoding="utf-8",
            )

            loaded = SkillRegistry(
                root,
                roots=[SkillRoot(source="project", path=root / ".agents" / "skills")],
            ).load("explain-code")

        self.assertEqual(loaded.definition.name, "explain-code")
        self.assertIn("name: explain-code", loaded.raw_content)
        self.assertEqual(
            loaded.body.strip(),
            "Explain `$ARGUMENTS` using a process-first mental model.",
        )

    def test_find_accepts_directory_name_as_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes.",
                    "---",
                    "",
                    "Review the current changes.",
                ]),
                encoding="utf-8",
            )

            registry = SkillRegistry(
                root,
                roots=[SkillRoot(source="project", path=root / ".agents" / "skills")],
            )

            self.assertEqual(registry.find("code-review").path, skill_dir / "SKILL.md")
            self.assertEqual(registry.find("review").path, skill_dir / "SKILL.md")
            self.assertIsNone(registry.find("missing"))

    def test_find_scans_skill_list_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = SkillDefinition(
                name="code-review",
                description="Review code.",
                path=root / "SKILL.md",
                directory_name="review",
            )
            registry = SkillRegistry(root, roots=[])
            calls = 0

            def fake_list():
                nonlocal calls
                calls += 1
                return [definition]

            registry.list = fake_list

            self.assertEqual(registry.find("review"), definition)
            self.assertEqual(calls, 1)

    def test_runtime_skill_roots_ignore_plugin_skill_dirs_without_manifest_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_skill = root / ".agents" / "skills" / "code-review"
            plugin_skill = root / "plugins" / "superpowers" / "skills" / "brainstorming"
            project_skill.mkdir(parents=True)
            plugin_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes.",
                    "---",
                    "",
                    "Review code.",
                ]),
                encoding="utf-8",
            )
            (plugin_skill / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: Explore requirements before implementation.",
                    "---",
                    "",
                    "Ask one question at a time.",
                ]),
                encoding="utf-8",
            )

            skills = SkillRegistry(root, roots=build_skill_roots(root)).list()

        self.assertTrue(any(skill.path == project_skill / "SKILL.md" for skill in skills))
        self.assertFalse(any(skill.path == plugin_skill / "SKILL.md" for skill in skills))

    def test_scan_discovers_lowercase_skill_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "lowercase"
            skill_dir.mkdir(parents=True)
            (skill_dir / "skill.md").write_text(
                "\n".join([
                    "---",
                    "name: lowercase",
                    "description: Lowercase entrypoint.",
                    "---",
                    "",
                    "Load this skill.",
                ]),
                encoding="utf-8",
            )

            skills = SkillRegistry(
                root,
                roots=[SkillRoot(source="project", path=root / ".agents" / "skills")],
            ).list()

        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "lowercase")
        self.assertEqual(skills[0].path.name, "skill.md")

    def test_explicit_empty_roots_disable_all_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes.",
                    "---",
                    "",
                    "Review code.",
                ]),
                encoding="utf-8",
            )

            skills = SkillRegistry(root, roots=[]).list()

        self.assertEqual(skills, [])

    def test_find_prefers_project_skill_when_names_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_skill = root / ".agents" / "skills" / "review"
            plugin_skill = root / "plugins" / "superpowers" / "skills" / "review"
            project_skill.mkdir(parents=True)
            plugin_skill.mkdir(parents=True)
            _write_codex_plugin_manifest(root / "plugins" / "superpowers", name="superpowers", skills="./skills")
            PluginStateStore(root).enable("superpowers")
            for skill_dir, description in [
                (project_skill, "Project review."),
                (plugin_skill, "Plugin review."),
            ]:
                (skill_dir / "SKILL.md").write_text(
                    "\n".join([
                        "---",
                        "name: review",
                        f"description: {description}",
                        "---",
                        "",
                        description,
                    ]),
                    encoding="utf-8",
                )

            skill = SkillRegistry(
                root,
                roots=build_skill_roots(root, plugin_roots=PluginManager(root).contributions().skill_roots),
            ).find("review")

        self.assertEqual(skill.source, "project")
        self.assertEqual(skill.description, "Project review.")

    def test_find_accepts_plugin_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_skill = root / ".agents" / "skills" / "review"
            plugin_skill = root / "plugins" / "superpowers" / "skills" / "review"
            project_skill.mkdir(parents=True)
            plugin_skill.mkdir(parents=True)
            for skill_dir, description in [
                (project_skill, "Project review."),
                (plugin_skill, "Plugin review."),
            ]:
                (skill_dir / "SKILL.md").write_text(
                    "\n".join([
                        "---",
                        "name: review",
                        f"description: {description}",
                        "---",
                        "",
                        "Review.",
                    ]),
                    encoding="utf-8",
                )

            registry = SkillRegistry(
                root,
                roots=[
                    SkillRoot(source="project", path=root / ".agents" / "skills"),
                    SkillRoot(source="plugin:superpowers", path=root / "plugins" / "superpowers" / "skills"),
                ],
            )

            self.assertEqual(registry.find("review").description, "Project review.")
            self.assertEqual(registry.find("superpowers:review").description, "Plugin review.")

    def test_registry_accepts_external_skill_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            external_root = Path(tmp) / "superpowers" / "skills"
            skill_dir = external_root / "test-driven-development"
            root.mkdir()
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: test-driven-development",
                    "description: Write a failing test before implementation.",
                    "---",
                    "",
                    "Use red-green-refactor.",
                ]),
                encoding="utf-8",
            )

            skills = SkillRegistry(
                root,
                roots=[SkillRoot(source="superpowers", path=external_root)],
            ).list()

        self.assertEqual(skills[0].name, "test-driven-development")
        self.assertEqual(skills[0].source, "superpowers")

    def test_registry_accepts_labeled_skill_roots_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            external_root = Path(tmp) / "superpowers" / "skills"
            skill_dir = external_root / "brainstorming"
            root.mkdir()
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: Explore requirements before implementation.",
                    "---",
                    "",
                    "Ask one question at a time.",
                ]),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SHADOWCLI_SKILL_ROOTS": f"superpowers={external_root}"}):
                skills = SkillRegistry(root, roots=build_skill_roots(root)).list()

        matches = [skill for skill in skills if skill.name == "brainstorming"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].source, "superpowers")


class PluginManagerTests(unittest.TestCase):
    def test_manifest_declared_skill_root_is_listed_by_skills_command(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            plugin_root = cwd / "plugins" / "superpowers"
            skill_dir = plugin_root / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            PluginStateStore(cwd).enable("superpowers")
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: Explore requirements before implementation.",
                    "---",
                    "",
                    "Ask one question at a time.",
                ]),
                encoding="utf-8",
            )
            manager = PluginManager(cwd)

            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=_FailingSessionStore(),
                long_term_memory=_StubLongTermMemory(),
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: self.fail("/skills 不应创建 agent"),
                run_agent_once=lambda *args, **kwargs: self.fail("/skills 不应运行 agent"),
            )
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/skills")

        self.assertTrue(keep_running)
        self.assertEqual(manager.diagnostics(), [])
        self.assertTrue(any("brainstorming" in message for message in renderer.messages))
        self.assertTrue(any("plugin:superpowers" in message for message in renderer.messages))

    def test_codex_plugin_manifest_declares_string_skill_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "cache" / "openai-curated" / "superpowers" / "2abb1c44"
            skill_dir = plugin_root / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills/")
            PluginStateStore(root).enable("superpowers")

            manager = PluginManager(root, extra_plugin_roots=[plugin_root])

            self.assertEqual(manager.diagnostics(), [])
            self.assertEqual(manager.contributions().skill_roots, [
                SkillRoot(source="plugin:superpowers", path=(plugin_root / "skills").resolve()),
            ])

    def test_plugin_skills_are_disabled_until_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "superpowers"
            (plugin_root / "skills").mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")

            disabled = PluginManager(root)

            self.assertEqual(disabled.contributions().skill_roots, [])
            self.assertFalse(disabled.list_plugins()[0].enabled)

            PluginStateStore(root).enable("superpowers")
            enabled = PluginManager(root)

            self.assertTrue(enabled.list_plugins()[0].enabled)
            self.assertEqual(enabled.contributions().skill_roots, [
                SkillRoot(source="plugin:superpowers", path=(plugin_root / "skills").resolve()),
            ])

    def test_codex_plugin_manifest_accepts_string_skill_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "cache" / "github" / "2abb1c44"
            first = plugin_root / "skills"
            second = plugin_root / "more-skills"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="github", skills=["./skills", "./more-skills"])
            PluginStateStore(root).enable("github")

            roots = PluginManager(root, extra_plugin_roots=[plugin_root]).contributions().skill_roots

        self.assertEqual(
            roots,
            [
                SkillRoot(source="plugin:github", path=first.resolve()),
                SkillRoot(source="plugin:github", path=second.resolve()),
            ],
        )

    def test_external_plugin_roots_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "codex-cache" / "superpowers" / "2abb1c44"
            skill_dir = plugin_root / "skills" / "brainstorming"
            root.mkdir()
            skill_dir.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills/")
            PluginStateStore(root).enable("superpowers")

            with patch.dict(os.environ, {"SHADOWCLI_PLUGIN_ROOTS": str(plugin_root)}):
                roots = PluginManager(root).contributions().skill_roots

        self.assertEqual(roots, [SkillRoot(source="plugin:superpowers", path=(plugin_root / "skills").resolve())])

    def test_plugin_dir_without_manifest_contributes_no_skill_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_skill = root / "plugins" / "random" / "skills" / "foo"
            plugin_skill.mkdir(parents=True)
            (plugin_skill / "SKILL.md").write_text("Do things.", encoding="utf-8")

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertEqual(manager.diagnostics(), [])

    def test_root_plugin_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "superpowers"
            skill_root = plugin_root / "skills"
            skill_root.mkdir(parents=True)
            (plugin_root / "plugin.json").write_text(
                json.dumps({
                    "id": "superpowers",
                    "name": "superpowers",
                    "version": "1.0.0",
                    "skills": [{"path": "skills"}],
                }),
                encoding="utf-8",
            )

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertEqual(manager.diagnostics(), [])

    def test_skill_path_must_be_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "broken"
            _write_codex_plugin_manifest(plugin_root, name="broken", skills=[{"path": 123}])

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertTrue(any("skills[0].path" in diagnostic.message for diagnostic in manager.diagnostics()))

    def test_skill_path_must_start_with_dot_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "bad-path"
            (plugin_root / "skills").mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="bad-path", skills="skills")

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertTrue(any("must start with './'" in diagnostic.message for diagnostic in manager.diagnostics()))

    def test_skill_path_cannot_escape_plugin_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "escape"
            _write_codex_plugin_manifest(plugin_root, name="escape", skills=[{"path": "./../outside"}])

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertTrue(any("outside plugin root" in diagnostic.message for diagnostic in manager.diagnostics()))

    def test_skill_path_must_point_to_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "file-skill"
            plugin_root.mkdir(parents=True)
            (plugin_root / "README.md").write_text("not a skill directory", encoding="utf-8")
            _write_codex_plugin_manifest(plugin_root, name="file-skill", skills=[{"path": "./README.md"}])

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertTrue(any("must point to a directory" in diagnostic.message for diagnostic in manager.diagnostics()))

    def test_manifest_requires_name_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "minimal"
            manifest_dir = plugin_root / ".codex-plugin"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "plugin.json").write_text(
                json.dumps({
                    "skills": [{"path": "skills"}],
                }),
                encoding="utf-8",
            )

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            messages = [diagnostic.message for diagnostic in manager.diagnostics()]
            self.assertTrue(any("name must be a non-empty string" in message for message in messages))
            self.assertTrue(any("version must be a non-empty string" in message for message in messages))

    def test_plugin_name_must_be_kebab_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "super-powers"
            (plugin_root / "skills").mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="Super Powers", skills="./skills")

            manager = PluginManager(root)

            self.assertEqual(manager.contributions().skill_roots, [])
            self.assertTrue(any("name must be kebab-case" in diagnostic.message for diagnostic in manager.diagnostics()))

    def test_codex_plugin_name_can_differ_from_cache_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "2abb1c44"
            skill_root = plugin_root / "skills"
            skill_root.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            PluginStateStore(root).enable("superpowers")

            manager = PluginManager(root)

            self.assertEqual(manager.diagnostics(), [])
            self.assertEqual(manager.contributions().skill_roots, [
                SkillRoot(source="plugin:superpowers", path=skill_root.resolve()),
            ])

    def test_plugin_manager_exposes_enabled_contributions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "superpowers"
            skill_root = plugin_root / "skills"
            skill_root.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            PluginStateStore(root).enable("superpowers")

            contributions = PluginManager(root).contributions()

        self.assertIsInstance(contributions, PluginContributions)
        self.assertEqual(contributions.skill_roots, [
            SkillRoot(source="plugin:superpowers", path=skill_root.resolve()),
        ])


class AppRuntimeTests(unittest.TestCase):
    def test_app_runtime_collects_core_runtime_resources(self):
        from app_runtime import AppRuntime, AppStateStore, EventBus, HookManager, SessionRuntime, SkillManager

        tool_runtime = ToolRuntime(ToolRegistry())
        session_store = _StubSessionStore()
        long_term = _StubLongTermMemory()
        event_bus = EventBus()

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=tool_runtime,
                session_store=session_store,
                long_term_memory=long_term,
                event_bus=event_bus,
            )

        self.assertIs(app.tool_runtime, tool_runtime)
        self.assertIs(app.session_store, session_store)
        self.assertIs(app.long_term_memory, long_term)
        self.assertIs(app.event_bus, event_bus)
        self.assertIsInstance(app.state_store, AppStateStore)
        self.assertIsInstance(app.hook_manager, HookManager)
        self.assertIs(app.hook_manager.event_bus, event_bus)
        self.assertEqual(len(app.tool_runtime.before_execute_hooks), 2)
        self.assertIsInstance(app.session_runtime, SessionRuntime)
        self.assertIs(app.session_runtime.long_term_memory, long_term)
        self.assertIsInstance(app.skill_manager, SkillManager)
        self.assertIs(app.skill_manager.state_store, app.state_store)
        self.assertIsInstance(app.plugin_manager, PluginManager)
        self.assertFalse(hasattr(app.skill_manager, "plugin_manager"))
        self.assertIsInstance(app.skill_manager.registry, SkillRegistry)

    def test_app_runtime_loads_mcp_tools_into_tool_runtime(self):
        class FakeMcpManager:
            def __init__(self):
                self.started = []
                self.shutdown_called = False

            def start_server_sync(self, name, config):
                self.started.append((name, config))
                return [{
                    "name": "search",
                    "description": "Search through fake MCP.",
                    "inputSchema": {"type": "object", "properties": {}},
                }]

            def call_tool_sync(self, *_args, **_kwargs):
                return "ok"

            def shutdown(self):
                self.shutdown_called = True

        config = type("Config", (), {"disabled": False})()
        manager = FakeMcpManager()
        runtime = ToolRuntime(ToolRegistry())

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=runtime,
                long_term_memory=_StubLongTermMemory(),
                mcp_manager=manager,
            )
            loaded, failed = app.load_mcp_tools({"filesystem": config})
            app.shutdown()

        self.assertEqual((loaded, failed), (1, 0))
        self.assertEqual(manager.started, [("filesystem", config)])
        self.assertTrue(manager.shutdown_called)
        self.assertIn(
            "mcp__filesystem__search",
            [definition["function"]["name"] for definition in runtime.get_all_definitions()],
        )

    def test_event_bus_publishes_subscribed_handlers_in_order(self):
        from app_runtime import EventBus

        events = []
        bus = EventBus()
        bus.subscribe("skills.refreshed", lambda event: events.append(("first", event.payload["count"])))
        bus.subscribe("skills.refreshed", lambda event: events.append(("second", event.payload["count"])))

        event = bus.publish("skills.refreshed", count=2)

        self.assertEqual(event.type, "skills.refreshed")
        self.assertEqual(events, [("first", 2), ("second", 2)])


class ReactAgentTests(unittest.TestCase):
    def test_runs_single_react_turn_with_streaming_chat(self):
        calls = []
        agent = ReactAgent(CaptureRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "你好，我是 ReAct 助手")):
            result = agent.run("你好")

        self.assertEqual(result, "你好，我是 ReAct 助手")
        self.assertEqual(calls[0][0][-1].content, "你好")
        self.assertIsNone(calls[0][1])

    def test_react_always_receives_tools_when_registry_has_definitions(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "你好")):
            agent.run("你好")

        self.assertIsNotNone(calls[0][1])
        self.assertEqual(calls[0][1][0]["function"]["name"], "read")

    def test_react_file_task_receives_tools(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "可以读取")):
            agent.run("读取 cli_app/runner.py 文件")

        self.assertIsNotNone(calls[0][1])
        self.assertEqual(calls[0][1][0]["function"]["name"], "read")

    def test_react_file_task_hides_duplicate_mcp_tools_by_default(self):
        calls = []
        agent = ReactAgent(_MixedToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "可以统计")):
            agent.run("统计这个项目的 Python 代码量")

        names = [tool["function"]["name"] for tool in calls[0][1]]
        self.assertIn("bash", names)
        self.assertNotIn("mcp__filesystem__search_files", names)

    def test_react_mcp_task_can_receive_mcp_tools(self):
        calls = []
        agent = ReactAgent(_MixedToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "可以用 MCP")):
            agent.run("用 MCP filesystem 列出项目文件")

        names = [tool["function"]["name"] for tool in calls[0][1]]
        self.assertIn("bash", names)
        self.assertIn("mcp__filesystem__search_files", names)

    def test_react_agent_prompt_injects_working_directory(self):
        prompt = react_agent_prompt("- read: 读取文件", cwd="E:/demo/project")

        self.assertIn("E:/demo/project", prompt)
        self.assertIn("cwd", prompt)

    def test_react_agent_prompt_is_sectioned(self):
        prompt = react_agent_prompt("- read: 读取文件", cwd="E:/demo/project")

        self.assertIn("## 身份", prompt)
        self.assertIn("## 工作方式", prompt)
        self.assertIn("## 代码修改原则", prompt)
        self.assertIn("## 验证标准", prompt)
        self.assertIn("## 沟通方式", prompt)
        self.assertIn("## 上下文纪律", prompt)
        self.assertIn("## 本地环境", prompt)
        self.assertIn("## 工具使用", prompt)
        self.assertIn("## 文件修改", prompt)
        self.assertIn("## 工具结果", prompt)
        self.assertIn("## 可用工具", prompt)
        self.assertIn("工具结果可能", prompt)
        self.assertIn("- read: 读取文件", prompt)

    def test_react_agent_prompt_includes_core_work_protocol(self):
        prompt = react_agent_prompt("- read: 读取文件", cwd="E:/demo/project")

        self.assertIn("能直接完成就直接完成", prompt)
        self.assertIn("先读现有代码", prompt)
        self.assertIn("不要覆盖用户已有改动", prompt)
        self.assertIn("声称完成前必须有验证依据", prompt)
        self.assertIn("测试失败", prompt)
        self.assertIn("工具结果、历史摘要、长期记忆可能不完整", prompt)

    def test_react_agent_prompt_includes_tool_guidance_when_present(self):
        prompt = react_agent_prompt(
            "- read: 读取文件",
            cwd="E:/demo/project",
            tool_guidance="- read: 先定位范围，再读取必要片段。",
        )

        self.assertIn("## 工具说明", prompt)
        self.assertIn("- read: 先定位范围，再读取必要片段。", prompt)

    def test_react_system_prompt_carries_current_working_directory(self):
        agent = ReactAgent(_ToolDefinitionRegistry())

        system_message = agent.conversation_messages[0]
        self.assertEqual(system_message.role, "system")
        self.assertIn(os.getcwd(), system_message.content)

    def test_react_system_prompt_collects_guidance_from_visible_tools(self):
        agent = ReactAgent(_GuidanceRegistry())

        system_message = agent.conversation_messages[0]
        self.assertIn("## 工具说明", system_message.content)
        self.assertIn("- read: 使用 read 读取项目文件。", system_message.content)
        self.assertNotIn("隐藏的 MCP 工具说明", system_message.content)

    def test_react_keeps_tool_call_and_result_messages_between_turns(self):
        calls = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("文件内容：hello")
        agent = ReactAgent(registry)

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-read",
                        "type": "function",
                        "name": "read",
                        "arguments": '{"path": "demo.txt"}',
                    },
                )
                yield StreamEvent("done", None)
                return
            if len(calls) == 2:
                yield StreamEvent("content", "读完了")
                yield StreamEvent("done", None)
                return
            yield StreamEvent("content", "上一轮读到 hello")
            yield StreamEvent("done", None)

        with patch("agent.agent_loop.chat_stream", fake_stream):
            agent.run("读取 demo.txt")
            agent.run("刚才读到了什么？")

        second_turn_messages = calls[-1][0]
        self.assertTrue(any(
            message.role == "assistant"
            and message.tool_calls
            and message.tool_calls[0].id == "call-read"
            for message in second_turn_messages
        ))
        self.assertTrue(any(
            message.role == "tool"
            and message.tool_call_id == "call-read"
            and "文件内容：hello" in (message.content or "")
            for message in second_turn_messages
        ))
        self.assertEqual(second_turn_messages[-1].role, "user")
        self.assertEqual(second_turn_messages[-1].content, "刚才读到了什么？")

    def test_react_agent_no_longer_accepts_legacy_memory_manager(self):
        self.assertNotIn("memory_manager", inspect.signature(ReactAgent).parameters)

    def test_react_agent_uses_conversation_message_names(self):
        params = inspect.signature(ReactAgent).parameters

        self.assertIn("conversation_messages", params)
        self.assertIn("on_message_appended", params)
        self.assertNotIn("session_messages", params)
        self.assertNotIn("message_sink", params)

    def test_react_turn_persists_exact_user_text_sent_to_model(self):
        calls = []
        agent = ReactAgent(CaptureRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "按你的偏好来")):
            agent.run("入口和 React 怎么安排？", context="## 相关长期记忆\n- 用户偏好：普通输入走 React")

        prompt = calls[0][0][-1].content
        self.assertIn("## 相关长期记忆", prompt)
        self.assertIn("用户偏好：普通输入走 React", prompt)
        self.assertIn("以下上下文只适用于本条消息末尾的“当前任务”", prompt)
        self.assertIn("当前任务：入口和 React 怎么安排？", prompt)
        self.assertTrue(any(
            message.role == "user"
            and message.content
            and "## 相关长期记忆" in message.content
            for message in agent.conversation_messages
        ))
        self.assertFalse(any(
            message.role == "user"
            and message.content == "入口和 React 怎么安排？"
            for message in agent.conversation_messages
        ))

    def test_react_agent_preserves_injected_conversation_messages(self):
        calls = []
        conversation_messages = [Message(role="user", content="上一轮的问题")]
        agent = ReactAgent(CaptureRegistry(), conversation_messages=conversation_messages)

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "继续回答")):
            agent.run("继续")

        self.assertIs(agent.conversation_messages, conversation_messages)
        self.assertEqual(calls[0][0][1].content, "上一轮的问题")
        self.assertEqual(calls[0][0][-1].content, "继续")

    def test_on_message_appended_receives_runtime_messages_immediately(self):
        persisted = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("文件内容")
        agent = ReactAgent(registry, on_message_appended=persisted.append)

        def fake_stream(messages, tools=None, cancel=None):
            if not persisted or persisted[-1].role == "user":
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-read",
                        "type": "function",
                        "name": "read",
                        "arguments": '{"path": "demo.txt"}',
                    },
                )
                yield StreamEvent("done", None)
                return
            yield StreamEvent("content", "完成")
            yield StreamEvent("done", None)

        with patch("agent.agent_loop.chat_stream", fake_stream):
            agent.run("读取 demo.txt")

        self.assertEqual([message.role for message in persisted], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(persisted[2].tool_call_id, "call-read")


class RuntimeContextBuilderTests(unittest.TestCase):
    def test_builds_context_from_branch_summary_and_long_term_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = SessionStore(root=Path(tmp) / "sessions").create(cwd)
            session.append_message(Message(role="user", content="root"))
            fork_point = session.append_message(Message(role="assistant", content="fork"))
            session.append_message(Message(role="user", content="短期对话不应该重复注入"))
            session.branch_to_with_summary(fork_point.id, summary="用户正在重构 session 和 memory。")
            long_term = TextLongTermMemory(session.path.parent.parent / "memory")
            long_term.remember("用户偏好：普通输入走 React")

            context = RuntimeContextBuilder(session=session, long_term=long_term).build("React 入口")

        self.assertIn("## 分支摘要", context)
        self.assertIn("用户正在重构 session 和 memory。", context)
        self.assertIn("## 相关长期记忆", context)
        self.assertIn("用户偏好：普通输入走 React", context)
        self.assertNotIn("短期对话不应该重复注入", context)


class ToolRegistryTests(unittest.TestCase):
    def test_definitions_are_exported_in_cache_stable_order(self):
        first = ToolRegistry().register(
            _SchemaTool("zeta", {"type": "object", "required": ["b", "a"]})
        ).register(
            _SchemaTool("alpha", {"required": ["y", "x"], "type": "object"})
        )
        second = ToolRegistry().register(
            _SchemaTool("alpha", {"type": "object", "required": ["x", "y"]})
        ).register(
            _SchemaTool("zeta", {"required": ["a", "b"], "type": "object"})
        )

        self.assertEqual(first.get_all_definitions(), second.get_all_definitions())
        self.assertEqual(
            [item["function"]["name"] for item in first.get_all_definitions()],
            ["alpha", "zeta"],
        )
        self.assertEqual(
            first.get_all_definitions()[0]["function"]["parameters"]["required"],
            ["x", "y"],
        )


class AgentLoopTests(unittest.TestCase):
    def test_exec_one_uses_registry_execute_as_single_tool_entrypoint(self):
        registry = _ExecuteOnlyRegistry()
        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(
                name="write",
                arguments='{"path": "demo.txt", "content": "ok"}',
            ),
        )

        result = agent._exec_one(tool_call)

        self.assertEqual(result, "executed:write")
        self.assertEqual(
            registry.calls,
            [("write", {"path": "demo.txt", "content": "ok"})],
        )

    def test_hard_rejected_tool_call_stops_current_agent(self):
        calls = []

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) > 1:
                raise AssertionError("硬拒绝后不应继续调用模型")
            yield StreamEvent(
                "tool_call",
                {
                    "id": "call-write",
                    "type": "function",
                    "name": "write",
                    "arguments": '{"path": "demo.txt", "content": "ok"}',
                },
            )
            yield StreamEvent("done", {"reason": "finished"})

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=_HardRejectRuntime(),
        )

        with patch("agent.agent_loop.chat_stream", fake_stream):
            with self.assertLogs("agent.agent_loop", level="WARNING"):
                events = list(agent.execute(Message(role="user", content="写文件")))

        done = [event for event in events if event.type == "done"][-1]
        tool_result = [event for event in events if event.type == "tool_result"][-1]
        self.assertEqual(done.data["reason"], "blocked")
        self.assertIn("用户拒绝", tool_result.data["result"])
        self.assertEqual(len(calls), 1)

    def test_blocked_tool_call_is_logged_as_warning(self):
        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=_HardRejectRuntime(),
        )
        tool_call = ToolCall(
            id="call-write",
            function=FunctionCall(
                name="write",
                arguments='{"path": "demo.txt", "content": "ok"}',
            ),
        )

        with self.assertLogs("agent.agent_loop", level="WARNING") as logs:
            with self.assertRaises(ToolExecutionBlocked):
                agent._exec_one(tool_call)

        output = "\n".join(logs.output)
        self.assertIn("被拒绝", output)
        self.assertIn("WARNING", output)

    def test_stream_usage_is_recorded_and_token_budget_stops_before_tool_execution(self):
        calls = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("不应执行")

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            yield StreamEvent(
                "tool_call",
                {
                    "id": "call-read",
                    "type": "function",
                    "name": "read",
                    "arguments": '{"path": "demo.txt"}',
                },
            )
            yield StreamEvent("done", {
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 3,
                    "prompt_tokens_details": {"cached_tokens": 2},
                }
            })

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        with patch.dict(os.environ, {"SHADOWCLI_REACT_TOKEN_BUDGET": "10"}, clear=False):
            with patch("agent.agent_loop.chat_stream", fake_stream):
                events = list(agent.execute(Message(role="user", content="读取文件")))

        done = [event for event in events if event.type == "done"][-1]
        content = "".join(event.data for event in events if event.type == "content")
        self.assertEqual(done.data["reason"], "token_budget_exceeded")
        self.assertIn("Token 预算已用尽", content)
        self.assertEqual(registry.executed, [])
        self.assertEqual(len(calls), 1)
        assistant = next(message for message in agent.conversation_history if message.role == "assistant")
        self.assertEqual(assistant.metadata["usage"]["input_tokens"], 9)
        self.assertEqual(assistant.metadata["usage"]["cached_input_tokens"], 2)
        self.assertEqual(assistant.metadata["usage"]["output_tokens"], 3)

    def test_repeated_tool_calls_are_detected_across_model_iterations(self):
        calls = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("same")

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            yield StreamEvent(
                "tool_call",
                {
                    "id": f"call-read-{len(calls)}",
                    "type": "function",
                    "name": "read",
                    "arguments": '{"path": "same.txt"}',
                },
            )
            yield StreamEvent("done", None)

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        with patch.dict(os.environ, {"SHADOWCLI_REACT_STAGNATION_WINDOW": "2"}, clear=False):
            with patch("agent.agent_loop.chat_stream", fake_stream):
                events = list(agent.execute(Message(role="user", content="重复读取")))

        done = [event for event in events if event.type == "done"][-1]
        self.assertEqual(done.data["reason"], "stagnation_detected")
        self.assertEqual(registry.executed, [("read", {"path": "same.txt"})])

    def test_tool_result_containing_rejection_phrase_does_not_stop_loop(self):
        calls = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool('源码片段：if "工具调用被拒绝" in result: ...')

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-read",
                        "type": "function",
                        "name": "read",
                        "arguments": '{"path": "agent_loop.py"}',
                    },
                )
                yield StreamEvent("done", None)
            else:
                yield StreamEvent("content", "读到了源码")
                yield StreamEvent("done", None)

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        with patch("agent.agent_loop.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="读取 agent_loop.py")))

        done = [event for event in events if event.type == "done"][-1]
        self.assertEqual(done.data["reason"], "finished")
        self.assertEqual(registry.executed, [("read", {"path": "agent_loop.py"})])
        self.assertEqual(len(calls), 2)
        tool_result = [event for event in events if event.type == "tool_result"][-1]
        self.assertIn("工具调用被拒绝", tool_result.data["result"])

    def test_read_only_tool_calls_run_in_parallel_until_write_boundary(self):
        calls = []
        registry = _TimedRegistry(delay=0.2)

        first_batch = [
            ("read", "r1"),
            ("grep", "g1"),
            ("edit", "e1"),
            ("find", "f2"),
            ("read", "r2"),
            ("edit", "e2"),
        ]

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                for name, label in first_batch:
                    yield StreamEvent(
                        "tool_call",
                        {
                            "id": f"call-{label}",
                            "type": "function",
                            "name": name,
                            "arguments": f'{{"label": "{label}"}}',
                        },
                    )
                yield StreamEvent("done", None)
            else:
                yield StreamEvent("content", "完成")
                yield StreamEvent("done", None)

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        start = time.perf_counter()
        with patch("agent.agent_loop.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="批量处理工具")))
        elapsed = time.perf_counter() - start

        tool_results = [event.data["result"] for event in events if event.type == "tool_result"]
        self.assertEqual(tool_results, ["read:r1", "grep:g1", "edit:e1", "find:f2", "read:r2", "edit:e2"])
        self.assertLess(elapsed, 1.0)

        timeline = registry.timeline_by_label()
        self.assertLess(timeline["r1"]["start"], timeline["g1"]["end"])
        self.assertLess(timeline["g1"]["start"], timeline["r1"]["end"])
        self.assertGreater(timeline["e1"]["start"], timeline["r1"]["end"])
        self.assertGreater(timeline["e1"]["start"], timeline["g1"]["end"])
        self.assertGreater(timeline["f2"]["start"], timeline["e1"]["end"])
        self.assertGreater(timeline["r2"]["start"], timeline["e1"]["end"])
        self.assertLess(timeline["f2"]["start"], timeline["r2"]["end"])
        self.assertLess(timeline["r2"]["start"], timeline["f2"]["end"])
        self.assertGreater(timeline["e2"]["start"], timeline["f2"]["end"])
        self.assertGreater(timeline["e2"]["start"], timeline["r2"]["end"])

    def test_metadata_read_tool_runs_parallel_without_agent_name_entry(self):
        calls = []
        registry = _TimedRegistry(
            delay=0.2,
            tool_metadata={
                "local_scan": _MetadataTool(effect="read", concurrency_safe=True),
                "local_symbols": _MetadataTool(effect="read", concurrency_safe=True),
            },
        )

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                for name, label in [("local_scan", "scan"), ("local_symbols", "symbols")]:
                    yield StreamEvent(
                        "tool_call",
                        {
                            "id": f"call-{label}",
                            "type": "function",
                            "name": name,
                            "arguments": f'{{"label": "{label}"}}',
                        },
                    )
                yield StreamEvent("done", None)
            else:
                yield StreamEvent("content", "完成")
                yield StreamEvent("done", None)

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        start = time.perf_counter()
        with patch("agent.agent_loop.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="并行本地扫描")))
        elapsed = time.perf_counter() - start

        tool_results = [event.data["result"] for event in events if event.type == "tool_result"]
        self.assertEqual(tool_results, ["local_scan:scan", "local_symbols:symbols"])
        self.assertLess(elapsed, 0.35)

        timeline = registry.timeline_by_label()
        self.assertLess(timeline["scan"]["start"], timeline["symbols"]["end"])
        self.assertLess(timeline["symbols"]["start"], timeline["scan"]["end"])

    def test_tools_without_parallel_read_metadata_run_serially(self):
        calls = []
        registry = _TimedRegistry(
            delay=0.15,
            tool_metadata={
                "maybe_read": _MetadataTool(),
                "maybe_read_again": _MetadataTool(),
            },
        )

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                for name, label in [("maybe_read", "first"), ("maybe_read_again", "second")]:
                    yield StreamEvent(
                        "tool_call",
                        {
                            "id": f"call-{label}",
                            "type": "function",
                            "name": name,
                            "arguments": f'{{"label": "{label}"}}',
                        },
                    )
                yield StreamEvent("done", None)
            else:
                yield StreamEvent("content", "完成")
                yield StreamEvent("done", None)

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )

        with patch("agent.agent_loop.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="串行未知工具")))

        tool_results = [event.data["result"] for event in events if event.type == "tool_result"]
        self.assertEqual(tool_results, ["maybe_read:first", "maybe_read_again:second"])

        timeline = registry.timeline_by_label()
        self.assertGreater(timeline["second"]["start"], timeline["first"]["end"])


class CliAgentTests(unittest.TestCase):
    def test_tree_and_jump_commands_are_parsed(self):
        self.assertTrue(cli.parse_skills_command("/skills"))
        self.assertFalse(cli.parse_skills_command("/skills now"))
        self.assertTrue(cli.parse_plugins_command("/plugins"))
        self.assertFalse(cli.parse_plugins_command("/plugins now"))
        self.assertEqual(cli.parse_plugin_command("/plugin"), ("", ""))
        self.assertEqual(cli.parse_plugin_command("/plugin enable superpowers"), ("enable", "superpowers"))
        self.assertEqual(cli.parse_plugin_command("/plugin disable superpowers"), ("disable", "superpowers"))
        self.assertEqual(cli.parse_plugin_command("/plugin enable"), ("enable", ""))
        self.assertIsNone(cli.parse_plugin_command("/pluginx enable superpowers"))
        self.assertEqual(cli.parse_skill_command("/skill"), ("", ""))
        self.assertEqual(cli.parse_skill_command("/skill code-review"), ("code-review", ""))
        self.assertEqual(cli.parse_skill_command("/skill code-review 检查当前改动"), ("code-review", "检查当前改动"))
        self.assertIsNone(cli.parse_skill_command("/skillcode-review 检查当前改动"))
        self.assertTrue(cli.parse_tokens_command("/tokens"))
        self.assertFalse(cli.parse_tokens_command("/tokens now"))
        self.assertTrue(cli.parse_tree_command("/tree"))
        self.assertFalse(cli.parse_tree_command("/tree now"))
        self.assertEqual(cli.parse_jump_command("/jump"), "")
        self.assertEqual(cli.parse_jump_command("/jump abc123"), "abc123")
        self.assertIsNone(cli.parse_jump_command("/jumpabc123"))
        self.assertEqual(cli.parse_compact_command("/compact"), "")
        self.assertIsNone(cli.parse_compact_command("/compact now"))

    def test_resume_menu_does_not_use_session_id_as_title(self):
        import cli_app.router as router
        from sessions import SessionMeta

        meta = SessionMeta(
            version=1,
            session_id="20260530_225232_5eac86",
            title=None,
            created_at="2026-05-30T14:56:44",
            updated_at="2026-05-30T14:56:44",
            message_count=38,
        )

        option = router._resume_select_options([meta])[0]

        self.assertEqual(option.label, "未命名对话")
        self.assertNotIn(meta.session_id, option.label)

    def test_prompt_falls_back_to_plain_input_when_prompt_toolkit_unavailable(self):
        import cli_app.terminal_input as terminal_input

        with (
            patch("cli_app.terminal_input._can_use_prompt_toolkit", return_value=True),
            patch("cli_app.terminal_input._build_prompt_toolkit_paste_prompt", side_effect=ImportError),
            patch("builtins.input", return_value="/help") as input_mock,
        ):
            prompt = terminal_input.build_prompt()
            line = prompt()

        self.assertEqual(line, "/help")
        input_mock.assert_called_once_with("\n> ")

    def test_prompt_uses_paste_prompt_when_prompt_toolkit_available(self):
        import cli_app.terminal_input as terminal_input

        prompt_func = lambda: "ok"
        with (
            patch("cli_app.terminal_input._can_use_prompt_toolkit", return_value=True),
            patch("cli_app.terminal_input._build_prompt_toolkit_paste_prompt", return_value=prompt_func),
        ):
            prompt = terminal_input.build_prompt()

        self.assertIs(prompt, prompt_func)

    def test_paste_placeholder_summarizes_multiline_text(self):
        import cli_app.terminal_input as terminal_input

        text = "a\r\nb\rc\n"
        normalized = terminal_input._normalize_paste_text(text)
        placeholder = terminal_input._paste_placeholder(1, normalized)
        expanded = terminal_input._expand_paste_placeholders(
            f"请看 {placeholder}",
            {placeholder: normalized},
        )

        self.assertEqual(normalized, "a\nb\nc\n")
        self.assertEqual(placeholder, "[Pasted text #1 +3 lines]")
        self.assertEqual(expanded, "请看 a\nb\nc\n")

    def test_format_session_tree_marks_current_branch_and_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            tree = cli.format_session_tree(session)

        self.assertIn("会话树", tree)
        self.assertIn(target_id, tree)
        self.assertIn(old_leaf_id, tree)
        self.assertIn("assistant", tree)
        self.assertIn("旧分支问题", tree)
        self.assertIn("<- current", tree)

    def test_format_token_usage_summarizes_current_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = SessionStore(root=Path(tmp) / "sessions").create(Path(tmp) / "project")
            session.append_message(Message(role="user", content="hi"))
            session.append_message(Message(
                role="assistant",
                content="hello",
                metadata={"usage": {"input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 50}},
            ))

            status = cli.format_token_usage(session)

        self.assertIn("输入（命中缓存）: 900", status)
        self.assertIn("输入（未命中缓存）: 100", status)
        self.assertIn("输出            : 50", status)
        self.assertIn("总量            : 1,050", status)
        self.assertIn("90.0%", status)

    def test_repl_builds_agent_with_tool_runtime_and_message_callback_on_first_message(self):
        runtime = ToolRuntime(ToolRegistry())
        seen = []
        renderer = _CaptureRenderer()

        def remember_registry(registry, *, conversation_messages=None, on_message_appended=None):
            seen.append((registry, conversation_messages, callable(on_message_appended)))
            return _StubReactAgent()

        def remember_runtime_agent(*, conversation_messages=None, on_message_appended=None):
            return remember_registry(
                runtime,
                conversation_messages=conversation_messages,
                on_message_appended=on_message_appended,
            )

        import cli_app.runner as runner
        with (
            patch("cli_app.runner.load_dotenv"),
            patch("app_runtime.runtime._configure_logging_once"),
            patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
            patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
            patch("cli_app.runner.SessionStore", return_value=_StubSessionStore()),
            patch("cli_app.runner.load_mcp_config", return_value={}),
            patch("app_runtime.runtime.AppRuntime.build_agent", side_effect=remember_runtime_agent),
            patch("builtins.input", side_effect=["你好", EOFError]),
        ):
            runner.repl(renderer=renderer)

        self.assertEqual(seen, [(runtime, [], True)])

    def test_repl_skills_command_lists_available_skills_without_starting_session(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            skill_dir = cwd / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes for bugs.",
                    "---",
                    "",
                    "Review the current diff.",
                ]),
                encoding="utf-8",
            )
            session_store = _FailingSessionStore()

            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=session_store,
                long_term_memory=_StubLongTermMemory(),
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: self.fail("/skills 不应创建 agent"),
                run_agent_once=lambda *args, **kwargs: self.fail("/skills 不应运行 agent"),
            )
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/skills")

        self.assertTrue(keep_running)
        self.assertTrue(any("code-review" in message for message in renderer.messages))
        self.assertTrue(any("Review code changes for bugs." in message for message in renderer.messages))
        self.assertTrue(any("project" in message for message in renderer.messages))

    def test_repl_plugin_enable_refreshes_skills(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            plugin_root = cwd / "plugins" / "superpowers"
            skill_dir = plugin_root / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: Brainstorm ideas.",
                    "---",
                    "",
                    "Brainstorm.",
                ]),
                encoding="utf-8",
            )

            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=_FailingSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: self.fail("/plugin 不应创建 agent"),
                run_agent_once=lambda *args, **kwargs: self.fail("/plugin 不应运行 agent"),
            )
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/plugins")
            repl_router.route("/skills")
            repl_router.route("/plugin enable superpowers")
            repl_router.route("/skills")

        self.assertTrue(keep_running)
        joined = "\n".join(renderer.messages)
        self.assertIn("superpowers", joined)
        self.assertIn("disabled", joined)
        self.assertIn("已启用插件: superpowers", joined)
        self.assertIn("superpowers:brainstorming", joined)

    def test_repl_skill_command_loads_skill_context_and_runs_task(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            skill_dir = cwd / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes for bugs.",
                    "argument-hint: [scope]",
                    "---",
                    "",
                    "Review `$ARGUMENTS` and report concrete risks.",
                ]),
                encoding="utf-8",
            )

            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/skill code-review 检查当前改动")

        self.assertTrue(keep_running)
        self.assertEqual(agent.inputs[0][0], "检查当前改动")
        context = agent.inputs[0][1]
        self.assertIn("## 当前 Skill", context)
        self.assertIn("code-review", context)
        self.assertIn("Review `检查当前改动` and report concrete risks.", context)
        self.assertNotIn("$ARGUMENTS", context)

    def test_repl_skill_command_allows_empty_task(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            skill_dir = cwd / ".agents" / "skills" / "code-review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: code-review",
                    "description: Review code changes.",
                    "---",
                    "",
                    "Review current state. $ARGUMENTS",
                ]),
                encoding="utf-8",
            )

            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/skill code-review")

        self.assertTrue(keep_running)
        self.assertEqual(agent.inputs[0][0], "按 skill 指令执行")
        context = agent.inputs[0][1]
        self.assertIn("Review current state.", context)
        self.assertNotIn("$ARGUMENTS", context)
        self.assertNotIn("- arguments:", context)

    def test_repl_skill_command_reports_missing_skill_without_running_agent(self):
        import cli_app.router as router

        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
            )

            keep_running = repl_router.route("/skill missing 做点事")

        self.assertTrue(keep_running)
        self.assertEqual(agent.inputs, [])
        self.assertTrue(any("未找到 skill: missing" in message for message in renderer.messages))

    def test_skill_selector_selects_plugin_skill_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            plugin_root = cwd / "plugins" / "superpowers"
            skill_dir = plugin_root / "skills" / "brainstorming"
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            PluginStateStore(cwd).enable("superpowers")
            _write_skill_file(
                skill_dir,
                name="brainstorming",
                description="Explore requirements before implementation.",
                when_to_use="Use before implementing a new feature.",
                body="SECRET BODY SHOULD NOT BE SENT TO SELECTOR.",
                argument_hint="[feature idea]",
            )
            manager = PluginManager(cwd)
            prompts = []

            def fake_chat(messages, tools=None):
                prompts.extend(message.content or "" for message in messages)
                return ChatResponse(content='{"skill": "superpowers:brainstorming", "reason": "需要先澄清新功能"}')

            selection = SkillSelector(
                SkillRegistry(cwd, roots=build_skill_roots(cwd, plugin_roots=manager.contributions().skill_roots)),
                chat_fn=fake_chat,
            ).select("我要加一个新功能")

        prompt = "\n".join(prompts)
        self.assertIsNotNone(selection.skill)
        self.assertEqual(selection.skill.source, "plugin:superpowers")
        self.assertEqual(selection.reason, "需要先澄清新功能")
        self.assertIn("superpowers:brainstorming", prompt)
        self.assertIn("Explore requirements before implementation.", prompt)
        self.assertIn("Use before implementing a new feature.", prompt)
        self.assertIn("[feature idea]", prompt)
        self.assertNotIn("SECRET BODY SHOULD NOT BE SENT TO SELECTOR.", prompt)

    def test_auto_skill_candidates_include_global_and_external_skills(self):
        root = Path("E:/demo")
        skills = [
            SkillDefinition(
                name="frontend-design",
                description="Frontend design.",
                path=root / "global" / "SKILL.md",
                directory_name="frontend-design",
                source="global",
            ),
            SkillDefinition(
                name="docs",
                description="Docs.",
                path=root / "external" / "SKILL.md",
                directory_name="docs",
                source="external:1",
            ),
            SkillDefinition(
                name="internal",
                description="Internal.",
                path=root / "internal" / "SKILL.md",
                directory_name="internal",
                source="internal",
            ),
        ]

        candidates = auto_skill_candidates(skills)

        self.assertEqual([skill.name for skill in candidates], ["docs", "frontend-design"])

    def test_auto_skill_candidates_prefer_project_over_global_duplicate(self):
        root = Path("E:/demo")
        global_skill = SkillDefinition(
            name="frontend-design",
            description="Global frontend design.",
            path=root / "global" / "SKILL.md",
            directory_name="frontend-design",
            source="global",
        )
        project_skill = SkillDefinition(
            name="frontend-design",
            description="Project frontend design.",
            path=root / "project" / "SKILL.md",
            directory_name="frontend-design",
            source="project",
        )

        candidates = auto_skill_candidates([global_skill, project_skill])

        self.assertEqual(candidates, [project_skill])

    def test_repl_auto_skill_loads_context_and_prints_reason(self):
        import cli_app.router as router

        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            _write_skill_file(
                cwd / ".agents" / "skills" / "code-review",
                name="code-review",
                description="Review code changes for bugs.",
                body="Review `$ARGUMENTS` and report concrete risks.",
            )
            app = AppRuntime.create(
                cwd,
                tool_runtime=runtime,
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            skill = app.skill_manager.registry.find("code-review")
            self.assertIsNotNone(skill)
            selector = _FixedSkillSelector(SkillSelection(skill, "任务是在执行代码审查"))
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)

            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
                skill_selector=selector,
            )

            with patch.dict(os.environ, {"SHADOWCLI_AUTO_SKILLS": "1"}, clear=False):
                keep_running = repl_router.route("检查当前改动")

        self.assertTrue(keep_running)
        self.assertEqual(selector.inputs, ["检查当前改动"])
        self.assertEqual(agent.inputs[0][0], "检查当前改动")
        context = agent.inputs[0][1]
        self.assertIn("## 当前 Skill", context)
        self.assertIn("code-review", context)
        self.assertIn("Review `检查当前改动` and report concrete risks.", context)
        output = "\n".join(renderer.messages)
        self.assertIn("自动加载 skill: code-review", output)
        self.assertIn("原因: 任务是在执行代码审查", output)

    def test_repl_auto_skill_null_selection_runs_plain_input(self):
        import cli_app.router as router

        agent = _StubReactAgent()
        renderer = _CaptureRenderer()
        selector = _FixedSkillSelector(SkillSelection(None, "没有明确匹配"))

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
                skill_selector=selector,
            )

            with patch.dict(os.environ, {"SHADOWCLI_AUTO_SKILLS": "1"}, clear=False):
                keep_running = repl_router.route("随便聊聊")

        self.assertTrue(keep_running)
        self.assertEqual(selector.inputs, ["随便聊聊"])
        self.assertEqual(agent.inputs, [("随便聊聊", "")])
        self.assertFalse(any("自动加载 skill:" in message for message in renderer.messages))

    def test_repl_plan_command_skips_auto_skill_selector(self):
        import cli_app.router as router

        agent = _StubReactAgent()
        renderer = _CaptureRenderer()
        skill = SkillDefinition(
            name="planning-helper",
            description="Help plan work.",
            path=Path("SKILL.md"),
            directory_name="planning-helper",
        )
        selector = _FixedSkillSelector(SkillSelection(skill, "不应调用"))

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
                skill_selector=selector,
            )

            with patch.dict(os.environ, {"SHADOWCLI_AUTO_SKILLS": "1"}, clear=False):
                keep_running = repl_router.route("/plan 梳理 runtime 架构")

        self.assertTrue(keep_running)
        self.assertEqual(selector.inputs, [])
        self.assertEqual(len(agent.inputs), 1)
        self.assertIn("单 Agent 计划执行模式", agent.inputs[0][0])
        self.assertNotIn("## 当前 Skill", agent.inputs[0][1])

    def test_repl_auto_skill_selector_is_disabled_by_default(self):
        import cli_app.router as router

        agent = _StubReactAgent()
        renderer = _CaptureRenderer()
        selector = _FixedSkillSelector(SkillSelection(None, "不应调用"))

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            _override_runtime_methods(app, build_agent=lambda *args, **kwargs: agent, run_agent_once=cli.run_once)
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=renderer,
                skill_selector=selector,
            )

            with patch.dict(os.environ, {"SHADOWCLI_AUTO_SKILLS": ""}, clear=False):
                keep_running = repl_router.route("普通输入")

        self.assertTrue(keep_running)
        self.assertEqual(selector.inputs, [])
        self.assertEqual(agent.inputs, [("普通输入", "")])

    def test_repl_router_has_no_post_turn_memory_suggester(self):
        import cli_app.router as router

        router_params = inspect.signature(router.ReplRouter).parameters
        run_params = inspect.signature(router.ReplRouter._run_agent_line).parameters

        self.assertNotIn("memory_suggester", router_params)
        for parameter_name in ["build_agent", "run_agent_once", "list_tools", "chat_fn", "build_branch_summary"]:
            self.assertNotIn(parameter_name, router_params)
        self.assertNotIn("allow_memory_suggestions", run_params)
        self.assertFalse(hasattr(router.ReplRouter, "_maybe_suggest_memory"))
        self.assertFalse(hasattr(router, "_memory_suggestions_enabled"))

    def test_repl_registers_propose_memory_tool(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
                session_store=_StubSessionStore(),
                long_term_memory=TextLongTermMemory(Path(tmp) / "memory"),
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: _StubReactAgent(),
                run_agent_once=_returning_run_once("assistant reply"),
            )
            router.ReplRouter(
                app_runtime=app,
                renderer=_CaptureRenderer(),
                confirm_memory=lambda suggestion: True,
            )

        definitions = app.tool_runtime.get_all_definitions()
        names = [definition["function"]["name"] for definition in definitions]
        self.assertIn("propose_memory", names)
        propose_definition = next(
            definition for definition in definitions
            if definition["function"]["name"] == "propose_memory"
        )
        type_schema = propose_definition["function"]["parameters"]["properties"]["type"]
        self.assertEqual(type_schema["enum"], ["user", "project", "feedback", "reference"])

    def test_repl_builds_agent_with_propose_memory_guidance(self):
        import cli_app.router as router

        system_prompts = []

        def build_agent(registry, *, conversation_messages=None, on_message_appended=None):
            agent = ReactAgent(
                registry,
                conversation_messages=conversation_messages,
                on_message_appended=on_message_appended,
            )
            system_prompts.append(agent.conversation_messages[0].content)
            return agent

        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
                session_store=_StubSessionStore(),
                long_term_memory=TextLongTermMemory(Path(tmp) / "memory"),
            )
            _override_runtime_methods(
                app,
                build_agent=build_agent,
                run_agent_once=lambda *args, **kwargs: "assistant reply",
            )
            repl_router = router.ReplRouter(
                app_runtime=app,
                renderer=_CaptureRenderer(),
                confirm_memory=lambda suggestion: True,
            )
            keep_running = repl_router.route("普通输入")

        self.assertTrue(keep_running)
        self.assertEqual(len(system_prompts), 1)
        self.assertIn("- propose_memory:", system_prompts[0])
        self.assertIn("用户确认", system_prompts[0])
        self.assertIn("临时任务状态", system_prompts[0])
        self.assertIn("会话压缩摘要", system_prompts[0])

    def test_propose_memory_tool_confirms_and_saves_user_approved_memory(self):
        import cli_app.router as router

        confirmations = []
        with tempfile.TemporaryDirectory() as tmp:
            memory = TextLongTermMemory(Path(tmp) / "memory")
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
                session_store=_StubSessionStore(),
                long_term_memory=memory,
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: _StubReactAgent(),
                run_agent_once=_returning_run_once("assistant reply"),
            )
            router.ReplRouter(
                app_runtime=app,
                renderer=_CaptureRenderer(),
                confirm_memory=lambda item: confirmations.append(item) or True,
            )

            result = app.tool_runtime.execute("propose_memory", {
                "type": "feedback",
                "text": "不要自动从压缩摘要写长期记忆",
                "reason": "用户明确纠正长期记忆写入边界",
            })
            feedback = (Path(tmp) / "memory" / "feedback.md").read_text(encoding="utf-8")

        self.assertIn("已保存长期记忆 [feedback]", result)
        self.assertEqual(
            confirmations,
            [MemoryProposal("feedback", "不要自动从压缩摘要写长期记忆", "用户明确纠正长期记忆写入边界")],
        )
        self.assertIn("- 不要自动从压缩摘要写长期记忆", feedback)

    def test_propose_memory_tool_skips_when_user_declines(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            memory = TextLongTermMemory(Path(tmp) / "memory")
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
                session_store=_StubSessionStore(),
                long_term_memory=memory,
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: _StubReactAgent(),
                run_agent_once=_returning_run_once("assistant reply"),
            )
            router.ReplRouter(
                app_runtime=app,
                renderer=_CaptureRenderer(),
                confirm_memory=lambda suggestion: False,
            )

            result = app.tool_runtime.execute("propose_memory", {
                "type": "feedback",
                "text": "不要自动写长期记忆",
                "reason": "用户纠正了记忆边界",
            })

        self.assertIn("已跳过长期记忆", result)
        self.assertEqual(list(memory), [])

    def test_propose_memory_tool_skips_duplicates_without_confirmation(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            memory = TextLongTermMemory(Path(tmp) / "memory")
            memory.remember("不要自动写长期记忆", memory_type="feedback")
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
                session_store=_StubSessionStore(),
                long_term_memory=memory,
            )
            _override_runtime_methods(
                app,
                build_agent=lambda *args, **kwargs: _StubReactAgent(),
                run_agent_once=_returning_run_once("assistant reply"),
            )
            router.ReplRouter(
                app_runtime=app,
                renderer=_CaptureRenderer(),
                confirm_memory=lambda suggestion: self.fail("重复记忆不应询问用户"),
            )

            result = app.tool_runtime.execute("propose_memory", {
                "type": "feedback",
                "text": "不要自动写长期记忆",
                "reason": "重复候选",
            })

        self.assertIn("已存在长期记忆", result)
        self.assertEqual(list(memory), ["不要自动写长期记忆"])

    def test_auto_skill_selector_excludes_disabled_plugin_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            _write_skill_file(
                cwd / ".agents" / "skills" / "code-review",
                name="code-review",
                description="Review code changes.",
                body="Review current changes.",
            )
            plugin_root = cwd / "plugins" / "superpowers"
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            _write_skill_file(
                plugin_root / "skills" / "brainstorming",
                name="brainstorming",
                description="Explore requirements before implementation.",
                body="Brainstorm.",
            )
            prompts = []

            def fake_chat(messages, tools=None):
                prompts.extend(message.content or "" for message in messages)
                return ChatResponse(content='{"skill": null, "reason": "no clear match"}')

            app = AppRuntime.create(
                cwd,
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            selection = SkillSelector(
                app.skill_manager.registry,
                chat_fn=fake_chat,
            ).select("我要加一个新功能")

        prompt = "\n".join(prompts)
        self.assertIsNone(selection.skill)
        self.assertIn("code-review", prompt)
        self.assertNotIn("brainstorming", prompt)
        self.assertNotIn("superpowers:brainstorming", prompt)

    def test_app_runtime_skill_registry_loads_manifest_declared_plugin_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            plugin_root = cwd / "plugins" / "superpowers"
            skill_dir = plugin_root / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            _write_codex_plugin_manifest(plugin_root, name="superpowers", skills="./skills")
            PluginStateStore(cwd).enable("superpowers")
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: brainstorming",
                    "description: Explore requirements before implementation.",
                    "---",
                    "",
                    "Ask one question at a time.",
                ]),
                encoding="utf-8",
            )

            app = AppRuntime.create(
                cwd,
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=_StubSessionStore(),
                long_term_memory=[],
            )
            registry = app.skill_manager.registry
            skill = registry.find("brainstorming")

        self.assertIsNotNone(skill)
        self.assertEqual(skill.source, "plugin:superpowers")

    def test_repl_tree_command_prints_session_tree(self):
        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=_StubReactAgent()),
                patch("builtins.input", side_effect=["/tree", "", EOFError]),
            ):
                runner.repl(renderer=renderer)

        output = "\n".join(renderer.messages)
        self.assertIn(target_id, output)
        self.assertIn(old_leaf_id, output)
        self.assertIn("current", output)

    def test_repl_tokens_command_prints_current_session_usage(self):
        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer()
        agent = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = SessionStore(root=Path(tmp) / "sessions").create(cwd)
            session.append_message(Message(role="assistant", content="hi", metadata={
                "usage": {"input_tokens": 100, "cached_input_tokens": 75, "output_tokens": 10}
            }))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=agent),
                patch("builtins.input", side_effect=["/tokens", EOFError]),
            ):
                runner.repl(renderer=renderer)

        output = "\n".join(renderer.messages)
        self.assertIn("当前会话 token 用量", output)
        self.assertIn("输入（命中缓存）: 75", output)
        self.assertEqual(agent.inputs, [])

    def test_repl_jump_command_moves_leaf_and_reloads_agent_history(self):
        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer(branch_choice=BranchNavigationChoice.DIRECT)

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=agent),
                patch("builtins.input", side_effect=[f"/jump {target_id}", EOFError]),
            ):
                runner.repl(renderer=renderer)

        self.assertEqual(session.get_leaf_id(), target_id)
        self.assertIn(old_leaf_id, {entry.id for entry in session.all_entries()})
        self.assertEqual([message.content for message in agent.reloaded[-1]], ["root", "fork"])

    def test_repl_jump_summary_choice_uses_summary_generator(self):
        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer(branch_choice=BranchNavigationChoice.SUMMARIZE)

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, _old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=_StubReactAgent()),
                patch("app_runtime.runtime.generate_branch_summary", return_value="总结旧分支"),
                patch("builtins.input", side_effect=[f"/jump {target_id}", EOFError]),
            ):
                runner.repl(renderer=renderer)

        leaf = session.all_entries()[-1]
        self.assertIsInstance(leaf, BranchSummaryEntry)
        self.assertEqual(leaf.summary, "总结旧分支")

    def test_repl_jump_uses_injected_renderer_for_branch_choice_and_messages(self):
        runtime = ToolRuntime(ToolRegistry())
        renderer = _CaptureRenderer(branch_choice=BranchNavigationChoice.DIRECT)
        agent = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, _old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=agent),
                patch("builtins.input", side_effect=[f"/jump {target_id}", EOFError]),
            ):
                runner.repl(renderer=renderer)

        self.assertEqual(renderer.branch_plans[0].to_id, target_id)
        self.assertTrue(any(message.startswith("已跳转到:") for message in renderer.messages))
        self.assertEqual([message.content for message in agent.reloaded[-1]], ["root", "fork"])

    def test_repl_compact_command_appends_compaction_and_reloads_agent_history(self):
        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = SessionStore(root=Path(tmp) / "sessions").create(cwd)
            session.append_message(Message(role="user", content="旧问题"))
            session.append_message(Message(role="assistant", content="旧回答"))
            session.append_message(Message(role="user", content="新问题"))
            session.append_message(Message(role="assistant", content="新回答"))

            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=agent),
                patch("app_runtime.runtime.default_chat", return_value=ChatResponse(content="旧对话已压缩")),
                patch("builtins.input", side_effect=["/compact", EOFError]),
            ):
                runner.repl(renderer=renderer)

        leaf = session.all_entries()[-1]
        self.assertIsInstance(leaf, CompactionEntry)
        self.assertEqual([message.content for message in agent.reloaded[-1]], ["新问题", "新回答"])
        self.assertIn("已压缩", "\n".join(renderer.messages))

    def test_repl_auto_compacts_before_running_when_branch_exceeds_threshold(self):
        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()
        renderer = _CaptureRenderer()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = SessionStore(root=Path(tmp) / "sessions").create(cwd)
            session.append_message(Message(role="user", content="旧问题"))
            session.append_message(Message(role="assistant", content="旧回答"))
            session.append_message(Message(role="user", content="新问题"))
            session.append_message(Message(role="assistant", content="新回答"))

            import cli_app.runner as runner
            with (
                patch.dict(os.environ, {"SHADOWCLI_COMPACT_MAX_TOKENS": "1"}, clear=False),
                patch("cli_app.runner.load_dotenv"),
                patch("app_runtime.runtime._configure_logging_once"),
                patch("app_runtime.runtime.build_default_tool_runtime", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=TextLongTermMemory(Path(tmp) / "memory")),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("app_runtime.runtime.AppRuntime.build_agent", return_value=agent),
                patch("app_runtime.runtime.default_chat", return_value=ChatResponse(content="旧对话已压缩")),
                patch("builtins.input", side_effect=["继续", EOFError]),
            ):
                runner.repl(renderer=renderer)

        leaf = session.all_entries()[-1]
        self.assertIsInstance(leaf, CompactionEntry)
        self.assertEqual([message.content for message in agent.reloaded[-1]], ["新问题", "新回答"])
        self.assertEqual(agent.inputs[0][0], "继续")
        self.assertIn("旧对话已压缩", agent.inputs[0][1])

    def test_cli_default_agent_is_react_agent(self):
        agent = ReactAgent(CaptureRegistry())

        self.assertIsInstance(agent, ReactAgent)

    def test_cli_does_not_export_plan_agent_factory(self):
        self.assertFalse(hasattr(cli, "build_plan_agent"))

    def test_build_long_term_memory_uses_project_memory_file_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            default_path = Path(tmp) / "agent_memory" / "memory"
            with patch("memory.long_term.DEFAULT_LONG_TERM_PATH", default_path):
                memory = build_long_term_memory()

            self.assertEqual(memory.storage_path, default_path)
            self.assertEqual(memory.storage_path.name, "memory")

    def test_run_once_routes_plain_input_to_react_agent(self):
        react = _StubReactAgent()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(react, "你好")

        self.assertEqual(react.inputs, [("你好", "")])

    def test_run_once_routes_agent_events_to_injected_renderer(self):
        react = _StubReactAgent()
        renderer = _CaptureRenderer()

        cli.run_once(react, "你好", renderer=renderer)

        self.assertEqual(react.inputs, [("你好", "")])
        self.assertEqual([event.type for event in renderer.events], ["content", "done"])

    def test_run_once_routes_plan_command_to_react_agent(self):
        react = _StubReactAgent()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(react, "/plan 统计当前目录")

        self.assertEqual(len(react.inputs), 1)
        self.assertIn("单 Agent 计划执行模式", react.inputs[0][0])
        self.assertIn("统计当前目录", react.inputs[0][0])

    def test_run_once_passes_context_to_agent_events(self):
        react = _StubReactAgent()
        cancel = threading.Event()
        journal = object()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(
                react,
                "你好",
                runtime_context_builder=_StaticRuntimeContextBuilder("## 相关长期记忆\n- fact"),
                cancel=cancel,
                journal=journal,
                turn_id="turn-1",
            )

        self.assertEqual(react.inputs, [("你好", "## 相关长期记忆\n- fact")])
        self.assertEqual(
            react.runtime_kwargs,
            [{"cancel": cancel, "journal": journal, "turn_id": "turn-1"}],
        )

    def test_run_once_rejects_legacy_agent_events_signature(self):
        react = _LegacyReactAgent()
        renderer = _CaptureRenderer()

        with self.assertLogs("app_runtime.agent_execution", level="ERROR"):
            result = cli.run_once(react, "你好", renderer=renderer)

        self.assertEqual(result, "")
        self.assertEqual(react.inputs, [])
        self.assertTrue(any("[ERROR] 执行失败" in message for message in renderer.messages))

    def test_run_once_error_prints_clean_message_without_traceback(self):
        react = _FailingReactAgent()
        output = io.StringIO()

        with self.assertLogs("app_runtime.agent_execution", level="ERROR"):
            with contextlib.redirect_stdout(output):
                cli.run_once(react, "你好")

        text = output.getvalue()
        self.assertIn("[ERROR] 执行失败: boom", text)
        self.assertNotIn("Traceback", text)

    def test_configure_logging_default_console_hides_info_logs(self):
        errors = io.StringIO()

        with _isolated_root_logger(), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHADOWCLI_LOG_LEVEL", None)
            os.environ.pop("SHADOWCLI_DEBUG_LOG", None)
            with contextlib.redirect_stderr(errors):
                cli.configure_logging()
                logging.getLogger("tests.console").info("internal info")
                logging.getLogger("tests.console").warning("visible warning")

        text = errors.getvalue()
        self.assertNotIn("internal info", text)
        self.assertIn("visible warning", text)

    def test_configure_logging_writes_debug_file_without_console_noise(self):
        errors = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "debug.log"
            with _isolated_root_logger(), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SHADOWCLI_LOG_LEVEL", None)
                os.environ.pop("SHADOWCLI_DEBUG_LOG", None)
                with contextlib.redirect_stderr(errors):
                    cli.configure_logging(debug_log_path=debug_path)
                    logging.getLogger("tests.debug.file").debug("deep debug detail")

            content = debug_path.read_text(encoding="utf-8")

        self.assertIn("deep debug detail", content)
        self.assertNotIn("deep debug detail", errors.getvalue())

    def test_configure_logging_suppresses_search_backend_info_logs(self):
        errors = io.StringIO()

        with _isolated_root_logger(), patch.dict(os.environ, {}, clear=False):
            os.environ["SHADOWCLI_LOG_LEVEL"] = "INFO"
            os.environ.pop("SHADOWCLI_DEBUG_LOG", None)
            with contextlib.redirect_stderr(errors):
                cli.configure_logging()
                logging.getLogger("ddgs").info("response: https://example.test 200")
                logging.getLogger("duckduckgo_search").info("Error in engine mojeek: TimeoutException")
                logging.getLogger("tests.visible").info("visible info")

        text = errors.getvalue()
        self.assertNotIn("response: https://example.test 200", text)
        self.assertNotIn("Error in engine mojeek", text)
        self.assertIn("visible info", text)

    def test_remember_command_writes_long_term_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "memory"
            memory = build_long_term_memory(memory_dir)

            message = cli.handle_remember(memory, "/remember 用户偏好：默认使用 React")

            self.assertIn("已记住", message)
            self.assertEqual(list(memory), ["用户偏好：默认使用 React"])
            self.assertIn(
                "- 用户偏好：默认使用 React",
                (memory_dir / "project.md").read_text(encoding="utf-8"),
            )

    def test_remember_command_accepts_explicit_memory_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "memory"
            memory = build_long_term_memory(memory_dir)

            message = cli.handle_remember(memory, "/remember feedback 不要自动写长期记忆")

            self.assertIn("已记住", message)
            self.assertIn(
                "- 不要自动写长期记忆",
                (memory_dir / "feedback.md").read_text(encoding="utf-8"),
            )

    def test_memory_status_shows_long_term_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = build_long_term_memory(Path(tmp) / "memory")
            memory.remember("用户偏好：默认使用 React")

            status = cli.format_memory_status(memory)

            self.assertNotIn("short_term", status)
            self.assertNotIn("tokens", status)
            self.assertIn("long_term : 1 facts", status)

    def test_empty_long_term_file_loads_as_empty_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory"

            memory = build_long_term_memory(path)

            self.assertEqual(len(memory), 0)

    def test_navigate_session_branch_direct_choice_moves_leaf_without_summary(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            result = router.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.DIRECT,
                build_branch_summary=lambda plan: self.fail("直接跳转不应生成摘要"),
            )

            self.assertEqual(result, BranchNavigationChoice.DIRECT)
            self.assertEqual(session.get_leaf_id(), target_id)
            self.assertFalse(any(isinstance(entry, BranchSummaryEntry) for entry in session.all_entries()))
            self.assertIn(old_leaf_id, {entry.id for entry in session.all_entries()})

    def test_navigate_session_branch_summary_choice_appends_branch_summary(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            seen = []

            result = router.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.SUMMARIZE,
                build_branch_summary=lambda plan: seen.append(plan) or "离开分支摘要",
            )

            leaf = session.all_entries()[-1]
            self.assertEqual(result, BranchNavigationChoice.SUMMARIZE)
            self.assertIsInstance(leaf, BranchSummaryEntry)
            self.assertEqual(leaf.parent_id, target_id)
            self.assertEqual(leaf.from_id, old_leaf_id)
            self.assertEqual(leaf.summary, "离开分支摘要")
            self.assertEqual([entry.content for entry in [e.message for e in seen[0].leaving_entries]], ["旧分支问题"])

    def test_navigate_session_branch_cancel_choice_keeps_current_leaf(self):
        import cli_app.router as router

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            result = router.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.CANCEL,
                build_branch_summary=lambda plan: self.fail("取消跳转不应生成摘要"),
            )

            self.assertEqual(result, BranchNavigationChoice.CANCEL)
            self.assertEqual(session.get_leaf_id(), old_leaf_id)


class TerminalBranchNavigationTests(unittest.TestCase):
    def test_ask_branch_navigation_choice_returns_summary_choice(self):
        output = io.StringIO()

        with patch("builtins.input", return_value="2"):
            choice = ask_branch_navigation_choice(out=output)

        self.assertEqual(choice, BranchNavigationChoice.SUMMARIZE)
        self.assertIn("跳转到旧消息？", output.getvalue())
        self.assertIn("总结当前分支后跳转", output.getvalue())

    def test_ask_branch_navigation_choice_reprompts_invalid_choice(self):
        output = io.StringIO()

        with patch("builtins.input", side_effect=["x", "3"]):
            choice = ask_branch_navigation_choice(out=output)

        self.assertEqual(choice, BranchNavigationChoice.CANCEL)
        self.assertIn("请输入 1、2 或 3", output.getvalue())


class _StubReactAgent:
    def __init__(self):
        self.inputs = []
        self.runtime_kwargs = []
        self.reloaded = []

    def events(self, user_input, context="", *, cancel=None, journal=None, turn_id=None):
        self.inputs.append((user_input, context))
        self.runtime_kwargs.append({"cancel": cancel, "journal": journal, "turn_id": turn_id})
        yield StreamEvent("content", f"react:{user_input}")
        yield StreamEvent("done", {"reason": "finished"})

    def cancel(self):
        return None

    def replace_conversation_messages(self, messages):
        self.reloaded.append(list(messages))


class _LegacyReactAgent:
    def __init__(self):
        self.inputs = []

    def events(self, user_input, context=""):
        self.inputs.append((user_input, context))
        yield StreamEvent("content", f"legacy:{user_input}")
        yield StreamEvent("done", {"reason": "finished"})

    def cancel(self):
        return None


class _CaptureRenderer:
    def __init__(self, branch_choice=BranchNavigationChoice.CANCEL):
        self.branch_choice = branch_choice
        self.messages = []
        self.events = []
        self.cancel_requested_count = 0
        self.branch_plans = []

    def message(self, message):
        self.messages.append(message)

    def agent_event(self, event, *, agent_name="react"):
        self.events.append(event)

    def cancel_requested(self):
        self.cancel_requested_count += 1

    def branch_navigation_choice(self, plan=None):
        self.branch_plans.append(plan)
        return self.branch_choice


class _FailingReactAgent:
    def events(self, user_input, context="", *, cancel=None, journal=None, turn_id=None):
        raise RuntimeError("boom")

    def cancel(self):
        return None


class _FixedSkillSelector:
    def __init__(self, selection):
        self.selection = selection
        self.inputs = []

    def select(self, user_input):
        self.inputs.append(user_input)
        return self.selection


def _returning_run_once(output):
    def run_once(agent, user_input, *, runtime_context_builder=None, renderer=None):
        context = runtime_context_builder.build(user_input) if runtime_context_builder is not None else ""
        agent.inputs.append((user_input, context))
        return output

    return run_once


def _override_runtime_methods(app, *, build_agent=None, run_agent_once=None, list_tools=None, chat_fn=None, branch_summary=None):
    if build_agent is not None:
        def runtime_build_agent(*, conversation_messages=None, on_message_appended=None):
            return build_agent(
                app.tool_runtime,
                conversation_messages=conversation_messages,
                on_message_appended=on_message_appended,
            )

        app.build_agent = runtime_build_agent
    if run_agent_once is not None:
        app.run_agent_once = run_agent_once
    if list_tools is not None:
        app.list_tools = list_tools
    if chat_fn is not None:
        app.chat = chat_fn
    if branch_summary is not None:
        app.build_branch_summary = branch_summary


class _StaticRuntimeContextBuilder:
    def __init__(self, context):
        self.context = context

    def build(self, query):
        return self.context


class _StubLongTermMemory:
    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0


class _StubSession:
    path = Path(".")

    def __init__(self):
        self.meta = type("Meta", (), {"session_id": "stub-session"})()
        self.appended = []

    def messages(self):
        return []

    def append_message(self, message):
        self.appended.append(message)

    def summary_text(self):
        return ""

    def get_branch(self):
        return []


class _StubSessionStore:
    def __init__(self):
        self.session = _StubSession()

    def open_recent(self, cwd):
        return self.session

    def create(self, cwd):
        return self.session

    def project_dir(self, cwd):
        return Path("agent_memory")


class _FailingSessionStore:
    def open_recent(self, cwd):
        raise AssertionError("/skills 不应打开历史会话")

    def create(self, cwd):
        raise AssertionError("/skills 不应创建会话")

    def project_dir(self, cwd):
        return Path("agent_memory")


class _FixedSessionStore:
    def __init__(self, session, project_dir):
        self.session = session
        self._project_dir = Path(project_dir)

    def open_recent(self, cwd):
        return self.session

    def create(self, cwd):
        return self.session

    def project_dir(self, cwd):
        return self._project_dir


def _branching_session(tmp: Path):
    cwd = tmp / "project"
    cwd.mkdir()
    session = SessionStore(root=tmp / "sessions").create(cwd)
    session.append_message(Message(role="user", content="root"))
    target = session.append_message(Message(role="assistant", content="fork"))
    old_leaf = session.append_message(Message(role="user", content="旧分支问题"))
    return session, target.id, old_leaf.id


def _write_codex_plugin_manifest(plugin_root: Path, *, name: str, skills) -> None:
    manifest_dir = plugin_root / ".codex-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Codex style test plugin",
        "skills": skills,
    }
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_skill_file(
    skill_dir: Path,
    *,
    name: str,
    description: str,
    body: str,
    argument_hint: str = "",
    when_to_use: str = "",
) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if when_to_use:
        lines.append(f"when_to_use: {when_to_use}")
    if argument_hint:
        lines.append(f"argument-hint: {argument_hint}")
    lines.extend(["---", "", body])
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def _stream_content(calls, content):
    def fake_stream(messages, tools=None, cancel=None):
        calls.append((list(messages), tools))
        yield StreamEvent("content", content)
        yield StreamEvent("done", {"reason": "finished"})

    return fake_stream


@contextlib.contextmanager
def _isolated_root_logger():
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    for handler in old_handlers:
        root.removeHandler(handler)
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)


class _StubTool:
    def __init__(self, result):
        self.result = result

    def execute(self, arguments):
        return self.result


class _MetadataTool:
    def __init__(
        self,
        *,
        category: str = "test",
        effect: str = "write",
        concurrency_safe: bool = False,
        result_kind: str = "text",
    ):
        self.category = category
        self.effect = effect
        self.concurrency_safe = concurrency_safe
        self.result_kind = result_kind


class _TimedRegistry:
    def __init__(self, delay, tool_metadata=None):
        self.delay = delay
        self.events = []
        self._lock = threading.Lock()
        self.tool_metadata = {
            "read": _MetadataTool(category="file", effect="read", concurrency_safe=True),
            "grep": _MetadataTool(category="file", effect="read", concurrency_safe=True),
            "find": _MetadataTool(category="file", effect="read", concurrency_safe=True),
            "edit": _MetadataTool(category="file", effect="write", concurrency_safe=False),
        }
        if tool_metadata:
            self.tool_metadata.update(tool_metadata)

    def get_all_definitions(self):
        return []

    def get(self, name):
        return self.tool_metadata[name]

    def execute(self, name, arguments):
        label = arguments["label"]
        with self._lock:
            self.events.append(("start", label, time.perf_counter()))
        time.sleep(self.delay)
        with self._lock:
            self.events.append(("end", label, time.perf_counter()))
        return f"{name}:{label}"

    def timeline_by_label(self):
        timeline = {}
        for event, label, timestamp in self.events:
            timeline.setdefault(label, {})[event] = timestamp
        return timeline


class _ExecuteOnlyRegistry:
    def __init__(self):
        self.calls = []

    def get(self, name):
        raise AssertionError("工具执行必须通过 registry.execute()")

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return f"executed:{name}"

    def get_all_definitions(self):
        return []


class _HardRejectRuntime:
    def get_all_definitions(self):
        return []

    def execute(self, name, arguments):
        raise ToolExecutionBlocked("用户拒绝")


class _ToolDefinitionRegistry:
    def get_all_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "读取文件内容",
                    "parameters": {},
                },
            }
        ]

    def execute(self, name, arguments):
        return "executed"


class _MixedToolDefinitionRegistry:
    def get_all_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "执行命令",
                    "parameters": {},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mcp__filesystem__search_files",
                    "description": "Search files through MCP filesystem",
                    "parameters": {},
                },
            },
        ]

    def execute(self, name, arguments):
        return "executed"


class _GuidanceTool:
    def __init__(self, name: str, guidance: str):
        self.name = name
        self.guidance = guidance


class _GuidanceRegistry:
    def __init__(self):
        self.tools = {
            "read": _GuidanceTool("read", "使用 read 读取项目文件。"),
            "mcp__filesystem__search_files": _GuidanceTool(
                "mcp__filesystem__search_files",
                "隐藏的 MCP 工具说明",
            ),
        }

    def get_all_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "读取文件内容",
                    "parameters": {},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mcp__filesystem__search_files",
                    "description": "Search files through MCP filesystem",
                    "parameters": {},
                },
            },
        ]

    def get(self, name):
        return self.tools[name]

    def execute(self, name, arguments):
        return "executed"


class BashToolTests(unittest.TestCase):
    def test_bash_supports_ls_in_project_shell(self):
        result = BashTool().execute({"command": "ls -l ."})

        self.assertIn("agent", result)
        self.assertNotIn("not recognized", result)

    def test_bash_reports_exit_code_when_stderr_is_empty(self):
        result = BashTool().execute({
            "command": 'python -c "import sys; sys.exit(7)"',
        })

        self.assertIn("命令执行失败（退出码", result)
        self.assertIn("没有 stdout/stderr 输出", result)

    def test_bash_truncates_long_success_stdout(self):
        result = BashTool().execute({
            "command": 'python -c "print(\'x\' * 20000)"',
        })

        self.assertIn("已截断", result)
        self.assertLess(len(result), 13000)

    def test_bash_truncates_long_failure_stderr_and_classifies_error(self):
        result = BashTool().execute({
            "command": 'python -c "import sys; sys.stderr.write(\'e\' * 20000); sys.exit(3)"',
        })

        self.assertTrue(result.startswith("命令执行失败（退出码"))
        self.assertIn("错误类型: command_failed", result)
        self.assertIn("stderr:", result)
        self.assertIn("已截断", result)
        self.assertLess(len(result), 13000)

    def test_bash_times_out(self):
        result = BashTool().execute({
            "command": 'python -c "import time; time.sleep(2)"',
            "timeout_seconds": 1,
        })

        self.assertIn("命令超时", result)
        self.assertIn("错误类型: timeout", result)
        self.assertIn("超过 1 秒", result)

    def test_bash_description_explains_windows_powershell_semantics(self):
        tool = BashTool()

        self.assertIn("PowerShell", tool.description)
        self.assertIn("禁止使用 Linux 命令", tool.parameters["properties"]["command"]["description"])
        self.assertIn("PowerShell 语法", tool.parameters["properties"]["command"]["description"])

    def test_bash_guidance_distinguishes_shell_from_shadowcli_commands(self):
        guidance = BashTool().guidance

        self.assertIn("PowerShell", guidance)
        self.assertIn("ShadowCLI slash 命令", guidance)
        self.assertIn("/skill", guidance)
        self.assertIn("不要通过 bash", guidance)


class PiStyleToolTests(unittest.TestCase):
    def test_read_write_edit_use_pi_style_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"

            write_out = WriteTool().execute({"path": str(path), "content": "hello old"})
            read_out = ReadTool().execute({"path": str(path)})
            edit_out = EditTool().execute({
                "path": str(path),
                "old_text": "old",
                "new_text": "new",
            })

            self.assertEqual(WriteTool().name, "write")
            self.assertEqual(ReadTool().name, "read")
            self.assertEqual(EditTool().name, "edit")
            self.assertIn("已创建", write_out)
            self.assertIn("hello old", read_out)
            self.assertIn("编辑成功", edit_out)
            self.assertEqual(path.read_text(encoding="utf-8"), "hello new")

    def test_read_can_read_multiple_paths_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.txt"
            second = root / "b.txt"
            first.write_text("alpha\n", encoding="utf-8")
            second.write_text("beta\n", encoding="utf-8")

            out = ReadTool().execute({"paths": [str(first), str(second)]})

            self.assertIn(f"==> {first}", out)
            self.assertIn("alpha", out)
            self.assertIn(f"==> {second}", out)
            self.assertIn("beta", out)
            self.assertLess(out.index(str(first)), out.index(str(second)))

    def test_read_multiple_paths_runs_reads_concurrently(self):
        class SlowReadTool(ReadTool):
            def _read_one(self, arguments):
                time.sleep(0.2)
                return super()._read_one(arguments)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for index in range(3):
                path = root / f"{index}.txt"
                path.write_text(f"file {index}\n", encoding="utf-8")
                paths.append(str(path))

            start = time.perf_counter()
            out = SlowReadTool().execute({"paths": paths})
            elapsed = time.perf_counter() - start

            self.assertIn("file 0", out)
            self.assertIn("file 1", out)
            self.assertIn("file 2", out)
            self.assertLess(elapsed, 0.45)

    def test_edit_rejects_ambiguous_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("same\nsame\n", encoding="utf-8")

            out = EditTool().execute({
                "path": str(path),
                "old_text": "same",
                "new_text": "other",
            })

            self.assertIn("匹配到 2 处", out)
            self.assertEqual(path.read_text(encoding="utf-8"), "same\nsame\n")

    def test_bash_ls_grep_find_use_pi_style_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('needle')\n", encoding="utf-8")
            (root / "README.md").write_text("needle docs\n", encoding="utf-8")

            ls_out = LsTool().execute({"path": str(root)})
            grep_out = GrepTool().execute({"path": str(root), "pattern": "needle"})
            find_out = FindTool().execute({"path": str(root), "name": "*.py"})
            bash_out = BashTool().execute({"command": "python --version"})

            self.assertEqual(BashTool().name, "bash")
            self.assertEqual(LsTool().name, "ls")
            self.assertEqual(GrepTool().name, "grep")
            self.assertEqual(FindTool().name, "find")
            self.assertIn("src", ls_out)
            self.assertIn("README.md", ls_out)
            self.assertIn("app.py:1:print('needle')", grep_out)
            self.assertIn("README.md:1:needle docs", grep_out)
            self.assertIn("src/app.py", find_out.replace("\\", "/"))
            self.assertIn("Python", bash_out)

    def test_cli_registry_exposes_only_canonical_tool_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AppRuntime.create(
                Path(tmp),
                tool_runtime=build_default_tool_runtime(),
            )
            registry = app.tool_runtime
        names = [d["function"]["name"] for d in registry.get_all_definitions()]

        for name in ["read", "write", "edit", "bash", "ls", "grep", "find", "web_search", "web_fetch"]:
            self.assertIn(name, names)
        for name in ["read_file", "write_file", "list_dir", "execute_command"]:
            self.assertNotIn(name, names)
        for name in ["index_codebase", "search_code"]:
            self.assertNotIn(name, names)

    def test_builtin_tools_declare_minimal_metadata(self):
        cases = [
            (ReadTool(), "file", "read", True, "text"),
            (LsTool(), "file", "read", True, "file_list"),
            (GrepTool(), "file", "read", True, "search_hits"),
            (FindTool(), "file", "read", True, "file_list"),
            (WriteTool(), "file", "write", False, "text"),
            (EditTool(), "file", "write", False, "text"),
            (BashTool(), "shell", "execute", False, "command_output"),
            (WebSearchTool(), "web", "read", True, "search_hits"),
            (WebFetchTool(), "web", "read", True, "web_text"),
        ]

        for tool, category, effect, concurrency_safe, result_kind in cases:
            with self.subTest(tool=tool.name):
                self.assertEqual(tool.category, category)
                self.assertEqual(tool.effect, effect)
                self.assertEqual(tool.concurrency_safe, concurrency_safe)
                self.assertEqual(tool.result_kind, result_kind)

    def test_file_search_guidance_names_shadowcli_tools_not_shell_commands(self):
        self.assertIn("ShadowCLI ls 工具", LsTool().guidance)
        self.assertIn("不是终端 ls 命令", LsTool().guidance)
        self.assertIn("ShadowCLI grep 工具", GrepTool().guidance)
        self.assertIn("不是终端 grep/rg 命令", GrepTool().guidance)
        self.assertIn("ShadowCLI find 工具", FindTool().guidance)
        self.assertIn("不是终端 find 命令", FindTool().guidance)

    def test_registry_executes_pi_style_tools_through_same_entrypoint(self):
        registry = ToolRegistry()
        registry.register(WriteTool()).register(ReadTool())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.txt"

            registry.execute("write", {"path": str(path), "content": "ok"})
            out = registry.execute("read", {"path": str(path)})

        self.assertIn("ok", out)

    def test_file_write_tools_do_not_require_approval_by_default(self):
        self.assertFalse(WriteTool().requires_approval({"path": "demo.txt"}))
        self.assertFalse(EditTool().requires_approval({"path": "demo.txt"}))
        self.assertTrue(BashTool().requires_approval({"command": "python --version"}))


if __name__ == "__main__":
    unittest.main()
