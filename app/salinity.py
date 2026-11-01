"""
Practical salinity from the EC probe and the temperature probe.

The firmware's EC library reports specific conductance at 25 °C, using a
linear compensation of 1.85 % per °C (DFRobot_EC). Practical Salinity Scale
1978 (UNESCO) expects the in-situ conductivity, so that compensation is
removed and PSS-78 is applied at the measured temperature and surface
pressure. The same coefficients are in shellsafev2.ino; keep the two copies
together.

The number is reported as ppt. On this seawater scale it matches practical
salinity (about 2–42 ppt). Fresher water still returns a small number; it is
not a laboratory salinity below 2 ppt.
"""

import math
from typing import Optional

# Must match DFRobot_EC::readEC and salinityPsu() in the firmware.
EC_COMP_PER_C = 0.0185
# Conductivity of standard seawater, S = 35, T = 15 °C, P = 0.
_C35_15_MS = 42.914
_A = (0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081)
_B = (0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144)
_K = 0.0162


def _half_powers(coeffs, rt: float) -> float:
    root = math.sqrt(rt)
    power = 1.0
    total = 0.0
    for coeff in coeffs:
        total += coeff * power
        power *= root
    return total


def practical_salinity(conductivity_mS: float, temp_c: float) -> Optional[float]:
    """PSS-78 salinity from in-situ conductivity (mS/cm) and temperature (°C)."""
    if conductivity_mS <= 0 or temp_c < -2 or temp_c > 40:
        return 0.0 if conductivity_mS <= 0 else None
    ratio = conductivity_mS / _C35_15_MS
    t2 = temp_c * temp_c
    rt = (
        0.6766097
        + 2.00564e-2 * temp_c
        + 1.104259e-4 * t2
        - 6.9698e-7 * t2 * temp_c
        + 1.0031e-9 * t2 * t2
    )
    if rt <= 0:
        return None
    rt_ratio = ratio / rt
    if rt_ratio <= 0:
        return 0.0
    delta = temp_c - 15.0
    salinity = _half_powers(_A, rt_ratio) + (delta / (1.0 + _K * delta)) * _half_powers(_B, rt_ratio)
    if salinity < 0:
        return 0.0
    if salinity > 50:
        return None
    return salinity


def salinity_psu(ec_uS_cm: Optional[float], temp_c: Optional[float]) -> Optional[float]:
    """
    Salinity (ppt) from specific conductance at 25 °C (µS/cm) and water
    temperature (°C). Returns None when an input is missing or out of range.
    """
    if ec_uS_cm is None or temp_c is None:
        return None
    try:
        ec = float(ec_uS_cm)
        temp = float(temp_c)
    except (TypeError, ValueError):
        return None
    if ec < 0 or temp < -2 or temp > 40:
        return None
    insitu_mS = (ec / 1000.0) * (1.0 + EC_COMP_PER_C * (temp - 25.0))
    return practical_salinity(insitu_mS, temp)
