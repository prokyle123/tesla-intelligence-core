"""GENESIS toy-fleet model improvement is offline, bounded and entirely synthetic."""
import unittest
from genesis.hivemind import MIN_COHORT, PrivacyGate
from genesis.fleet_simulator import simulate_fleet

class SyntheticFleetTests(unittest.TestCase):
    def test_toy_global_model_improves_on_holdout_without_network(self):
        result = simulate_fleet(vehicles=32, rounds=30, seed=19)
        self.assertTrue(result["improved"])
        self.assertLess(result["final_mae"], result["baseline_mae"] * .2)
        self.assertFalse(result["network_enabled"])
        self.assertFalse(result["publishable"])
        self.assertFalse(result["real_vehicle_data"])
        self.assertFalse(result["secure_aggregation"])
        self.assertFalse(result["differential_privacy"])
        self.assertEqual(len(result["learning_curve"]), 31)

    def test_repeatable_and_no_input_telemetry(self):
        self.assertEqual(simulate_fleet(vehicles=MIN_COHORT, rounds=10),
                         simulate_fleet(vehicles=MIN_COHORT, rounds=10))

    def test_cohort_and_compute_boundaries(self):
        with self.assertRaises(PrivacyGate):
            simulate_fleet(vehicles=MIN_COHORT-1)
        with self.assertRaises(PrivacyGate):
            simulate_fleet(vehicles=201)
        with self.assertRaises(ValueError):
            simulate_fleet(rounds=101)

if __name__ == "__main__":
    unittest.main()
