import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import re

# =========================
# GOOGLE SHEETS CONNECTION
# =========================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

credentials = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=scope
)

client = gspread.authorize(credentials)

SHEET_NAME = "ContaCibo_DB"
sheet = client.open(SHEET_NAME)

foods_ws = sheet.worksheet("foods")
logs_ws = sheet.worksheet("logs")

foods = pd.DataFrame(foods_ws.get_all_records())
logs = pd.DataFrame(logs_ws.get_all_records())

foods["alimento"] = foods["alimento"].astype(str).str.lower().str.strip()
foods["tipo"] = foods["tipo"].astype(str).str.lower().str.strip()

foods["valor_kcal"] = (
    foods["valor_kcal"]
    .astype(str)
    .str.replace(",", ".", regex=False)
    .astype(float)
)

# Si Sheets interpretó "220,00" como 22000, lo corregimos (÷100)
foods.loc[foods["valor_kcal"] > 2000, "valor_kcal"] = foods.loc[foods["valor_kcal"] > 2000, "valor_kcal"] / 100.0

MEALS = ["desayuno","almuerzo","merienda","post entreno","cena","extra"]

# =========================
# HELPERS
# =========================

def save_food(nombre, tipo, valor):
    nombre = nombre.strip().lower()
    tipo = tipo.strip().lower()
    valor = float(valor)

    existing = foods[foods["alimento"] == nombre]

    if not existing.empty:
        row_index = existing.index[0] + 2
        foods_ws.update(f"B{row_index}:D{row_index}", [[nombre, tipo, valor]])
        return "Alimento actualizado"

    new_id = int(foods["id"].max()) + 1 if not foods.empty else 1
    foods_ws.append_row([new_id, nombre, tipo, valor])
    return "Alimento agregado"

def find_food(name):
    name = name.lower().strip()
    if name.endswith("s") and name[:-1] in foods["alimento"].values:
        name = name[:-1]
    row = foods[foods["alimento"] == name]
    if row.empty:
        return None
    return row.iloc[0]

def calc_meal(text):
    total = 0.0
    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip().lower()
        if not line:
            continue

        # ✅ Caso: "250kc" o "250 kcal" (kcal directas)
        m_kc = re.match(r"^\s*(\d+(?:[\.,]\d+)?)\s*(kc|kcal)\s*$", line)
        if m_kc:
            qty_kcal = float(m_kc.group(1).replace(",", "."))
            total += qty_kcal
            continue

        # ✅ Caso: "alimento 480 g" o "alimento 480 gr" o "alimento 480g"
        m_weight = re.match(r"^(.+?)\s+(\d+(?:[\.,]\d+)?)\s*(g|gr)\s*$", line)

        # ✅ Caso: "alimento 1" (unidad)
        m_unit = re.match(r"^(.+?)\s+(\d+(?:[\.,]\d+)?)\s*$", line)

        if m_weight:
            name = m_weight.group(1).strip()
            qty = float(m_weight.group(2).replace(",", "."))

            food = find_food(name)
            if food is None:
                return None, f"No existe: {name}"
            if food["tipo"] != "100g":
                return None, f"{name} es unidad (ej: '{name} 1')"

            kcal_value = float(food["valor_kcal"])
            total += (qty / 100.0) * kcal_value

        elif m_unit:
            name = m_unit.group(1).strip()
            qty = float(m_unit.group(2).replace(",", "."))

            food = find_food(name)
            if food is None:
                return None, f"No existe: {name}"
            if food["tipo"] != "unidad":
                return None, f"{name} es 100g (ej: '{name} 200 g')"

            kcal_value = float(food["valor_kcal"])
            total += qty * kcal_value

        else:
            return None, f"No pude interpretar: {line}"

    return total, None

# =========================
# UI
# =========================

st.title("🇮🇹 ContaCibo")

mode = st.radio("Modo", ["Calcular","Agregar alimento","Ver hoy"])

# -------- CALCULAR --------
if mode == "Calcular":

    if "pending_total" not in st.session_state:
        st.session_state.pending_total = None
        st.session_state.pending_meal = None
        st.session_state.pending_text = None

    meal = st.selectbox("Comida", MEALS)
    text = st.text_area("Ingresa alimentos (uno por línea)")

    if st.button("Calcular"):
        total, error = calc_meal(text)
        if error:
            st.error(error)
        else:
            st.session_state.pending_total = total
            st.session_state.pending_meal = meal
            st.session_state.pending_text = text
            st.success(f"{meal.capitalize()} = {round(total)} kcal")

    # Mostrar botón Guardar si ya se calculó algo
    if st.session_state.pending_total is not None:

        st.info(f"Total pendiente: {round(st.session_state.pending_total)} kcal")

        if st.button("Guardar"):
            new_id = int(logs["id"].max()) + 1 if not logs.empty else 1

            logs_ws.append_row([
                new_id,
                str(date.today()),
                str(datetime.now()),
                st.session_state.pending_meal,
                float(st.session_state.pending_total),
                st.session_state.pending_text
            ])

            st.success("Guardado ✅")

            # Reset estado
            st.session_state.pending_total = None
            st.session_state.pending_meal = None
            st.session_state.pending_text = None
# -------- AGREGAR --------
if mode == "Agregar alimento":
    nombre = st.text_input("Nombre")
    tipo = st.selectbox("Tipo", ["100g","unidad"])
    valor = st.number_input("Valor kcal", min_value=0.0)

    if st.button("Guardar alimento"):
        msg = save_food(nombre, tipo, valor)
        st.success(msg)

# -------- VER HOY --------
if mode == "Ver hoy":
    today = str(date.today())
    today_logs = logs[logs["fecha"] == today]

    if today_logs.empty:
        st.info("No hay registros hoy.")
    else:
        resumen = today_logs.groupby("meal")["total_kcal"].sum()
        for meal, kcal in resumen.items():
            st.write(f"**{meal.capitalize()}**: {round(kcal)} kcal")

        st.write("---")
        st.write(f"**Total del día:** {round(resumen.sum())} kcal")
