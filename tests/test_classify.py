"""
Unit Tests — File Classification

Tests ingest/classify_files.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase
from ingest.classify_files import classify_file, classify_directory, SKIP_EXTENSIONS


class TestClassifyFile(HiveMindTestCase):
    """Tests for classify_file()"""

    def test_pipeline_yaml(self):
        # Only files NAMED pipeline.yaml/yml are classified as pipeline
        result = classify_file("pipelines/pipeline.yaml", "cicd/harness")
        self.assertEqual(result, "pipeline")

    def test_non_pipeline_yaml_in_pipelines_dir(self):
        # Other YAML files in pipelines/ dir are NOT classified as pipeline
        result = classify_file("pipelines/deploy_audit.yaml", "cicd/harness")
        self.assertEqual(result, "unknown")

    def test_terraform_file(self):
        result = classify_file("layer_01_keyvaults/main.tf", "infrastructure/terraform")
        self.assertEqual(result, "terraform")

    def test_helm_chart(self):
        result = classify_file("charts/audit-service/Chart.yaml", "helm")
        self.assertEqual(result, "helm_chart")

    def test_helm_values(self):
        result = classify_file("charts/audit-service/values.yaml", "helm")
        self.assertEqual(result, "helm_values")

    def test_helm_template_returns_template(self):
        # Files in templates/ dir return "template" (not "helm_template")
        result = classify_file("charts/audit-service/templates/deployment.yaml", "helm")
        self.assertEqual(result, "template")

    def test_harness_service(self):
        result = classify_file(".harness/services/audit_service.yaml", "cicd/harness")
        self.assertEqual(result, "harness_svc")

    def test_template_file(self):
        result = classify_file("templates/rollout_k8s.yaml", "cicd/harness")
        self.assertEqual(result, "template")

    def test_skip_extension(self):
        result = classify_file("image.png", "unknown")
        self.assertEqual(result, "skip")

    def test_hcl_not_skipped(self):
        # .hcl is NOT in SKIP_EXTENSIONS — returns unknown
        result = classify_file(".terraform.lock.hcl", "infrastructure/terraform")
        self.assertEqual(result, "unknown")

    def test_lock_extension_skipped(self):
        # .lock IS in SKIP_EXTENSIONS
        result = classify_file("package.lock", "unknown")
        self.assertEqual(result, "skip")

    def test_readme_classified_as_readme(self):
        # README files return "readme" (not "docs")
        result = classify_file("README.md", "unknown")
        self.assertEqual(result, "readme")

    def test_tfvars_classified_as_terraform(self):
        # .tfvars returns "terraform" (not "terraform_vars")
        result = classify_file("layer_01_keyvaults/dev.tfvars", "infrastructure/terraform")
        self.assertEqual(result, "terraform")

    def test_unknown_file(self):
        result = classify_file("random.xyz", "unknown")
        self.assertIsNotNone(result)

    def test_dockerfile(self):
        result = classify_file("Dockerfile", "unknown")
        self.assertEqual(result, "dockerfile")

    def test_harness_env(self):
        result = classify_file(".harness/environments/dev.yaml", "cicd/harness")
        self.assertEqual(result, "harness_env")


class TestClassifyDirectory(HiveMindTestCase):
    """Tests for classify_directory()"""

    def test_classifies_harness_repo(self):
        from tests.conftest import FAKE_HARNESS_REPO
        results = classify_directory(str(FAKE_HARNESS_REPO))
        self.assertGreater(len(results), 0)
        # Results use "classification" key (not "type")
        classifications = [r["classification"] for r in results]
        # Should find templates and harness services
        self.assertIn("template", classifications)
        self.assertIn("harness_svc", classifications)

    def test_directory_has_pipeline(self):
        from tests.conftest import FAKE_HARNESS_REPO
        results = classify_directory(str(FAKE_HARNESS_REPO))
        classifications = [r["classification"] for r in results]
        # pipeline.yaml fixture exists -> should find "pipeline"
        self.assertIn("pipeline", classifications)

    def test_classifies_terraform_repo(self):
        from tests.conftest import FAKE_TERRAFORM_REPO
        results = classify_directory(str(FAKE_TERRAFORM_REPO))
        classifications = [r["classification"] for r in results]
        self.assertIn("terraform", classifications)

    def test_classifies_helm_repo(self):
        from tests.conftest import FAKE_HELM_REPO
        results = classify_directory(str(FAKE_HELM_REPO))
        classifications = [r["classification"] for r in results]
        self.assertIn("helm_chart", classifications)

    def test_results_have_correct_keys(self):
        from tests.conftest import FAKE_HARNESS_REPO
        results = classify_directory(str(FAKE_HARNESS_REPO))
        for r in results:
            self.assertIn("file", r)
            self.assertIn("relative_path", r)
            self.assertIn("classification", r)

    def test_skip_extensions_are_skipped(self):
        from tests.conftest import FAKE_HARNESS_REPO
        results = classify_directory(str(FAKE_HARNESS_REPO))
        for r in results:
            ext = Path(r["file"]).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                self.assertEqual(
                    r["classification"], "skip",
                    f"Extension {ext} should be classified as skip",
                )


class TestSkipExtensions(unittest.TestCase):
    """Tests for SKIP_EXTENSIONS set."""

    def test_common_binary_extensions_included(self):
        self.assertIn(".png", SKIP_EXTENSIONS)
        self.assertIn(".jpg", SKIP_EXTENSIONS)
        self.assertIn(".zip", SKIP_EXTENSIONS)

    def test_yaml_not_skipped(self):
        self.assertNotIn(".yaml", SKIP_EXTENSIONS)
        self.assertNotIn(".yml", SKIP_EXTENSIONS)

    def test_tf_not_skipped(self):
        self.assertNotIn(".tf", SKIP_EXTENSIONS)

    def test_hcl_not_in_skip(self):
        self.assertNotIn(".hcl", SKIP_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
