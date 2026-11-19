"""Exporta el modelo entrenado en el TP3 a un artefacto JSON portable (versión 1.1).

El TP3 guardó el pipeline en modelos/modelo_genea.joblib. Ese archivo depende de la
versión de scikit-learn con la que se entrenó (los escaladores son objetos de sklearn).
Para el servicio lo pasamos a un JSON con números puros: medias, desvíos, centroides,
medianas de imputación y pesos. El modelo es exactamente el mismo; no se reentrena nada.

La versión 1.1 agrega lo que pidió la devolución del TP3 sobre datos nuevos:
- medianas regionales y globales para TODAS las variables (no solo las de origen),
  calculadas igual que en el TP3: sobre los 65 países y en la escala ya transformada;
- la mediana regional del nivel de ingreso codificado, para imputarlo si falta;
- la lista de regiones y niveles de ingreso válidos, para detectar categorías no vistas.

Uso (desde la carpeta del proyecto):
    python scripts/exportar_artefacto.py --tp3 ../../tp3
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]

ESTRATEGIAS = {
    0: "Propuesta centrada en la búsqueda transfronteriza: rastrear la rama de la familia en otro país.",
    1: "Propuesta centrada en archivos y registros nacionales.",
    2: "Expansión a través de países puente: entrar desde España o Estados Unidos con la misma base de apellidos, con precios adaptados.",
    3: "Propuesta centrada en descubrir orígenes múltiples.",
    4: "En general no prioritarios para un modelo de suscripción digital.",
}
RASGOS = {
    0: "Alto poder adquisitivo y familias con apellidos compartidos con otros países.",
    1: "Mercado fuerte, apellidos locales y la población más envejecida.",
    2: "La menor diversidad de origen, apellidos muy compartidos y mercado medio.",
    3: "La mayor diversidad de origen.",
    4: "Bajo uso de internet.",
}


def main(tp3: Path) -> None:
    art = joblib.load(tp3 / "modelos" / "modelo_genea.joblib")
    leer = dict(keep_default_na=False, na_values=[""])
    paises = pd.read_csv(tp3 / "data" / "processed" / "features_paises.csv", index_col="country_code", **leer)
    base = paises.loc[art["metadatos"]["paises_entrenamiento"]].copy()

    # Medianas en la escala transformada, como en el TP3 (ingreso codificado y log1p)
    tmp = base.copy()
    tmp["ingreso_ordinal"] = tmp["income"].map(art["orden_ingreso"])
    for col in art["variables_log"]:
        tmp[col] = np.log1p(tmp[col])
    variables = art["variables_modelo"]
    medianas_region = {c: {r: float(v) for r, v in tmp.groupby("region")[c].median().items()} for c in variables}
    medianas_global = {c: float(tmp[c].median()) for c in variables}

    # Las medianas de origen tienen que ser exactamente las del TP3 (paridad)
    for c in art["variables_origen"]:
        for r, v in art["medianas_origen_region"][c].items():
            assert abs(medianas_region[c][r] - v) < 1e-12, (c, r)
        assert abs(medianas_global[c] - art["medianas_origen_global"][c]) < 1e-12

    ev, ei = art["escalador_variables"], art["escalador_indices"]
    salida = {
        "version": "1.1",
        "origen": "Modelo entrenado en el TP3 (k-means, k = 5, sobre 3 índices). Exportado sin reentrenar.",
        "fecha_entrenamiento": art["fecha_entrenamiento"],
        "variables_modelo": variables,
        "variables_log": art["variables_log"],
        "orden_ingreso": art["orden_ingreso"],
        "regiones": sorted(base["region"].unique().tolist()),
        "bloques": art["bloques"],
        "escalador_variables": {"media": dict(zip(variables, ev.mean_.tolist())),
                                "desvio": dict(zip(variables, ev.scale_.tolist()))},
        "escalador_indices": {"media": dict(zip(list(art["bloques"]), ei.mean_.tolist())),
                              "desvio": dict(zip(list(art["bloques"]), ei.scale_.tolist()))},
        "medianas_region": medianas_region,
        "medianas_global": medianas_global,
        "centroides": np.asarray(art["centroides"]).tolist(),
        "segmentos": {str(k): {"nombre": v, "rasgo": RASGOS[k], "estrategia": ESTRATEGIAS[k]}
                      for k, v in art["nombres_segmentos"].items()},
        "pesos_ranking": art["pesos_ranking"],
        "escala_puntaje": list(art["escala_puntaje"]),
        "sensibilidad": {"concentracion_dirichlet": 30, "simulaciones": 5000, "semilla": 42, "top": 10},
        "regla_prioridad": {"prioridad_1_prob_top10_min": 0.5, "prioridad_2_puesto_mediano_max": 25},
        "puentes": {"similitud_minima": 0.2, "cantidad": 3},
        "paises_entrenamiento": art["metadatos"]["paises_entrenamiento"],
    }
    # Embudo de la regla de selección de la grilla (devolución del TP3: mostrar cómo opera)
    g = pd.read_csv(tp3 / "resultados" / "grilla_modelos.csv")
    estable, tamano = g["estabilidad"] >= 0.7, g["tamaño_mínimo"] >= 5
    cand = g[estable & tamano].sort_values("silhouette", ascending=False)
    salida["seleccion"] = {
        "total": int(len(g)), "pasan_estabilidad": int(estable.sum()), "pasan_tamano": int(tamano.sum()),
        "pasan_ambos": int((estable & tamano).sum()),
        "por_espacio": {e: {"total": int(len(d)), "pasan_ambos": int(((d["estabilidad"] >= 0.7) & (d["tamaño_mínimo"] >= 5)).sum())}
                        for e, d in g.groupby("espacio")},
        "candidatas": [{"espacio": r.espacio, "algoritmo": r.algoritmo, "k": int(r.k), "silhouette": round(float(r.silhouette), 3),
                        "estabilidad": round(float(r.estabilidad), 3), "tamano_minimo": int(r.tam)}
                       for r in cand.rename(columns={"tamaño_mínimo": "tam"}).itertuples()],
    }
    destino = RAIZ / "genea" / "datos" / "modelo_genea_v1.1.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Artefacto escrito en", destino)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tp3", type=Path, required=True, help="Carpeta del entregable del TP3")
    main(ap.parse_args().tp3)
