"""
Benchmark Questions — All 30 benchmark questions with tool sequences and validators

Each question defines:
    - id, category, question text
    - tool_calls: ordered list of tool calls to execute
    - expected_tools: which tools the question SHOULD route to
    - validators: checks applied to accumulated results for scoring

Scoring rubric:
    3 = correct result + file citation + correct file path
    2 = correct result + file citation (wrong/missing path detail)
    1 = correct result only (no citation)
    0 = wrong or missing result

Tool call format:
    {"tool": "<tool_name>", "args": {<kwargs>}}

    Special arg values:
    - "$SKELETON_ID"  → replaced with skeleton_id from most recent hti_get_skeleton result
    - "$CLIENT"       → replaced with the active client name

Validator types:
    - has_results:       at least one tool returned non-empty results
    - file_in_results:   a file path pattern appears in accumulated result text
    - content_matches:   ALL listed patterns appear in accumulated result text
    - content_any:       AT LEAST ONE listed pattern appears in result text
    - result_count_gte:  a numeric count extracted from results >= threshold
    - no_error:          no tool returned an error
"""

BENCHMARK_QUESTIONS = [
    # -------------------------------------------------------------------------
    # CATEGORY A — HTI Structural Queries (target: 88-95%)
    # -------------------------------------------------------------------------
    {
        "id": "A1",
        "category": "A_HTI_Structural",
        "question": "What are all the steps in the Deploy stage of cd_deploy_env pipeline?",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_path": "cd_deploy_env/pipeline.yaml",
                    "file_type": "harness",
                },
            },
            {
                "tool": "hti_fetch_nodes",
                "args": {
                    "skeleton_id": "$SKELETON_ID",
                    "node_paths": "root.pipeline.stages",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "file_in_results", "value": "cd_deploy_env/pipeline.yaml"},
            {"type": "content_any", "patterns": ["stage", "stages", "deploy", "step"]},
        ],
    },
    {
        "id": "A2",
        "category": "A_HTI_Structural",
        "question": "Show all approval gates across all Harness pipelines",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_type": "harness",
                    "file_path": "cd",
                    "max_skeletons": 10,
                },
            },
            {
                "tool": "hti_fetch_nodes",
                "args": {
                    "skeleton_id": "$SKELETON_ID",
                    "node_paths": "root.pipeline.stages",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["approv", "Approval", "HarnessApproval", "stage"]},
        ],
    },
    {
        "id": "A3",
        "category": "A_HTI_Structural",
        "question": "What pipeline variables are defined in cd_deploy_env?",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_path": "cd_deploy_env/pipeline.yaml",
                    "file_type": "harness",
                },
            },
            {
                "tool": "hti_fetch_nodes",
                "args": {
                    "skeleton_id": "$SKELETON_ID",
                    "node_paths": "root.pipeline.variables",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "file_in_results", "value": "cd_deploy_env/pipeline.yaml"},
            {"type": "content_any", "patterns": ["variable", "variables", "name"]},
        ],
    },
    {
        "id": "A4",
        "category": "A_HTI_Structural",
        "question": "What are the CPU and memory limits for presentation-service in Helm?",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "repo": "newAd_Artifacts",
                    "file_path": "presentation-service",
                    "file_type": "helm",
                },
            },
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "presentation-service CPU memory limits resources",
                    "top_k": 5,
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "resource", "limits", "cpu", "memory", "presentation-service",
                "BestEffort",
            ]},
        ],
    },
    {
        "id": "A5",
        "category": "A_HTI_Structural",
        "question": "What Terraform variables are defined in Eastwood-terraform main?",
        "tool_calls": [
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "variables.tf",
                    "repo": "Eastwood-terraform",
                },
            },
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "repo": "Eastwood-terraform",
                    "file_type": "terraform",
                    "max_skeletons": 50,
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["variable", "variables.tf", "layer"]},
        ],
    },
    {
        "id": "A6",
        "category": "A_HTI_Structural",
        "question": "What is the rollback strategy for presentation-service deployment?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "presentation-service rollback strategy deployment",
                    "top_k": 5,
                },
            },
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_path": "rollout",
                    "file_type": "harness",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "rollback", "rollout", "presentation-service", "strategy",
            ]},
        ],
    },
    {
        "id": "A7",
        "category": "A_HTI_Structural",
        "question": "What stages run in parallel in the cd_deploy_env versioning stage?",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_path": "cd_deploy_env/pipeline.yaml",
                    "file_type": "harness",
                },
            },
            {
                "tool": "hti_fetch_nodes",
                "args": {
                    "skeleton_id": "$SKELETON_ID",
                    "node_paths": "root.pipeline.stages[0]",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "file_in_results", "value": "cd_deploy_env/pipeline.yaml"},
            {"type": "content_any", "patterns": ["parallel", "version", "stage"]},
        ],
    },
    {
        "id": "A8",
        "category": "A_HTI_Structural",
        "question": "What are the liveness probe settings for tagging-service?",
        "tool_calls": [
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "repo": "newAd_Artifacts",
                    "file_path": "tagging-service",
                },
            },
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "tagging-service liveness probe settings",
                    "top_k": 5,
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "livenessProbe", "liveness", "probe", "failureThreshold",
                "periodSeconds", "tagging-service",
            ]},
        ],
    },
    {
        "id": "A9",
        "category": "A_HTI_Structural",
        "question": "What outputs are defined in Eastwood-terraform?",
        "tool_calls": [
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "outputs.tf",
                    "repo": "Eastwood-terraform",
                },
            },
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "repo": "Eastwood-terraform",
                    "file_type": "terraform",
                    "file_path": "outputs.tf",
                    "max_skeletons": 50,
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["output", "outputs.tf"]},
        ],
    },
    {
        "id": "A10",
        "category": "A_HTI_Structural",
        "question": "What connectors does Orchestrator pipeline use?",
        "tool_calls": [
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "orchestrator",
                    "file_type": "pipeline",
                },
            },
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "file_path": "orchestrator",
                    "file_type": "harness",
                },
            },
        ],
        "expected_tools": ["hti_get_skeleton", "hti_fetch_nodes"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "connector", "orchestrator", "pipeline",
            ]},
        ],
    },

    # -------------------------------------------------------------------------
    # CATEGORY B — ChromaDB/BM25 Broad Search (target: 65-75%)
    # -------------------------------------------------------------------------
    {
        "id": "B1",
        "category": "B_Broad_Search",
        "question": "Which services have blue-green deployment configured?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "blue-green deployment service",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["blue-green", "blue_green", "frontend"]},
        ],
    },
    {
        "id": "B2",
        "category": "B_Broad_Search",
        "question": "Which services have readinessProbe configured?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "readinessProbe configured",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["readinessProbe", "readiness"]},
        ],
    },
    {
        "id": "B3",
        "category": "B_Broad_Search",
        "question": "Which pipelines reference the acreus2npdeswdalec container registry?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "acreus2npdeswdalec container registry pipeline",
                    "top_k": 10,
                },
            },
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "acreus2npdeswdalec",
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": ["acreus2npdeswdalec", "acr", "registry"]},
        ],
    },
    {
        "id": "B4",
        "category": "B_Broad_Search",
        "question": "Find all services that reference KeyVault in their Helm charts",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "KeyVault Helm chart service secret",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "keyvault", "key_vault", "KeyVault", "secret",
            ]},
        ],
    },
    {
        "id": "B5",
        "category": "B_Broad_Search",
        "question": "Which services have different replica counts for QA vs production?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "replica count QA production environment",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "replica", "replicaCount", "hpa", "autoscal",
            ]},
        ],
    },
    {
        "id": "B6",
        "category": "B_Broad_Search",
        "question": "Find services with JVM memory configuration",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "JVM memory MaxRAMPercentage JAVA_OPTS Xmx",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "MaxRAMPercentage", "JAVA_OPTS", "jvm", "Xmx", "memory",
            ]},
        ],
    },
    {
        "id": "B7",
        "category": "B_Broad_Search",
        "question": "Which pipelines use the sledgehammer versioning template?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "sledgehammer versioning template pipeline",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "sledgehammer", "versioning", "template",
            ]},
        ],
    },
    {
        "id": "B8",
        "category": "B_Broad_Search",
        "question": "Find all Azure Service Bus configurations across repos",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "Azure Service Bus servicebus queue topic namespace",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "servicebus", "service_bus", "ServiceBus", "queue", "topic",
            ]},
        ],
    },
    {
        "id": "B9",
        "category": "B_Broad_Search",
        "question": "Which services mount secrets from KeyVault via CSI driver?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "CSI driver KeyVault secret mount volume",
                    "top_k": 10,
                },
            },
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "csi",
                },
            },
        ],
        "expected_tools": ["query_memory", "get_secret_flow"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "csi", "CSI", "secretProvider", "keyvault", "secret",
            ]},
        ],
    },
    {
        "id": "B10",
        "category": "B_Broad_Search",
        "question": "Which services have New Relic monitoring configured?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "New Relic monitoring newrelic agent configuration",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "newrelic", "new_relic", "NewRelic", "NR_", "NEW_RELIC",
            ]},
        ],
    },

    # -------------------------------------------------------------------------
    # CATEGORY C — Cross-repo Dependencies (target: 70-80%)
    # -------------------------------------------------------------------------
    {
        "id": "C1",
        "category": "C_Cross_Repo",
        "question": "If I change tagging-service, what other services are affected?",
        "tool_calls": [
            {
                "tool": "impact_analysis",
                "args": {
                    "client": "$CLIENT",
                    "entity": "tagging-service",
                },
            },
        ],
        "expected_tools": ["impact_analysis"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "affected", "tagging-service", "risk",
            ]},
        ],
    },
    {
        "id": "C2",
        "category": "C_Cross_Repo",
        "question": "What does presentation-service depend on?",
        "tool_calls": [
            {
                "tool": "query_graph",
                "args": {
                    "client": "$CLIENT",
                    "entity": "presentation-service",
                    "direction": "out",
                    "depth": 2,
                },
            },
            {
                "tool": "get_entity",
                "args": {
                    "client": "$CLIENT",
                    "name": "presentation-service",
                },
            },
        ],
        "expected_tools": ["query_graph", "get_entity"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "presentation-service", "depend", "edge", "outbound",
            ]},
        ],
    },
    {
        "id": "C3",
        "category": "C_Cross_Repo",
        "question": "How does tagging-service get its database credentials?",
        "tool_calls": [
            {
                "tool": "get_secret_flow",
                "args": {
                    "client": "$CLIENT",
                    "secret": "tagging-service",
                },
            },
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "tagging-service database credentials secret PostgreSQL",
                    "top_k": 5,
                },
            },
        ],
        "expected_tools": ["get_secret_flow"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "secret", "credential", "database", "postgres",
                "keyvault", "key_vault", "tagging",
            ]},
        ],
    },
    {
        "id": "C4",
        "category": "C_Cross_Repo",
        "question": "Which Harness pipelines deploy presentation-service?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "pipeline deploy presentation-service presentation_service",
                    "top_k": 10,
                },
            },
            {
                "tool": "search_files",
                "args": {
                    "client": "$CLIENT",
                    "query": "presentation",
                    "file_type": "pipeline",
                },
            },
        ],
        "expected_tools": ["get_pipeline", "query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "presentation", "pipeline", "deploy",
            ]},
        ],
    },
    {
        "id": "C5",
        "category": "C_Cross_Repo",
        "question": "What Azure resources does Eastwood-terraform create?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "Eastwood-terraform Azure resource azurerm",
                    "top_k": 10,
                },
            },
            {
                "tool": "hti_get_skeleton",
                "args": {
                    "client": "$CLIENT",
                    "repo": "Eastwood-terraform",
                    "file_type": "terraform",
                    "max_skeletons": 20,
                },
            },
        ],
        "expected_tools": ["query_memory", "hti_get_skeleton"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "azurerm", "resource", "terraform", "layer",
            ]},
        ],
    },
    {
        "id": "C6",
        "category": "C_Cross_Repo",
        "question": "What changed in Harness pipelines between release_26_2 and release_26_3?",
        "tool_calls": [
            {
                "tool": "diff_branches",
                "args": {
                    "client": "$CLIENT",
                    "repo": "dfin-harness-pipelines",
                    "base": "release_26_2",
                    "compare": "release_26_3",
                },
            },
        ],
        "expected_tools": ["diff_branches"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "added", "modified", "deleted", "changed", "diff",
            ]},
        ],
    },
    {
        "id": "C7",
        "category": "C_Cross_Repo",
        "question": "Which services share the same managed identity in Eastwood-terraform?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "managed identity workload identity shared services Eastwood-terraform",
                    "top_k": 10,
                },
            },
            {
                "tool": "impact_analysis",
                "args": {
                    "client": "$CLIENT",
                    "entity": "managed-identity",
                    "repo": "Eastwood-terraform",
                },
            },
        ],
        "expected_tools": ["query_memory", "impact_analysis"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "identity", "managed_identity", "workload_identity", "service",
            ]},
        ],
    },
    {
        "id": "C8",
        "category": "C_Cross_Repo",
        "question": "Show me everything HiveMind knows about sifi-adapter",
        "tool_calls": [
            {
                "tool": "get_entity",
                "args": {
                    "client": "$CLIENT",
                    "name": "k8s_secret:sifi-adapter-secrets",
                },
            },
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "sifi-adapter service configuration deployment",
                    "top_k": 10,
                },
            },
            {
                "tool": "impact_analysis",
                "args": {
                    "client": "$CLIENT",
                    "entity": "sifi-adapter",
                },
            },
        ],
        "expected_tools": ["get_entity", "query_memory", "impact_analysis"],
        "validators": [
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "sifi-adapter", "sifi_adapter",
            ]},
        ],
    },
    {
        "id": "C9",
        "category": "C_Cross_Repo",
        "question": "Which services use the ACR connector in their pipelines?",
        "tool_calls": [
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "ACR connector pipeline container registry",
                    "top_k": 10,
                },
            },
            {
                "tool": "query_graph",
                "args": {
                    "client": "$CLIENT",
                    "entity": "acr",
                    "direction": "in",
                    "depth": 2,
                },
            },
        ],
        "expected_tools": ["query_memory", "query_graph"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "acr", "ACR", "connector", "registry", "container",
            ]},
        ],
    },
    {
        "id": "C10",
        "category": "C_Cross_Repo",
        "question": "What would break if the newAd Helm chart values changed?",
        "tool_calls": [
            {
                "tool": "impact_analysis",
                "args": {
                    "client": "$CLIENT",
                    "entity": "newAd_Artifacts",
                    "depth": 3,
                },
            },
            {
                "tool": "query_memory",
                "args": {
                    "client": "$CLIENT",
                    "query": "newAd_Artifacts Helm chart values dependency",
                    "top_k": 10,
                },
            },
        ],
        "expected_tools": ["impact_analysis", "query_memory"],
        "validators": [
            {"type": "no_error"},
            {"type": "has_results"},
            {"type": "content_any", "patterns": [
                "affected", "service", "chart", "helm", "impact",
                "newAd", "newad",
            ]},
        ],
    },
]


def get_questions_by_category(category_prefix: str) -> list:
    """Filter questions by category prefix (e.g. 'A', 'B', 'C')."""
    return [q for q in BENCHMARK_QUESTIONS if q["id"].startswith(category_prefix)]


def get_question_by_id(qid: str) -> dict | None:
    """Get a single question by its ID."""
    for q in BENCHMARK_QUESTIONS:
        if q["id"] == qid:
            return q
    return None
