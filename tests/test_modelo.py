"""Tests de la lógica del modelo: paridad con el TP3 y robustez ante datos nuevos."""
import json
from pathlib import Path

import pandas as pd
import pytest

from genea import BuscadorApellidos, DatosInvalidos, ModeloGenea, NoEncontrado

REF = Path(__file__).resolve().parents[1] / "docs" / "referencia_tp3"


@pytest.fixture(scope="module")
def modelo():
    return ModeloGenea()


@pytest.fixture(scope="module")
def buscador(modelo):
    return BuscadorApellidos(modelo)


@pytest.fixture(scope="module")
def ranking_tp3():
    return pd.read_csv(REF / "ranking_mercados.csv", index_col="country_code", keep_default_na=False)


# ---------------------------------------------------------------- paridad con el TP3

def test_reproduce_puntajes_y_puestos_del_tp3(modelo, ranking_tp3):
    r = modelo.ranking_base.loc[ranking_tp3.index]
    assert (r["puntaje"] - ranking_tp3["puntaje"]).abs().max() < 1e-9
    assert (r["puesto"] == ranking_tp3["puesto"]).all()


def test_reproduce_sensibilidad_y_prioridades_del_tp3(modelo, ranking_tp3):
    r = modelo.ranking_base.loc[ranking_tp3.index]
    assert (r["puesto_mediano"] == ranking_tp3["puesto mediano"]).all()
    assert (r["prob_top10"] - ranking_tp3["prob. top 10"]).abs().max() < 1e-12
    assert (r["prioridad"].map(lambda p: f"Prioridad {p}") == ranking_tp3["prioridad"]).all()
    assert (r["prioridad"] == 1).sum() == 11


def test_reproduce_segmentos_del_tp3(modelo):
    segmentos = json.loads((REF / "segmentos.json").read_text(encoding="utf-8"))
    for seg, info in segmentos.items():
        for codigo in info["paises"]:
            assert int(modelo.segmento_ref[codigo]) == int(seg)


def test_reproduce_paises_puente_del_tp3(modelo, ranking_tp3):
    for codigo, esperado in ranking_tp3["países puente"].items():
        calculado = ", ".join(p["codigo"] for p in modelo.puentes(codigo)) or "sin puente claro"
        assert calculado == esperado


def test_escenario_sin_cambios_da_el_mismo_resultado(modelo):
    r = modelo.evaluar({}, base_codigo="AR")
    orig = modelo.ranking_base.loc["AR"]
    assert r["ranking"]["puesto"] == orig["puesto"]
    assert abs(r["ranking"]["puntaje"] - orig["puntaje"]) < 0.01
    assert r["segmento"]["id"] == int(modelo.segmento_ref["AR"])
    assert r["avisos"] == [] and r["calidad"] == "alta"


# ---------------------------------------------------------------- robustez ante datos nuevos

def test_region_conocida_imputa_con_mediana_regional(modelo):
    r = modelo.evaluar({}, base_codigo="TW")  # Taiwán no tiene datos del Banco Mundial
    tipos = {a["tipo"] for a in r["avisos"]}
    assert tipos == {"imputado_region"}
    assert set(r["variables_imputadas"]) == {"pbi_pc_ppa", "internet_pct", "ingreso_ordinal", "urbana_pct", "poblacion", "mayores65_pct"}
    assert r["calidad"] == "baja"
    assert r["ranking"]["de"] == 66


def test_region_no_vista_usa_mediana_global_y_avisa(modelo):
    r = modelo.evaluar({"region": "Atlántida", "income": "alto", "pbi_pc_ppa": 50000, "internet_pct": 90,
                        "urbana_pct": 80, "poblacion": 5e6, "mayores65_pct": 15, "similitud_max": 0.5,
                        "cuota_apellidos_transregionales": 0.7, "paises_por_apellido_pond": 9})
    tipos = [a["tipo"] for a in r["avisos"]]
    assert "region_no_vista" in tipos
    assert tipos.count("imputado_global") == 2  # las dos variables de origen
    assert "imputado_region" not in tipos


def test_region_faltante_avisa(modelo):
    r = modelo.evaluar({"region": None, "income": "High income", **{v: 1 for v in ["n_familias_relevantes"]}})
    assert any(a["tipo"] == "region_faltante" for a in r["avisos"])


def test_categorias_en_castellano_y_sin_acentos(modelo):
    a = modelo.evaluar({"income": "Ingreso medio alto", "region": "america latina y el caribe"}, base_codigo="AR")
    b = modelo.evaluar({"income": "Upper middle income", "region": "Latin America & Caribbean"}, base_codigo="AR")
    assert a["ranking"] == b["ranking"]


def test_ingreso_desconocido_es_error(modelo):
    with pytest.raises(DatosInvalidos) as e:
        modelo.evaluar({"income": "rico"}, base_codigo="AR")
    assert e.value.detalles[0]["campo"] == "income"


@pytest.mark.parametrize("campo,valor", [("internet_pct", 150), ("pbi_pc_ppa", -5), ("similitud_max", 2), ("poblacion", "mucha")])
def test_valores_invalidos_son_error(modelo, campo, valor):
    with pytest.raises(DatosInvalidos) as e:
        modelo.evaluar({campo: valor}, base_codigo="AR")
    assert e.value.detalles[0]["campo"] == campo


def test_extrapolacion_genera_aviso(modelo):
    r = modelo.evaluar({"pbi_pc_ppa": 250000}, base_codigo="AR")
    assert any(a["tipo"] == "fuera_de_rango_observado" for a in r["avisos"])


def test_pais_inexistente(modelo):
    with pytest.raises(NoEncontrado):
        modelo.ficha("XX")
    with pytest.raises(NoEncontrado):
        modelo.evaluar({}, base_codigo="XX")


# ---------------------------------------------------------------- pesos

def test_pesos_se_normalizan(modelo):
    w = modelo.validar_pesos({"mercado": 2, "diversidad_origen": 2, "conectividad": 2, "poblacion": 2, "mayores65_pct": 2})
    assert all(abs(v - 0.2) < 1e-12 for v in w.values())


@pytest.mark.parametrize("pesos", [{"mercado": -1}, {"mercado": 0, "poblacion": 0}, {"precio": 1}, {"mercado": "x"}])
def test_pesos_invalidos(modelo, pesos):
    with pytest.raises(DatosInvalidos):
        modelo.validar_pesos(pesos)


def test_escenario_mercado_primero_del_tp3(modelo):
    r = modelo.resumen_ranking({"mercado": 0.60, "diversidad_origen": 0.10, "conectividad": 0.05, "poblacion": 0.20, "mayores65_pct": 0.05})
    assert r["top10_compartido_con_base"] == 8  # igual que en la sección 8.2 del TP3


def test_pesos_teoricos(modelo):
    d = modelo.descripcion()
    pbi = next(p for p in d["pesos_variables"] if p["variable"] == "pbi_pc_ppa")
    assert pbi["peso_en_indice"] == 0.25 and pbi["peso_efectivo_en_puntaje"] == 0.0875
    assert abs(sum(p["peso_efectivo_en_puntaje"] for p in d["pesos_variables"]) - 1) < 1e-3


# ---------------------------------------------------------------- apellidos

def test_apellido_del_grupo(buscador):
    r = buscador.buscar("varela")
    assert r["apellido"] == "Varela"
    assert {p["codigo"] for p in r["paises"]} == {"US", "CO", "MX", "ES", "CL"}
    assert set(r["paises_prioridad_1"]) == {"US", "ES"}


def test_apellido_con_acentos_y_particulas(buscador):
    assert buscador.buscar("GARCÍA")["cantidad_paises"] == buscador.buscar("garcia")["cantidad_paises"]
    r = buscador.buscar("de la Fuente")
    assert r["cantidad_paises"] >= 1


def test_apellido_inexistente(buscador):
    with pytest.raises(NoEncontrado):
        buscador.buscar("Ezcurra")
    with pytest.raises(ValueError):
        buscador.buscar("a")
