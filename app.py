import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

st.set_page_config(page_title="ContaCibo", page_icon="🇮🇹", layout="centered")

# =========================
# GOOGLE SHEETS
# =========================

@st.cache_resource
def get_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope
    )
    return gspread.authorize(credentials)

client = get_client()
sheet = client.open("ContaCibo_DB")
foods_ws = sheet.worksheet("foods")
logs_ws = sheet.worksheet("logs")

# =========================
# LOAD DATA (CACHED)
# =========================

@st.cache_data
def load_foods():
    df = pd.DataFrame(foods_ws.get_all_records())
    if df.empty:
        return pd.DataFrame(columns=["id","alimento","tipo","valor_kcal"])

    df["alimento"] = df["alimento"].astype(str).str.lower().str.strip()
    df["tipo"] = df["tipo"].astype(str).str.lower().str.strip()

    df["valor_kcal"] = (
        df["valor_kcal"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .astype(float)
    )

    df.loc[df["valor_kcal"] > 2000, "valor_kcal"] /= 100.0
    return df


@st.cache_data
def load_logs():
    df = pd.DataFrame(logs_ws.get_all_records())
    if df.empty:
        return pd.DataFrame(columns=["id","fecha","timestamp","meal","total_kcal","detalle"])
    return df


foods = load_foods()
logs = load_logs()

MEALS = ["desayuno","almuerzo","merienda","post entreno","cena","extra"]

# =========================
# UI
# =========================

st.title("🇮🇹 ContaCibo")

mode = st.radio("Modo", ["Calcular","Agregar alimento","Ver hoy"], horizontal=True)

# =========================
# CALCULAR
# =========================

if mode == "Calcular":

    if "rows_count" not in st.session_state:
        st.session_state.rows_count = 4

    if "pending_total" not in st.session_state:
        st.session_state.pending_total = None
        st.session_state.pending_detalle = None
        st.session_state.pending_meal = None

    meal = st.selectbox("Comida", MEALS)

    st.divider()

    kcal_libres = st.number_input("Kcal libres", min_value=0.0)

    rows_data = []

    for i in range(st.session_state.rows_count):

        col1, col2 = st.columns([4,1])

        with col1:
            alimento = st.selectbox(
                f"Alimento {i+1}",
                options=[""] + sorted(foods["alimento"].tolist()),
                key=f"food_{i}"
            )

        with col2:
            cantidad = st.number_input(
                "Cant.",
                min_value=0.0,
                key=f"qty_{i}"
            )

        rows_data.append((alimento, cantidad))

    col1, col2 = st.columns(2)

    with col1:
        if st.button("➕ Agregar"):
            st.session_state.rows_count += 1
            st.rerun()

    with col2:
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

            st.session_state.pending_total = total
            st.session_state.pending_detalle = detalle
            st.session_state.pending_meal = meal

    # Mostrar resultado si existe
    if st.session_state.pending_total is not None:

        st.success(f"{st.session_state.pending_meal.capitalize()} = {round(st.session_state.pending_total)} kcal")

        if st.button("Guardar"):

            logs_actual = load_logs()
            new_id = int(logs_actual["id"].max()) + 1 if not logs_actual.empty else 1

            logs_ws.append_row([
                new_id,
                str(date.today()),
                str(datetime.now()),
                st.session_state.pending_meal,
                float(st.session_state.pending_total),
                "\n".join(st.session_state.pending_detalle)
            ])

            load_logs.clear()

            st.success("Guardado ✅")

            st.session_state.pending_total = None
            st.session_state.pending_detalle = None
            st.session_state.pending_meal = None

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

        load_foods.clear()

# =========================
# VER HOY
# =========================

if mode == "Ver hoy":

    logs = load_logs()
    today = str(date.today())

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

            st.divider()
            st.write(f"**Total del día:** {round(total_dia)} kcal")

            # Mostrar ambas metas
            restante_sin_gym = 1700 - total_dia
            restante_con_gym = 1950 - total_dia

            st.write("------")
            st.write(f"Meta sin gym (1700): {round(restante_sin_gym)} kcal restantes")
            st.write(f"Meta con gym (1950): {round(restante_con_gym)} kcal restantes")
