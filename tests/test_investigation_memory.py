"""
Unit Tests — Investigation Memory (save + recall)

Tests tools/save_investigation.py and tools/recall_investigation.py
"""

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestSaveInvestigation(HiveMindTestCase):
    """Tests for save_investigation()."""

    def test_save_creates_json_file(self):
        """save_investigation writes a JSON file under investigations/."""
        import tools.save_investigation as si

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            result = si.save_investigation(
                client="testclient",
                service_name="audit-service",
                incident_type="CrashLoopBackOff",
                root_cause_summary="Bean init failure due to missing dependency.",
                resolution="Restarted the dependency service.",
                files_cited=[{"file_path": "deploy.yaml", "repo": "repo1", "branch": "main", "relevance": "primary"}],
                tags=["spring-boot", "crash"],
            )

        self.assertTrue(result["saved"])
        self.assertIn("id", result)
        self.assertIn("path", result)

        # Verify JSON file exists and is valid
        json_path = Path(result["path"])
        self.assertTrue(json_path.exists())

        with open(json_path, "r") as f:
            data = json.load(f)

        self.assertEqual(data["service_name"], "audit-service")
        self.assertEqual(data["incident_type"], "CrashLoopBackOff")
        self.assertEqual(data["client"], "testclient")
        self.assertEqual(len(data["files_cited"]), 1)
        self.assertEqual(len(data["tags"]), 2)
        self.assertIn("timestamp", data)

    def test_save_generates_unique_ids(self):
        """Each save_investigation call generates a unique UUID."""
        import tools.save_investigation as si

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            r1 = si.save_investigation(
                client="testclient",
                service_name="svc1",
                incident_type="OOMKilled",
                root_cause_summary="Memory limit too low.",
                resolution="Increased memory limit.",
            )
            r2 = si.save_investigation(
                client="testclient",
                service_name="svc2",
                incident_type="ProbeFailure",
                root_cause_summary="Liveness probe misconfigured.",
                resolution="Fixed probe path.",
            )

        self.assertNotEqual(r1["id"], r2["id"])

    def test_save_creates_investigations_directory(self):
        """save_investigation creates the investigations/ dir if missing."""
        import tools.save_investigation as si

        inv_dir = self.test_dir / "memory" / "newclient" / "investigations"
        self.assertFalse(inv_dir.exists())

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            si.save_investigation(
                client="newclient",
                service_name="svc",
                incident_type="Unknown",
                root_cause_summary="Some issue.",
                resolution="Fixed it.",
            )

        self.assertTrue(inv_dir.exists())

    def test_save_invalid_incident_type_defaults_to_unknown(self):
        """Invalid incident_type is replaced with 'Unknown'."""
        import tools.save_investigation as si

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            result = si.save_investigation(
                client="testclient",
                service_name="svc",
                incident_type="InvalidType",
                root_cause_summary="Issue.",
                resolution="Fix.",
            )

        json_path = Path(result["path"])
        with open(json_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["incident_type"], "Unknown")

    def test_save_missing_client_returns_error(self):
        """save_investigation returns error when client is empty."""
        import tools.save_investigation as si
        result = si.save_investigation(
            client="",
            service_name="svc",
            incident_type="Unknown",
            root_cause_summary="Issue.",
            resolution="Fix.",
        )
        self.assertIn("error", result)

    def test_save_missing_service_returns_error(self):
        """save_investigation returns error when service_name is empty."""
        import tools.save_investigation as si
        result = si.save_investigation(
            client="testclient",
            service_name="",
            incident_type="Unknown",
            root_cause_summary="Issue.",
            resolution="Fix.",
        )
        self.assertIn("error", result)

    def test_save_missing_root_cause_returns_error(self):
        """save_investigation returns error when root_cause_summary is empty."""
        import tools.save_investigation as si
        result = si.save_investigation(
            client="testclient",
            service_name="svc",
            incident_type="Unknown",
            root_cause_summary="",
            resolution="Fix.",
        )
        self.assertIn("error", result)

    def test_save_missing_resolution_returns_error(self):
        """save_investigation returns error when resolution is empty."""
        import tools.save_investigation as si
        result = si.save_investigation(
            client="testclient",
            service_name="svc",
            incident_type="Unknown",
            root_cause_summary="Issue.",
            resolution="",
        )
        self.assertIn("error", result)

    def test_save_with_no_files_or_tags(self):
        """save_investigation works with empty files_cited and tags."""
        import tools.save_investigation as si

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            result = si.save_investigation(
                client="testclient",
                service_name="svc",
                incident_type="OOMKilled",
                root_cause_summary="Out of memory.",
                resolution="Bump limits.",
            )

        self.assertTrue(result["saved"])
        json_path = Path(result["path"])
        with open(json_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["files_cited"], [])
        self.assertEqual(data["tags"], [])

    def test_save_all_valid_incident_types(self):
        """All valid incident types are accepted."""
        import tools.save_investigation as si

        for itype in si.VALID_INCIDENT_TYPES:
            with patch.object(si, "PROJECT_ROOT", self.test_dir):
                result = si.save_investigation(
                    client="testclient",
                    service_name="svc",
                    incident_type=itype,
                    root_cause_summary="Issue.",
                    resolution="Fix.",
                )
            self.assertTrue(result["saved"], f"Failed for incident_type={itype}")


class TestRecallInvestigation(HiveMindTestCase):
    """Tests for recall_investigation() — JSON fallback path."""

    def _save_test_investigations(self):
        """Helper: save several test investigations to JSON."""
        import tools.save_investigation as si

        with patch.object(si, "PROJECT_ROOT", self.test_dir):
            si.save_investigation(
                client="testclient",
                service_name="tagging-service",
                incident_type="CrashLoopBackOff",
                root_cause_summary="Spring bean coreTaxonomySearchService failed to initialize due to search backend unavailable in predemo environment.",
                resolution="Confirmed search service dependency was down. Restarted search-service pod. tagging-service recovered automatically.",
                files_cited=[{"file_path": "charts/tagging-service/templates/deployment.yaml", "repo": "newAd_Artifacts", "branch": "release_26_2"}],
                tags=["spring-boot", "bean-init", "dependency", "search-service"],
            )
            si.save_investigation(
                client="testclient",
                service_name="audit-service",
                incident_type="OOMKilled",
                root_cause_summary="JVM heap exceeded container memory limit during peak load.",
                resolution="Increased memory limit from 512Mi to 1Gi in Helm values.",
                tags=["jvm", "memory", "helm"],
            )
            si.save_investigation(
                client="testclient",
                service_name="payment-service",
                incident_type="SecretMount",
                root_cause_summary="KeyVault secret rotation broke CSI driver mount. New secret version not synced to K8s.",
                resolution="Recycled SecretProviderClass and restarted pods.",
                tags=["keyvault", "csi-driver", "secret-rotation"],
            )

    def test_recall_empty_returns_empty_list(self):
        """recall_investigation returns [] when no investigations exist."""
        import tools.recall_investigation as ri

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="anything",
            )
        self.assertEqual(results, [])

    def test_recall_finds_matching_investigation(self):
        """recall_investigation finds a saved investigation by query."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="tagging-service startup failure spring bean",
            )

        self.assertGreater(len(results), 0)
        # The tagging-service investigation should be the top result
        self.assertEqual(results[0]["service_name"], "tagging-service")

    def test_recall_returns_all_fields(self):
        """recall_investigation returns all expected fields."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="spring bean initialization",
            )

        self.assertGreater(len(results), 0)
        result = results[0]
        self.assertIn("id", result)
        self.assertIn("service_name", result)
        self.assertIn("incident_type", result)
        self.assertIn("root_cause_summary", result)
        self.assertIn("resolution", result)
        self.assertIn("tags", result)
        self.assertIn("relevance_pct", result)

    def test_recall_service_name_filter(self):
        """recall_investigation filters by service_name."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="service failure",
                service_name="audit-service",
            )

        # Should only return audit-service results
        for r in results:
            self.assertEqual(r["service_name"], "audit-service")

    def test_recall_incident_type_filter(self):
        """recall_investigation filters by incident_type."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="service issue",
                incident_type="OOMKilled",
            )

        for r in results:
            self.assertEqual(r["incident_type"], "OOMKilled")

    def test_recall_respects_top_k(self):
        """recall_investigation returns at most top_k results."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="service",
                top_k=1,
            )

        self.assertLessEqual(len(results), 1)

    def test_recall_empty_query_returns_empty(self):
        """recall_investigation returns [] for empty query."""
        import tools.recall_investigation as ri

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="",
            )
        self.assertEqual(results, [])

    def test_recall_empty_client_returns_empty(self):
        """recall_investigation returns [] for empty client."""
        import tools.recall_investigation as ri

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="",
                query="something",
            )
        self.assertEqual(results, [])

    def test_recall_relevance_ordering(self):
        """Results are ordered by relevance (highest first)."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="OOMKilled JVM heap memory",
            )

        if len(results) > 1:
            for i in range(len(results) - 1):
                self.assertGreaterEqual(results[i]["relevance_pct"], results[i + 1]["relevance_pct"])

    def test_recall_no_match_returns_empty(self):
        """recall_investigation returns [] when query matches nothing."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="xyznonexistent12345",
            )
        self.assertEqual(results, [])

    def test_recall_crashloopbackoff_dependency_query(self):
        """recall_investigation finds CrashLoopBackOff investigation by dependency query."""
        import tools.save_investigation as si
        import tools.recall_investigation as ri

        self._save_test_investigations()

        with patch.object(ri, "PROJECT_ROOT", self.test_dir):
            results = ri.recall_investigation(
                client="testclient",
                query="CrashLoopBackOff dependency",
            )

        self.assertGreater(len(results), 0)
        # The tagging-service investigation mentions both terms
        service_names = [r["service_name"] for r in results]
        self.assertIn("tagging-service", service_names)


class TestSaveInvestigationCLI(unittest.TestCase):
    """Tests for the save_investigation CLI."""

    def test_cli_help(self):
        """CLI --help exits 0."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "save_investigation.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--client", result.stdout)
        self.assertIn("--service", result.stdout)


class TestRecallInvestigationCLI(unittest.TestCase):
    """Tests for the recall_investigation CLI."""

    def test_cli_help(self):
        """CLI --help exits 0."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "recall_investigation.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--client", result.stdout)
        self.assertIn("--query", result.stdout)


if __name__ == "__main__":
    unittest.main()
