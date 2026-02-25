import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

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

sheet = client.open("ContaCibo_DB")

foods_ws = sheet.worksheet("foods")
logs_ws = sheet.worksheet("logs")

foods = pd.DataFrame(foods_ws.get_all_records())
logs = pd.DataFrame(logs_ws.get_all_records())

# Si logs vacío
if logs.empty:
    logs = pd.DataFrame(columns=["id","fecha","timestamp","meal","total_kcal","detalle"])

# Normalizar foods
foods["alimento"] = foods["alimento"].astype(str).str.lower().str.strip()
foods["tipo"] = foods["tipo"].astype(str).str.lower().str.strip()

foods["valor_kcal"] = (
    foods["valor_kcal"]
    .astype(str)
    .str.replace(",", ".", regex=False)
    .astype(float)
)

# Corregir error Sheets 220,00 → 22000
foods.loc[foods["valor_kcal"] > 2000, "valor_kcal"] /= 100.0

MEALS = ["desayuno","almuerzo","merienda","post entreno","cena","extra"]

# =========================
# UI
# =========================

st.title("🇮🇹 ContaCibo")

mode = st.radio("Modo", ["Calcular","Agregar alimento","Ver hoy"])

# =========================
# CALCULAR
# =========================

if mode == "Calcular":

    if "rows_count" not in st.session_state:
        st.session_state.rows_count = 5

    meal = st.selectbox("Comida", MEALS)

    st.subheader("Agregar alimentos")

    rows_data = []

    for i in range(st.session_state.rows_count):

        col1, col2 = st.columns([2,1])

        with col1:
            alimento = st.selectbox(
                f"Alimento {i+1}",
                options=[""] + sorted(foods["alimento"].tolist()),
                key=f"food_{i}"
            )

        with col2:
            cantidad = st.number_input(
                f"Cantidad {i+1}",
                min_value=0.0,
                key=f"qty_{i}"
            )

        rows_data.append((alimento, cantidad))

    kcal_libres = st.number_input("Kcal libres", min_value=0.0)

    if st.button("➕ Agregar fila"):
        st.session_state.rows_count += 1
        st.rerun()

    if st.button("Calcular"):

        total = 0.0
        detalle = []

        for alimento, cantidad in rows_data:
            if alimento and cantidad > 0:
                food_row = foods[foods["alimento"] == alimento].iloc[0]

                if food_row["tipo"] == "100g":
                    total += (cantidad / 100.0) * float(food_row["valor_kcal"])
                else:
                    total += cantidad * float(food_row["valor_kcal"])

                detalle.append(f"{alimento} {cantidad}")

        if kcal_libres > 0:
            total += kcal_libres
            detalle.append(f"{kcal_libres} kcal libres")

        st.success(f"{meal.capitalize()} = {round(total)} kcal")

        if st.button("Guardar"):

            logs = pd.DataFrame(logs_ws.get_all_records())
            new_id = int(logs["id"].max()) + 1 if not logs.empty else 1

            logs_ws.append_row([
                new_id,
                str(date.today()),
                str(datetime.now()),
                meal,
                float(total),
                "\n".join(detalle)
            ])

            st.success("Guardado ✅")

# =========================
# AGREGAR ALIMENTO
# =========================

if mode == "Agregar alimento":

    nombre = st.text_input("Nombre")
    tipo = st.selectbox("Tipo", ["100g","unidad"])
    valor = st.number_input("Valor kcal", min_value=0.0)

    if st.button("Guardar alimento"):

        existing = foods[foods["alimento"] == nombre.lower().strip()]

        if not existing.empty:
            row_index = existing.index[0] + 2
            foods_ws.update(f"B{row_index}:D{row_index}",
                            [[nombre.lower(), tipo, valor]])
            st.success("Actualizado ✅")
        else:
            new_id = int(foods["id"].max()) + 1 if not foods.empty else 1
            foods_ws.append_row([new_id, nombre.lower(), tipo, valor])
            st.success("Agregado ✅")

# =========================
# VER HOY
# =========================

if mode == "Ver hoy":

    today = str(date.today())
    logs = pd.DataFrame(logs_ws.get_all_records())

    if logs.empty:
        st.info("No hay registros.")
    else:
        today_logs = logs[logs["fecha"] == today]

        if today_logs.empty:
            st.info("No hay registros hoy.")
        else:
            resumen = today_logs.groupby("meal")["total_kcal"].sum()

            total_dia = resumen.sum()

            for meal_name, kcal in resumen.items():
                st.write(f"**{meal_name.capitalize()}**: {round(kcal)} kcal")

            st.write("---")
            st.write(f"**Total del día:** {round(total_dia)} kcal")

            gym = st.toggle("Fui al gimnasio hoy?")
            meta = 1950 if gym else 1700

            restante = meta - total_dia

            st.write(f"Meta diaria: {meta} kcal")
            st.write(f"Restantes: {round(restante)} kcal")
