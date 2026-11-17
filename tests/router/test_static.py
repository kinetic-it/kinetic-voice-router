"""Static guard rails for the public package (reads source and JSON, runs no integration code)."""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
KVR = ROOT / "custom_components" / "kinetic_voice_router"

# Each of these would be a second action path past the Assist exposure settings, a new
# control ability for the model, or a hidden change of the user's setup.
FORBIDDEN_CALLS = {
    "services.async_call": "direct Home Assistant service call",
    "async_converse": "hand-over to another conversation agent",
    "async_handle_intents": "internal local-first API",
    "ConversationEntityFeature.CONTROL": "control ability for the model",
    "llm.async_get_api": "Home Assistant LLM API",
    "async_register_entity_service": "new service",
    "async_set_preferred": "automatic Assist pipeline change",
    "async_update_pipeline": "automatic Assist pipeline change",
    "should_expose": "exposure handling",
    "async_expose_entity": "automatic entity exposure",
    "async_set_should_expose": "automatic entity exposure",
}
# Network/process access is confined to the Hermes client (aiohttp) and nothing else.
FORBIDDEN_IMPORTS = {"http", "httpx", "requests", "socket", "ssl", "subprocess", "urllib", "ftplib"}
ROUTER_CORE_FORBIDDEN = FORBIDDEN_IMPORTS | {"aiohttp", "asyncio", "os", "shutil", "homeassistant"}


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _leaves(value: object, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        out: dict[str, str] = {}
        for key, item in value.items():
            out.update(_leaves(item, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: str(value)}


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"{([a-z_]+)}", text))


class ActionPathGuards(unittest.TestCase):
    # Genau eine Datei und genau ein Ziel duerfen einen Home-Assistant-Dienst
    # aufrufen: der Wecker-Pfad in conversation.py ueber AUTHORIZED_TARGETS.
    SERVICE_CALL = "services.async_call"
    SERVICE_CALL_FILE = "conversation.py"
    ALLOWLIST_NAME = "AUTHORIZED_TARGETS"

    def test_no_action_path_outside_the_authorized_alarm_capability(self):
        erlaubt = KVR / self.SERVICE_CALL_FILE
        for path in KVR.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for needle, why in FORBIDDEN_CALLS.items():
                if needle == self.SERVICE_CALL and path == erlaubt:
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), needle=needle):
                    self.assertNotIn(needle, source, why)

    def test_the_only_service_call_is_bound_to_the_alarm_allowlist(self):
        """Der Dienstaufruf existiert genau einmal, steht in der Allowlist-Pruefung
        und ist ohne Allowlist-Treffer nicht erreichbar."""
        source = (KVR / self.SERVICE_CALL_FILE).read_text(encoding="utf-8")
        self.assertEqual(source.count(self.SERVICE_CALL), 1)
        block = self._innermost_function_with(source, self.SERVICE_CALL)
        self.assertIn("ensure_authorized_target", block)

        auth = (KVR / "voice_router" / "authorization.py").read_text(encoding="utf-8")
        guard = self._innermost_function_with(auth, "raise PermissionError")
        self.assertIn(self.ALLOWLIST_NAME, guard)
        self.assertIn("raise PermissionError", guard)
        for path in KVR.rglob("*.py"):
            fremd = "raise PermissionError" in path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(fremd, path.name == "authorization.py")

        alarm = (KVR / "voice_router" / "alarm.py").read_text(encoding="utf-8")
        ziele = re.findall(r"AUTHORIZED_TARGETS\s*=\s*frozenset\(\{(.*?)\}\)", alarm, re.S)
        self.assertEqual(len(ziele), 1, "genau eine Allowlist-Definition erwartet")
        self.assertEqual(ziele[0].strip(), "(DOMAIN, SERVICE)")
        for path in KVR.rglob("*.py"):
            if path.name == "alarm.py":
                continue
            with self.subTest(file=path.name):
                self.assertNotIn(
                    "AUTHORIZED_TARGETS =",
                    path.read_text(encoding="utf-8"),
                    "Allowlist nur in voice_router/alarm.py",
                )

    def test_the_alarm_capability_cannot_reach_hermes(self):
        """Der autorisierte Pfad uebergibt nur die Aktion, nie einen Hermes-Aufruf."""
        source = (KVR / self.SERVICE_CALL_FILE).read_text(encoding="utf-8")
        block = self._innermost_function_with(source, self.SERVICE_CALL)
        for verboten in ("call_hermes", "_ask_hermes", "hermes_client", "async_inference"):
            self.assertNotIn(verboten, block)
        alarm = (KVR / "voice_router" / "alarm.py").read_text(encoding="utf-8")
        for verboten in ("hermes", "aiohttp", "async_inference"):
            self.assertNotIn(verboten, alarm.lower())

    @staticmethod
    def _innermost_function_with(source: str, needle: str) -> str:
        """Kleinste Funktion (auch verschachtelt), die den Ausdruck enthaelt."""
        treffer: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                segment = ast.get_source_segment(source, node) or ""
                if needle in segment:
                    treffer.append(segment)
        if not treffer:
            raise AssertionError(f"keine Funktion mit {needle!r}")
        return min(treffer, key=len)


class ManifestAndPackaging(unittest.TestCase):
    manifest = json.loads((KVR / "manifest.json").read_text(encoding="utf-8"))

    def test_required_manifest_keys(self):
        m = self.manifest
        self.assertEqual(m["domain"], "kinetic_voice_router")
        for key in ("name", "version", "documentation", "issue_tracker", "codeowners"):
            self.assertTrue(m[key], key)
        self.assertIs(m["config_flow"], True)
        self.assertIs(m["single_config_entry"], True)
        self.assertEqual(m["requirements"], [])
        self.assertIn("conversation", m["dependencies"])
        self.assertEqual(m["integration_type"], "service")
        self.assertEqual(m["iot_class"], "local_polling")
        self.assertEqual(m["documentation"], "https://github.com/kinetic-it/kinetic-voice-router")
        self.assertEqual(
            m["issue_tracker"], "https://github.com/kinetic-it/kinetic-voice-router/issues"
        )

    def test_versions_agree(self):
        const = (KVR / "const.py").read_text(encoding="utf-8")
        model = (KVR / "voice_router" / "model.py").read_text(encoding="utf-8")
        self.assertIn(f'INTEGRATION_VERSION: Final = "{self.manifest["version"]}"', const)
        self.assertIn(f'ROUTER_VERSION = "{self.manifest["version"]}"', model)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{self.manifest['version']}]", changelog)

    def test_version_is_a_prerelease_until_released(self):
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+(?:b|rc|a)\d+$")

    def test_hacs_json(self):
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(hacs["name"], "Kinetic Voice Router")
        self.assertNotIn("zip_release", hacs)  # no artifact is promised before a release exists

    def test_exactly_one_integration(self):
        self.assertEqual(
            [p.name for p in (ROOT / "custom_components").iterdir() if p.is_dir()],
            ["kinetic_voice_router"],
        )

    def test_licence_and_notice(self):
        licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(licence.startswith("MIT License"))
        self.assertIn("AS IS", licence)
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Codename-11/hermes-homeassistant", notice)
        self.assertIn("Copyright (c) 2026 Bailey Dixon", notice)


class Translations(unittest.TestCase):
    strings = json.loads((KVR / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((KVR / "translations" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((KVR / "translations" / "de.json").read_text(encoding="utf-8"))

    def test_en_equals_source_strings(self):
        self.assertEqual(self.strings, self.en)

    def test_german_has_exactly_the_same_keys_and_placeholders(self):
        a, b = _leaves(self.en), _leaves(self.de)
        self.assertEqual(set(a), set(b))
        for key in a:
            with self.subTest(key=key):
                self.assertEqual(_placeholders(a[key]), _placeholders(b[key]))

    def test_every_flow_step_and_error_used_in_code_has_text(self):
        source = (KVR / "config_flow.py").read_text(encoding="utf-8")
        steps = set(re.findall(r'step_id="([a-z_]+)"', source))
        known_steps = set(self.en["config"]["step"]) | set(self.en["options"]["step"])
        self.assertTrue(steps <= known_steps, steps - known_steps)
        # error keys: values of _PROBE_ERRORS, `return None, "key"` and errors["base"] = "key"
        used: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_PROBE_ERRORS"
            ):
                used.update(v.value for v in node.value.values if isinstance(v, ast.Constant))
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                first, *rest = node.value.elts
                if isinstance(first, ast.Constant) and first.value is None:
                    used.update(e.value for e in rest if isinstance(e, ast.Constant))
            elif (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.targets[0], ast.Subscript)
            ):
                used.add(node.value.value)
        used = {u for u in used if isinstance(u, str)}
        known = set(self.en["config"]["error"]) | set(self.en["options"]["error"])
        self.assertTrue({"cannot_connect", "invalid_auth", "invalid_url"} <= used)
        self.assertTrue(used <= known, used - known)

    def test_no_secret_or_url_example_in_texts_beyond_placeholders(self):
        dumped = json.dumps([self.en, self.de])
        self.assertNotRegex(dumped, r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
        self.assertNotRegex(dumped, r"Bearer\s+[A-Za-z0-9._~+/-]{12,}")

    def test_experimental_notice_is_shown_at_setup(self):
        self.assertIn("no warranty", self.en["config"]["step"]["user"]["description"].lower())
        self.assertIn("ohne gewähr", self.de["config"]["step"]["user"]["description"].lower())


class PublicHygiene(unittest.TestCase):
    def test_audit_script_is_clean(self):
        spec = importlib.util.spec_from_file_location(
            "audit_public", ROOT / "scripts" / "audit_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        problems = module.scan(ROOT) + module.check_licence_files(ROOT)
        self.assertEqual(problems, [])

    def test_audit_script_detects_what_it_promises(self):
        import tempfile

        spec = importlib.util.spec_from_file_location(
            "audit_public", ROOT / "scripts" / "audit_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Built from pieces so that this file itself contains no matching literal.
        samples = {
            "token": "x = '" + "ghp" + "_" + "a" * 36 + "'",
            "ip": "url = 'http://" + "192" + ".168.0.58:8765'",
            "ip10": "url = 'http://" + "10" + ".0.0.5'",
            "mail": "contact = 'someone" + "@" + "example.org'",
            "wi": "# see " + "WI" + "-0181",
            "repo": "# " + "kinetic-it" + "/" + "homeassistant",
            "bearer": "h = 'Bearer " + "abcdefghijklmnopqrstuvwxyz" + "0123456789'",
            "key": "-----BEGIN " + "PRIVATE KEY-----",
            "host": "target = '" + "hass" + "-os'",
        }
        for name, content in samples.items():
            with self.subTest(sample=name), tempfile.TemporaryDirectory() as tmp:
                (pathlib.Path(tmp) / "x.py").write_text(content, encoding="utf-8")
                self.assertTrue(module.scan(pathlib.Path(tmp)), name)

    def test_required_public_documents_exist(self):
        for name in ("README.md", "LICENSE", "NOTICE", "SECURITY.md", "CHANGELOG.md", "hacs.json"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
