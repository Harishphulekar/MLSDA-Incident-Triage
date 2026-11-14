"""Locust Load Testing File for Incident Triage Assistant."""
import json
import random
from locust import HttpUser, task, between

SAMPLE_ALERTS = [
    {
        "alert_payload": "Host postgres-primary-01 disk usage at 88% and climbing steadily. Table and index sizes are not growing.",
        "on_call_notes": "disk filling, cause unknown. Investigating replication lag.",
        "client_id": "locust_load_test"
    },
    {
        "alert_payload": "PostgreSQL error: FATAL: remaining connection slots are reserved for non-replication superuser connections (max_connections reached).",
        "on_call_notes": "Spike in client backend checkout connections.",
        "client_id": "locust_load_test"
    },
    {
        "alert_payload": "Replica postgres-replica-02: replication lag exceeds 350MB. Read traffic serving stale data.",
        "on_call_notes": "Network interface latency elevated between primary and standby.",
        "client_id": "locust_load_test"
    },
    {
        "alert_payload": "Deadlock detected rate > 15/sec on payment transactions.",
        "on_call_notes": "Concurrent invoice settlement workers.",
        "client_id": "locust_load_test"
    }
]

class IncidentTriageUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(5)
    def submit_incident(self):
        payload = random.choice(SAMPLE_ALERTS)
        headers = {
            "Content-Type": "application/json",
            "X-Client-ID": f"client_{random.randint(1, 5)}"
        }
        with self.client.post("/api/v1/incidents", json=payload, headers=headers, catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if "run_id" in data:
                    response.success()
                else:
                    response.failure("Missing run_id in response")
            elif response.status_code == 429:
                # Rate limit is an expected guardrail under heavy load
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")

    @task(2)
    def submit_feedback(self):
        feedback_payload = {
            "run_id": f"run_locust_{random.randint(1, 1000)}",
            "satisfactory": random.choice([True, True, True, False]),
            "reason": "Automated Locust test feedback"
        }
        self.client.post("/api/v1/feedback", json=feedback_payload)

    @task(1)
    def check_health(self):
        self.client.get("/health")

    @task(1)
    def check_metrics(self):
        self.client.get("/metrics")
