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
        for skill_name in ["k8s-debug", "secret-audit", "postmortem"]:
            content = read_skill(skill_name)
            if content is None:
                self.fail(f"Missing skill file: {skill_name}")
            self.assertTrue(
                "NEVER run commands" in content or "NEVER run any commands" in content,
                f"Skill {skill_name}: missing 'NEVER run commands' constraint",
            )

    def test_never_block_on_sherlock_constraint(self):
        """Investigation skills must have a NEVER-block-on-Sherlock constraint."""
        for skill_name in ["k8s-debug", "secret-audit"]:
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
        for skill_name in ["k8s-debug", "secret-audit", "postmortem"]:
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

    INVESTIGATION_SKILLS = ["k8s-debug", "secret-audit", "postmortem"]

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
        for skill_name in ["k8s-debug", "secret-audit"]:
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
        for skill_name in ["k8s-debug", "secret-audit"]:
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


class TestCrossSkillConsistency(unittest.TestCase):
    """Validate consistency across all skills."""

    SKILLS = ["incident-triage", "k8s-debug", "secret-audit", "postmortem"]

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
        for skill_name in ["k8s-debug", "secret-audit", "postmortem"]:
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
