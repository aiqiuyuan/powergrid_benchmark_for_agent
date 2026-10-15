"""Bounded local droop starter; one independent instance per PV inverter."""


class Controller:
    def __init__(self, metadata):
        self.bound = metadata["action_bound"]
        self.gain = 1.0

    def act(self, observation):
        voltage = observation["pv_voltage_pu"][0]
        return [max(-self.bound, min(self.bound, self.gain * (1.0 - voltage)))]
