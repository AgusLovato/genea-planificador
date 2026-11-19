"""Tests de la capa de servicio: contrato de entradas y salidas y manejo de errores."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def test_health(cliente):
    r = cliente.get("/api/health")
    assert r.status_code == 200 and r.json()["estado"] == "ok" and r.json()["paises"] == 65


def test_modelo_describe_pesos_y_reglas(cliente):
    d = cliente.get("/api/modelo").json()
    assert len(d["pesos_variables"]) == 11
    assert len(d["regla_seleccion_modelo"]) == 4 and len(d["orden_preparacion"]) == 6


def test_paises_y_filtros(cliente):
    assert cliente.get("/api/paises").json()["cantidad"] == 65
    p1 = cliente.get("/api/paises", params={"prioridad": 1}).json()
    assert p1["cantidad"] == 11 and p1["paises"][0]["codigo"] == "US"
    assert cliente.get("/api/paises", params={"prioridad": 7}).status_code == 422


def test_ficha(cliente):
    f = cliente.get("/api/paises/ar").json()
    assert f["pais"] == "Argentina" and f["ranking"]["puesto"] == 18
    assert [p["codigo"] for p in f["puentes"]] == ["ES", "CO", "UY"]
    r = cliente.get("/api/paises/XX")
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "no_encontrado"


def test_ficha_pais_sin_datos(cliente):
    f = cliente.get("/api/paises/TW").json()
    assert f["en_modelo"] is False


def test_ranking_con_pesos(cliente):
    r = cliente.post("/api/ranking", json={"pesos": {"mercado": 1, "diversidad_origen": 1, "conectividad": 1, "poblacion": 1, "mayores65_pct": 1}})
    d = r.json()
    assert r.status_code == 200 and len(d["paises"]) == 65
    assert abs(sum(d["pesos_normalizados"].values()) - 1) < 1e-9


@pytest.mark.parametrize("cuerpo,campo", [
    ({"pesos": {"mercado": -1}}, "pesos.mercado"),
    ({"pesos": {"precio": 1}}, "pesos.precio"),
    ({"pesos": {"mercado": "mucho"}}, "pesos.mercado"),
    ({"simulaciones": 5}, "simulaciones"),
])
def test_ranking_errores(cliente, cuerpo, campo):
    r = cliente.post("/api/ranking", json=cuerpo)
    assert r.status_code == 422
    assert any(d["campo"] == campo for d in r.json()["error"]["detalles"])


def test_evaluar_escenario(cliente):
    r = cliente.post("/api/evaluar", json={"base_codigo": "AR", "pais": {"pbi_pc_ppa": 45000, "internet_pct": 95}})
    d = r.json()
    assert r.status_code == 200 and d["segmento"]["nombre"] == "Conectados y diversos"
    assert d["comparacion_original"]["puesto"] == 18 and d["ranking"]["de"] == 65


def test_evaluar_pais_nuevo_con_imputacion(cliente):
    r = cliente.post("/api/evaluar", json={"pais": {"nombre": "Nuevo", "region": "Europa y Asia Central", "income": "alto"}})
    d = r.json()
    assert r.status_code == 200 and d["calidad"] == "baja" and d["ranking"]["de"] == 66
    assert all(a["tipo"] == "imputado_region" for a in d["avisos"])


@pytest.mark.parametrize("pais,campo", [
    ({"internet_pct": 140}, "internet_pct"),
    ({"income": "millonario"}, "income"),
    ({"pbi_pc_ppa": "abc"}, "pbi_pc_ppa"),
    ({"color": "azul"}, "pais.color"),
])
def test_evaluar_errores(cliente, pais, campo):
    r = cliente.post("/api/evaluar", json={"base_codigo": "AR", "pais": pais})
    assert r.status_code == 422
    assert any(d["campo"] == campo for d in r.json()["error"]["detalles"])


def test_json_invalido(cliente):
    r = cliente.post("/api/evaluar", content="{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "pedido_invalido"


def test_apellidos(cliente):
    d = cliente.get("/api/apellidos/Varela").json()
    assert d["cantidad_paises"] == 5
    r = cliente.get("/api/apellidos/Ezcurra")
    assert r.status_code == 404
    assert "Lovato" in cliente.get("/api/apellidos", params={"q": "lova"}).json()["sugerencias"]


def test_web_se_sirve(cliente):
    assert cliente.get("/").status_code == 200
