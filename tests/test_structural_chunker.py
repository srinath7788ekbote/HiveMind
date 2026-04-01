"""
Tests for structure-aware chunking (YAML, HCL, Helm values).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.chunkers.structural_chunker import (
    chunk_harness_pipeline,
    chunk_terraform_hcl,
    chunk_helm_values,
    chunk_generic_yaml,
    chunk_structured_file,
)


# ─────────────────────────────────────────────────────────────
# Fixtures — realistic but minimal YAML/HCL content
# ─────────────────────────────────────────────────────────────

HARNESS_PIPELINE_3_STAGES = """\
pipeline:
  name: deploy_service
  identifier: deploy_service
  stages:
    - stage:
        name: Build Image
        identifier: build_image
        type: CI
        spec:
          execution:
            steps:
              - step:
                  name: Run Unit Tests
                  identifier: run_tests
                  type: Run
                  spec:
                    command: mvn test
              - step:
                  name: Build Docker
                  identifier: build_docker
                  type: BuildAndPushDockerRegistry
                  spec:
                    dockerfile: Dockerfile
    - stage:
        name: Deploy to Dev
        identifier: deploy_dev
        type: Deployment
        spec:
          execution:
            steps:
              - step:
                  name: Rollout Deployment
                  identifier: rollout
                  type: K8sRollingDeploy
                  spec:
                    timeout: 10m
    - stage:
        name: Deploy to Prod
        identifier: deploy_prod
        type: Deployment
        spec:
          execution:
            steps:
              - step:
                  name: Approval
                  identifier: approval
                  type: HarnessApproval
              - step:
                  name: Rollout Prod
                  identifier: rollout_prod
                  type: K8sRollingDeploy
                  spec:
                    timeout: 15m
"""


def _make_large_stage(num_steps: int = 30) -> str:
    """Generate a pipeline YAML with one stage containing many steps."""
    steps = []
    for i in range(num_steps):
        steps.append(f"""\
              - step:
                  name: Step {i} with a longer name for padding purposes
                  identifier: step_{i}
                  type: Run
                  spec:
                    command: echo "Running step {i} which has a fairly long command line to increase the character count"
                    envVariables:
                      VAR_{i}: value_{i}
                      ANOTHER_VAR_{i}: another_value_{i}""")
    steps_yaml = "\n".join(steps)
    return f"""\
pipeline:
  name: large_pipeline
  identifier: large_pipeline
  stages:
    - stage:
        name: Large Stage
        identifier: large_stage
        type: CI
        spec:
          execution:
            steps:
{steps_yaml}
"""


TERRAFORM_3_RESOURCES = """\
resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-prod"
  location            = var.location
  resource_group_name = var.resource_group
  dns_prefix          = "aks-prod"

  default_node_pool {
    name       = "default"
    node_count = 3
    vm_size    = "Standard_D4s_v3"
  }
}

resource "azurerm_key_vault" "main" {
  name                = "kv-prod"
  location            = var.location
  resource_group_name = var.resource_group
  sku_name            = "standard"
  tenant_id           = var.tenant_id
}

resource "azurerm_container_registry" "main" {
  name                = "acrprod"
  resource_group_name = var.resource_group
  location            = var.location
  sku                 = "Premium"
  admin_enabled       = false
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "resource_group" {
  type    = string
  default = "rg-prod"
}

variable "tenant_id" {
  type = string
}

variable "sku" {
  type    = string
  default = "Standard"
}

variable "node_count" {
  type    = number
  default = 3
}
"""


HELM_VALUES_4_SERVICES = """\
presentationService:
  image:
    repository: acr.azurecr.io/presentation-service
    tag: "1.2.3"
  replicaCount: 2
  resources:
    limits:
      cpu: 500m
      memory: 512Mi
    requests:
      cpu: 250m
      memory: 256Mi

taggingService:
  image:
    repository: acr.azurecr.io/tagging-service
    tag: "2.0.1"
  replicaCount: 3
  resources:
    limits:
      cpu: 1000m
      memory: 1Gi

auditService:
  image:
    repository: acr.azurecr.io/audit-service
    tag: "3.1.0"
  replicaCount: 1

parserService:
  image:
    repository: acr.azurecr.io/parser-service
    tag: "4.0.0"
  replicaCount: 2
"""


GENERIC_YAML_5_KEYS = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-deployment
  labels:
    app: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
        - name: myapp
          image: myapp:latest
"""


# ─────────────────────────────────────────────────────────────
# Harness Pipeline Tests
# ─────────────────────────────────────────────────────────────

class TestHarnessPipelineChunker:
    def test_chunks_by_stage(self):
        chunks = chunk_harness_pipeline(HARNESS_PIPELINE_3_STAGES, "pipelines/deploy.yaml")
        assert len(chunks) == 3
        stage_names = [c["metadata"]["stage_name"] for c in chunks]
        assert "Build Image" in stage_names
        assert "Deploy to Dev" in stage_names
        assert "Deploy to Prod" in stage_names

    def test_no_cross_stage_content(self):
        chunks = chunk_harness_pipeline(HARNESS_PIPELINE_3_STAGES, "pipelines/deploy.yaml")
        # The Build Image chunk should not contain "Deploy to Dev" text
        build_chunk = next(c for c in chunks if c["metadata"]["stage_name"] == "Build Image")
        assert "Deploy to Dev" not in build_chunk["text"]
        assert "Deploy to Prod" not in build_chunk["text"]

    def test_large_stage_splits_at_steps(self):
        large_yaml = _make_large_stage(30)
        chunks = chunk_harness_pipeline(large_yaml, "pipelines/large.yaml", max_chunk_chars=3000)
        # Should produce multiple chunks from the single large stage
        assert len(chunks) > 1
        # All chunks should reference the same stage name
        for c in chunks:
            assert c["metadata"]["stage_name"] == "Large Stage"

    def test_metadata_fields(self):
        chunks = chunk_harness_pipeline(HARNESS_PIPELINE_3_STAGES, "pipelines/deploy.yaml")
        for i, chunk in enumerate(chunks):
            assert chunk["metadata"]["chunk_type"] == "harness_stage"
            assert chunk["metadata"]["chunking_strategy"] == "structural_harness"
            assert chunk["metadata"]["source_file"] == "pipelines/deploy.yaml"
            assert "stage_index" in chunk["metadata"]

    def test_context_header_in_text(self):
        chunks = chunk_harness_pipeline(HARNESS_PIPELINE_3_STAGES, "pipelines/deploy.yaml")
        for c in chunks:
            assert c["text"].startswith("# File: pipelines/deploy.yaml")
            assert "# Stage:" in c["text"]

    def test_fallback_on_bad_yaml(self):
        bad_yaml = "pipeline:\n  stages:\n    - stage:\n      name: Bad\n  {{{{invalid"
        # Should not raise, should return some chunks (regex fallback)
        chunks = chunk_harness_pipeline(bad_yaml, "bad.yaml")
        # May return empty or regex-split chunks — but must not raise
        assert isinstance(chunks, list)


# ─────────────────────────────────────────────────────────────
# Terraform HCL Tests
# ─────────────────────────────────────────────────────────────

class TestTerraformChunker:
    def test_chunks_by_resource_block(self):
        chunks = chunk_terraform_hcl(TERRAFORM_3_RESOURCES, "layer_3/main.tf")
        # Should have resource chunks + variable group chunks
        resource_chunks = [c for c in chunks if c["metadata"]["block_type"] == "resource"]
        assert len(resource_chunks) == 3

    def test_resource_metadata(self):
        chunks = chunk_terraform_hcl(TERRAFORM_3_RESOURCES, "layer_3/main.tf")
        resource_chunks = [c for c in chunks if c["metadata"]["block_type"] == "resource"]
        for c in resource_chunks:
            assert c["metadata"]["chunk_type"] == "terraform_block"
            assert c["metadata"]["chunking_strategy"] == "structural_terraform"
            assert c["metadata"]["source_file"] == "layer_3/main.tf"

    def test_groups_small_variables(self):
        chunks = chunk_terraform_hcl(TERRAFORM_3_RESOURCES, "layer_3/main.tf")
        # Variables should be grouped (not 5 individual chunks)
        var_chunks = [c for c in chunks if "variable" in c["metadata"].get("block_type", "")]
        total_var_chunks = len(var_chunks)
        # Should be fewer chunks than 5 individual variables
        assert total_var_chunks < 5

    def test_context_header(self):
        chunks = chunk_terraform_hcl(TERRAFORM_3_RESOURCES, "layer_3/main.tf")
        for c in chunks:
            assert c["text"].startswith("# File: layer_3/main.tf")

    def test_fallback_on_parse_error(self):
        bad_hcl = "resource azurerm_xxx main {\n  invalid {{{\n}"
        # Should not raise
        chunks = chunk_terraform_hcl(bad_hcl, "bad.tf")
        assert isinstance(chunks, list)


# ─────────────────────────────────────────────────────────────
# Helm Values Tests
# ─────────────────────────────────────────────────────────────

class TestHelmValuesChunker:
    def test_chunks_by_top_level_key(self):
        chunks = chunk_helm_values(HELM_VALUES_4_SERVICES, "charts/my-service/values.yaml")
        assert len(chunks) == 4
        keys = [c["metadata"]["section_key"] for c in chunks]
        assert "presentationService" in keys
        assert "taggingService" in keys
        assert "auditService" in keys
        assert "parserService" in keys

    def test_section_header_in_text(self):
        chunks = chunk_helm_values(HELM_VALUES_4_SERVICES, "charts/my-service/values.yaml")
        for c in chunks:
            assert c["text"].startswith("# File: charts/my-service/values.yaml")
            assert "# Section:" in c["text"]

    def test_metadata_fields(self):
        chunks = chunk_helm_values(HELM_VALUES_4_SERVICES, "charts/my-service/values.yaml")
        for c in chunks:
            assert c["metadata"]["chunk_type"] == "helm_values_section"
            assert c["metadata"]["chunking_strategy"] == "structural_helm"

    def test_root_scalars_grouped(self):
        yaml_with_scalars = """\
replicaCount: 3
nameOverride: my-svc
fullnameOverride: my-svc-full
presentationService:
  image:
    repository: acr.azurecr.io/svc
    tag: "1.0"
"""
        chunks = chunk_helm_values(yaml_with_scalars, "values.yaml")
        scalar_chunks = [c for c in chunks if c["metadata"]["section_key"] == "root_scalars"]
        assert len(scalar_chunks) == 1
        assert "replicaCount" in scalar_chunks[0]["text"]


# ─────────────────────────────────────────────────────────────
# Generic YAML Tests
# ─────────────────────────────────────────────────────────────

class TestGenericYamlChunker:
    def test_chunks_by_top_level_key(self):
        chunks = chunk_generic_yaml(GENERIC_YAML_5_KEYS, "k8s/deployment.yaml")
        assert len(chunks) >= 1
        # Should have keys like apiVersion, kind, metadata, spec
        all_text = " ".join(c["text"] for c in chunks)
        assert "apiVersion" in all_text
        assert "spec" in all_text

    def test_metadata_fields(self):
        chunks = chunk_generic_yaml(GENERIC_YAML_5_KEYS, "k8s/deployment.yaml")
        for c in chunks:
            assert c["metadata"]["chunk_type"] == "yaml_section"
            assert c["metadata"]["chunking_strategy"] == "structural_yaml"


# ─────────────────────────────────────────────────────────────
# Dispatcher Tests
# ─────────────────────────────────────────────────────────────

class TestDispatcher:
    def test_routes_tf_to_terraform(self):
        result = chunk_structured_file(TERRAFORM_3_RESOURCES, "layer_3/main.tf")
        assert result is not None
        assert len(result) > 0
        assert result[0]["metadata"]["chunking_strategy"] == "structural_terraform"

    def test_routes_pipeline_yaml(self):
        result = chunk_structured_file(HARNESS_PIPELINE_3_STAGES, "pipelines/deploy.yaml")
        assert result is not None
        assert len(result) > 0
        assert result[0]["metadata"]["chunking_strategy"] == "structural_harness"

    def test_routes_values_yaml(self):
        result = chunk_structured_file(HELM_VALUES_4_SERVICES, "charts/svc/values.yaml")
        assert result is not None
        assert len(result) > 0
        assert result[0]["metadata"]["chunking_strategy"] == "structural_helm"

    def test_routes_generic_yaml(self):
        result = chunk_structured_file(GENERIC_YAML_5_KEYS, "k8s/deployment.yaml")
        assert result is not None
        assert len(result) > 0
        assert result[0]["metadata"]["chunking_strategy"] == "structural_yaml"

    def test_returns_none_for_python(self):
        result = chunk_structured_file("def hello(): pass", "src/main.py")
        assert result is None

    def test_returns_none_for_markdown(self):
        result = chunk_structured_file("# Heading\nSome text", "README.md")
        assert result is None

    def test_returns_none_for_json(self):
        result = chunk_structured_file('{"key": "value"}', "config.json")
        assert result is None

    def test_no_exception_on_empty_file(self):
        result = chunk_structured_file("", "empty.yaml")
        assert result is None or result == []

    def test_no_exception_on_whitespace_file(self):
        result = chunk_structured_file("   \n\n  ", "blank.yaml")
        assert result is None or result == []

    def test_no_exception_on_none_like_content(self):
        # Edge case: YAML that parses to None
        result = chunk_structured_file("---\n", "null.yaml")
        assert result is None or result == []

    def test_tfvars_routes_to_terraform(self):
        tfvars = 'location = "eastus2"\nresource_group = "rg-prod"\n'
        result = chunk_structured_file(tfvars, "env/prod.tfvars")
        # May return None if tfvars doesn't parse well, but must not crash
        assert result is None or isinstance(result, list)


# ─────────────────────────────────────────────────────────────
# Integration with embed_chunks.py
# ─────────────────────────────────────────────────────────────

class TestEmbedChunksIntegration:
    def test_uses_structural_for_yaml(self, tmp_path):
        """_file_to_chunks uses structural chunking for pipeline YAML."""
        from ingest.embed_chunks import _file_to_chunks

        yaml_file = tmp_path / "pipeline.yaml"
        yaml_file.write_text(HARNESS_PIPELINE_3_STAGES, encoding="utf-8")

        chunks = _file_to_chunks(str(yaml_file), str(tmp_path))
        assert len(chunks) == 3
        # All chunks should have structural metadata
        for c in chunks:
            assert c["metadata"].get("chunking_strategy") == "structural_harness"
            assert c["metadata"].get("chunk_type") == "harness_stage"

    def test_falls_back_for_python(self, tmp_path):
        """_file_to_chunks uses fixed-size chunking for .py files."""
        from ingest.embed_chunks import _file_to_chunks

        py_file = tmp_path / "main.py"
        py_file.write_text("x = 1\n" * 200, encoding="utf-8")

        chunks = _file_to_chunks(str(py_file), str(tmp_path))
        assert len(chunks) > 0
        # No structural metadata
        assert chunks[0]["metadata"].get("chunking_strategy") is None

    def test_structural_chunk_has_standard_fields(self, tmp_path):
        """Structural chunks have all standard fields (id, text, metadata.file_path, etc.)."""
        from ingest.embed_chunks import _file_to_chunks

        yaml_file = tmp_path / "pipeline.yaml"
        yaml_file.write_text(HARNESS_PIPELINE_3_STAGES, encoding="utf-8")

        chunks = _file_to_chunks(str(yaml_file), str(tmp_path))
        for c in chunks:
            assert "id" in c
            assert "text" in c
            assert "file_path" in c["metadata"]
            assert "repo" in c["metadata"]
            assert "branch" in c["metadata"]
            assert "chunk_index" in c["metadata"]
            assert "total_chunks" in c["metadata"]

    def test_structural_chunk_has_source_file_normalized(self, tmp_path):
        """source_file in structural chunks uses forward slashes."""
        from ingest.embed_chunks import _file_to_chunks

        sub = tmp_path / "charts" / "svc"
        sub.mkdir(parents=True)
        yaml_file = sub / "values.yaml"
        yaml_file.write_text(HELM_VALUES_4_SERVICES, encoding="utf-8")

        chunks = _file_to_chunks(str(yaml_file), str(tmp_path))
        assert len(chunks) > 0
        for c in chunks:
            assert "\\" not in c["metadata"]["file_path"]

    def test_embed_repo_incremental_compat(self, tmp_path):
        """embed_repo still tracks mtime correctly with structural chunks."""
        from ingest.embed_chunks import embed_repo, _load_embed_state

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pipeline.yaml").write_text(HARNESS_PIPELINE_3_STAGES, encoding="utf-8")

        mem = tmp_path / "mem"
        mem.mkdir()

        result = embed_repo(
            repo_path=str(repo),
            memory_dir=str(mem),
            branch="default",
            collection_name="repo_default",
        )

        assert result["chunk_count"] == 3
        assert result["file_count"] == 1

        # Verify mtime state was saved
        state = _load_embed_state(mem, "repo_default")
        assert "pipeline.yaml" in state

        # Run again — should skip
        result2 = embed_repo(
            repo_path=str(repo),
            memory_dir=str(mem),
            branch="default",
            collection_name="repo_default",
        )
        assert result2["skipped_files"] == 1
        assert result2["chunk_count"] == 0

    def test_falls_back_for_markdown(self, tmp_path):
        """_file_to_chunks uses fixed-size for .md files."""
        from ingest.embed_chunks import _file_to_chunks

        md_file = tmp_path / "README.md"
        md_file.write_text("# Title\n\nSome content\n" * 50, encoding="utf-8")

        chunks = _file_to_chunks(str(md_file), str(tmp_path))
        assert len(chunks) > 0
        assert chunks[0]["metadata"].get("chunking_strategy") is None
        assert chunks[0]["metadata"]["file_type"] == "markdown"

    def test_terraform_file_uses_structural(self, tmp_path):
        """_file_to_chunks uses structural chunking for .tf files."""
        from ingest.embed_chunks import _file_to_chunks

        tf_file = tmp_path / "main.tf"
        tf_file.write_text(TERRAFORM_3_RESOURCES, encoding="utf-8")

        chunks = _file_to_chunks(str(tf_file), str(tmp_path))
        assert len(chunks) > 0
        # Should have structural terraform metadata
        has_structural = any(
            c["metadata"].get("chunking_strategy") == "structural_terraform"
            for c in chunks
        )
        assert has_structural

    def test_helm_values_uses_structural(self, tmp_path):
        """_file_to_chunks uses structural chunking for values.yaml."""
        from ingest.embed_chunks import _file_to_chunks

        values_file = tmp_path / "values.yaml"
        values_file.write_text(HELM_VALUES_4_SERVICES, encoding="utf-8")

        chunks = _file_to_chunks(str(values_file), str(tmp_path))
        assert len(chunks) == 4
        for c in chunks:
            assert c["metadata"].get("chunking_strategy") == "structural_helm"
