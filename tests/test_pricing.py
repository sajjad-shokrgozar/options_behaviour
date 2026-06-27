"""Tests for src/pricing.py — BS formulas, IV round-trip, parity identity."""
import sys
from pathlib import Path
import math

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pricing import bs_price, bs_delta, iv_from_price, parity_basis, shadow_price


class TestBSPrice:
    def test_call_positive(self):
        p = bs_price(100, 100, 1.0, 0.05, 0.2, "call")
        assert p > 0

    def test_put_positive(self):
        p = bs_price(100, 100, 1.0, 0.05, 0.2, "put")
        assert p > 0

    def test_deep_itm_call(self):
        """Deep ITM call ≈ intrinsic value."""
        S, K, T, r, sigma = 200, 100, 0.001, 0.0, 0.01
        p = bs_price(S, K, T, r, sigma, "call")
        assert abs(p - max(0, S - K)) < 1.0

    def test_call_put_parity_identity(self):
        """C - P = S - K e^{-rT}"""
        S, K, T, r, sigma = 100, 105, 0.5, 0.04, 0.25
        c = bs_price(S, K, T, r, sigma, "call")
        p = bs_price(S, K, T, r, sigma, "put")
        lhs = c - p
        rhs = S - K * math.exp(-r * T)
        assert abs(lhs - rhs) < 1e-8

    def test_invalid_inputs_return_nan(self):
        assert math.isnan(bs_price(0, 100, 1, 0.05, 0.2, "call"))
        assert math.isnan(bs_price(100, 100, -1, 0.05, 0.2, "call"))
        assert math.isnan(bs_price(100, 100, 1, 0.05, 0, "call"))


class TestIVRoundTrip:
    @pytest.mark.parametrize("sigma", [0.05, 0.1, 0.2, 0.4, 0.8, 1.5])
    def test_round_trip_call(self, sigma):
        S, K, T, r = 100, 100, 1.0, 0.03
        price = bs_price(S, K, T, r, sigma, "call")
        iv, flag = iv_from_price(price, S, K, T, r, "call")
        assert flag == "ok", f"IV flag={flag} for sigma={sigma}"
        assert abs(iv - sigma) < 1e-5, f"Round-trip error: {abs(iv-sigma):.2e}"

    @pytest.mark.parametrize("sigma", [0.1, 0.3, 0.6])
    def test_round_trip_put(self, sigma):
        S, K, T, r = 100, 110, 0.5, 0.05
        price = bs_price(S, K, T, r, sigma, "put")
        iv, flag = iv_from_price(price, S, K, T, r, "put")
        assert flag == "ok"
        assert abs(iv - sigma) < 1e-5

    def test_no_arb_flagged(self):
        """Price violating no-arb bounds should return flag='no_arb'."""
        S, K, T, r = 100, 100, 1.0, 0.0
        # Price below intrinsic for call: max(0, S-K) = 0, but try price < 0
        iv, flag = iv_from_price(-1.0, S, K, T, r, "call")
        assert flag in ("no_arb", "invalid_input")

    def test_zero_time_returns_invalid(self):
        iv, flag = iv_from_price(5.0, 100, 100, 0.0, 0.05, "call")
        assert flag == "invalid_input"


class TestParity:
    def test_parity_basis_at_fair_value(self):
        """At fair value with known r, basis should be ~0."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.04, 0.2
        C = bs_price(S, K, T, r, sigma, "call")
        P = bs_price(S, K, T, r, sigma, "put")
        basis = parity_basis(C, P, S, K, T, r)
        assert abs(basis) < 1e-7

    def test_shadow_price_equals_S_at_parity(self):
        S, K, T, r, sigma = 100, 100, 1.0, 0.04, 0.2
        C = bs_price(S, K, T, r, sigma, "call")
        P = bs_price(S, K, T, r, sigma, "put")
        S_star = shadow_price(C, P, K, T, r)
        assert abs(S_star - S) < 1e-7

    def test_parity_nan_on_missing_input(self):
        assert math.isnan(parity_basis(float("nan"), 5, 100, 100, 1, 0.04))


class TestDelta:
    def test_call_delta_between_0_and_1(self):
        d = bs_delta(100, 100, 1.0, 0.04, 0.2, "call")
        assert 0 < d < 1

    def test_put_delta_between_minus1_and_0(self):
        d = bs_delta(100, 100, 1.0, 0.04, 0.2, "put")
        assert -1 < d < 0

    def test_call_put_delta_relation(self):
        """Δ_call - Δ_put = 1."""
        S, K, T, r, sigma = 100, 95, 0.5, 0.05, 0.3
        dc = bs_delta(S, K, T, r, sigma, "call")
        dp = bs_delta(S, K, T, r, sigma, "put")
        assert abs((dc - dp) - 1.0) < 1e-10
