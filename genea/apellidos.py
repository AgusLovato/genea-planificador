"""Buscador de apellidos: en qué países aparece un apellido según la fuente del proyecto.

Es la cara del modelo para una persona: ingresa su apellido y ve en qué países tiene
registros, con qué peso, y cuáles de esos países son prioritarios para Genea.

La fuente (surname-frequency, limpiada en el TP2) registra los apellidos más frecuentes de
cada país, no todos. Que un apellido no aparezca en un país no significa que no exista ahí.
"""
from __future__ import annotations

import difflib
import unicodedata
from pathlib import Path

import pandas as pd

from .modelo import DATOS, NoEncontrado
from .nombres import PAISES_ES

PARTICULAS = {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "di", "van", "von", "der", "le", "du", "el", "al"}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    t = "".join(ch if ch.isalnum() or ch in " -'" else " " for ch in t.casefold())
    return " ".join(t.replace("-", " ").replace("'", " ").split())


def sin_particulas(clave: str) -> str:
    partes = [p for p in clave.split() if p not in PARTICULAS]
    return " ".join(partes) if partes else clave


class BuscadorApellidos:
    def __init__(self, modelo, carpeta: Path = DATOS):
        self.modelo = modelo
        df = pd.read_csv(carpeta / "apellidos.csv.gz", keep_default_na=False, na_values=[""])
        df = df.rename(columns={"count": "registros"})
        df["clave"] = df["name"].map(normalizar)
        self.df = df
        self.claves = sorted(df["clave"].unique())
        self._por_clave = {k: g for k, g in df.groupby("clave")}
        self.total_paises = int(df["country_code"].nunique())

    def sugerencias(self, texto: str, n: int = 8) -> list[str]:
        clave = normalizar(texto)
        if len(clave) < 2:
            return []
        prefijo = [k for k in self.claves if k.startswith(clave)][:n]
        parecidos = difflib.get_close_matches(clave, self.claves, n=n, cutoff=0.8)
        vistos, salida = set(), []
        for k in prefijo + parecidos:
            if k not in vistos:
                vistos.add(k)
                salida.append(self._por_clave[k]["name"].mode().iloc[0])
        return salida[:n]

    def buscar(self, apellido: str) -> dict:
        texto = (apellido or "").strip()
        if len(normalizar(texto)) < 2:
            raise ValueError("Escribí un apellido de al menos 2 letras.")
        clave = normalizar(texto)
        usado = clave
        if clave not in self._por_clave and sin_particulas(clave) in self._por_clave:
            usado = sin_particulas(clave)
        if usado not in self._por_clave:
            raise NoEncontrado(f"El apellido '{texto}' no figura en la fuente.")
        g = self._por_clave[usado].sort_values("registros", ascending=False)
        m = self.modelo
        paises = []
        for f in g.itertuples(index=False):
            en_modelo = f.country_code in m.ranking_base.index
            fila = {"codigo": f.country_code, "pais": PAISES_ES.get(f.country_code, f.country_name), "registros": int(f.registros),
                    "cuota_en_pais": None if pd.isna(f.pct_pais) else round(float(f.pct_pais), 6),
                    "puesto_en_pais": None if pd.isna(f.rango_pais) else int(f.rango_pais),
                    "supera_umbral": bool(f.nativo), "en_modelo": en_modelo}
            if en_modelo:
                r = m.ranking_base.loc[f.country_code]
                seg = int(m.segmento_ref[f.country_code])
                fila.update({"prioridad": int(r["prioridad"]), "puesto_ranking": int(r["puesto"]),
                             "nombre_segmento": m.art["segmentos"][str(seg)]["nombre"]})
            paises.append(fila)
        origenes = g["origin"].dropna()
        familias = g.loc[g["familia_origen"] != "Sin dato", "familia_origen"]
        prioritarios = [p for p in paises if p.get("prioridad") == 1]
        return {
            "consulta": texto, "apellido": g["name"].mode().iloc[0],
            "se_busco_sin_particulas": usado != clave,
            "origen": origenes.mode().iloc[0] if len(origenes) else None,
            "familia_origen": familias.mode().iloc[0] if len(familias) else None,
            "cantidad_paises": len(paises), "total_paises_fuente": self.total_paises,
            "registros_totales": int(g["registros"].sum()),
            "paises": paises,
            "paises_prioridad_1": [p["codigo"] for p in prioritarios],
            "nota": ("La fuente registra los apellidos más frecuentes de cada país. Que tu apellido no aparezca en un país "
                     "no significa que no haya familias con ese apellido ahí."),
        }
