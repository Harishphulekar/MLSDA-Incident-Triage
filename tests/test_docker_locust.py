"""Tests for Docker Compose, Prometheus Config, and Locustfile Integrity."""
import os
import yaml

def test_docker_compose_structure():
    assert os.path.exists("docker-compose.yml")
    with open("docker-compose.yml", "r", encoding="utf-8") as f:
        dc = yaml.safe_load(f)

    services = dc.get("services", {})
    assert "api" in services
    assert "agent-worker" in services
    assert "redis" in services
    assert "vector-db" in services
    assert "prometheus" in services
    assert "grafana" in services
    assert "jaeger" in services

    # Verify at least 4 independent services with healthchecks
    assert len(services) >= 4
    assert "healthcheck" in services["api"]
    assert "healthcheck" in services["redis"]

def test_prometheus_and_grafana_provisioning_files():
    assert os.path.exists("prometheus/prometheus.yml")
    with open("prometheus/prometheus.yml", "r", encoding="utf-8") as f:
        prom = yaml.safe_load(f)
    assert "scrape_configs" in prom

    assert os.path.exists("grafana/provisioning/datasources/datasources.yml")
    assert os.path.exists("grafana/provisioning/dashboards/dashboards.yml")
    assert os.path.exists("grafana/dashboards/incident_triage_dashboard.json")

def test_locustfile_and_scenarios_exist():
    assert os.path.exists("locust/locustfile.py")
    assert os.path.exists("locust/run_load_test.py")
    assert os.path.exists("src/agentops/evaluation/scenarios.json")
