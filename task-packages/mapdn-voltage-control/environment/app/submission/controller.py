"""Local voltage droop starter; one independent instance per assigned actor."""


class Controller:
    def __init__(self, metadata):
        self.bound = metadata["action_bound"]
        self.gain = metadata.get("droop_gain", 2.0)
        self.target = metadata.get("target_voltage_pu", 1.0)
        self.pv_count = metadata["pv_count"]

    def act(self, observation):
        voltages = observation["pv_voltage_pu"]
        if len(voltages) != self.pv_count:
            raise ValueError("Expected one current voltage per assigned PV")
        return [
            max(-self.bound, min(self.bound, self.gain * (self.target - voltage)))
            for voltage in voltages
        ]
