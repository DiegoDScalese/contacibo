import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date

st.set_page_config(page_title="ContaCibo", page_icon="🍽", layout="centered")

# ==================================================
# GOOGLE SHEETS (una sola conexión)
# ==================================================

@st.cache_resource
def get_worksheets():
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

foods_ws, logs_ws = get_worksheets()

MEALS = ["desayuno", "almuerzo", "merienda", "post entreno", "cena", "extra"]


# ==================================================
# PARSEO NUMÉRICO DEFINITIVO (sin inflar x100)
# ==================================================

def parse_number(x) -> float:
    """
    Convierte números que vengan como texto de Sheets:
    - "29,59" -> 29.59
    - "380,00" -> 380.0
    - "1.234,56" -> 1234.56
    - "1234.56" -> 1234.56
    """
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return 0.0

    # saco espacios raros
    s = s.replace("\u00a0", " ").strip()

    # si tiene miles europeo: 1.234,56
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    # si solo tiene coma: 29,59
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    # si solo tiene punto: lo dejo

    return float(s)


def safe_int(x) -> int:
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return 0
    # por si viene "12.0" o "12,0"
    return int(round(parse_number(s)))


# ==================================================
# CARGA CACHEADA DESDE get_all_values() (clave)
# ==================================================

@st.cache_data
def load_foods_df() -> pd.DataFrame:
    values = foods_ws.get_all_values()  # <- IMPORTANTE: texto tal cual se ve
    if not values or len(values) < 2:
        return pd.DataFrame(columns=["id", "alimento", "tipo", "valor_kcal"])

    header = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    # normalizo columnas esperadas
    for col in ["id", "alimento", "tipo", "valor_kcal"]:
        if col not in df.columns:
            df[col] = ""

    df["id"] = df["id"].apply(safe_int)
    df["alimento"] = df["alimento"].astype(str).str.lower().str.strip()
    df["tipo"] = df["tipo"].astype(str).str.lower().str.strip()
    df["valor_kcal"] = df["valor_kcal"].apply(parse_number)

    # filtro filas vacías
    df = df[df["alimento"] != ""].copy()

    return df


@st.cache_data
def load_logs_df() -> pd.DataFrame:
    values = logs_ws.get_all_values()  # <- IMPORTANTE
    if not values or len(values) < 2:
        return pd.DataFrame(columns=["id", "fecha", "timestamp", "meal", "total_kcal", "detalle"])

    header = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    for col in ["id", "fecha", "timestamp", "meal", "total_kcal", "detalle"]:
        if col not in df.columns:
            df[col] = ""

    df["id"] = df["id"].apply(safe_int)
    df["meal"] = df["meal"].astype(str).str.lower().str.strip()
    df["total_kcal"] = df["total_kcal"].apply(parse_number)
    df["fecha"] = df["fecha"].astype(str).str.strip()

    return df


foods = load_foods_df()
logs = load_logs_df()


# ==================================================
# CÁLCULO
# ==================================================

def calc_items(rows_data, kcal_libres: int):
    total = 0.0
    detail_lines = []

    for alimento, cantidad in rows_data:
        if not alimento or cantidad <= 0:
            continue

        row = foods[foods["alimento"] == alimento]
        if row.empty:
            # si no existe, lo ignoramos (o podrías mostrar error)
            continue

        food = row.iloc[0]
        if food["tipo"] == "100g":
            kcal_item = (cantidad / 100.0) * float(food["valor_kcal"])
        else:
            kcal_item = cantidad * float(food["valor_kcal"])

        total += kcal_item
        detail_lines.append(f"{alimento}: {round(kcal_item)} kcal")

    if kcal_libres and kcal_libres > 0:
        total += kcal_libres
        detail_lines.append(f"Kcal libres: {int(kcal_libres)} kcal")

    return total, detail_lines


# ==================================================
# UI
# ==================================================

st.title("🍽 ContaCibo")
mode = st.radio("Modo", ["Calcular", "Agregar alimento", "Ver hoy"], horizontal=True)

# --------------------------
# CALCULAR
# --------------------------
if mode == "Calcular":

    if "rows_count" not in st.session_state:
        st.session_state.rows_count = 4

    if "pending_total" not in st.session_state:
        st.session_state.pending_total = None
        st.session_state.pending_detail = None
        st.session_state.pending_meal = None

    meal = st.selectbox("Comida", MEALS)
    st.divider()

    kcal_libres = st.number_input("Kcal libres", min_value=0, step=1, format="%d")

    rows_data = []
    for i in range(st.session_state.rows_count):
        col1, col2 = st.columns([4, 1])

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

        rows_data.append((alimento, int(cantidad)))

    c1, c2 = st.columns(2)
    with c1:
        if st.button("➕ Agregar"):
            st.session_state.rows_count += 1
            st.rerun()

    with c2:
        if st.button("Calcular"):
            total, detail_lines = calc_items(rows_data, int(kcal_libres))
            st.session_state.pending_total = float(total)
            st.session_state.pending_detail = detail_lines
            st.session_state.pending_meal = meal

    if st.session_state.pending_total is not None:
        st.success(f"{st.session_state.pending_meal.capitalize()} = {round(st.session_state.pending_total)} kcal")
        st.write("Detalle (kcal):")
        for line in st.session_state.pending_detail:
            st.write("-", line)

        if st.button("Guardar"):
            logs_actual = load_logs_df()
            new_id = int(logs_actual["id"].max()) + 1 if not logs_actual.empty else 1

            # Guardamos total_kcal como texto con punto (RAW) para que no lo reinterprete
            logs_ws.append_row(
                [
                    new_id,
                    str(date.today()),
                    str(datetime.now()),
                    st.session_state.pending_meal,
                    f"{st.session_state.pending_total:.2f}",
                    "\n".join(st.session_state.pending_detail),
                ],
                value_input_option="RAW"
            )

            load_logs_df.clear()
            st.success("Guardado ✅")

            st.session_state.pending_total = None
            st.session_state.pending_detail = None
            st.session_state.pending_meal = None


# --------------------------
# AGREGAR ALIMENTO
# --------------------------
if mode == "Agregar alimento":

    nombre = st.text_input("Nombre")
    tipo = st.selectbox("Tipo", ["100g", "unidad"])
    valor = st.text_input("Valor kcal (ej: 29,59 o 380,00)")

    if st.button("Guardar alimento"):
        nombre_n = nombre.strip().lower()
        if not nombre_n:
            st.error("Falta el nombre.")
        else:
            try:
                valor_f = parse_number(valor)
            except Exception:
                st.error("Valor kcal inválido. Ej: 29,59 o 380,00")
                st.stop()

            # recargo foods cacheado (por si cambió)
            foods_now = load_foods_df()

            existing = foods_now[foods_now["alimento"] == nombre_n]
            if not existing.empty:
                # actualizar por id/fila: buscamos la fila en la hoja por id (más seguro)
                # pero como es chico, actualizamos por búsqueda simple en columna alimento
                values = foods_ws.get_all_values()
                header = values[0]
                alimento_col = header.index("alimento") + 1
                tipo_col = header.index("tipo") + 1
                kcal_col = header.index("valor_kcal") + 1

                # encontrar fila (1-index + header)
                target_row = None
                for idx, row in enumerate(values[1:], start=2):
                    if str(row[alimento_col-1]).strip().lower() == nombre_n:
                        target_row = idx
                        break

                if target_row is None:
                    st.error("No encontré la fila para actualizar.")
                else:
                    foods_ws.update(f"{gspread.utils.rowcol_to_a1(target_row, alimento_col)}:{gspread.utils.rowcol_to_a1(target_row, kcal_col)}",
                                    [[nombre_n, tipo, f"{valor_f:.2f}"]],
                                    value_input_option="RAW")
                    load_foods_df.clear()
                    st.success("Actualizado ✅")
            else:
                new_id = int(foods_now["id"].max()) + 1 if not foods_now.empty else 1
                foods_ws.append_row([new_id, nombre_n, tipo, f"{valor_f:.2f}"], value_input_option="RAW")
                load_foods_df.clear()
                st.success("Agregado ✅")


# --------------------------
# VER HOY (con detalle por comida)
# --------------------------
if mode == "Ver hoy":

    logs_today = load_logs_df()
    hoy = str(date.today())

    today_logs = logs_today[logs_today["fecha"] == hoy]
    if today_logs.empty:
        st.info("No hay registros hoy.")
    else:
        # Totales por comida
        resumen = today_logs.groupby("meal")["total_kcal"].sum()
        total_dia = float(today_logs["total_kcal"].sum())

        for meal_name in MEALS:
            if meal_name in resumen.index:
                st.subheader(f"{meal_name.capitalize()} — {round(float(resumen.loc[meal_name]))} kcal")
                # mostrar detalle guardado de cada entrada
                sub = today_logs[today_logs["meal"] == meal_name].sort_values("id")
                for _, r in sub.iterrows():
                    st.code(r["detalle"])

        st.divider()
        st.subheader(f"Total del día: {round(total_dia)} kcal")
        st.write(f"Meta sin gym (1700): {round(1700 - total_dia)} kcal restantes")
        st.write(f"Meta con gym (1950): {round(1950 - total_dia)} kcal restantes")
