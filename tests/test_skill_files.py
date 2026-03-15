"""
test_skill_files.py -- Validates structure and content of HiveMind SKILL.md files.

Ensures every skill file has correct YAML frontmatter, mandatory sections,
constraint tables, Sherlock fallback rules, output format templates,
and required HiveMind tool references. Validates cross-skill consistency
(no trigger collisions, all slash commands unique, shared constraints present).
"""

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SKILLS_DIR = PROJECT_ROOT / ".github" / "skills"


def read_skill(name):
    """Read and return a skill file's content, or None if missing."""
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def extract_frontmatter(content):
    """Extract YAML frontmatter between --- markers.
    
    Handles files that may start with backtick fence wrappers
    (e.g., `````skill or ````skill) before the --- markers.
    """
    if not content:
        return ""
    lines = content.split("\n")
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip backtick fence lines (e.g., ````skill, `````skill)
        if stripped.startswith("`"):
            continue
        if stripped == "---":
            if start_idx is None:
                start_idx = i
            else:
                end_idx = i
                break
    if start_idx is not None and end_idx is not None:
        return "\n".join(lines[start_idx + 1:end_idx])
    return ""


class TestSkillFilesExist(unittest.TestCase):
    """Verify all expected skill files exist."""

    EXPECTED_SKILLS = [
        "incident-triage",
        "k8s-debug",
        "secret-audit",
        "postmortem",
        "cert-audit",
        "db-debug",
        "perf-debug",
    ]

    def test_all_new_skill_files_exist(self):
        """Every new skill has a SKILL.md file in the skills directory."""
        for name in self.EXPECTED_SKILLS:
            path = SKILLS_DIR / name / "SKILL.md"
            self.assertTrue(path.exists(), f"Missing skill file: {path}")

    def test_skill_files_are_nonempty(self):
        """Every skill file has substantial content (>100 lines)."""
        for name in self.EXPECTED_SKILLS:
            content = read_skill(name)
            if content is None:
                self.fail(f"Missing skill file: {name}")
            line_count = len(content.strip().split("\n"))
            self.assertGreater(
                line_count, 100,
                f"Skill {name} has only {line_count} lines — expected >100",
            )


class TestSkillFrontmatter(unittest.TestCase):
    """Validate YAML frontmatter in each skill file."""

    SKILLS = {
        "incident-triage": {
            "name": "incident-triage",
            "slash_command": "/triage",
            "min_triggers": 10,
        },
        "k8s-debug": {
            "name": "k8s-debug",
            "slash_command": "/k8s",
            "min_triggers": 10,
        },
        "secret-audit": {
            "name": "secret-audit",
            "slash_command": "/secrets",
            "min_triggers": 10,
        },
        "postmortem": {
            "name": "postmortem",
            "slash_command": "/postmortem",
            "min_triggers": 3,
        },
        "cert-audit": {
            "name": "cert-audit",
            "slash_command": "/cert-audit",
            "min_triggers": 10,
        },
        "db-debug": {
            "name": "db-debug",
            "slash_command": "/db",
            "min_triggers": 10,
        },
        "perf-debug": {
            "name": "perf-debug",
            "slash_command": "/perf",
            "min_triggers": 10,
        },
    }

    def test_frontmatter_has_name(self):
        """Each skill frontmatter declares a name field."""
        for skill_name, expected in self.SKILLS.items():
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            fm = extract_frontmatter(content)
            self.assertIn(
                f"name: {expected['name']}",
                fm,
                f"Skill {skill_name}: frontmatter missing name: {expected['name']}",
            )

    def test_frontmatter_has_description(self):
        """Each skill frontmatter declares a description field."""
        for skill_name in self.SKILLS:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            fm = extract_frontmatter(content)
            self.assertIn(
                "description:",
                fm,
                f"Skill {skill_name}: frontmatter missing description",
            )

    def test_frontmatter_has_triggers(self):
        """Each skill frontmatter declares triggers with minimum count."""
        for skill_name, expected in self.SKILLS.items():
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            fm = extract_frontmatter(content)
            self.assertIn(
                "triggers:",
                fm,
                f"Skill {skill_name}: frontmatter missing triggers",
            )
            trigger_lines = re.findall(r"^\s+-\s+.+$", fm, re.MULTILINE)
            self.assertGreaterEqual(
                len(trigger_lines),
                expected["min_triggers"],
                f"Skill {skill_name}: expected >= {expected['min_triggers']} triggers, "
                f"found {len(trigger_lines)}",
            )

    def test_frontmatter_has_slash_command(self):
        """Each skill frontmatter declares a slash_command."""
        for skill_name, expected in self.SKILLS.items():
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            fm = extract_frontmatter(content)
            self.assertIn(
                f"slash_command: {expected['slash_command']}",
                fm,
                f"Skill {skill_name}: missing slash_command: {expected['slash_command']}",
            )

    def test_slash_commands_are_unique(self):
        """No two skills share the same slash command."""
        commands = {}
        for skill_name, expected in self.SKILLS.items():
            cmd = expected["slash_command"]
            self.assertNotIn(
                cmd,
                commands,
                f"Slash command {cmd} used by both {commands.get(cmd)} and {skill_name}",
            )
            commands[cmd] = skill_name


class TestPostmortemExplicitActivation(unittest.TestCase):
    """Validate postmortem has explicit-only activation — never auto-triggers."""

    def setUp(self):
        self.content = read_skill("postmortem")
        if self.content is None:
            self.fail("Missing skill file: postmortem")
        self.fm = extract_frontmatter(self.content)

    def test_activation_explicit_only(self):
        """Postmortem frontmatter declares activation: explicit-only."""
        self.assertIn(
            "activation: explicit-only",
            self.fm,
            "Postmortem must have activation: explicit-only in frontmatter",
        )

    def test_no_broad_triggers(self):
        """Postmortem must NOT have broad triggers that overlap with triage."""
        banned_triggers = [
            "RCA",
            "root cause analysis",
            "incident report",
            "what happened",
            "how long were we down",
            "what was the impact",
            "incident summary",
            "outage report",
            "PIR",
            "after action",
            "incident review",
        ]
        for trigger in banned_triggers:
            # Check that trigger is NOT in the frontmatter triggers list
            pattern = rf"^\s+-\s+{re.escape(trigger)}\s*$"
            match = re.search(pattern, self.fm, re.MULTILINE | re.IGNORECASE)
            self.assertIsNone(
                match,
                f"Postmortem has banned broad trigger: '{trigger}' — "
                f"this should NOT be a trigger (explicit-only activation)",
            )

    def test_only_explicit_postmortem_triggers(self):
        """Postmortem triggers should only match explicit postmortem requests."""
        trigger_lines = re.findall(r"^\s+-\s+(.+)$", self.fm, re.MULTILINE)
        triggers = [t.strip().strip('"').strip("'") for t in trigger_lines]
        for trigger in triggers:
            # After "triggers:" but before "slash_command:", skip non-trigger lines
            if trigger.startswith("name:") or trigger.startswith("description"):
                continue
            # Each trigger must contain "postmortem" or be the slash command
            self.assertTrue(
                "postmortem" in trigger.lower() or trigger == "/postmortem",
                f"Postmortem trigger '{trigger}' does not contain 'postmortem' — "
                f"broad triggers are banned for this skill",
            )

    def test_p0_constraint_exists(self):
        """Postmortem must have P-0 constraint about explicit activation."""
        self.assertIn(
            "P-0",
            self.content,
            "Postmortem missing P-0 constraint (explicit activation guard)",
        )
        self.assertIn(
            "NEVER activate unless the user EXPLICITLY",
            self.content,
            "P-0 constraint must state NEVER activate unless explicitly asked",
        )


class TestSkillConstraints(unittest.TestCase):
    """Validate each skill has mandatory constraint rules."""

    SKILLS_WITH_CONSTRAINTS = {
        "incident-triage": {"prefix": "C-", "min_count": 5},
        "k8s-debug": {"prefix": "K-", "min_count": 8},
        "secret-audit": {"prefix": "S-", "min_count": 8},
        "postmortem": {"prefix": "P-", "min_count": 8},
        "cert-audit": {"prefix": "CA-", "min_count": 8},
        "db-debug": {"prefix": "DB-C", "min_count": 8},
        "perf-debug": {"prefix": "PD-", "min_count": 8},
    }

    def test_constraints_section_exists(self):
        """Each skill has a CONSTRAINTS section."""
        for skill_name in self.SKILLS_WITH_CONSTRAINTS:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertIn(
                "CONSTRAINTS",
                content,
                f"Skill {skill_name}: missing CONSTRAINTS section",
            )

    def test_constraint_count(self):
        """Each skill has at least the minimum number of constraints."""
        for skill_name, spec in self.SKILLS_WITH_CONSTRAINTS.items():
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            prefix = spec["prefix"]
            # Match constraints like "| K-1 |" or "| S-10 |"
            pattern = rf"\|\s*{re.escape(prefix)}\d+\s*\|"
            matches = re.findall(pattern, content)
            self.assertGreaterEqual(
                len(matches),
                spec["min_count"],
                f"Skill {skill_name}: expected >= {spec['min_count']} constraints with "
                f"prefix '{prefix}', found {len(matches)}",
            )

    def test_never_run_commands_constraint(self):
        """All investigation skills must have a NEVER-run-commands constraint."""
        for skill_name in ["k8s-debug", "secret-audit", "postmortem", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertTrue(
                "NEVER run commands" in content or "NEVER run any commands" in content,
                f"Skill {skill_name}: missing 'NEVER run commands' constraint",
            )

    def test_never_block_on_sherlock_constraint(self):
        """Investigation skills must have a NEVER-block-on-Sherlock constraint."""
        for skill_name in ["k8s-debug", "secret-audit", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertIn(
                "NEVER block on Sherlock",
                content,
                f"Skill {skill_name}: missing 'NEVER block on Sherlock' constraint",
            )

    def test_always_cite_sources_constraint(self):
        """All skills must require source citation."""
        for skill_name in ["k8s-debug", "secret-audit", "postmortem", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            has_cite = (
                "ALWAYS cite" in content
                or "ALWAYS provide exact file path" in content
                or "ALWAYS cite sources" in content
            )
            self.assertTrue(
                has_cite,
                f"Skill {skill_name}: missing source citation constraint",
            )


class TestSherlockFallback(unittest.TestCase):
    """Validate Sherlock fallback rule in each investigation skill."""

    INVESTIGATION_SKILLS = ["k8s-debug", "secret-audit", "postmortem", "cert-audit", "db-debug", "perf-debug"]

    def test_sherlock_fallback_section_exists(self):
        """Each investigation skill has a SHERLOCK FALLBACK section."""
        for skill_name in self.INVESTIGATION_SKILLS:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertIn(
                "SHERLOCK FALLBACK",
                content,
                f"Skill {skill_name}: missing SHERLOCK FALLBACK section",
            )

    def test_path_a_and_path_b_defined(self):
        """Each skill defines both Path A (Sherlock available) and Path B (fallback)."""
        for skill_name in self.INVESTIGATION_SKILLS:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertIn(
                "Path A",
                content,
                f"Skill {skill_name}: missing Path A definition",
            )
            self.assertIn(
                "Path B",
                content,
                f"Skill {skill_name}: missing Path B definition",
            )

    def test_sherlock_tool_references(self):
        """Investigation skills reference at least one Sherlock MCP tool."""
        for skill_name in ["k8s-debug", "secret-audit", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertRegex(
                content,
                r"mcp_sherlock_\w+",
                f"Skill {skill_name}: missing Sherlock MCP tool references",
            )

    def test_kubectl_fallback_commands(self):
        """Investigation skills provide kubectl commands as Path B fallback."""
        for skill_name in ["k8s-debug", "secret-audit", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertIn(
                "kubectl",
                content,
                f"Skill {skill_name}: missing kubectl fallback commands",
            )


class TestHiveMindToolReferences(unittest.TestCase):
    """Validate each skill references required HiveMind MCP tools."""

    def test_secret_audit_references_get_secret_flow(self):
        """secret-audit must always reference hivemind_get_secret_flow."""
        content = read_skill("secret-audit")
        if content is None:
            self.fail("Missing skill file: secret-audit")
        self.assertIn(
            "hivemind_get_secret_flow",
            content,
            "secret-audit must reference hivemind_get_secret_flow",
        )

    def test_secret_audit_references_impact_analysis(self):
        """secret-audit must always reference hivemind_impact_analysis."""
        content = read_skill("secret-audit")
        if content is None:
            self.fail("Missing skill file: secret-audit")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "secret-audit must reference hivemind_impact_analysis for blast radius",
        )

    def test_k8s_debug_references_impact_analysis(self):
        """k8s-debug must always reference hivemind_impact_analysis."""
        content = read_skill("k8s-debug")
        if content is None:
            self.fail("Missing skill file: k8s-debug")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "k8s-debug must reference hivemind_impact_analysis",
        )

    def test_postmortem_references_impact_analysis(self):
        """postmortem must always reference hivemind_impact_analysis."""
        content = read_skill("postmortem")
        if content is None:
            self.fail("Missing skill file: postmortem")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "postmortem must reference hivemind_impact_analysis for blast radius",
        )

    def test_k8s_debug_references_query_memory(self):
        """k8s-debug must reference hivemind_query_memory."""
        content = read_skill("k8s-debug")
        if content is None:
            self.fail("Missing skill file: k8s-debug")
        self.assertIn(
            "hivemind_query_memory",
            content,
            "k8s-debug must reference hivemind_query_memory",
        )

    def test_secret_audit_references_query_memory(self):
        """secret-audit must reference hivemind_query_memory."""
        content = read_skill("secret-audit")
        if content is None:
            self.fail("Missing skill file: secret-audit")
        self.assertIn(
            "hivemind_query_memory",
            content,
            "secret-audit must reference hivemind_query_memory",
        )

    def test_postmortem_references_get_entity(self):
        """postmortem must reference hivemind_get_entity for blast radius services."""
        content = read_skill("postmortem")
        if content is None:
            self.fail("Missing skill file: postmortem")
        self.assertIn(
            "hivemind_get_entity",
            content,
            "postmortem must reference hivemind_get_entity",
        )

    def test_cert_audit_references_impact_analysis(self):
        """cert-audit must always reference hivemind_impact_analysis."""
        content = read_skill("cert-audit")
        if content is None:
            self.fail("Missing skill file: cert-audit")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "cert-audit must reference hivemind_impact_analysis for blast radius",
        )

    def test_cert_audit_references_query_memory(self):
        """cert-audit must reference hivemind_query_memory."""
        content = read_skill("cert-audit")
        if content is None:
            self.fail("Missing skill file: cert-audit")
        self.assertIn(
            "hivemind_query_memory",
            content,
            "cert-audit must reference hivemind_query_memory",
        )

    def test_db_debug_references_impact_analysis(self):
        """db-debug must always reference hivemind_impact_analysis."""
        content = read_skill("db-debug")
        if content is None:
            self.fail("Missing skill file: db-debug")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "db-debug must reference hivemind_impact_analysis for blast radius",
        )

    def test_db_debug_references_query_memory(self):
        """db-debug must reference hivemind_query_memory."""
        content = read_skill("db-debug")
        if content is None:
            self.fail("Missing skill file: db-debug")
        self.assertIn(
            "hivemind_query_memory",
            content,
            "db-debug must reference hivemind_query_memory",
        )

    def test_db_debug_references_get_secret_flow(self):
        """db-debug must reference hivemind_get_secret_flow."""
        content = read_skill("db-debug")
        if content is None:
            self.fail("Missing skill file: db-debug")
        self.assertIn(
            "hivemind_get_secret_flow",
            content,
            "db-debug must reference hivemind_get_secret_flow",
        )

    def test_perf_debug_references_impact_analysis(self):
        """perf-debug must always reference hivemind_impact_analysis."""
        content = read_skill("perf-debug")
        if content is None:
            self.fail("Missing skill file: perf-debug")
        self.assertIn(
            "hivemind_impact_analysis",
            content,
            "perf-debug must reference hivemind_impact_analysis for blast radius",
        )

    def test_perf_debug_references_query_memory(self):
        """perf-debug must reference hivemind_query_memory."""
        content = read_skill("perf-debug")
        if content is None:
            self.fail("Missing skill file: perf-debug")
        self.assertIn(
            "hivemind_query_memory",
            content,
            "perf-debug must reference hivemind_query_memory",
        )

    def test_perf_debug_references_diff_branches(self):
        """perf-debug must reference hivemind_diff_branches."""
        content = read_skill("perf-debug")
        if content is None:
            self.fail("Missing skill file: perf-debug")
        self.assertIn(
            "hivemind_diff_branches",
            content,
            "perf-debug must reference hivemind_diff_branches for change correlation",
        )


class TestSecretAuditStructure(unittest.TestCase):
    """Validate secret-audit skill structure and content."""

    def setUp(self):
        self.content = read_skill("secret-audit")
        if self.content is None:
            self.fail("Missing skill file: secret-audit")

    def test_seven_failure_modes_defined(self):
        """secret-audit defines all 7 failure modes (FM-1 through FM-7)."""
        for i in range(1, 8):
            self.assertIn(
                f"FM-{i}",
                self.content,
                f"secret-audit missing failure mode FM-{i}",
            )

    def test_failure_mode_labels(self):
        """secret-audit has named labels for each failure mode."""
        expected_labels = [
            "SECRET MISSING",
            "SECRET WRONG VERSION",
            "ACCESS DENIED",
            "CSI MOUNT FAILED",
            "IDENTITY BROKEN",
            "SECRET NAME MISMATCH",
            "CONFIG MISSING",
        ]
        for label in expected_labels:
            self.assertIn(
                label,
                self.content,
                f"secret-audit missing failure mode label: {label}",
            )

    def test_secret_chain_present(self):
        """secret-audit has the secret chain diagram (7 links)."""
        chain_links = [
            "TERRAFORM",
            "KEYVAULT",
            "IDENTITY",
            "CSI DRIVER",
            "K8S SECRET",
            "POD MOUNT",
            "APP READ",
        ]
        for link in chain_links:
            self.assertIn(
                link,
                self.content,
                f"secret-audit missing chain link: {link}",
            )

    def test_investigation_layers_present(self):
        """secret-audit has all 6 investigation layers."""
        layers = [
            "LAYER 1",
            "LAYER 2",
            "LAYER 3",
            "LAYER 4",
            "LAYER 5",
            "LAYER 6",
        ]
        for layer in layers:
            self.assertIn(
                layer,
                self.content,
                f"secret-audit missing {layer}",
            )

    def test_blast_radius_section(self):
        """secret-audit has a blast radius check section."""
        self.assertIn(
            "Blast Radius",
            self.content,
            "secret-audit missing Blast Radius section",
        )

    def test_output_format_section(self):
        """secret-audit has a SECRET AUDIT REPORT output format."""
        self.assertIn(
            "SECRET AUDIT REPORT",
            self.content,
            "secret-audit missing SECRET AUDIT REPORT output format",
        )

    def test_kb_cross_reference_map(self):
        """secret-audit has a KB Cross-Reference map."""
        self.assertIn(
            "KB Cross-Reference",
            self.content,
            "secret-audit missing KB Cross-Reference map",
        )

    def test_workload_identity_coverage(self):
        """secret-audit covers workload identity debugging."""
        self.assertIn(
            "workload identity",
            self.content.lower(),
            "secret-audit must cover workload identity",
        )
        self.assertIn(
            "federated credential",
            self.content.lower(),
            "secret-audit must cover federated credentials",
        )

    def test_az_keyvault_commands(self):
        """secret-audit includes az keyvault commands for verification."""
        self.assertIn(
            "az keyvault secret list",
            self.content,
            "secret-audit must include az keyvault secret list command",
        )
        self.assertIn(
            "az keyvault secret show",
            self.content,
            "secret-audit must include az keyvault secret show command",
        )

    def test_spring_boot_config_coverage(self):
        """secret-audit covers Spring Boot config (@Value, application.yaml)."""
        self.assertIn(
            "@Value",
            self.content,
            "secret-audit must cover Spring Boot @Value references",
        )
        self.assertIn(
            "application.yaml",
            self.content,
            "secret-audit must cover application.yaml references",
        )


class TestCertAuditStructure(unittest.TestCase):
    """Validate cert-audit skill structure and content."""

    def setUp(self):
        self.content = read_skill("cert-audit")
        if self.content is None:
            self.fail("Missing skill file: cert-audit")

    def test_file_exists_and_substantial(self):
        """cert-audit SKILL.md exists and has >100 lines."""
        line_count = len(self.content.strip().split("\n"))
        self.assertGreater(
            line_count, 100,
            f"cert-audit has only {line_count} lines — expected >100",
        )

    def test_six_failure_modes_defined(self):
        """cert-audit defines all 6 failure modes (CM-1 through CM-6)."""
        for i in range(1, 7):
            self.assertIn(
                f"CM-{i}",
                self.content,
                f"cert-audit missing failure mode CM-{i}",
            )

    def test_failure_mode_labels(self):
        """cert-audit has named labels for each failure mode."""
        expected_labels = [
            "CERT EXPIRED",
            "CERT EXPIRING SOON",
            "CERT NOT TRUSTED",
            "CERT WRONG DOMAIN",
            "CERT ROTATION FAILED",
            "MTLS HANDSHAKE FAILED",
        ]
        for label in expected_labels:
            self.assertIn(
                label,
                self.content,
                f"cert-audit missing failure mode label: {label}",
            )

    def test_auto_detection_section(self):
        """cert-audit has an auto-detection phase."""
        self.assertIn(
            "Auto-Detection",
            self.content,
            "cert-audit missing Auto-Detection section",
        )

    def test_auto_detection_platforms(self):
        """cert-audit auto-detection covers all 5 platforms."""
        platforms = [
            "PLATFORM A",
            "PLATFORM B",
            "PLATFORM C",
            "PLATFORM D",
            "PLATFORM E",
        ]
        for platform in platforms:
            self.assertIn(
                platform,
                self.content,
                f"cert-audit missing {platform} in auto-detection",
            )

    def test_five_investigation_layers(self):
        """cert-audit has all 5 investigation layers."""
        layers = [
            "LAYER 1",
            "LAYER 2",
            "LAYER 3",
            "LAYER 4",
            "LAYER 5",
        ]
        for layer in layers:
            self.assertIn(
                layer,
                self.content,
                f"cert-audit missing {layer}",
            )

    def test_slash_command(self):
        """cert-audit has /cert-audit slash command."""
        fm = extract_frontmatter(self.content)
        self.assertIn(
            "slash_command: /cert-audit",
            fm,
            "cert-audit missing slash_command: /cert-audit in frontmatter",
        )

    def test_sherlock_fallback(self):
        """cert-audit has Sherlock fallback section."""
        self.assertIn(
            "SHERLOCK FALLBACK",
            self.content,
            "cert-audit missing SHERLOCK FALLBACK section",
        )

    def test_blast_radius_section(self):
        """cert-audit has a blast radius check section."""
        self.assertIn(
            "Blast Radius",
            self.content,
            "cert-audit missing Blast Radius section",
        )

    def test_never_run_commands(self):
        """cert-audit has NEVER-run-commands constraint."""
        self.assertTrue(
            "NEVER run commands" in self.content or "NEVER run any commands" in self.content,
            "cert-audit missing 'NEVER run commands' constraint",
        )

    def test_expiry_timeline_section(self):
        """cert-audit has an expiry timeline section."""
        self.assertIn(
            "Expiry Timeline",
            self.content,
            "cert-audit missing Expiry Timeline section",
        )

    def test_cert_audit_report_output(self):
        """cert-audit has a CERT AUDIT REPORT output format."""
        self.assertIn(
            "CERT AUDIT REPORT",
            self.content,
            "cert-audit missing CERT AUDIT REPORT output format",
        )

    def test_cert_manager_coverage(self):
        """cert-audit covers cert-manager resources."""
        self.assertIn("cert-manager", self.content, "cert-audit must cover cert-manager")
        self.assertIn("CertificateRequest", self.content, "cert-audit must cover CertificateRequest")
        self.assertIn("Issuer", self.content, "cert-audit must cover Issuer")

    def test_istio_mtls_coverage(self):
        """cert-audit covers Istio mTLS."""
        self.assertIn("PeerAuthentication", self.content, "cert-audit must cover PeerAuthentication")
        self.assertIn("DestinationRule", self.content, "cert-audit must cover DestinationRule")
        self.assertIn("istiod", self.content, "cert-audit must cover istiod")

    def test_keyvault_certificate_coverage(self):
        """cert-audit covers Azure KeyVault certificates."""
        self.assertIn(
            "az keyvault certificate",
            self.content,
            "cert-audit must include az keyvault certificate commands",
        )

    def test_jvm_truststore_coverage(self):
        """cert-audit covers JVM truststore/keystore."""
        self.assertIn("javax.net.ssl", self.content, "cert-audit must cover javax.net.ssl")
        self.assertIn("keytool", self.content, "cert-audit must cover keytool")
        self.assertIn("PKIX", self.content, "cert-audit must cover PKIX")

    def test_openssl_commands(self):
        """cert-audit includes openssl commands for cert verification."""
        self.assertIn(
            "openssl",
            self.content,
            "cert-audit must include openssl commands",
        )

    def test_never_assume_platform_constraint(self):
        """cert-audit has NEVER-assume-platform constraint."""
        self.assertIn(
            "NEVER assume platform",
            self.content,
            "cert-audit missing 'NEVER assume platform' constraint",
        )


class TestK8sDebugStructure(unittest.TestCase):
    """Validate k8s-debug skill structure and content."""

    def setUp(self):
        self.content = read_skill("k8s-debug")
        if self.content is None:
            self.fail("Missing skill file: k8s-debug")

    def test_decision_tree_present(self):
        """k8s-debug has a decision tree section."""
        self.assertIn(
            "Decision Tree",
            self.content,
            "k8s-debug missing Decision Tree",
        )

    def test_investigation_layers_present(self):
        """k8s-debug has investigation layers (at least 5)."""
        layer_count = len(re.findall(r"Layer\s+\d+", self.content))
        self.assertGreaterEqual(
            layer_count, 5,
            f"k8s-debug has only {layer_count} layer references — expected >= 5",
        )

    def test_aks_gotchas_section(self):
        """k8s-debug has AKS-specific gotchas."""
        has_aks = (
            "AKS Gotchas" in self.content
            or "AKS-Specific" in self.content
            or "AKS gotcha" in self.content.lower()
        )
        self.assertTrue(has_aks, "k8s-debug missing AKS gotchas section")

    def test_spring_boot_gotchas_section(self):
        """k8s-debug has Spring Boot gotchas."""
        has_spring = (
            "Spring Boot" in self.content
            or "spring boot" in self.content.lower()
        )
        self.assertTrue(has_spring, "k8s-debug missing Spring Boot coverage")

    def test_no_file_write_constraint(self):
        """k8s-debug must have a constraint about never writing files."""
        has_no_write = (
            "NEVER stage or write files" in self.content
            or "NEVER stage" in self.content
            or "does NOT stage" in self.content
        )
        self.assertTrue(
            has_no_write,
            "k8s-debug missing no-file-write constraint (K-11)",
        )

    def test_command_output_interpretation(self):
        """k8s-debug has a command output interpretation guide."""
        has_interp = (
            "Output Interpretation" in self.content
            or "output interpretation" in self.content.lower()
            or "Command Output" in self.content
        )
        self.assertTrue(
            has_interp,
            "k8s-debug missing command output interpretation section",
        )

    def test_pod_status_coverage(self):
        """k8s-debug covers major pod status failure modes."""
        statuses = ["CrashLoopBackOff", "OOMKilled", "Pending", "ImagePullBackOff"]
        for status in statuses:
            self.assertIn(
                status,
                self.content,
                f"k8s-debug missing coverage of pod status: {status}",
            )


class TestPostmortemStructure(unittest.TestCase):
    """Validate postmortem skill structure and content."""

    def setUp(self):
        self.content = read_skill("postmortem")
        if self.content is None:
            self.fail("Missing skill file: postmortem")

    def test_mandatory_section_timeline(self):
        """Postmortem has Timeline of Events section."""
        self.assertIn(
            "Timeline of Events",
            self.content,
            "Postmortem missing Timeline of Events section",
        )

    def test_mandatory_section_contributing_factors(self):
        """Postmortem has Contributing Factors section."""
        self.assertIn(
            "Contributing Factors",
            self.content,
            "Postmortem missing Contributing Factors section",
        )

    def test_mandatory_section_mttr_mttd(self):
        """Postmortem has MTTR / MTTD Metrics section."""
        self.assertIn("MTTR", self.content, "Postmortem missing MTTR metric")
        self.assertIn("MTTD", self.content, "Postmortem missing MTTD metric")

    def test_mandatory_section_blast_radius(self):
        """Postmortem has Blast Radius / Services Affected section."""
        self.assertIn(
            "Blast Radius",
            self.content,
            "Postmortem missing Blast Radius section",
        )

    def test_mandatory_section_prevention_measures(self):
        """Postmortem has Prevention Measures section."""
        self.assertIn(
            "Prevention Measures",
            self.content,
            "Postmortem missing Prevention Measures section",
        )

    def test_no_file_creation_constraint(self):
        """Postmortem must state it never creates files."""
        self.assertIn(
            "NEVER create files",
            self.content,
            "Postmortem missing P-6 (NEVER create files) constraint",
        )

    def test_investigation_completeness_check(self):
        """Postmortem has an investigation completeness check gate."""
        has_check = (
            "Investigation Completeness" in self.content
            or "root cause not yet identified" in self.content.lower()
            or "Root cause not yet identified" in self.content
        )
        self.assertTrue(
            has_check,
            "Postmortem missing investigation completeness check",
        )

    def test_input_gathering_phase(self):
        """Postmortem has an input gathering phase before generating."""
        self.assertIn(
            "Input Gathering",
            self.content,
            "Postmortem missing Input Gathering phase",
        )

    def test_four_input_sources(self):
        """Postmortem defines 4 input sources: Chat, Sherlock, KB, User."""
        for source in ["Current Chat", "Sherlock", "HiveMind KB", "User"]:
            self.assertIn(
                source,
                self.content,
                f"Postmortem missing input source: {source}",
            )

    def test_priority_levels_defined(self):
        """Postmortem defines P1/P2/P3 priorities for prevention measures."""
        self.assertIn("P1", self.content, "Postmortem missing P1 priority level")
        self.assertIn("P2", self.content, "Postmortem missing P2 priority level")
        self.assertIn("P3", self.content, "Postmortem missing P3 priority level")

    def test_output_format_template(self):
        """Postmortem has an INCIDENT POSTMORTEM output format header."""
        self.assertIn(
            "INCIDENT POSTMORTEM",
            self.content,
            "Postmortem missing INCIDENT POSTMORTEM output format",
        )

    def test_sources_table_in_output(self):
        """Postmortem output format includes All Sources table."""
        self.assertIn(
            "All Sources",
            self.content,
            "Postmortem missing All Sources table in output format",
        )

    def test_banned_vague_words_rule(self):
        """Postmortem bans vague words like 'issues', 'opportunities'."""
        self.assertIn(
            "opportunities for improvement",
            self.content,
            "Postmortem should explicitly ban 'opportunities for improvement'",
        )

    def test_graceful_degradation(self):
        """Postmortem has a graceful degradation section."""
        has_degradation = (
            "Graceful Degradation" in self.content
            or "graceful degradation" in self.content.lower()
        )
        self.assertTrue(
            has_degradation,
            "Postmortem missing Graceful Degradation section",
        )


class TestIncidentTriageStructure(unittest.TestCase):
    """Validate incident-triage skill structure and content."""

    def setUp(self):
        self.content = read_skill("incident-triage")
        if self.content is None:
            self.fail("Missing skill file: incident-triage")

    def test_has_triage_phases(self):
        """incident-triage has investigation phases."""
        phase_count = len(re.findall(r"Phase\s+\d+|PHASE\s+\d+", self.content))
        self.assertGreaterEqual(
            phase_count, 3,
            f"incident-triage has only {phase_count} phases — expected >= 3",
        )

    def test_has_incident_type_playbooks(self):
        """incident-triage has playbooks for different incident types."""
        has_playbook = (
            "Playbook" in self.content
            or "playbook" in self.content.lower()
        )
        self.assertTrue(
            has_playbook,
            "incident-triage missing incident type playbooks",
        )

    def test_references_sibling_skills(self):
        """incident-triage references sibling skills or their domains for handoff."""
        # incident-triage should reference the domains handled by sibling skills
        # It may reference them by name or by their domain keywords
        sibling_checks = [
            ("secret-audit", ["secret", "keyvault", "secret-audit"]),
            ("k8s-debug", ["k8s", "kubernetes", "pod", "k8s-debug", "kubectl"]),
        ]
        for sibling_name, keywords in sibling_checks:
            found = any(kw.lower() in self.content.lower() for kw in keywords)
            self.assertTrue(
                found,
                f"incident-triage should reference sibling skill domain: {sibling_name} "
                f"(looked for: {keywords})",
            )


class TestDbDebugStructure(unittest.TestCase):
    """Validate db-debug skill structure and content."""

    def setUp(self):
        self.content = read_skill("db-debug")
        if self.content is None:
            self.fail("Missing skill file: db-debug")

    def test_file_exists_and_substantial(self):
        """db-debug SKILL.md exists and has >100 lines."""
        line_count = len(self.content.strip().split("\n"))
        self.assertGreater(
            line_count, 100,
            f"db-debug has only {line_count} lines -- expected >100",
        )

    def test_eight_failure_modes_defined(self):
        """db-debug defines all 8 failure modes (DB-1 through DB-8)."""
        for i in range(1, 9):
            self.assertIn(
                f"DB-{i}",
                self.content,
                f"db-debug missing failure mode DB-{i}",
            )

    def test_failure_mode_labels(self):
        """db-debug has named labels for each failure mode."""
        expected_labels = [
            "CONNECTION POOL EXHAUSTED",
            "SLOW QUERY",
            "MIGRATION FAILED",
            "DEADLOCK",
            "REPLICATION LAG",
            "PRIMARY FAILOVER",
            "SERVICE BUS DLQ",
            "SERVICE BUS PROCESSING FAILURE",
        ]
        for label in expected_labels:
            self.assertIn(
                label,
                self.content,
                f"db-debug missing failure mode label: {label}",
            )

    def test_auto_detection_section(self):
        """db-debug has an auto-detection phase."""
        self.assertIn(
            "Auto-Detection",
            self.content,
            "db-debug missing Auto-Detection section",
        )

    def test_auto_detection_platforms(self):
        """db-debug auto-detection covers all 6 platforms."""
        platforms = [
            "PLATFORM A", "PLATFORM B", "PLATFORM C",
            "PLATFORM D", "PLATFORM E", "PLATFORM F",
        ]
        for platform in platforms:
            self.assertIn(
                platform,
                self.content,
                f"db-debug missing auto-detection platform: {platform}",
            )

    def test_six_investigation_layers(self):
        """db-debug has all 6 investigation layers."""
        layers = ["LAYER 1", "LAYER 2", "LAYER 3", "LAYER 4", "LAYER 5", "LAYER 6"]
        for layer in layers:
            self.assertIn(
                layer,
                self.content,
                f"db-debug missing investigation layer: {layer}",
            )

    def test_slash_command(self):
        """db-debug has /db slash command."""
        fm = extract_frontmatter(self.content)
        self.assertIn(
            "slash_command: /db",
            fm,
            "db-debug missing slash_command: /db in frontmatter",
        )

    def test_sherlock_fallback(self):
        """db-debug has Sherlock fallback section with Path A and Path B."""
        self.assertIn(
            "SHERLOCK FALLBACK",
            self.content,
            "db-debug missing SHERLOCK FALLBACK section",
        )
        self.assertIn("Path A", self.content, "db-debug missing Path A")
        self.assertIn("Path B", self.content, "db-debug missing Path B")

    def test_blast_radius_section(self):
        """db-debug has a blast radius check section."""
        self.assertIn(
            "Blast Radius",
            self.content,
            "db-debug missing Blast Radius section",
        )

    def test_never_run_commands(self):
        """db-debug has NEVER-run-commands constraint."""
        self.assertTrue(
            "NEVER run commands" in self.content or "NEVER run any commands" in self.content,
            "db-debug missing 'NEVER run commands' constraint",
        )

    def test_hikaricp_section(self):
        """db-debug covers HikariCP connection pool."""
        self.assertIn(
            "HikariCP",
            self.content,
            "db-debug missing HikariCP coverage",
        )
        self.assertIn(
            "maximum-pool-size",
            self.content,
            "db-debug missing maximum-pool-size config reference",
        )

    def test_service_bus_section(self):
        """db-debug covers Azure Service Bus."""
        self.assertIn(
            "Service Bus",
            self.content,
            "db-debug missing Service Bus coverage",
        )
        self.assertIn(
            "Dead Letter",
            self.content,
            "db-debug missing Dead Letter Queue coverage",
        )

    def test_spring_boot_gotchas(self):
        """db-debug has Spring Boot / JVM gotchas section."""
        self.assertTrue(
            "Spring Boot" in self.content and "Gotcha" in self.content,
            "db-debug missing Spring Boot gotchas section",
        )

    def test_postgresql_commands(self):
        """db-debug includes PostgreSQL diagnostic commands."""
        self.assertIn(
            "pg_stat_activity",
            self.content,
            "db-debug missing pg_stat_activity reference",
        )
        self.assertIn(
            "pg_stat_statements",
            self.content,
            "db-debug missing pg_stat_statements reference",
        )

    def test_references_impact_analysis(self):
        """db-debug references hivemind_impact_analysis."""
        self.assertIn(
            "hivemind_impact_analysis",
            self.content,
            "db-debug missing hivemind_impact_analysis reference",
        )

    def test_references_get_secret_flow(self):
        """db-debug references hivemind_get_secret_flow."""
        self.assertIn(
            "hivemind_get_secret_flow",
            self.content,
            "db-debug missing hivemind_get_secret_flow reference",
        )

    def test_db_debug_report_output(self):
        """db-debug has a DB DEBUG REPORT output format."""
        self.assertIn(
            "DB DEBUG REPORT",
            self.content,
            "db-debug missing DB DEBUG REPORT output format",
        )

    def test_never_assume_platform_constraint(self):
        """db-debug has NEVER assume constraint."""
        self.assertTrue(
            "NEVER assume PostgreSQL" in self.content
            or "NEVER assume" in self.content,
            "db-debug missing 'NEVER assume' platform constraint",
        )

    def test_generic_messaging_alternatives(self):
        """db-debug has generic messaging alternatives (SQS, Kafka, RabbitMQ)."""
        for platform in ["SQS", "Kafka", "RabbitMQ"]:
            self.assertIn(
                platform,
                self.content,
                f"db-debug missing generic messaging alternative: {platform}",
            )

    def test_connection_pool_variants(self):
        """db-debug covers multiple connection pool technologies."""
        for pool in ["HikariCP", "c3p0", "DBCP2", "pg-pool", "SQLAlchemy"]:
            self.assertIn(
                pool,
                self.content,
                f"db-debug missing connection pool variant: {pool}",
            )

    def test_migration_tool_variants(self):
        """db-debug covers multiple migration tools."""
        for tool in ["Flyway", "Liquibase", "Alembic"]:
            self.assertIn(
                tool,
                self.content,
                f"db-debug missing migration tool variant: {tool}",
            )


class TestPerfDebugStructure(unittest.TestCase):
    """Validate perf-debug skill structure and content."""

    def setUp(self):
        self.content = read_skill("perf-debug")
        if self.content is None:
            self.fail("Missing skill file: perf-debug")

    def test_file_exists_and_substantial(self):
        """perf-debug SKILL.md exists and has >100 lines."""
        line_count = len(self.content.strip().split("\n"))
        self.assertGreater(
            line_count, 100,
            f"perf-debug has only {line_count} lines -- expected >100",
        )

    def test_eight_failure_modes_defined(self):
        """perf-debug defines all 8 failure modes (PF-1 through PF-8)."""
        for i in range(1, 9):
            self.assertIn(
                f"PF-{i}",
                self.content,
                f"perf-debug missing failure mode PF-{i}",
            )

    def test_failure_mode_labels(self):
        """perf-debug has named labels for each failure mode."""
        expected_labels = [
            "LATENCY DEGRADATION",
            "THROUGHPUT DROP",
            "MEMORY LEAK",
            "CPU THROTTLING",
            "GC PRESSURE",
            "THREAD EXHAUSTION",
            "DEPENDENCY SLOWDOWN",
            "RESOURCE SATURATION",
        ]
        for label in expected_labels:
            self.assertIn(
                label,
                self.content,
                f"perf-debug missing failure mode label: {label}",
            )

    def test_golden_signals_section(self):
        """perf-debug has a Golden Signals section."""
        self.assertIn(
            "Golden Signals",
            self.content,
            "perf-debug missing Golden Signals section",
        )

    def test_golden_signals_four_signals(self):
        """perf-debug Golden Signals covers latency, traffic, errors, saturation."""
        for signal in ["Latency", "Traffic", "Errors", "Saturation"]:
            self.assertIn(
                signal,
                self.content,
                f"perf-debug Golden Signals missing signal: {signal}",
            )

    def test_sherlock_first_approach(self):
        """perf-debug has a Sherlock-first approach section."""
        self.assertIn(
            "Sherlock-First",
            self.content,
            "perf-debug missing Sherlock-First Approach section",
        )

    def test_eight_investigation_layers(self):
        """perf-debug has all 8 investigation layers."""
        layers = [
            "LAYER 1", "LAYER 2", "LAYER 3", "LAYER 4",
            "LAYER 5", "LAYER 6", "LAYER 7", "LAYER 8",
        ]
        for layer in layers:
            self.assertIn(
                layer,
                self.content,
                f"perf-debug missing investigation layer: {layer}",
            )

    def test_slash_command(self):
        """perf-debug has /perf slash command."""
        fm = extract_frontmatter(self.content)
        self.assertIn(
            "slash_command: /perf",
            fm,
            "perf-debug missing slash_command: /perf in frontmatter",
        )

    def test_sherlock_fallback(self):
        """perf-debug has Sherlock fallback section with Path A and Path B."""
        self.assertIn(
            "SHERLOCK FALLBACK",
            self.content,
            "perf-debug missing SHERLOCK FALLBACK section",
        )
        self.assertIn("Path A", self.content, "perf-debug missing Path A")
        self.assertIn("Path B", self.content, "perf-debug missing Path B")

    def test_blast_radius_section(self):
        """perf-debug has a blast radius check section."""
        self.assertIn(
            "Blast Radius",
            self.content,
            "perf-debug missing Blast Radius section",
        )

    def test_change_correlation_section(self):
        """perf-debug has a change correlation section."""
        self.assertIn(
            "Change Correlation",
            self.content,
            "perf-debug missing Change Correlation section",
        )

    def test_jvm_spring_boot_section(self):
        """perf-debug has a JVM / Spring Boot section."""
        self.assertIn(
            "Spring Boot",
            self.content,
            "perf-debug missing Spring Boot section",
        )
        self.assertIn(
            "JVM",
            self.content,
            "perf-debug missing JVM section",
        )

    def test_never_run_commands(self):
        """perf-debug has NEVER-run-commands constraint."""
        self.assertTrue(
            "NEVER run commands" in self.content or "NEVER run any commands" in self.content,
            "perf-debug missing 'NEVER run commands' constraint",
        )

    def test_never_skip_sherlock(self):
        """perf-debug has NEVER-skip-Sherlock constraint."""
        self.assertIn(
            "NEVER skip Sherlock",
            self.content,
            "perf-debug missing 'NEVER skip Sherlock' constraint",
        )

    def test_never_heap_dump_without_approval(self):
        """perf-debug has NEVER-heap-dump-without-approval constraint."""
        self.assertTrue(
            "NEVER recommend heap dump without explicit user approval" in self.content
            or "heap dump" in self.content.lower() and "approval" in self.content.lower(),
            "perf-debug missing heap dump approval constraint",
        )

    def test_references_impact_analysis(self):
        """perf-debug references hivemind_impact_analysis."""
        self.assertIn(
            "hivemind_impact_analysis",
            self.content,
            "perf-debug missing hivemind_impact_analysis reference",
        )

    def test_references_diff_branches(self):
        """perf-debug references hivemind_diff_branches."""
        self.assertIn(
            "hivemind_diff_branches",
            self.content,
            "perf-debug missing hivemind_diff_branches reference",
        )

    def test_perf_debug_report_output(self):
        """perf-debug has a PERF DEBUG REPORT output format."""
        self.assertIn(
            "PERF DEBUG REPORT",
            self.content,
            "perf-debug missing PERF DEBUG REPORT output format",
        )

    def test_decision_matrix(self):
        """perf-debug has a decision matrix for Golden Signals to failure mode."""
        self.assertIn(
            "Decision Matrix",
            self.content,
            "perf-debug missing Decision Matrix section",
        )

    def test_actuator_endpoints(self):
        """perf-debug covers Spring Boot Actuator endpoints."""
        self.assertIn(
            "/actuator/metrics",
            self.content,
            "perf-debug missing Actuator metrics endpoint reference",
        )

    def test_gc_types_coverage(self):
        """perf-debug covers GC types (Minor, Major, Full)."""
        for gc_type in ["Minor GC", "Major GC", "Full GC"]:
            self.assertIn(
                gc_type,
                self.content,
                f"perf-debug missing GC type coverage: {gc_type}",
            )

    def test_non_jvm_platforms(self):
        """perf-debug covers non-JVM platforms (Node.js, Python, Go)."""
        for platform in ["Node.js", "Python", "Go"]:
            self.assertIn(
                platform,
                self.content,
                f"perf-debug missing non-JVM platform coverage: {platform}",
            )

    def test_never_diagnose_hard_failure(self):
        """perf-debug has constraint to redirect hard failures."""
        self.assertIn(
            "NEVER diagnose hard failure",
            self.content,
            "perf-debug missing PD-10 constraint (redirect hard failures)",
        )

    def test_mandatory_sherlock_queries(self):
        """perf-debug lists mandatory Sherlock queries (S-1 through S-8)."""
        for i in range(1, 9):
            self.assertIn(
                f"S-{i}",
                self.content,
                f"perf-debug missing mandatory Sherlock query S-{i}",
            )

    def test_failure_mode_sherlock_signals(self):
        """Each failure mode playbook has Sherlock-related investigation guidance."""
        # Each PF playbook should reference how to confirm via observability
        for i in range(1, 9):
            self.assertIn(
                f"PF-{i}:",
                self.content,
                f"perf-debug missing playbook header PF-{i}:",
            )


class TestCrossSkillConsistency(unittest.TestCase):
    """Validate consistency across all skills."""

    SKILLS = ["incident-triage", "k8s-debug", "secret-audit", "postmortem", "cert-audit", "db-debug", "perf-debug"]

    def test_all_skills_mention_hivemind(self):
        """All skills reference HiveMind tools or KB."""
        for skill_name in self.SKILLS:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            has_hivemind = (
                "hivemind_" in content
                or "HiveMind" in content
            )
            self.assertTrue(
                has_hivemind,
                f"Skill {skill_name} does not reference HiveMind",
            )

    def test_all_skills_mention_avd_or_commands(self):
        """All investigation skills mention AVD limitation or command recommendations."""
        for skill_name in ["k8s-debug", "secret-audit", "postmortem", "cert-audit", "db-debug", "perf-debug"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            has_avd = (
                "AVD" in content
                or "jump host" in content
                or "NEVER run commands" in content
            )
            self.assertTrue(
                has_avd,
                f"Skill {skill_name} does not mention AVD / jump host / command restriction",
            )

    def test_no_trigger_collision_postmortem_vs_triage(self):
        """postmortem triggers must NOT overlap with incident-triage triggers."""
        postmortem_fm = extract_frontmatter(read_skill("postmortem") or "")
        triage_fm = extract_frontmatter(read_skill("incident-triage") or "")

        postmortem_triggers = set(
            t.strip().strip('"').strip("'").lower()
            for t in re.findall(r"^\s+-\s+(.+)$", postmortem_fm, re.MULTILINE)
        )
        triage_triggers = set(
            t.strip().strip('"').strip("'").lower()
            for t in re.findall(r"^\s+-\s+(.+)$", triage_fm, re.MULTILINE)
        )

        # Postmortem should not share any triggers with triage
        overlap = postmortem_triggers & triage_triggers
        # Filter out lines that are actually metadata, not triggers
        real_overlap = {t for t in overlap if not t.startswith("name:") and not t.startswith("description")}
        self.assertEqual(
            len(real_overlap),
            0,
            f"Postmortem and incident-triage share these triggers (collision): {real_overlap}",
        )


class TestCopilotInstructionsSection8(unittest.TestCase):
    """Validate copilot-instructions.md Section 8 exists and has required subsections."""

    def setUp(self):
        path = PROJECT_ROOT / ".github" / "copilot-instructions.md"
        if not path.exists():
            self.fail("Missing .github/copilot-instructions.md")
        self.content = path.read_text(encoding="utf-8")

    def test_section_8_exists(self):
        """copilot-instructions.md has Section 8 (Automatic Incident Investigation Trigger)."""
        self.assertIn(
            "Automatic Incident Investigation Trigger",
            self.content,
            "copilot-instructions.md missing Section 8: Automatic Incident Investigation Trigger",
        )

    def test_section_8_trigger_conditions(self):
        """Section 8.1 defines trigger conditions."""
        self.assertIn(
            "Trigger Conditions",
            self.content,
            "Section 8 missing subsection 8.1: Trigger Conditions",
        )

    def test_section_8_mandatory_sequence(self):
        """Section 8.2 defines mandatory automatic sequence."""
        self.assertIn(
            "Mandatory Automatic Sequence",
            self.content,
            "Section 8 missing subsection 8.2: Mandatory Automatic Sequence",
        )

    def test_section_8_never_rules(self):
        """Section 8.3 defines NEVER rules."""
        self.assertIn(
            "NEVER Do These on Incident Paste",
            self.content,
            "Section 8 missing subsection 8.3: NEVER rules",
        )

    def test_section_8_agent_routing(self):
        """Section 8.4 defines agent routing protocol."""
        self.assertIn(
            "Agent Routing Protocol",
            self.content,
            "Section 8 missing subsection 8.4: Agent Routing Protocol",
        )

    def test_section_8_output_format(self):
        """Section 8.5 defines output format."""
        self.assertIn(
            "Output Format for Automatic Investigations",
            self.content,
            "Section 8 missing subsection 8.5: Output Format",
        )

    def test_section_8_graceful_degradation(self):
        """Section 8.6 defines graceful degradation."""
        self.assertIn(
            "Graceful Degradation",
            self.content,
            "Section 8 missing subsection 8.6: Graceful Degradation",
        )

    def test_section_8_keyword_triggers(self):
        """Section 8.1 includes critical keyword triggers."""
        keywords = ["CrashLoopBackOff", "OOMKilled", "probe failed", "connection refused"]
        for kw in keywords:
            self.assertIn(
                kw,
                self.content,
                f"Section 8 missing keyword trigger: {kw}",
            )


if __name__ == "__main__":
    unittest.main()
