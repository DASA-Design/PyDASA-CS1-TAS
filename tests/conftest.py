# -*- coding: utf-8 -*-
"""
Module conftest.py
==================

Shared pytest fixtures for the whole test tree. Fixtures are lazy and scoped so files that do not depend on them pay no runtime cost.

Dimensional / PyDASA fixtures (used by `tests/dimensional/`):

    - `method_cfg` / `dflt_profile` / `opti_profile`: session-scoped JSON loads.
    - `schema` / `tas1_vars` / `engine_bare` / `engine_ready`: module-scoped PyDASA build steps for TAS_{1}.
    - `sensitivity_results`: module-scoped, derived from `engine_ready`.

Experimental fixtures (used by `tests/experimental/`):

    - `sample_jsonl_record`: one canonical per-request flow record.
    - `sample_envelope`: one canonical apparatus-envelope dict.
    - `sample_csv_columns` / `sample_csv_row`: standard per-service CSV column schema + row.
    - `make_desc`: factory that builds `ServiceDescription` instances.
    - `fastapi_healthz_app` / `flask_healthz_app`: tiny `/healthz` apps for transport / runtime tests.
"""
# native python modules
from __future__ import annotations

import json
from pathlib import Path

# data types
from typing import Any, Callable, Dict, Tuple

# testing framework
import pytest

# web stack
from fastapi import FastAPI
from flask import Flask, jsonify

# pydasa library
from pydasa import AnalysisEngine
from pydasa.dimensional.vaschy import Schema

# local modules
from src.dimensional import (analyse_symbolic,
                             build_engine,
                             build_schema,
                             derive_coefs)
from src.experimental.common.registry.description import ServiceDescription


_ROOT = Path(__file__).resolve().parents[1]
_METHOD_DIM = _ROOT / "data" / "config" / "method" / "dimensional.json"
_DFLT_PATH = _ROOT / "data" / "config" / "profile" / "dflt.json"
_OPTI_PATH = _ROOT / "data" / "config" / "profile" / "opti.json"

SVC_COLUMNS = [
    "req_id",
    "srv_name",
    "kind",
    "recv_ts",
    "start_ts",
    "local_end_ts",
    "end_ts",
    "c_used_at_start",
    "success",
    "status_code",
    "size_bytes",
]


# ---- Dimensional / PyDASA fixtures ----

@pytest.fixture(scope="session")
def method_cfg() -> Dict[str, Any]:
    """*method_cfg()* `data/config/method/dimensional.json` parsed once per session."""
    return json.loads(_METHOD_DIM.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def dflt_profile() -> Dict[str, Any]:
    """*dflt_profile()* `data/config/profile/dflt.json` parsed once per session."""
    return json.loads(_DFLT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def opti_profile() -> Dict[str, Any]:
    """*opti_profile()* `data/config/profile/opti.json` parsed once per session."""
    return json.loads(_OPTI_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema(method_cfg: Dict[str, Any]) -> Schema:
    """*schema()* PyDASA `Schema` built from `method_cfg["fdus"]`, module-cached."""
    return build_schema(method_cfg["fdus"])


@pytest.fixture(scope="module")
def tas1_vars(dflt_profile: Dict[str, Any]) -> Dict[str, Any]:
    """*tas1_vars()* `dflt_profile["artifacts"]["TAS_{1}"]["vars"]`, module-cached."""
    return dflt_profile["artifacts"]["TAS_{1}"]["vars"]


@pytest.fixture(scope="module")
def engine_bare(schema: Schema,
                tas1_vars: Dict[str, Any]) -> AnalysisEngine:
    """*engine_bare()* TAS_{1} engine with variables attached but BEFORE `run_analysis()`."""
    return build_engine("TAS_{1}", tas1_vars, schema)


@pytest.fixture(scope="module")
def engine_ready(schema: Schema,
                 tas1_vars: Dict[str, Any],
                 method_cfg: Dict[str, Any]) -> Tuple[AnalysisEngine, Dict[str, Any]]:
    """*engine_ready()* `(engine, derived)` after `run_analysis()` + `derive_coefs()` with every setpoint evaluated; `derived` is the 4-entry dict returned by `derive_coefs`."""
    _eng = build_engine("TAS_{1}", tas1_vars, schema)
    _eng.run_analysis()
    # raw Pi-groups need an explicit setpoint pass; PyDASA leaves them lazy after run_analysis
    for _c in _eng.coefficients.values():
        _c.calculate_setpoint()
    _der = derive_coefs(_eng, method_cfg["coefficients"],
                        artifact_key="TAS_{1}")
    for _c in _der.values():
        _c.calculate_setpoint()
    return _eng, _der


@pytest.fixture(scope="module")
def sensitivity_results(engine_ready: Tuple[AnalysisEngine, Dict[str, Any]],
                        schema: Schema,
                        method_cfg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """*sensitivity_results()* `analyse_symbolic(engine, schema, val_type, cat)` over `engine_ready[0]`, module-cached."""
    _eng, _ = engine_ready
    _sc = method_cfg["sensitivity"]
    return analyse_symbolic(_eng, schema,
                            val_type=_sc["val_type"],
                            cat=_sc["cat"])


# ---- Experimental fixtures ----

@pytest.fixture
def sample_jsonl_record() -> dict[str, Any]:
    """Return one canonical per-request flow record.

    Returns:
        dict[str, Any]: dict with the fields a real flow record carries.
    """
    _record: dict[str, Any] = {
        "req_id": "u47-r0312",
        "kind": "medical_analysis",
        "client_id": "user-42",
        "submitted_ts": 1736282400.123456,
        "completed_ts": 1736282400.139201,
        "outcome": "success",
        "total_latency_s": 0.015745,
    }
    return _record


@pytest.fixture
def sample_envelope() -> dict[str, Any]:
    """Return one canonical apparatus-envelope dict.

    Returns:
        dict[str, Any]: minimal envelope with host_profile + timer fields.
    """
    _env: dict[str, Any] = {
        "host_profile": {"os": "Windows"},
        "timer": {"median_ns": 100},
    }
    return _env


@pytest.fixture
def sample_csv_columns() -> list[str]:
    """Return the standard per-service CSV column schema.

    Returns:
        list[str]: column names matching the LOG_COLUMNS schema.
    """
    return list(SVC_COLUMNS)


@pytest.fixture
def sample_csv_row() -> dict[str, Any]:
    """Return one canonical per-service invocation row.

    Returns:
        dict[str, Any]: dict whose keys match `sample_csv_columns`.
    """
    _row: dict[str, Any] = {
        "req_id": "u47-r0312",
        "srv_name": "TAS_{1}",
        "kind": "medical_analysis",
        "recv_ts": 1736282400.124,
        "start_ts": 1736282400.125,
        "local_end_ts": 1736282400.138,
        "end_ts": 1736282400.139,
        "c_used_at_start": 3,
        "success": True,
        "status_code": 200,
        "size_bytes": 1024,
    }
    return _row


@pytest.fixture
def make_desc() -> Callable[..., ServiceDescription]:
    """Return a factory that builds `ServiceDescription` instances with sensible defaults.

    Returns:
        Callable[..., ServiceDescription]: factory accepting `name` (str) and optional `port` (int, default 8001), `operations` (tuple, default `("op_a", "op_b")`), and `custom_props` (dict, default `{"failure_rate": 0.05}` when None is passed).
    """
    def _factory(
        name: str,
        port: int = 8001,
        operations: tuple[str, ...] = ("op_a", "op_b"),
        custom_props: dict[str, Any] | None = None,
    ) -> ServiceDescription:
        """Build one `ServiceDescription` with apparatus-friendly defaults.

        Args:
            name (str): service name (also used to derive `_id` as `id-<name>`).
            port (int, optional): TCP port for the synthesised endpoint URL. Defaults to 8001.
            operations (tuple[str, ...], optional): supported operation names. Defaults to `("op_a", "op_b")`.
            custom_props (dict[str, Any] | None, optional): QoS hints. Defaults to None, which expands to `{"failure_rate": 0.05}`.

        Returns:
            ServiceDescription: a frozen dataclass instance ready to register with `ServiceRegistry`.
        """
        if custom_props is None:
            _props = {"failure_rate": 0.05}
        else:
            _props = custom_props
        _desc = ServiceDescription(
            _id=f"id-{name}",
            name=name,
            endpoint=f"http://127.0.0.1:{port}",
            operations=operations,
            custom_props=_props,
        )
        return _desc
    return _factory


@pytest.fixture
def fastapi_healthz_app() -> FastAPI:
    """Build a FastAPI app exposing a single `/healthz` endpoint.

    Routes are registered via `add_api_route` (not the `@app.get` decorator) so the static analyser sees the handler as referenced.

    Returns:
        FastAPI: configured app whose `/healthz` returns `{"status": "ok"}`.
    """
    _app = FastAPI()

    def _healthz_handler() -> dict[str, str]:
        return {"status": "ok"}

    _app.add_api_route("/healthz",
                       _healthz_handler,
                       methods=["GET"])
    return _app


@pytest.fixture
def flask_healthz_app() -> Flask:
    """Build a Flask app exposing a single `/healthz` endpoint.

    Returns:
        Flask: configured app whose `/healthz` returns `{"status": "ok"}` as JSON.
    """
    _app = Flask(__name__)

    def _healthz_handler() -> Any:  # noqa: ANN401  (Flask response type is Any-ish)
        return jsonify({"status": "ok"})

    _app.add_url_rule("/healthz",
                      view_func=_healthz_handler,
                      methods=["GET"])
    return _app
