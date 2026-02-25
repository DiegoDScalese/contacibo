import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

st.set_page_config(page_title="ContaCibo", page_icon="🍽", layout="centered")

# ==================================================
# GOOGLE SHEETS (SE CONECTA UNA SOLA VEZ)
# ==================================================

@st.cache_resource
def get_sheets():
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

    return sheet.worksheet("foods"), sheet.worksheet("logs")


foods_ws, logs_ws = get_sheets()


# ==================================================
# LIMPIEZA NUMÉRICA CORRECTA (SIN INFLAR DECIMALES)
# ==================================================

def to_float_safe(x):
    s = str(x).strip()

    # Caso europeo: 1.234,56
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Caso coma decimal: 123,45
    elif "," in s:
        s = s.replace(",", ".")
    # Caso normal con punto decimal: no tocar

    return float(s)


# ==================================================
# LOAD DATA (CACHEADO)
# ==================================================

@st.cache_data
def load_foods():
    df = pd.DataFrame(foods_ws.get_all_records())

    if df.empty:
        return pd.DataFrame(columns=["id","alimento","tipo","valor_kcal"])

    df["alimento"] = df["alimento"].astype(str).str.lower().str.strip()
    df["tipo"] = df["tipo"].astype(str).str.lower().str.strip()
    df["valor_kcal"] = df["valor_kcal"].apply(to_float_safe)

    return df


@st.cache_data
def load_logs():
    df = pd.DataFrame(logs_ws.get_all_records())

    if df.empty:
        return pd.DataFrame(columns=["id","fecha","timestamp","meal","total_kcal","detalle"])

    df["total_kcal"] = df["total_kcal"].apply(to_float_safe)

    return df


foods = load_foods()
logs = load_logs()

MEALS = ["desayuno","almuerzo","merienda","post entreno","cena","extra"]

# ==================================================
# UI
# ==================================================

st.title("🍽 ContaCibo")

mode = st.radio("Modo", ["Calcular","Agregar alimento","Ver hoy"], horizontal=True)

# ==================================================
# CALCULAR
# ==================================================

if mode == "Calcular":

    if "rows_count" not in st.session_state:
        st.session_state.rows_count = 4

    meal = st.selectbox("Comida", MEALS)

    st.divider()

    kcal_libres = st.number_input(
        "Kcal libres",
        min_value=0,
        step=1,
        format="%d"
    )

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
                min_value=0,
                step=1,
                format="%d",
                key=f"qty_{i}"
            )

        rows_data.append((alimento, cantidad))

    col1, col2 = st.columns(2)

    with col1:
        if st.button("➕ Agregar"):
            st.session_state.rows_count += 1
            st.rerun()

    with col2:
        calcular = st.button("Calcular")

    if calcular:

        total = 0.0
        detalle_kcal = []

        for alimento, cantidad in rows_data:
            if alimento and cantidad > 0:

                food_row = foods[foods["alimento"] == alimento].iloc[0]

                if food_row["tipo"] == "100g":
                    kcal_item = (cantidad / 100.0) * food_row["valor_kcal"]
                else:
                    kcal_item = cantidad * food_row["valor_kcal"]

                total += kcal_item

                detalle_kcal.append(
                    f"{alimento}: {round(kcal_item)} kcal"
                )

        if kcal_libres > 0:
            total += kcal_libres
            detalle_kcal.append(
                f"Kcal libres: {kcal_libres} kcal"
            )

        st.success(f"{meal.capitalize()} = {round(total)} kcal")

        st.write("Detalle:")
        for d in detalle_kcal:
            st.write(f"- {d}")

        if st.button("Guardar"):

            logs_actual = load_logs()
            new_id = int(logs_actual["id"].max()) + 1 if not logs_actual.empty else 1

            logs_ws.append_row([
                new_id,
                str(date.today()),
                str(datetime.now()),
                meal,
                round(total, 2),
                "\n".join(detalle_kcal)
            ])

            load_logs.clear()

            st.success("Guardado ✅")

# ==================================================
# VER HOY
# ==================================================

if mode == "Ver hoy":

    logs = load_logs()
    today = str(date.today())

    today_logs = logs[logs["fecha"] == today]

    if today_logs.empty:
        st.info("No hay registros hoy.")
    else:

        total_dia = today_logs["total_kcal"].sum()

        for meal_name in MEALS:

            meal_logs = today_logs[today_logs["meal"] == meal_name]

            if not meal_logs.empty:

                meal_total = meal_logs["total_kcal"].sum()

                st.subheader(
                    f"{meal_name.capitalize()} — {round(meal_total)} kcal"
                )

                for _, row in meal_logs.iterrows():
                    st.code(row["detalle"])

        st.divider()
        st.subheader(f"Total del día: {round(total_dia)} kcal")

        st.write(
            f"Meta sin gym (1700): {round(1700 - total_dia)} kcal restantes"
        )
        st.write(
            f"Meta con gym (1950): {round(1950 - total_dia)} kcal restantes"
        )
