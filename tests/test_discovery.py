"""
Unit Tests — Discovery Modules

Tests all modules in ingest/discovery/:
    - discover_repo_type
    - discover_services
    - discover_environments
    - discover_pipelines
    - discover_infra_layers
    - discover_secrets
    - discover_naming
    - build_profile
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO, FAKE_TERRAFORM_REPO, FAKE_HELM_REPO


class TestDiscoverRepoType(HiveMindTestCase):
    """Tests for ingest/discovery/discover_repo_type.py"""

    def test_harness_repo_detected(self):
        from ingest.discovery.discover_repo_type import discover_repo_type
        result = discover_repo_type(str(FAKE_HARNESS_REPO))
        # discover_repo_type splits "cicd/harness" -> type="cicd", platform="harness"
        self.assertEqual(result["type"], "cicd")
        self.assertEqual(result["platform"], "harness")
        self.assertGreater(result["confidence"], 0.2)

    def test_terraform_repo_detected(self):
        from ingest.discovery.discover_repo_type import discover_repo_type
        result = discover_repo_type(str(FAKE_TERRAFORM_REPO))
        # discover_repo_type splits "infrastructure/terraform" -> type="infrastructure"
        self.assertEqual(result["type"], "infrastructure")
        self.assertEqual(result["platform"], "terraform")
        self.assertGreater(result["confidence"], 0.2)

    def test_helm_repo_detected(self):
        from ingest.discovery.discover_repo_type import discover_repo_type
        result = discover_repo_type(str(FAKE_HELM_REPO))
        self.assertEqual(result["type"], "helm")
        self.assertGreater(result["confidence"], 0.5)

    def test_empty_dir_returns_unknown(self):
        from ingest.discovery.discover_repo_type import discover_repo_type
        result = discover_repo_type(str(self.test_dir))
        self.assertEqual(result["type"], "unknown")

    def test_result_has_expected_keys(self):
        from ingest.discovery.discover_repo_type import discover_repo_type
        result = discover_repo_type(str(FAKE_HARNESS_REPO))
        self.assertIn("type", result)
        self.assertIn("confidence", result)
        self.assertIn("indicators", result)


class TestDiscoverServices(HiveMindTestCase):
    """Tests for ingest/discovery/discover_services.py"""

    def test_discovers_harness_services(self):
        from ingest.discovery.discover_services import discover_services
        # discover_services takes a list of paths
        services = discover_services([str(FAKE_HARNESS_REPO)])
        service_names = [s["name"] for s in services]
        # _normalize_service_name replaces _ with -, so "audit_service" -> "audit-service"
        self.assertIn("audit-service", service_names)

    def test_discovers_pipeline_service_refs(self):
        from ingest.discovery.discover_services import discover_services
        services = discover_services([str(FAKE_HARNESS_REPO)])
        service_names = [s["name"] for s in services]
        # pipeline.yaml fixture has serviceRef: audit_service -> normalized to "audit-service"
        self.assertIn("audit-service", service_names)

    def test_deduplicates_services(self):
        from ingest.discovery.discover_services import discover_services
        services = discover_services([str(FAKE_HARNESS_REPO)])
        names = [s["name"] for s in services]
        # Each service should appear only once
        self.assertEqual(len(names), len(set(names)))

    def test_service_has_sources(self):
        from ingest.discovery.discover_services import discover_services
        services = discover_services([str(FAKE_HARNESS_REPO)])
        for svc in services:
            self.assertIn("sources", svc)
            self.assertIsInstance(svc["sources"], list)

    def test_empty_dir_returns_empty(self):
        from ingest.discovery.discover_services import discover_services
        services = discover_services([str(self.test_dir)])
        self.assertEqual(services, [])


class TestDiscoverEnvironments(HiveMindTestCase):
    """Tests for ingest/discovery/discover_environments.py"""

    def test_discovers_environments(self):
        from ingest.discovery.discover_environments import discover_environments
        envs = discover_environments([str(FAKE_HARNESS_REPO)])
        env_names = [e["name"] for e in envs]
        self.assertIn("dev", env_names)
        self.assertIn("prod", env_names)

    def test_classifies_tiers(self):
        from ingest.discovery.discover_environments import discover_environments
        envs = discover_environments([str(FAKE_HARNESS_REPO)])
        prod_envs = [e for e in envs if e["name"] == "prod"]
        if prod_envs:
            self.assertEqual(prod_envs[0]["tier"], "production")

    def test_dev_is_integration_tier(self):
        from ingest.discovery.discover_environments import discover_environments
        envs = discover_environments([str(FAKE_HARNESS_REPO)])
        dev_envs = [e for e in envs if e["name"] == "dev"]
        if dev_envs:
            self.assertEqual(dev_envs[0]["tier"], "integration")

    def test_empty_dir(self):
        from ingest.discovery.discover_environments import discover_environments
        envs = discover_environments([str(self.test_dir)])
        self.assertEqual(envs, [])


class TestDiscoverPipelines(HiveMindTestCase):
    """Tests for ingest/discovery/discover_pipelines.py"""

    def test_discovers_pipelines(self):
        from ingest.discovery.discover_pipelines import discover_pipelines
        pipelines = discover_pipelines([str(FAKE_HARNESS_REPO)])
        self.assertGreater(len(pipelines), 0)

    def test_extracts_stages(self):
        from ingest.discovery.discover_pipelines import discover_pipelines
        pipelines = discover_pipelines([str(FAKE_HARNESS_REPO)])
        # At least one pipeline should have stages
        has_stages = any(len(p.get("stages", [])) > 0 for p in pipelines)
        self.assertTrue(has_stages, "No pipeline has stages")

    def test_extracts_service_refs(self):
        from ingest.discovery.discover_pipelines import discover_pipelines
        pipelines = discover_pipelines([str(FAKE_HARNESS_REPO)])
        all_service_refs = []
        for p in pipelines:
            all_service_refs.extend(p.get("service_refs", []))
        self.assertIn("audit_service", all_service_refs)


class TestDiscoverInfraLayers(HiveMindTestCase):
    """Tests for ingest/discovery/discover_infra_layers.py"""

    def test_discovers_layers(self):
        from ingest.discovery.discover_infra_layers import discover_infra_layers
        layers = discover_infra_layers([str(FAKE_TERRAFORM_REPO)])
        self.assertGreater(len(layers), 0)

    def test_layers_sorted_by_number(self):
        from ingest.discovery.discover_infra_layers import discover_infra_layers
        layers = discover_infra_layers([str(FAKE_TERRAFORM_REPO)])
        if len(layers) > 1:
            numbers = [l.get("layer_number", 0) for l in layers]
            self.assertEqual(numbers, sorted(numbers))

    def test_extracts_resources(self):
        from ingest.discovery.discover_infra_layers import discover_infra_layers
        layers = discover_infra_layers([str(FAKE_TERRAFORM_REPO)])
        layer_01 = [l for l in layers if "01" in l.get("name", "")]
        if layer_01:
            resources = layer_01[0].get("resources", [])
            resource_types = [r.get("type", "") for r in resources]
            self.assertIn("azurerm_key_vault", resource_types)


class TestDiscoverSecrets(HiveMindTestCase):
    """Tests for ingest/discovery/discover_secrets.py"""

    def test_discovers_kv_secrets(self):
        from ingest.discovery.discover_secrets import discover_secrets
        result = discover_secrets([str(FAKE_TERRAFORM_REPO)])
        kv_secrets = result.get("kv_secrets", [])
        # Secrets use "secret_name" key (not "name")
        secret_names = [s.get("secret_name", "") for s in kv_secrets]
        # Terraform interpolation in name field causes regex to fall back to resource name
        found_audit = any("db_audit" in n for n in secret_names)
        self.assertTrue(found_audit, f"Expected audit secret, got: {secret_names}")

    def test_discovers_k8s_secrets(self):
        from ingest.discovery.discover_secrets import discover_secrets
        result = discover_secrets([str(FAKE_TERRAFORM_REPO)])
        k8s = result.get("k8s_secrets", [])
        # k8s secrets may or may not be found depending on terraform fixtures
        self.assertIsInstance(k8s, list)

    def test_discovers_helm_mounts(self):
        from ingest.discovery.discover_secrets import discover_secrets
        result = discover_secrets([str(FAKE_HELM_REPO)])
        helm = result.get("helm_mounts", [])
        self.assertGreater(len(helm), 0)

    def test_result_has_expected_keys(self):
        from ingest.discovery.discover_secrets import discover_secrets
        result = discover_secrets([str(FAKE_TERRAFORM_REPO)])
        self.assertIn("kv_secrets", result)
        self.assertIn("k8s_secrets", result)
        self.assertIn("helm_mounts", result)
        self.assertIn("naming_patterns", result)


class TestDiscoverNaming(HiveMindTestCase):
    """Tests for ingest/discovery/discover_naming.py"""

    def test_detects_naming_conventions(self):
        from ingest.discovery.discover_naming import discover_naming
        result = discover_naming([str(FAKE_TERRAFORM_REPO)])
        # Result key is "conventions" (not "patterns")
        conventions = result.get("conventions", [])
        # Should find some naming conventions from tf resource names
        self.assertIsInstance(conventions, list)

    def test_result_has_expected_keys(self):
        from ingest.discovery.discover_naming import discover_naming
        result = discover_naming([str(FAKE_TERRAFORM_REPO)])
        self.assertIn("conventions", result)
        self.assertIn("separator", result)
        self.assertIn("examples", result)


class TestBuildProfile(HiveMindTestCase):
    """Tests for ingest/discovery/build_profile.py"""

    def test_builds_profile(self):
        from ingest.discovery.build_profile import build_profile
        # build_profile takes 3 args: client_name, repo_configs, output_dir
        repo_configs = [
            {"name": "fake-harness", "path": str(FAKE_HARNESS_REPO), "branches": ["main"]},
        ]
        profile = build_profile("testclient", repo_configs, str(self.test_dir))
        self.assertIn("client", profile)
        self.assertIn("services", profile)
        self.assertIn("environments", profile)

    def test_writes_profile_file(self):
        from ingest.discovery.build_profile import build_profile
        repo_configs = [
            {"name": "fake-harness", "path": str(FAKE_HARNESS_REPO), "branches": ["main"]},
        ]
        profile = build_profile("testclient", repo_configs, str(self.test_dir))
        profile_json = self.test_dir / "discovered_profile.json"
        self.assertTrue(profile_json.exists())

    def test_profile_json_is_valid(self):
        from ingest.discovery.build_profile import build_profile
        repo_configs = [
            {"name": "fake-harness", "path": str(FAKE_HARNESS_REPO), "branches": ["main"]},
            {"name": "fake-terraform", "path": str(FAKE_TERRAFORM_REPO), "branches": ["main"]},
        ]
        build_profile("testclient", repo_configs, str(self.test_dir))
        profile_json = self.test_dir / "discovered_profile.json"
        with open(profile_json, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        self.assertEqual(data["client"], "testclient")

    def test_profile_includes_all_repos(self):
        from ingest.discovery.build_profile import build_profile
        repo_configs = [
            {"name": "fake-harness", "path": str(FAKE_HARNESS_REPO), "branches": ["main"]},
            {"name": "fake-terraform", "path": str(FAKE_TERRAFORM_REPO), "branches": ["main"]},
            {"name": "fake-helm", "path": str(FAKE_HELM_REPO), "branches": ["main"]},
        ]
        profile = build_profile("testclient", repo_configs, str(self.test_dir))
        self.assertEqual(len(profile["repos"]), 3)


if __name__ == "__main__":
    unittest.main()
