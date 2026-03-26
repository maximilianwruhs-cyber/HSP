import asyncio
import json
import unittest
from collections import OrderedDict

from sonification_pipeline_async import (
    ConnectionManager,
    app,
    apply_control_command,
    control_http,
    get_state,
    map_to_midi,
    parse_escalation_regulator,
    validate_control_payload,
    websocket_auth_token,
)


class _FakeConnection:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.messages = []

    async def send_json(self, message):
        if self.should_fail:
            raise RuntimeError("send failure")
        self.messages.append(message)


class _FakeWebSocket:
    def __init__(self, authorization: str = "", query_token: str = ""):
        self.headers = {"authorization": authorization} if authorization else {}
        self.query_params = {"token": query_token} if query_token else {}


class TestAsyncHardening(unittest.TestCase):
    def setUp(self):
        app.state.control_lock = asyncio.Lock()
        app.state.control_command_results = OrderedDict()
        app.state.control_state_version = 0
        app.state.escalation_regulator = 1.0
        app.state.metrics_source = "local"
        app.state.experience_profile = "night-patrol-techno"
        app.state.latest_payload = {}

    def test_parse_escalation_regulator_clamps(self):
        self.assertAlmostEqual(parse_escalation_regulator(0.1), 0.35)
        self.assertAlmostEqual(parse_escalation_regulator(3.0), 2.5)
        self.assertAlmostEqual(parse_escalation_regulator(1.7), 1.7)

    def test_parse_escalation_regulator_rejects_invalid_values(self):
        self.assertIsNone(parse_escalation_regulator("nan"))
        self.assertIsNone(parse_escalation_regulator("inf"))
        self.assertIsNone(parse_escalation_regulator("not-a-number"))

    def test_websocket_auth_token_prefers_bearer_header(self):
        ws = _FakeWebSocket(authorization="Bearer top-secret", query_token="fallback")
        self.assertEqual(websocket_auth_token(ws), "top-secret")

    def test_websocket_auth_token_uses_query_param(self):
        ws = _FakeWebSocket(query_token="query-secret")
        self.assertEqual(websocket_auth_token(ws), "query-secret")

    def test_validate_control_payload_rejects_unknown_fields(self):
        command, error = validate_control_payload({"command_id": "cmd-1", "mystery": 1})
        self.assertIsNone(command)
        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "unknown_fields")

    def test_validate_control_payload_requires_mutation(self):
        command, error = validate_control_payload({"command_id": "cmd-1"})
        self.assertIsNone(command)
        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "no_mutation_fields")

    def test_validate_control_payload_accepts_normalized_values(self):
        command, error = validate_control_payload(
            {
                "command_id": "cmd-2",
                "escalation_regulator": 1.8,
                "metrics_source": "EXTERNAL",
                "experience_profile": "droid-horror-escalation",
            }
        )
        self.assertIsNone(error)
        self.assertIsNotNone(command)
        self.assertEqual(command["command_id"], "cmd-2")
        self.assertEqual(command["updates"]["metrics_source"], "external")
        self.assertEqual(command["updates"]["experience_profile"], "droid-horror-escalation")

    def test_apply_control_command_is_idempotent_by_command_id(self):
        command, error = validate_control_payload(
            {
                "command_id": "cmd-3",
                "escalation_regulator": 2.0,
                "metrics_source": "external",
            }
        )
        self.assertIsNone(error)
        ack_first = asyncio.run(apply_control_command(command))
        ack_second = asyncio.run(apply_control_command(command))

        self.assertEqual(ack_first["state_version"], 1)
        self.assertFalse(ack_first["deduplicated"])
        self.assertTrue(ack_second["deduplicated"])
        self.assertEqual(ack_second["state_version"], 1)
        self.assertAlmostEqual(app.state.escalation_regulator, 2.0)
        self.assertEqual(app.state.metrics_source, "external")

    def test_disconnect_is_idempotent(self):
        manager = ConnectionManager()
        ws = object()
        manager.active_connections.append(ws)

        manager.disconnect(ws)
        manager.disconnect(ws)

        self.assertEqual(manager.active_connections, [])

    def test_broadcast_prunes_stale_connections(self):
        manager = ConnectionManager()
        good = _FakeConnection(should_fail=False)
        bad = _FakeConnection(should_fail=True)
        manager.active_connections = [good, bad]

        asyncio.run(manager.broadcast({"cpu": 10.0}))

        self.assertEqual(manager.active_connections, [good])
        self.assertEqual(good.messages, [{"cpu": 10.0}])

    def test_map_to_midi_changes_with_experience_profile(self):
        kwargs = {
            "cpu": 81.0,
            "ram": 67.0,
            "gpu": 73.0,
            "use_pitch_bend": True,
            "activity_score": 0.74,
            "phrase_step": 11,
            "iowait_pct": 24.0,
            "disk_busy_pct": 88.0,
        }
        ambient = map_to_midi(experience_profile="calm-observatory-ambient", **kwargs)
        industrial = map_to_midi(experience_profile="high-load-alarm-industrial", **kwargs)
        horror = map_to_midi(experience_profile="droid-horror-escalation", **kwargs)

        self.assertNotEqual(ambient, industrial)
        self.assertNotEqual(industrial, horror)
        self.assertNotEqual(ambient, horror)

    def test_map_to_midi_unknown_profile_falls_back_to_default(self):
        kwargs = {
            "cpu": 58.0,
            "ram": 42.0,
            "gpu": 25.0,
            "use_pitch_bend": True,
            "activity_score": 0.41,
            "phrase_step": 6,
            "iowait_pct": 7.0,
            "disk_busy_pct": 31.0,
        }
        default_mapping = map_to_midi(experience_profile="night-patrol-techno", **kwargs)
        unknown_mapping = map_to_midi(experience_profile="unknown-profile", **kwargs)

        self.assertEqual(unknown_mapping, default_mapping)

    def test_get_state_returns_latest_payload(self):
        app.state.latest_payload = {"cpu": 42.5, "metrics_source": "local"}
        state = asyncio.run(get_state())
        self.assertEqual(state["cpu"], 42.5)
        self.assertEqual(state["metrics_source"], "local")

    def test_get_state_returns_warming_up_when_no_payload(self):
        app.state.latest_payload = {}
        state = asyncio.run(get_state())
        self.assertEqual(state["status"], "warming_up")
        self.assertEqual(state["metrics_source"], "local")

    def test_control_http_returns_ack(self):
        ack = asyncio.run(
            control_http(
                {
                    "command_id": "http-cmd-1",
                    "metrics_source": "external",
                    "escalation_regulator": 1.9,
                }
            )
        )

        self.assertTrue(ack["ok"])
        self.assertEqual(ack["type"], "control_ack")
        self.assertEqual(ack["command_id"], "http-cmd-1")
        self.assertEqual(ack["applied"]["metrics_source"], "external")
        self.assertAlmostEqual(app.state.escalation_regulator, 1.9)
        self.assertEqual(app.state.metrics_source, "external")

    def test_control_http_returns_validation_error(self):
        response = asyncio.run(control_http({"command_id": "http-cmd-2"}))
        self.assertEqual(response.status_code, 400)

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["type"], "control_error")
        self.assertEqual(body["code"], "no_mutation_fields")


if __name__ == "__main__":
    unittest.main()
