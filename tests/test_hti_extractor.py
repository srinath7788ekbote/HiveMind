"""
Tests for HTI Extractor — tests written BEFORE implementation (TDD).

Validates:
    - extract YAML dict -> correct skeleton structure
    - extract YAML list -> correct _length and _sample
    - extract nested YAML (Harness pipeline with 3+ depth) -> correct paths
    - max_depth truncation -> nodes beyond max_depth get _truncated flag
    - large array (>10 items) -> only first 3 + last 1 in _sample
    - leaf values -> only _preview (80 chars max), not full value
    - node_paths are unique and correct for every node
    - extract_yaml_tree returns (skeleton, nodes) tuple
    - nodes list contains all addressable nodes with correct depth
    - detect_file_type returns correct types
    - HCL/Terraform extraction basics
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixture YAML: Harness pipeline with realistic structure
# ---------------------------------------------------------------------------

HARNESS_PIPELINE_YAML = """
pipeline:
  name: presentation-service-deploy
  identifier: presentation_service_deploy
  projectIdentifier: newAd
  orgIdentifier: default
  stages:
    - stage:
        name: Build
        identifier: Build
        type: CI
        spec:
          execution:
            steps:
              - step:
                  name: Compile
                  identifier: compile
                  type: Run
                  spec:
                    command: mvn clean package
    - stage:
        name: Deploy Dev
        identifier: Deploy_Dev
        type: Deployment
        spec:
          execution:
            steps:
              - step:
                  name: Rollout
                  identifier: rollout
                  type: K8sRollingDeploy
                  spec:
                    skipDryRun: false
              - step:
                  name: Verify
                  identifier: verify
                  type: Verify
                  spec:
                    type: Rolling
    - stage:
        name: Approval
        identifier: Approval
        type: Approval
        spec:
          approvalType: HarnessApproval
  variables:
    - name: serviceVersion
      type: String
      value: "1.0.0"
    - name: environment
      type: String
      value: dev
"""

SIMPLE_YAML = """
name: test
version: 1
enabled: true
description: "A simple test configuration with a fairly long description that might need truncation at eighty characters"
"""

LARGE_ARRAY_YAML = """
items:
  - name: item0
    value: zero
  - name: item1
    value: one
  - name: item2
    value: two
  - name: item3
    value: three
  - name: item4
    value: four
  - name: item5
    value: five
  - name: item6
    value: six
  - name: item7
    value: seven
  - name: item8
    value: eight
  - name: item9
    value: nine
  - name: item10
    value: ten
  - name: item11
    value: eleven
"""

TERRAFORM_HCL = """
variable "environment" {
  type    = string
  default = "dev"
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.environment}"
  location = "eastus2"
}

output "resource_group_id" {
  value = azurerm_resource_group.main.id
}
"""

NESTED_YAML = """
root_key:
  level1:
    level2:
      level3:
        level4:
          level5:
            level6:
              level7:
                level8:
                  level9:
                    deep_value: "found it"
"""

NULL_VALUE_YAML = """
database:
  host: localhost
  port: 5432
  password: null
  ssl: true
"""


# ---------------------------------------------------------------------------
# detect_file_type tests
# ---------------------------------------------------------------------------

class TestDetectFileType(unittest.TestCase):
    """Test file type detection."""

    def test_harness_by_path_pipeline(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("newad/cd/cd_deploy_env/pipeline.yaml"), "harness")

    def test_harness_by_path_harness(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type(".harness/pipelines/build.yaml"), "harness")

    def test_harness_by_content(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(
            detect_file_type("config.yaml", content="pipeline:\n  name: test"),
            "harness",
        )

    def test_terraform_tf_extension(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("layer_01/main.tf"), "terraform")

    def test_terraform_hcl_extension(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("config.hcl"), "terraform")

    def test_helm_by_charts_path(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("charts/audit-service/values.yaml"), "helm")

    def test_helm_by_values_path(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("values.yaml"), "helm")

    def test_helm_by_content(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(
            detect_file_type("config.yaml", content="replicaCount: 3\nimage: test"),
            "helm",
        )

    def test_generic_fallback(self):
        from hivemind_mcp.hti.utils import detect_file_type
        self.assertEqual(detect_file_type("random/config.yaml"), "generic")


# ---------------------------------------------------------------------------
# extract_yaml_tree tests
# ---------------------------------------------------------------------------

class TestExtractYAMLDict(unittest.TestCase):
    """Test YAML dict extraction -> correct skeleton structure."""

    def test_returns_tuple(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            result = extract_yaml_tree(f.name)
        os.unlink(f.name)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_skeleton_is_object_at_root(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        self.assertEqual(skeleton["_type"], "object")
        self.assertEqual(skeleton["_path"], "root")

    def test_skeleton_has_keys(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        self.assertIn("_keys", skeleton)
        self.assertIn("name", skeleton["_keys"])
        self.assertIn("version", skeleton["_keys"])
        self.assertIn("enabled", skeleton["_keys"])

    def test_leaf_has_preview(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        name_node = skeleton["_children"]["name"]
        self.assertEqual(name_node["_type"], "str")
        self.assertEqual(name_node["_preview"], "test")

    def test_leaf_preview_truncated_to_80_chars(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        desc = skeleton["_children"]["description"]
        self.assertLessEqual(len(desc["_preview"]), 80)

    def test_nodes_list_populated(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        self.assertGreater(len(nodes), 0)

    def test_nodes_have_required_keys(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        for node in nodes:
            self.assertIn("node_path", node)
            self.assertIn("depth", node)
            self.assertIn("content_json", node)


class TestExtractYAMLList(unittest.TestCase):
    """Test YAML list extraction -> correct _length and _sample."""

    def test_large_array_has_length(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(LARGE_ARRAY_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        items = skeleton["_children"]["items"]
        self.assertEqual(items["_type"], "array")
        self.assertEqual(items["_length"], 12)

    def test_large_array_sample_is_first3_last1(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(LARGE_ARRAY_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        items = skeleton["_children"]["items"]
        self.assertEqual(items["_sample"], [0, 1, 2, 11])

    def test_small_array_includes_all(self):
        """Array with <= 10 items should include all indices in _sample."""
        yaml_content = """
items:
  - a
  - b
  - c
"""
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        items = skeleton["_children"]["items"]
        self.assertEqual(items["_length"], 3)
        self.assertEqual(items["_sample"], [0, 1, 2])


class TestExtractNestedYAML(unittest.TestCase):
    """Test nested YAML (Harness pipeline with 3+ stage depth)."""

    def test_harness_pipeline_stages_is_array(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(HARNESS_PIPELINE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        stages = skeleton["_children"]["pipeline"]["_children"]["stages"]
        self.assertEqual(stages["_type"], "array")
        self.assertEqual(stages["_length"], 3)

    def test_harness_pipeline_paths_are_correct(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(HARNESS_PIPELINE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        # Check pipeline path
        pipeline = skeleton["_children"]["pipeline"]
        self.assertEqual(pipeline["_path"], "root.pipeline")
        # Check stages path
        stages = pipeline["_children"]["stages"]
        self.assertEqual(stages["_path"], "root.pipeline.stages")

    def test_node_paths_are_unique(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(HARNESS_PIPELINE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        paths = [n["node_path"] for n in nodes]
        self.assertEqual(len(paths), len(set(paths)), "Node paths must be unique")

    def test_all_nodes_have_correct_depth(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(HARNESS_PIPELINE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        for node in nodes:
            # Depth should match the number of dots/brackets in the path
            path = node["node_path"]
            expected_depth = path.count(".") + path.count("[")
            self.assertEqual(
                node["depth"], expected_depth,
                f"Node {path} depth {node['depth']} != expected {expected_depth}",
            )

    def test_deep_node_content_is_valid_json(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(HARNESS_PIPELINE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        for node in nodes:
            try:
                json.loads(node["content_json"])
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON in node {node['node_path']}")


class TestMaxDepthTruncation(unittest.TestCase):
    """Test max_depth truncation -> nodes beyond max_depth get _truncated flag."""

    def test_truncated_at_max_depth(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(NESTED_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name, max_depth=4)
        os.unlink(f.name)
        # Walk to depth 4 and check truncation
        node = skeleton
        for key in ["root_key", "level1", "level2", "level3"]:
            node = node["_children"][key]
        # level4 should be truncated (depth 5 > max_depth 4)
        level4 = node["_children"]["level4"]
        self.assertEqual(level4["_type"], "truncated")


class TestNullValues(unittest.TestCase):
    """Test null/None values in YAML."""

    def test_null_value_type(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(NULL_VALUE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        password = skeleton["_children"]["database"]["_children"]["password"]
        self.assertEqual(password["_type"], "null")


class TestExtractHCLTree(unittest.TestCase):
    """Test HCL/Terraform file extraction."""

    def test_extract_hcl_returns_tuple(self):
        from hivemind_mcp.hti.extractor import extract_hcl_tree
        with tempfile.NamedTemporaryFile(suffix=".tf", mode="w", delete=False, encoding="utf-8") as f:
            f.write(TERRAFORM_HCL)
            f.flush()
            try:
                result = extract_hcl_tree(f.name)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 2)
            except ImportError:
                # python-hcl2 not installed — acceptable
                self.skipTest("python-hcl2 not installed")
        os.unlink(f.name)

    def test_extract_hcl_skeleton_is_object(self):
        from hivemind_mcp.hti.extractor import extract_hcl_tree
        with tempfile.NamedTemporaryFile(suffix=".tf", mode="w", delete=False, encoding="utf-8") as f:
            f.write(TERRAFORM_HCL)
            f.flush()
            try:
                skeleton, nodes = extract_hcl_tree(f.name)
                self.assertEqual(skeleton["_type"], "object")
                self.assertEqual(skeleton["_path"], "root")
            except ImportError:
                self.skipTest("python-hcl2 not installed")
        os.unlink(f.name)


class TestExtractYAMLTreeEdgeCases(unittest.TestCase):
    """Edge cases for YAML extraction."""

    def test_empty_file_returns_empty(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write("")
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        # Should return a minimal skeleton, not crash
        self.assertIsInstance(skeleton, dict)
        self.assertIsInstance(nodes, list)

    def test_invalid_yaml_returns_error(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write("invalid: yaml: [broken: {")
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        # Should handle gracefully — return error skeleton or empty
        self.assertIsInstance(skeleton, dict)

    def test_nonexistent_file_returns_error(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        skeleton, nodes = extract_yaml_tree("/nonexistent/file.yaml")
        self.assertIsInstance(skeleton, dict)
        self.assertIn("_error", skeleton)

    def test_bool_leaf_type(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        enabled = skeleton["_children"]["enabled"]
        self.assertEqual(enabled["_type"], "bool")

    def test_int_leaf_type(self):
        from hivemind_mcp.hti.extractor import extract_yaml_tree
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SIMPLE_YAML)
            f.flush()
            skeleton, nodes = extract_yaml_tree(f.name)
        os.unlink(f.name)
        version = skeleton["_children"]["version"]
        self.assertEqual(version["_type"], "int")


if __name__ == "__main__":
    unittest.main()
