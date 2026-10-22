"""Monotone endpoint mappings for the TIGER development split, fitted out-of-fold.

Prespecified in docs/validation/stil-tiger-calibration-spec.md. Pure Python; no
dependence on reference data beyond the arrays passed in.
"""

import math


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _logit(p):
    return math.log(p / (1 - p))


def _sigmoid(z):
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit_log_logit(x, r, offset, clip=(0.5, 99.5)):
    """OLS of logit(r/100) on ln(x + offset) with slope constrained >= 0."""
    _require(len(x) == len(r) and len(x) >= 2, "need paired data")
    _require(offset > 0 and all(v >= 0 for v in x), "features must be nonnegative with a positive offset")
    t = [math.log(v + offset) for v in x]
    z = [_logit(min(max(v, clip[0]), clip[1]) / 100) for v in r]
    mt, mz = sum(t) / len(t), sum(z) / len(z)
    stt = sum((a - mt) ** 2 for a in t)
    b = sum((a - mt) * (c - mz) for a, c in zip(t, z)) / stt if stt > 0 else 0.0
    if b < 0:
        b = 0.0
    a = mz - b * mt
    return {"model": "log_logit", "a": a, "b": b, "offset": offset}


def fit_isotonic(x, r):
    """Increasing pool-adjacent-violators fit; returns block (x, value) knots."""
    _require(len(x) == len(r) and len(x) >= 1, "need paired data")
    pairs = sorted(zip(x, r))
    # Pool exact ties first so each x has one value.
    xs, ws, vs = [], [], []
    for xv, rv in pairs:
        if xs and xs[-1] == xv:
            vs[-1] = (vs[-1] * ws[-1] + rv) / (ws[-1] + 1)
            ws[-1] += 1
        else:
            xs.append(xv)
            ws.append(1)
            vs.append(rv)
    blocks = []  # [x_lo, x_hi, weight, value]
    for xv, w, v in zip(xs, ws, vs):
        blocks.append([xv, xv, w, v])
        while len(blocks) > 1 and blocks[-2][3] > blocks[-1][3]:
            lo, hi = blocks[-2], blocks[-1]
            wsum = lo[2] + hi[2]
            blocks[-2:] = [[lo[0], hi[1], wsum, (lo[3] * lo[2] + hi[3] * hi[2]) / wsum]]
    knots = []
    for lo, hi, _, v in blocks:
        knots.append((lo, v))
        if hi != lo:
            knots.append((hi, v))
    return {"model": "isotonic", "knots": knots}


def predict(model, x):
    if model["model"] == "log_logit":
        return [100 * _sigmoid(model["a"] + model["b"] * math.log(v + model["offset"])) for v in x]
    knots = model["knots"]
    out = []
    for v in x:
        if v <= knots[0][0]:
            out.append(knots[0][1])
        elif v >= knots[-1][0]:
            out.append(knots[-1][1])
        else:
            for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
                if x0 <= v <= x1:
                    out.append(y0 if x1 == x0 else y0 + (y1 - y0) * (v - x0) / (x1 - x0))
                    break
    return out


def fit(model_name, x, r, offset=None):
    if model_name == "log_logit":
        return fit_log_logit(x, r, offset)
    if model_name == "isotonic":
        return fit_isotonic(x, r)
    raise ValueError("unknown model " + model_name)


def cross_fit(ids, x, r, folds, model_name, offset=None):
    """Out-of-fold predictions: for each fold, fit on the others and predict it."""
    _require(len(ids) == len(x) == len(r) == len(folds), "length mismatch")
    oof = {}
    fitted = {}
    for k in sorted(set(folds)):
        train = [i for i, f in enumerate(folds) if f != k]
        test = [i for i, f in enumerate(folds) if f == k]
        m = fit(model_name, [x[i] for i in train], [r[i] for i in train], offset)
        fitted[k] = m
        for i, p in zip(test, predict(m, [x[i] for i in test])):
            oof[ids[i]] = p
    return oof, fitted
