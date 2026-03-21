"""
Tests for HTI MCP Tools — hivemind_hti_get_skeleton and hivemind_hti_fetch_nodes

Validates:
    - hti_get_skeleton returns correct structure when DB has data
    - hti_get_skeleton returns empty list gracefully when no data indexed
    - hti_get_skeleton filters by file_type correctly
    - hti_get_skeleton filters by repo correctly
    - hti_fetch_nodes returns full content for valid node_paths
    - hti_fetch_nodes handles missing node_paths gracefully
    - hti_fetch_nodes returns found: false for invalid paths
    - Both tools registered in MCP server
    - Tool count in server updated correctly
"""

import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestHTIToolsRegistered(unittest.TestCase):
    """Verify HTI tools are registered in the MCP server."""

    def test_hti_get_skeleton_registered(self):
        """hivemind_hti_get_skeleton is in TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertIn("hivemind_hti_get_skeleton", TOOL_REGISTRY)

    def test_hti_fetch_nodes_registered(self):
        """hivemind_hti_fetch_nodes is in TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertIn("hivemind_hti_fetch_nodes", TOOL_REGISTRY)

    def test_total_tool_count_is_21(self):
        """TOOL_REGISTRY contains exactly 21 tools with HTI additions."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertEqual(len(TOOL_REGISTRY), 21)

    def test_hti_tools_are_callable(self):
        """Both HTI tools are callable async functions."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        import inspect
        for name in ["hivemind_hti_get_skeleton", "hivemind_hti_fetch_nodes"]:
            fn = TOOL_REGISTRY[name]
            self.assertTrue(callable(fn), f"{name} is not callable")
            self.assertTrue(
                inspect.iscoroutinefunction(fn),
                f"{name} is not async",
            )


class TestHTIGetSkeletonWithData(unittest.TestCase):
    """Test hti_get_skeleton with pre-populated DB data."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_hti_test_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True)

        # Create and populate hti.sqlite
        self.db_path = self.memory_dir / "hti.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        schema_sql = (PROJECT_ROOT / "hivemind_mcp" / "hti" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Insert test skeleton
        skeleton = {
            "_type": "object",
            "_path": "root",
            "_keys": ["pipeline"],
            "_children": {
                "pipeline": {
                    "_type": "object",
                    "_path": "root.pipeline",
                    "_keys": ["name", "stages"],
                    "_children": {
                        "name": {"_type": "str", "_path": "root.pipeline.name", "_preview": "test-deploy"},
                        "stages": {
                            "_type": "array",
                            "_path": "root.pipeline.stages",
                            "_length": 2,
                            "_sample": [0, 1],
                            "_children": {},
                        },
                    },
                },
            },
        }

        conn.execute(
            """INSERT INTO hti_skeletons
               (id, client, repo, branch, file_path, file_type, skeleton_json, node_count, mtime_epoch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("testclient:test-repo:main:pipeline.yaml", "testclient", "test-repo",
             "main", "pipeline.yaml", "harness", json.dumps(skeleton), 5, 1000000),
        )

        # Insert a second skeleton (terraform type)
        tf_skeleton = {
            "_type": "object", "_path": "root", "_keys": ["resource"],
            "_children": {"resource": {"_type": "object", "_path": "root.resource", "_keys": ["main"], "_children": {}}},
        }
        conn.execute(
            """INSERT INTO hti_skeletons
               (id, client, repo, branch, file_path, file_type, skeleton_json, node_count, mtime_epoch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("testclient:tf-repo:main:main.tf", "testclient", "tf-repo",
             "main", "main.tf", "terraform", json.dumps(tf_skeleton), 2, 1000000),
        )

        # Insert test nodes
        conn.execute(
            """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
               VALUES (?, ?, ?, ?, ?)""",
            ("testclient:test-repo:main:pipeline.yaml:root",
             "testclient:test-repo:main:pipeline.yaml",
             "root", 0, json.dumps({"pipeline": {"name": "test-deploy", "stages": []}})),
        )
        conn.execute(
            """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
               VALUES (?, ?, ?, ?, ?)""",
            ("testclient:test-repo:main:pipeline.yaml:root.pipeline",
             "testclient:test-repo:main:pipeline.yaml",
             "root.pipeline", 1, json.dumps({"name": "test-deploy", "stages": []})),
        )
        conn.execute(
            """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
               VALUES (?, ?, ?, ?, ?)""",
            ("testclient:test-repo:main:pipeline.yaml:root.pipeline.name",
             "testclient:test-repo:main:pipeline.yaml",
             "root.pipeline.name", 2, json.dumps("test-deploy")),
        )
        conn.execute(
            """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
               VALUES (?, ?, ?, ?, ?)""",
            ("testclient:test-repo:main:pipeline.yaml:root.pipeline.stages",
             "testclient:test-repo:main:pipeline.yaml",
             "root.pipeline.stages", 2, json.dumps([])),
        )

        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_returns_data(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient")
            ))
            self.assertIn("skeletons", result)
            self.assertGreater(len(result["skeletons"]), 0)
            self.assertEqual(result["total_found"], 2)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_filters_by_file_type(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient", file_type="harness")
            ))
            self.assertEqual(result["total_found"], 1)
            self.assertEqual(result["skeletons"][0]["file_type"], "harness")

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_filters_by_repo(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient", repo="tf-repo")
            ))
            self.assertEqual(result["total_found"], 1)
            self.assertEqual(result["skeletons"][0]["repo"], "tf-repo")

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_has_usage_hint(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient")
            ))
            self.assertIn("usage_hint", result)
            self.assertIn("hivemind_hti_fetch_nodes", result["usage_hint"])

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_skeleton_structure(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient", file_type="harness")
            ))
            skel = result["skeletons"][0]
            self.assertIn("skeleton_id", skel)
            self.assertIn("file_path", skel)
            self.assertIn("skeleton", skel)
            self.assertEqual(skel["skeleton"]["_type"], "object")


class TestHTIGetSkeletonEmpty(unittest.TestCase):
    """Test hti_get_skeleton with empty DB."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_hti_empty_"))
        self.memory_dir = self.test_dir / "memory" / "emptyclient"
        self.memory_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_get_skeleton_empty_returns_gracefully(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="emptyclient")
            ))
            self.assertIn("skeletons", result)
            self.assertEqual(len(result["skeletons"]), 0)
            self.assertEqual(result["total_found"], 0)


class TestHTIFetchNodes(unittest.TestCase):
    """Test hti_fetch_nodes tool."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_hti_fetch_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True)

        self.db_path = self.memory_dir / "hti.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        schema_sql = (PROJECT_ROOT / "hivemind_mcp" / "hti" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        skeleton = {"_type": "object", "_path": "root"}
        conn.execute(
            """INSERT INTO hti_skeletons
               (id, client, repo, branch, file_path, file_type, skeleton_json, node_count, mtime_epoch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("testclient:repo:main:file.yaml", "testclient", "repo",
             "main", "file.yaml", "harness", json.dumps(skeleton), 3, 1000),
        )

        # Insert nodes
        for path, depth, content in [
            ("root", 0, {"pipeline": {"name": "test"}}),
            ("root.pipeline", 1, {"name": "test"}),
            ("root.pipeline.name", 2, "test"),
        ]:
            conn.execute(
                """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"testclient:repo:main:file.yaml:{path}",
                 "testclient:repo:main:file.yaml",
                 path, depth, json.dumps(content)),
            )

        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_nodes_returns_content(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:file.yaml",
                    node_paths="root.pipeline",
                )
            ))
            self.assertIn("nodes", result)
            self.assertEqual(len(result["nodes"]), 1)
            self.assertTrue(result["nodes"][0]["found"])
            self.assertEqual(result["nodes"][0]["content"], {"name": "test"})

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_multiple_nodes(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:file.yaml",
                    node_paths="root.pipeline,root.pipeline.name",
                )
            ))
            self.assertEqual(len(result["nodes"]), 2)
            self.assertTrue(all(n["found"] for n in result["nodes"]))

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_nodes_missing_path(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:file.yaml",
                    node_paths="root.nonexistent",
                )
            ))
            self.assertEqual(len(result["nodes"]), 1)
            self.assertFalse(result["nodes"][0]["found"])
            self.assertIn("root.nonexistent", result["missing_paths"])

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_nodes_mixed_found_and_missing(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:file.yaml",
                    node_paths="root.pipeline,root.nonexistent",
                )
            ))
            found = [n for n in result["nodes"] if n["found"]]
            missing = [n for n in result["nodes"] if not n["found"]]
            self.assertEqual(len(found), 1)
            self.assertEqual(len(missing), 1)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_nodes_returns_metadata(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:file.yaml",
                    node_paths="root",
                )
            ))
            self.assertEqual(result["file_path"], "file.yaml")
            self.assertEqual(result["repo"], "repo")
            self.assertEqual(result["branch"], "main")

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_nodes_invalid_skeleton_id(self, mock_root):
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:repo:main:nonexistent.yaml",
                    node_paths="root",
                )
            ))
            self.assertIn("error", result)

    def test_fetch_nodes_malformed_skeleton_id(self):
        from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
        result = json.loads(asyncio.run(
            hivemind_hti_fetch_nodes(
                skeleton_id="bad-id",
                node_paths="root",
            )
        ))
        self.assertIn("error", result)


class TestHTIGetSkeletonPagination(unittest.TestCase):
    """Test that hti_get_skeleton returns more than 5 results when available."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_hti_pagination_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True)

        self.db_path = self.memory_dir / "hti.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        schema_sql = (PROJECT_ROOT / "hivemind_mcp" / "hti" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Insert 15 terraform skeletons to exceed old limit of 5
        tf_skeleton = json.dumps({
            "_type": "object", "_path": "root", "_keys": ["variable"],
            "_children": {"variable": {"_type": "array", "_path": "root.variable"}},
        })
        for i in range(15):
            skel_id = f"testclient:tf-repo:main:layer_{i}/variables.tf"
            conn.execute(
                """INSERT INTO hti_skeletons
                   (id, client, repo, branch, file_path, file_type, skeleton_json, node_count, mtime_epoch)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (skel_id, "testclient", "tf-repo", "main",
                 f"layer_{i}/variables.tf", "terraform", tf_skeleton, 3, 1000000 + i),
            )

        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_returns_more_than_5_terraform_skeletons(self, mock_root):
        """Default max_skeletons (50) returns all 15 terraform files, not just 5."""
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient", file_type="terraform")
            ))
            self.assertEqual(result["total_found"], 15)
            self.assertEqual(result["returned"], 15)
            self.assertEqual(len(result["skeletons"]), 15)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_max_skeletons_default_is_50(self, mock_root):
        """Verify the default max_skeletons parameter is 50, not 5."""
        import inspect
        from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
        sig = inspect.signature(hivemind_hti_get_skeleton)
        default = sig.parameters["max_skeletons"].default
        self.assertEqual(default, 50)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_explicit_limit_overrides_default(self, mock_root):
        """Passing max_skeletons=3 returns only 3 even when more exist."""
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_get_skeleton
            result = json.loads(asyncio.run(
                hivemind_hti_get_skeleton(client="testclient", file_type="terraform", max_skeletons=3)
            ))
            self.assertEqual(result["total_found"], 15)
            self.assertEqual(result["returned"], 3)
            self.assertEqual(len(result["skeletons"]), 3)


class TestHTIFetchNodesHCL(unittest.TestCase):
    """Test hti_fetch_nodes correctly handles HCL node paths with bracket notation."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_hti_hcl_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True)

        self.db_path = self.memory_dir / "hti.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        schema_sql = (PROJECT_ROOT / "hivemind_mcp" / "hti" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        skeleton = {"_type": "object", "_path": "root", "_keys": ["variable"]}
        conn.execute(
            """INSERT INTO hti_skeletons
               (id, client, repo, branch, file_path, file_type, skeleton_json, node_count, mtime_epoch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("testclient:tf-repo:main:variables.tf", "testclient", "tf-repo",
             "main", "variables.tf", "terraform", json.dumps(skeleton), 4, 1000),
        )

        # Insert HCL-style nodes with bracket notation
        for path, depth, content in [
            ("root", 0, {"variable": [{"rg_name": {"type": "string"}}]}),
            ("root.variable", 1, [{"rg_name": {"type": "string"}}]),
            ("root.variable[0]", 2, {"rg_name": {"type": "string"}}),
            ("root.variable[0].rg_name", 3, {"type": "string"}),
        ]:
            conn.execute(
                """INSERT INTO hti_nodes (id, skeleton_id, node_path, depth, content_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"testclient:tf-repo:main:variables.tf:{path}",
                 "testclient:tf-repo:main:variables.tf",
                 path, depth, json.dumps(content)),
            )

        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_hcl_bracket_node_path(self, mock_root):
        """Fetching HCL node path root.variable[0] returns exact match."""
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:tf-repo:main:variables.tf",
                    node_paths="root.variable[0]",
                )
            ))
            self.assertEqual(len(result["nodes"]), 1)
            self.assertTrue(result["nodes"][0]["found"])
            self.assertEqual(result["nodes"][0]["node_path"], "root.variable[0]")
            self.assertIn("rg_name", result["nodes"][0]["content"])

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_hcl_nested_bracket_path(self, mock_root):
        """Fetching root.variable[0].rg_name returns the nested HCL content."""
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:tf-repo:main:variables.tf",
                    node_paths="root.variable[0].rg_name",
                )
            ))
            self.assertEqual(len(result["nodes"]), 1)
            self.assertTrue(result["nodes"][0]["found"])
            self.assertEqual(result["nodes"][0]["content"], {"type": "string"})

    @patch("hivemind_mcp.hti.utils.PROJECT_ROOT")
    def test_fetch_hcl_prefix_match_fallback(self, mock_root):
        """A partial HCL path falls back to prefix match."""
        with patch("hivemind_mcp.hti.utils.PROJECT_ROOT", self.test_dir):
            from hivemind_mcp.hivemind_server import hivemind_hti_fetch_nodes
            result = json.loads(asyncio.run(
                hivemind_hti_fetch_nodes(
                    skeleton_id="testclient:tf-repo:main:variables.tf",
                    node_paths="root.variable[0].rg",
                )
            ))
            node = result["nodes"][0]
            self.assertTrue(node["found"])
            self.assertEqual(node.get("matched_via"), "prefix")


if __name__ == "__main__":
    unittest.main()
