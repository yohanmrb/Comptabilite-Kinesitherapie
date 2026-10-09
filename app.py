"""Compta kiné remplaçant — appli Streamlit perso.

Lancer :  streamlit run app.py
Les données sont sauvegardées dans data/compta.json (créé automatiquement).
"""

import hmac
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Compta kiné", page_icon="🩺", layout="wide")

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
DATA_FILE = Path(__file__).parent / "data" / "compta.json"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

PARAMS_DEFAUT = {
    "cotisations_pct": 50.0,         # URSSAF + CARPIMKO, en % du résultat
    "impot_pct": 10.0,               # impôt sur le revenu estimé, en % du net
    "retro_defaut_pct": 20.0,        # % des honoraires reversé au titulaire
    "retro_sur_depassements": True,  # la rétrocession s'applique aussi aux dépassements
}

COLONNES = ["annee", "semaine", "jours", "patients",
            "honoraires", "depassements", "retro_pct"]

SOMMES = ["jours", "patients", "honoraires", "depassements", "recettes",
          "retro", "resultat", "cotisations", "net", "impot", "poche"]

CONFIG = {
    "annee": st.column_config.NumberColumn("Année", min_value=2020, max_value=2100, step=1, format="%d"),
    "semaine": st.column_config.NumberColumn("N° semaine", min_value=1, max_value=53, step=1, format="%d"),
    "jours": st.column_config.NumberColumn("Jours travaillés", min_value=0, max_value=7, step=1, format="%d"),
    "patients": st.column_config.NumberColumn("Patients", min_value=0, step=1, format="%d"),
     "honoraires": st.column_config.NumberColumn("Honoraires / patient (€)", min_value=0.0, step=0.01, format="%.2f",
                                                help="Honoraires moyens par patient (nomenclature)"),
    "depassements": st.column_config.NumberColumn("HN / patient (€)", min_value=0.0, step=0.01, format="%.2f",
                                                  help="Hors nomenclature (dépassements) par patient"),
    "retro_pct": st.column_config.NumberColumn("Rétrocession (%)", min_value=0.0, max_value=100.0, step=0.5,
                                               format="%.1f", help="% reversé au titulaire"),
}


# ----------------------------------------------------------------------------
# Mot de passe (optionnel : actif seulement si APP_PASSWORD est dans les secrets)
# ----------------------------------------------------------------------------
def verifier_mot_de_passe():
    try:
        attendu = str(st.secrets["APP_PASSWORD"])
    except Exception:
        return
    if st.session_state.get("auth_ok"):
        return
    saisi = st.text_input("Mot de passe", type="password")
    if saisi:
        if hmac.compare_digest(saisi.encode(), attendu.encode()):
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Mot de passe incorrect.")
    st.stop()


# ----------------------------------------------------------------------------
# Données : chargement / sauvegarde
# ----------------------------------------------------------------------------
def typer(df):
    df = df.reindex(columns=COLONNES).copy()
    for c in ("annee", "semaine", "jours", "patients"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ("honoraires", "depassements", "retro_pct"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
    return df


def normaliser(df):
    df = typer(df).drop_duplicates(["annee", "semaine"], keep="last")
    return df.sort_values(["annee", "semaine"]).reset_index(drop=True)


def lire_brut(brut):
    params = {**PARAMS_DEFAUT, **brut.get("parametres", {})}
    df = normaliser(pd.DataFrame(brut.get("semaines", []), columns=COLONNES))
    return params, df


def charger():
    if not DATA_FILE.exists():
        return lire_brut({})
    try:
        brut = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.error(f"Le fichier {DATA_FILE} est illisible. Je n'écrase rien : "
                 "vérifie-le ou restaure une sauvegarde.")
        st.stop()
    return lire_brut(brut)


def vers_json(params, df):
    return json.dumps(
        {"parametres": params, "semaines": json.loads(df.to_json(orient="records"))},
        ensure_ascii=False, indent=2,
    )


def sauver(params, df):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(vers_json(params, df), encoding="utf-8")
    tmp.replace(DATA_FILE)


# ----------------------------------------------------------------------------
# Calculs
# ----------------------------------------------------------------------------
def centimes(s):
    """Arrondi au centime (0,5 centime arrondi vers le haut), pour que les totaux tombent juste."""
    return np.floor(s * 100 + 0.5 + 1e-9) / 100


def calculer(df, p):
    d = df.copy()
    d["honoraires"] = centimes(d["honoraires"] * d["patients"])
    d["depassements"] = centimes(d["depassements"] * d["patients"])
    d["recettes"] = centimes(d["honoraires"] + d["depassements"])
    base_retro = d["recettes"] if p["retro_sur_depassements"] else d["honoraires"]
    d["retro"] = centimes(base_retro * d["retro_pct"] / 100)
    d["resultat"] = d["recettes"] - d["retro"]
    d["cotisations"] = centimes(d["resultat"] * p["cotisations_pct"] / 100)
    d["net"] = d["resultat"] - d["cotisations"]
    d["impot"] = centimes(d["net"] * p["impot_pct"] / 100)
    d["poche"] = d["net"] - d["impot"]
    # Une semaine appartient au mois (et à l'année) de son jeudi (règle ISO).
    d["lundi"] = [date.fromisocalendar(int(a), int(s), 1) for a, s in zip(d["annee"], d["semaine"])]
    d["dimanche"] = [x + timedelta(days=6) for x in d["lundi"]]
    d["mois"] = [(x + timedelta(days=3)).month for x in d["lundi"]]
    return d


def valider(df):
    erreurs = []
    for i, r in enumerate(df.itertuples(index=False), start=1):
        try:
            date.fromisocalendar(int(r.annee), int(r.semaine), 1)
        except ValueError:
            erreurs.append(f"Ligne {i} : la semaine {int(r.semaine)} n'existe pas en {int(r.annee)} "
                           "(ligne incomplète ?).")
        if not 0 <= r.jours <= 7:
            erreurs.append(f"Ligne {i} : les jours travaillés doivent être entre 0 et 7.")
        if not 0 <= r.retro_pct <= 100:
            erreurs.append(f"Ligne {i} : la rétrocession doit être entre 0 et 100 %.")
    if df.duplicated(["annee", "semaine"]).any():
        erreurs.append("Une même semaine apparaît deux fois.")
    return erreurs


def semaine_suivante(df):
    if df.empty:
        iso = date.today().isocalendar()
        return date.fromisocalendar(iso.year, iso.week, 1)
    der = df.iloc[-1]
    return date.fromisocalendar(int(der["annee"]), int(der["semaine"]), 1) + timedelta(days=7)


def lignes_vides(n, premier_lundi, retro):
    rows = []
    for i in range(n):
        iso = (premier_lundi + timedelta(weeks=i)).isocalendar()
        rows.append({"annee": iso.year, "semaine": iso.week, "jours": 0, "patients": 0,
                     "honoraires": 0.0, "depassements": 0.0, "retro_pct": float(retro)})
    return typer(pd.DataFrame(rows, columns=COLONNES))


# ----------------------------------------------------------------------------
# Affichage
# ----------------------------------------------------------------------------
def eur(x):
    return f"{x:,.2f}".replace(",", "\u202f").replace(".", ",") + " €"


def recap(d, p):
    """Récapitulatif détaillé d'un ensemble de semaines."""
    if d.empty:
        st.info("Aucune donnée pour cette période.")
        return
    t = d[SOMMES].sum().to_dict()

    c1, c2, c3 = st.columns(3)
    c1.metric("Encaissé", eur(t["recettes"]), help="Honoraires + dépassements")
    c2.metric("Net gagné", eur(t["net"]), help="Après rétrocession et cotisations, avant impôt")
    c3.metric("💰 Dans ma poche", eur(t["poche"]),
              help="Net gagné − impôt estimé : ce que tu peux te virer sur ton compte perso")

    jours, patients = t["jours"], t["patients"]
    st.caption(
        f"{int(jours)} jours travaillés · {int(patients)} patients · "
        f"{eur(t['recettes'] / jours) if jours else '—'} encaissés par jour · "
        f"{eur(t['recettes'] / patients) if patients else '—'} par patient"
    )

    lignes = [
        ("Honoraires (nomenclature)", t["honoraires"]),
        ("+ Hors nomenclature (dépassements)", t["depassements"]),
        ("= Encaissé", t["recettes"]),
        ("− Rétrocession au titulaire", -t["retro"]),
        ("= Résultat avant cotisations", t["resultat"]),
        (f"− Cotisations URSSAF + CARPIMKO ({p['cotisations_pct']:g} %)", -t["cotisations"]),
        ("= Net gagné", t["net"]),
        (f"− Impôt estimé ({p['impot_pct']:g} %)", -t["impot"]),
        ("= Dans ma poche", t["poche"]),
    ]
    st.table(pd.DataFrame({"Poste": [a for a, _ in lignes],
                           "Montant": [eur(b) for _, b in lignes]}).set_index("Poste"))


COLONNES_AFF = {"jours": "Jours", "patients": "Patients", "recettes": "Encaissé",
                "retro": "Rétrocession", "cotisations": "Cotisations", "net": "Net gagné",
                "impot": "Impôt", "poche": "Dans ma poche"}


def afficher_table(g, etiquettes):
    """Tableau par période (une ligne par semaine ou par mois) avec ligne TOTAL."""
    g = g[list(COLONNES_AFF)].reset_index(drop=True)
    etiquettes = list(etiquettes)
    if len(g) > 1:
        g = pd.concat([g, g.sum().to_frame().T], ignore_index=True)
        etiquettes.append("TOTAL")
    aff = pd.DataFrame({"Période": etiquettes})
    for c, nom in COLONNES_AFF.items():
        aff[nom] = g[c].map(lambda v: str(int(v))) if c in ("jours", "patients") else g[c].map(eur)
    st.dataframe(aff, hide_index=True)


def libelle_semaine(r, court=False):
    if court:
        return f"S{int(r['semaine'])} · {r['lundi']:%d/%m} → {r['dimanche']:%d/%m}"
    return f"Semaine {int(r['semaine'])} ({r['lundi']:%d/%m/%Y} → {r['dimanche']:%d/%m/%Y})"


# ----------------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------------
verifier_mot_de_passe()
st.session_state.setdefault("v", 0)

params_charges, df = charger()
p = dict(params_charges)

with st.sidebar:
    st.header("⚙️ Paramètres")
    p["cotisations_pct"] = st.number_input(
        "Cotisations URSSAF + CARPIMKO (%)", 0.0, 100.0, float(p["cotisations_pct"]), 0.5,
        help="Part du résultat (après rétrocession) qui part en cotisations. À affiner avec ton avis de cotisations.")
    p["impot_pct"] = st.number_input(
        "Impôt sur le revenu estimé (%)", 0.0, 100.0, float(p["impot_pct"]), 0.5,
        help="Taux moyen estimé appliqué au net gagné.")
    p["retro_defaut_pct"] = st.number_input(
        "Rétrocession par défaut (%)", 0.0, 100.0, float(p["retro_defaut_pct"]), 0.5,
        help="% des honoraires reversé au titulaire. Pré-rempli à chaque saisie, modifiable par semaine.")
    p["retro_sur_depassements"] = st.checkbox(
        "La rétrocession s'applique aussi aux dépassements", value=bool(p["retro_sur_depassements"]))
    if p != params_charges:
        sauver(p, df)

    st.divider()
    st.header("💾 Sauvegarde")
    st.caption("Tout est enregistré automatiquement dans data/compta.json. "
               "Télécharge une copie de temps en temps.")
    st.download_button("⬇️ Télécharger ma sauvegarde", data=vers_json(p, df),
                       file_name=f"compta_{date.today():%Y-%m-%d}.json", mime="application/json")
    fichier = st.file_uploader("Restaurer une sauvegarde (.json)", type="json")
    if fichier is not None and st.button("Restaurer (remplace tout)"):
        try:
            p2, df2 = lire_brut(json.loads(fichier.getvalue().decode("utf-8")))
        except Exception:
            st.error("Fichier de sauvegarde illisible.")
        else:
            sauver(p2, df2)
            st.session_state["v"] += 1
            st.session_state["flash"] = "Sauvegarde restaurée."
            st.rerun()

st.title("🩺 Ma compta de kiné remplaçant")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

d = calculer(df, p)
v = st.session_state["v"]

tab_saisie, tab_sem, tab_mois, tab_an = st.tabs(["➕ Saisie", "📅 Semaine", "🗓️ Mois", "📆 Année"])

# ---- Saisie -----------------------------------------------------------------
with tab_saisie:
    n = st.number_input("Combien de semaines veux-tu saisir ?", min_value=1, max_value=52, value=1, step=1)
    st.caption("Une ligne par semaine. Les numéros de semaine sont pré-remplis à la suite de ta dernière saisie "
               "— modifie-les si besoin. Si une semaine existe déjà, elle est remplacée.")
    base = lignes_vides(int(n), semaine_suivante(df), p["retro_defaut_pct"])
    with st.form("form_saisie"):
        edite = st.data_editor(base, column_config=CONFIG, num_rows="fixed", hide_index=True,
                               key=f"saisie_{v}_{int(n)}_{p['retro_defaut_pct']}")
        envoye = st.form_submit_button("💾 Enregistrer", type="primary")
    if envoye:
        saisie = typer(edite)
        erreurs = valider(saisie)
        if erreurs:
            for e in erreurs:
                st.error(e)
        else:
            deja = len(df.merge(saisie[["annee", "semaine"]]))
            df = normaliser(pd.concat([df, saisie], ignore_index=True))
            sauver(p, df)
            st.session_state["v"] += 1
            msg = f"{len(saisie)} semaine(s) enregistrée(s)"
            st.session_state["flash"] = msg + (f" (dont {deja} remplacée(s))." if deja else ".")
            st.rerun()

    with st.expander(f"📋 Historique ({len(df)} semaine(s)) — corriger ou supprimer"):
        if df.empty:
            st.caption("Rien d'enregistré pour l'instant.")
        else:
            st.caption("Modifie une cellule directement. Pour supprimer : coche la ligne (à gauche) puis touche Suppr.")
            with st.form("form_histo"):
                modif = st.data_editor(df, column_config=CONFIG, num_rows="dynamic", hide_index=True,
                                       key=f"histo_{v}")
                envoye2 = st.form_submit_button("💾 Enregistrer les modifications")
            if envoye2:
                nouveau = typer(modif.dropna(how="all"))
                erreurs = valider(nouveau)
                if erreurs:
                    for e in erreurs:
                        st.error(e)
                else:
                    sauver(p, normaliser(nouveau))
                    st.session_state["v"] += 1
                    st.session_state["flash"] = "Historique mis à jour."
                    st.rerun()

# ---- Semaine ----------------------------------------------------------------
with tab_sem:
    if d.empty:
        st.info("Commence par saisir une semaine dans l'onglet « Saisie ».")
    else:
        ordre = d.sort_values(["annee", "semaine"], ascending=False).index.tolist()
        k = st.selectbox("Semaine", ordre, format_func=lambda i: libelle_semaine(d.loc[i]))
        recap(d.loc[[k]], p)

# ---- Mois -------------------------------------------------------------------
with tab_mois:
    if d.empty:
        st.info("Commence par saisir une semaine dans l'onglet « Saisie ».")
    else:
        dispo = sorted(d[["annee", "mois"]].drop_duplicates().itertuples(index=False, name=None), reverse=True)
        a_m = st.selectbox("Mois", dispo, format_func=lambda am: f"{MOIS[int(am[1]) - 1].capitalize()} {int(am[0])}")
        dm = d[(d["annee"] == a_m[0]) & (d["mois"] == a_m[1])].sort_values("semaine")
        recap(dm, p)
        st.markdown("**Semaines de ce mois** (une semaine compte dans le mois de son jeudi)")
        afficher_table(dm, [libelle_semaine(r, court=True) for _, r in dm.iterrows()])

# ---- Année ------------------------------------------------------------------
with tab_an:
    if d.empty:
        st.info("Commence par saisir une semaine dans l'onglet « Saisie ».")
    else:
        annees = sorted((int(x) for x in d["annee"].unique()), reverse=True)
        a = st.selectbox("Année", annees)
        da = d[d["annee"] == a]
        recap(da, p)

        g = da.groupby("mois")[SOMMES].sum()
        st.markdown("**Mois par mois**")
        afficher_table(g, [MOIS[int(m) - 1].capitalize() for m in g.index])

        st.bar_chart(pd.DataFrame(
            {"Net gagné": g["net"].values, "Dans ma poche": g["poche"].values},
            index=[f"{int(m):02d}-{MOIS[int(m) - 1][:3]}" for m in g.index]))

        export = da[["annee", "semaine", "lundi", "jours", "patients", "honoraires", "depassements",
                     "retro_pct", "recettes", "retro", "resultat", "cotisations", "net", "impot", "poche"]]
        st.download_button("⬇️ Détail de l'année (CSV pour Excel)",
                           data=export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                           file_name=f"compta_{a}.csv", mime="text/csv")

with st.expander("ℹ️ Comment c'est calculé ?"):
    st.markdown(
        """
- **Encaissé** = honoraires + hors nomenclature (dépassements)
- **Rétrocession** = % reversé au titulaire × encaissé (ou × honoraires seuls si tu décoches l'option)
- **Résultat avant cotisations** = encaissé − rétrocession
- **Cotisations** = résultat × % URSSAF + CARPIMKO (réglage dans la barre latérale)
- **Net gagné** = résultat − cotisations
- **Dans ma poche** = net gagné − impôt estimé (taux moyen fixe)

Ce sont des **estimations** : les vraies cotisations sont calculées sur ton revenu annuel et régularisées
l'année suivante, et l'impôt dépend de ta situation globale. Affine les pourcentages avec tes avis
d'appel de cotisations et d'imposition, ou fais valider avec un comptable.
        """
    )
