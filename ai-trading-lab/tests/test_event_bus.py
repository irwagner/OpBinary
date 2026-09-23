from __future__ import annotations

import unittest

from ai_trading_lab.event_bus import Event, EventBus


class EventBusTests(unittest.TestCase):
    def test_delivers_event_to_subscriber(self) -> None:
        received: list[str] = []
        bus = EventBus()
        bus.subscribe("experiment.created", lambda event: received.append(str(event.payload["id"])))

        result = bus.publish(Event("experiment.created", {"id": "EXP-000001"}))

        self.assertEqual(["EXP-000001"], received)
        self.assertEqual(1, result.delivered)
        self.assertEqual((), result.failures)

    def test_isolates_failing_subscriber(self) -> None:
        received: list[str] = []
        bus = EventBus()

        def broken_handler(event: Event) -> None:
            raise RuntimeError("expected")

        bus.subscribe("state.changed", broken_handler)
        bus.subscribe("state.changed", lambda event: received.append(event.name))

        result = bus.publish(Event("state.changed", {}))

        self.assertEqual(["state.changed"], received)
        self.assertEqual(1, result.delivered)
        self.assertEqual(("broken_handler: RuntimeError",), result.failures)

    def test_unsubscribe_stops_delivery(self) -> None:
        received: list[str] = []
        bus = EventBus()
        unsubscribe = bus.subscribe("event", lambda event: received.append(event.name))

        unsubscribe()
        bus.publish(Event("event", {}))

        self.assertEqual([], received)
