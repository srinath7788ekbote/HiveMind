"""
test_agent_files.py -- Validates .github/agents and .github/skills structure.

Ensures all agent files have correct frontmatter, all skill files exist,
and all handoff targets reference existing agent files.
"""

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestAgentFiles(unittest.TestCase):
    """Validate .github/agents/*.agent.md files."""

    AGENTS_DIR = PROJECT_ROOT / ".github" / "agents"
    SKILLS_DIR = PROJECT_ROOT / ".github" / "skills"

    EXPECTED_AGENTS = [
        "hivemind-team-lead",
        "hivemind-devops",
        "hivemind-architect",
        "hivemind-security",
        "hivemind-investigator",
        "hivemind-analyst",
        "hivemind-planner",
    ]

    EXPECTED_SKILLS = [
        "query-memory",
        "query-graph",
        "get-entity",
        "search-files",
        "get-pipeline",
        "get-secret-flow",
        "impact-analysis",
        "diff-branches",
        "list-branches",
        "incident-triage",
        "k8s-debug",
        "secret-audit",
        "postmortem",
    ]

    def test_all_agent_files_exist(self):
        """Every expected agent has a .agent.md file."""
        for name in self.EXPECTED_AGENTS:
            path = self.AGENTS_DIR / f"{name}.agent.md"
            self.assertTrue(path.exists(), f"Missing agent file: {path}")

    def test_agent_frontmatter_has_required_fields(self):
        """Each agent file has name, description, tools, handoffs in frontmatter."""
        required = ["name:", "description:", "tools:", "handoffs:"]
        for name in self.EXPECTED_AGENTS:
            path = self.AGENTS_DIR / f"{name}.agent.md"
            if not path.exists():
                self.fail(f"Missing agent file: {path}")
            content = path.read_text(encoding="utf-8")
            # Frontmatter is between --- markers
            self.assertTrue(content.startswith("---"), f"{name}: missing frontmatter start")
            end = content.index("---", 3)
            frontmatter = content[3:end]
            for field in required:
                self.assertIn(field, frontmatter, f"{name}: missing {field} in frontmatter")

    def test_all_skill_files_exist(self):
        """Every expected skill has a SKILL.md file."""
        for name in self.EXPECTED_SKILLS:
            path = self.SKILLS_DIR / name / "SKILL.md"
            self.assertTrue(path.exists(), f"Missing skill file: {path}")

    def test_skill_files_reference_existing_tools(self):
        """Each skill's SKILL.md references a python tool that exists."""
        tool_pattern = re.compile(r"python\s+tools/(\w+)\.py")
        for name in self.EXPECTED_SKILLS:
            path = self.SKILLS_DIR / name / "SKILL.md"
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            matches = tool_pattern.findall(content)
            for tool_name in matches:
                tool_path = PROJECT_ROOT / "tools" / f"{tool_name}.py"
                self.assertTrue(
                    tool_path.exists(),
                    f"Skill {name} references tools/{tool_name}.py but it does not exist",
                )

    def test_copilot_instructions_exists(self):
        """copilot-instructions.md exists and has required sections."""
        path = PROJECT_ROOT / ".github" / "copilot-instructions.md"
        self.assertTrue(path.exists(), "Missing .github/copilot-instructions.md")
        content = path.read_text(encoding="utf-8")
        required_sections = [
            "PRIME DIRECTIVE",
            "Anti-Hallucination",
            "Branch Awareness",
            "Client Architecture",
            "MCP Tool Calling",
            "Response Format",
            "Agent Roster",
        ]
        for section in required_sections:
            self.assertIn(
                section, content, f"copilot-instructions.md missing section: {section}"
            )

    def test_handoff_targets_exist(self):
        """Every handoff agent: target refers to an existing agent file."""
        existing_agents = {
            f.stem.replace(".agent", "")
            for f in self.AGENTS_DIR.glob("*.agent.md")
        }
        agent_pattern = re.compile(r"^\s+agent:\s+(.+)$", re.MULTILINE)
        for agent_file in self.AGENTS_DIR.glob("*.agent.md"):
            content = agent_file.read_text(encoding="utf-8")
            targets = agent_pattern.findall(content)
            for target in targets:
                target = target.strip()
                self.assertIn(
                    target,
                    existing_agents,
                    f"{agent_file.name}: handoff target '{target}' has no matching agent file",
                )


if __name__ == "__main__":
    unittest.main()
