import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date, timedelta
import json

st.set_page_config(page_title="ContaCibo", page_icon="🍽️", layout="centered")

# ==================================================
# CONFIG
# ==================================================
MEALS = ["desayuno", "almuerzo", "merienda", "post entreno", "cena", "extra"]
META_NORMAL = 1700
META_GYM = 1950


# ==================================================
# GOOGLE SHEETS (una sola conexión)
# ==================================================
@st.cache_resource
def get_worksheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(credentials)
    sheet = client.open("ContaCibo_DB")

    foods_ws = sheet.worksheet("foods")
    logs_ws = sheet.worksheet("logs")

    # hoja nueva
    daily_ws = sheet.worksheet("daily_status")

    return foods_ws, logs_ws, daily_ws


foods_ws, logs_ws, daily_ws = get_worksheets()


# ==================================================
# PARSEO NUMÉRICO DEFINITIVO
# ==================================================
def parse_number(x) -> float:
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return 0.0
    s = s.replace("\u00a0", " ").strip()
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    return float(s)


def safe_int(x) -> int:
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return 0
    return int(round(parse_number(s)))


def safe_bool(x) -> bool:
    s = str(x).strip().lower()
    return s in ("true", "1", "yes", "si", "sí", "y", "t")


# ==================================================
# HELPERS SHEETS
# ==================================================
def ensure_headers(ws, required_cols):
    """
    Asegura que la primera fila (headers) contenga required_cols.
    Si falta alguna, la agrega al final.
    """
    values = ws.get_all_values()
    if not values:
        ws.append_row(required_cols, value_input_option="RAW")
        return required_cols

    header = [h.strip() for h in values[0]]
    missing = [c for c in required_cols if c not in header]
    if missing:
        new_header = header + missing
        ws.update("1:1", [new_header], value_input_option="RAW")
        return new_header
    return header


def find_row_index_by_id(ws, target_id: int) -> int | None:
    """
    Devuelve el número de fila (1-indexed) en la hoja, incluyendo header.
    Busca por columna 'id'. Retorna None si no encuentra.
    """
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return None
    header = [h.strip() for h in values[0]]
    if "id" not in header:
        return None
    id_col = header.index("id")
    for r_idx, row in enumerate(values[1:], start=2):
        if id_col < len(row) and safe_int(row[id_col]) == int(target_id):
            return r_idx
    return None


# ==================================================
# SCHEMAS (headers requeridos)
# ==================================================
FOODS_COLS = ["id", "alimento", "tipo", "valor_kcal"]

# logs: agregamos columnas para edición real
LOGS_COLS = ["id", "fecha", "timestamp", "meal", "total_kcal", "detalle", "kcal_libres", "detalle_json"]

DAILY_COLS = ["fecha", "gym", "meta"]

# aseguramos headers
ensure_headers(foods_ws, FOODS_COLS)
ensure_headers(logs_ws, LOGS_COLS)
ensure_headers(daily_ws, DAILY_COLS)


# ==================================================
# CARGA CACHEADA
# ==================================================
@st.cache_data
def load_foods_df() -> pd.DataFrame:
    values = foods_ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame(columns=FOODS_COLS)

    header = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    for col in FOODS_COLS:
        if col not in df.columns:
            df[col] = ""

    df["id"] = df["id"].apply(safe_int)
    df["alimento"] = df["alimento"].astype(str).str.lower().str.strip()
    df["tipo"] = df["tipo"].astype(str).str.lower().str.strip()
    df["valor_kcal"] = df["valor_kcal"].apply(parse_number)
    df = df[df["alimento"] != ""].copy()
    return df


@st.cache_data
def load_logs_df() -> pd.DataFrame:
    values = logs_ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame(columns=LOGS_COLS)

    header = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    for col in LOGS_COLS:
        if col not in df.columns:
            df[col] = ""

    df["id"] = df["id"].apply(safe_int)
    df["meal"] = df["meal"].astype(str).str.lower().str.strip()
    df["total_kcal"] = df["total_kcal"].apply(parse_number)
    df["kcal_libres"] = df["kcal_libres"].apply(safe_int)
    df["fecha"] = df["fecha"].astype(str).str.strip()
    df["timestamp"] = df["timestamp"].astype(str).str.strip()
    df["detalle"] = df["detalle"].astype(str)
    df["detalle_json"] = df["detalle_json"].astype(str)
    return df


@st.cache_data
def load_daily_status_df() -> pd.DataFrame:
    values = daily_ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame(columns=DAILY_COLS)

    header = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    for col in DAILY_COLS:
        if col not in df.columns:
            df[col] = ""

    df["fecha"] = df["fecha"].astype(str).str.strip()
    df["gym"] = df["gym"].apply(safe_bool)
    df["meta"] = df["meta"].apply(safe_int)
    return df


foods = load_foods_df()


# ==================================================
# CÁLCULO
# ==================================================
def calc_items(rows_data, kcal_libres: int):
    total = 0.0
    detail_lines = []
    detail_json = []

    for alimento, cantidad in rows_data:
        if not alimento or cantidad <= 0:
            continue

        row = foods[foods["alimento"] == alimento]
        if row.empty:
            continue

        food = row.iloc[0]
        if food["tipo"] == "100g":
            kcal_item = (cantidad / 100.0) * float(food["valor_kcal"])
        else:
            kcal_item = cantidad * float(food["valor_kcal"])

        total += kcal_item
        detail_lines.append(f"{alimento}: {round(kcal_item)} kcal")
        detail_json.append(
            {
                "alimento": alimento,
                "cantidad": int(cantidad),
                "tipo": food["tipo"],
                "valor_kcal": float(food["valor_kcal"]),
                "kcal": float(kcal_item),
            }
        )

    if kcal_libres and kcal_libres > 0:
        total += kcal_libres
        detail_lines.append(f"Kcal libres: {int(kcal_libres)} kcal")

    payload = {
        "items": detail_json,
        "kcal_libres": int(kcal_libres or 0),
    }

    return total, detail_lines, payload


# ==================================================
# DAILY STATUS (GYM/META POR DÍA)
# ==================================================
def get_or_create_daily_status(fecha_str: str):
    df = load_daily_status_df()
    row = df[df["fecha"] == fecha_str]
    if row.empty:
        # default normal
        gym = False
        meta = META_NORMAL
        daily_ws.append_row([fecha_str, "FALSE", str(meta)], value_input_option="RAW")
        load_daily_status_df.clear()
        return gym, meta
    gym = bool(row.iloc[0]["gym"])
    meta = int(row.iloc[0]["meta"]) if int(row.iloc[0]["meta"]) > 0 else (META_GYM if gym else META_NORMAL)
    return gym, meta


def upsert_daily_status(fecha_str: str, gym: bool):
    meta = META_GYM if gym else META_NORMAL
    values = daily_ws.get_all_values()
    header = [h.strip() for h in values[0]] if values else DAILY_COLS
    if not values:
        daily_ws.append_row(DAILY_COLS, value_input_option="RAW")
        values = daily_ws.get_all_values()
        header = DAILY_COLS

    fecha_col = header.index("fecha")
    gym_col = header.index("gym")
    meta_col = header.index("meta")

    target_row = None
    for idx, row in enumerate(values[1:], start=2):
        if fecha_col < len(row) and str(row[fecha_col]).strip() == fecha_str:
            target_row = idx
            break

    if target_row is None:
        daily_ws.append_row([fecha_str, "TRUE" if gym else "FALSE", str(meta)], value_input_option="RAW")
    else:
        # update 3 cols
        rng = f"{gspread.utils.rowcol_to_a1(target_row, gym_col+1)}:{gspread.utils.rowcol_to_a1(target_row, meta_col+1)}"
        daily_ws.update(rng, [["TRUE" if gym else "FALSE", str(meta)]], value_input_option="RAW")

    load_daily_status_df.clear()


# ==================================================
# UI STATE
# ==================================================
if "rows_count" not in st.session_state:
    st.session_state.rows_count = 4

if "pending_total" not in st.session_state:
    st.session_state.pending_total = None
    st.session_state.pending_detail = None
    st.session_state.pending_payload = None
    st.session_state.pending_meal = None

if "edit_log_id" not in st.session_state:
    st.session_state.edit_log_id = None  # si no es None, guardamos actualizando esa fila

# Cambio de modo programático (si viene de editar)
if st.session_state.get("force_mode"):
    st.session_state.mode_selector = st.session_state.force_mode
    st.session_state.force_mode = None

st.title("🍽️ ContaCibo")
if "mode_selector" not in st.session_state:
    st.session_state.mode_selector = "Calcular"

mode = st.radio(
    "Modo",
    ["Calcular", "Agregar alimento", "Ver hoy", "Resumen"],
    horizontal=True,
    key="mode_selector"
)

# ==================================================
# CALCULAR
# ==================================================
if mode == "Calcular":
    # meal (si venimos de editar, puede estar precargada)
    default_meal = st.session_state.get("prefill_meal", MEALS[0])
    if default_meal not in MEALS:
        default_meal = MEALS[0]
    meal = st.selectbox("Comida", MEALS, index=MEALS.index(default_meal))
    st.divider()

    kcal_libres_default = int(st.session_state.get("prefill_kcal_libres", 0))
    kcal_libres = st.number_input("Kcal libres", min_value=0, step=1, format="%d", value=kcal_libres_default)

    # Si hay prefill de items, los usamos una vez
    prefill_items = st.session_state.get("prefill_items", None)

    rows_data = []
    foods_list = [""] + sorted(foods["alimento"].tolist())

    # si hay prefill, ajustamos rows_count para que entren
    if prefill_items is not None:
        st.session_state.rows_count = max(st.session_state.rows_count, len(prefill_items))

    for i in range(st.session_state.rows_count):
        col1, col2 = st.columns([4, 1])

        # defaults para prefill
        default_food = ""
        default_qty = 0
        if prefill_items is not None and i < len(prefill_items):
            default_food = str(prefill_items[i].get("alimento", "")).strip().lower()
            default_qty = int(prefill_items[i].get("cantidad", 0))

        with col1:
            alimento = st.selectbox(
                f"Alimento {i+1}",
                options=foods_list,
                index=foods_list.index(default_food) if default_food in foods_list else 0,
                key=f"food_{i}",
            )
        with col2:
            cantidad = st.number_input(
                "Cant.",
                min_value=0,
                step=1,
                format="%d",
                value=int(default_qty),
                key=f"qty_{i}",
            )

        rows_data.append((alimento, int(cantidad)))

    # consumimos el prefill para no “reinyectar” siempre
    if prefill_items is not None:
        st.session_state.prefill_items = None

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("➕ Agregar"):
            st.session_state.rows_count += 1
            st.rerun()

    with c2:
        if st.button("Calcular"):
            total, detail_lines, payload = calc_items(rows_data, int(kcal_libres))
            st.session_state.pending_total = float(total)
            st.session_state.pending_detail = detail_lines
            st.session_state.pending_payload = payload
            st.session_state.pending_meal = meal

    with c3:
        if st.session_state.edit_log_id is not None:
            if st.button("Cancelar edición"):
                st.session_state.edit_log_id = None
                st.session_state.pending_total = None
                st.session_state.pending_detail = None
                st.session_state.pending_payload = None
                st.session_state.pending_meal = None
                st.session_state.prefill_meal = MEALS[0]
                st.session_state.prefill_kcal_libres = 0
                st.session_state.prefill_items = None
                st.success("Edición cancelada.")
                st.rerun()

    if st.session_state.pending_total is not None:
        if st.session_state.edit_log_id is None:
            st.success(f"{st.session_state.pending_meal.capitalize()} = {round(st.session_state.pending_total)} kcal")
        else:
            st.warning(
                f"Editando ID {st.session_state.edit_log_id} — "
                f"{st.session_state.pending_meal.capitalize()} = {round(st.session_state.pending_total)} kcal"
            )

        st.write("Detalle (kcal):")
        for line in st.session_state.pending_detail:
            st.write("-", line)

        if st.button("Guardar"):
            logs_actual = load_logs_df()

            fecha_str = str(date.today())
            ts_str = str(datetime.now())

            meal_str = st.session_state.pending_meal
            total_str = f"{st.session_state.pending_total:.2f}"
            detalle_str = "\n".join(st.session_state.pending_detail)
            kcal_libres_str = str(int(st.session_state.pending_payload.get("kcal_libres", 0)))
            detalle_json_str = json.dumps(st.session_state.pending_payload, ensure_ascii=False)

            if st.session_state.edit_log_id is None:
                new_id = int(logs_actual["id"].max()) + 1 if not logs_actual.empty else 1
                logs_ws.append_row(
                    [
                        new_id,
                        fecha_str,
                        ts_str,
                        meal_str,
                        total_str,
                        detalle_str,
                        kcal_libres_str,
                        detalle_json_str,
                    ],
                    value_input_option="RAW",
                )
                st.success("Guardado ✅")
            else:
                # update fila existente por ID
                target_id = int(st.session_state.edit_log_id)
                target_row = find_row_index_by_id(logs_ws, target_id)
                if target_row is None:
                    st.error("No encontré la fila para actualizar (ID no existe).")
                else:
                    values = logs_ws.get_all_values()
                    header = [h.strip() for h in values[0]]
                    # indices
                    fecha_col = header.index("fecha") + 1
                    ts_col = header.index("timestamp") + 1
                    meal_col = header.index("meal") + 1
                    total_col = header.index("total_kcal") + 1
                    detalle_col = header.index("detalle") + 1
                    kcal_libres_col = header.index("kcal_libres") + 1
                    detalle_json_col = header.index("detalle_json") + 1

                    # update de fecha..detalle_json (rango continuo)
                    start_col = fecha_col
                    end_col = detalle_json_col
                    rng = f"{gspread.utils.rowcol_to_a1(target_row, start_col)}:{gspread.utils.rowcol_to_a1(target_row, end_col)}"
                    logs_ws.update(
                        rng,
                        [[fecha_str, ts_str, meal_str, total_str, detalle_str, kcal_libres_str, detalle_json_str]],
                        value_input_option="RAW",
                    )
                    st.success("Actualizado ✅")

                st.session_state.edit_log_id = None

            load_logs_df.clear()

            st.session_state.pending_total = None
            st.session_state.pending_detail = None
            st.session_state.pending_payload = None
            st.session_state.pending_meal = None

            st.session_state.prefill_meal = MEALS[0]
            st.session_state.prefill_kcal_libres = 0
            st.session_state.prefill_items = None

            st.rerun()


# ==================================================
# AGREGAR ALIMENTO
# ==================================================
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

            foods_now = load_foods_df()
            existing = foods_now[foods_now["alimento"] == nombre_n]

            values = foods_ws.get_all_values()
            header = [h.strip() for h in values[0]]
            alimento_col = header.index("alimento") + 1
            tipo_col = header.index("tipo") + 1
            kcal_col = header.index("valor_kcal") + 1

            if not existing.empty:
                target_row = None
                for idx, row in enumerate(values[1:], start=2):
                    if str(row[alimento_col - 1]).strip().lower() == nombre_n:
                        target_row = idx
                        break

                if target_row is None:
                    st.error("No encontré la fila para actualizar.")
                else:
                    rng = f"{gspread.utils.rowcol_to_a1(target_row, alimento_col)}:{gspread.utils.rowcol_to_a1(target_row, kcal_col)}"
                    foods_ws.update(
                        rng,
                        [[nombre_n, tipo, f"{valor_f:.2f}"]],
                        value_input_option="RAW",
                    )
                    load_foods_df.clear()
                    st.success("Actualizado ✅")
            else:
                new_id = int(foods_now["id"].max()) + 1 if not foods_now.empty else 1
                foods_ws.append_row([new_id, nombre_n, tipo, f"{valor_f:.2f}"], value_input_option="RAW")
                load_foods_df.clear()
                st.success("Agregado ✅")


# ==================================================
# VER HOY (con eliminar + editar + meta/gym)
# ==================================================
if mode == "Ver hoy":
    hoy = str(date.today())

    # estado del día
    gym_current, meta_current = get_or_create_daily_status(hoy)

    st.subheader("Estado del día")
    choice = st.radio(
        "Meta de hoy",
        options=[f"Normal ({META_NORMAL})", f"Gimnasio ({META_GYM})"],
        index=1 if gym_current else 0,
        horizontal=True,
    )

    gym_new = choice.startswith("Gimnasio")
    if gym_new != gym_current:
        upsert_daily_status(hoy, gym_new)
        gym_current, meta_current = get_or_create_daily_status(hoy)
        st.success("Estado del día actualizado ✅")
        st.rerun()

    logs_today = load_logs_df()
    today_logs = logs_today[logs_today["fecha"] == hoy].copy()

    st.divider()

    if today_logs.empty:
        st.info("No hay registros hoy.")
        st.write(f"Meta hoy: **{meta_current}** kcal")
    else:
        # Totales por comida
        resumen = today_logs.groupby("meal")["total_kcal"].sum()
        total_dia = float(today_logs["total_kcal"].sum())
        delta = float(total_dia - meta_current)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total hoy", f"{round(total_dia)} kcal")
        c2.metric("Meta", f"{meta_current} kcal")
        c3.metric("Delta", f"{'+' if delta>0 else ''}{round(delta)} kcal")

        st.divider()

        # Mostrar por comida, con acciones por fila (id)
        for meal_name in MEALS:
            sub = today_logs[today_logs["meal"] == meal_name].sort_values("id")
            if sub.empty:
                continue

            st.subheader(f"{meal_name.capitalize()} — {round(float(resumen.loc[meal_name]))} kcal")

            for _, r in sub.iterrows():
                log_id = int(r["id"])
                ts = r["timestamp"]
                total_k = float(r["total_kcal"])

                st.caption(f"ID {log_id} · {ts} · {round(total_k)} kcal")
                st.code(r["detalle"] if str(r["detalle"]).strip() else "(sin detalle)")

                b1, b2 = st.columns(2)

                # EDITAR (edición real si hay detalle_json válido; si no, igual permite editar pero vacío)
                with b1:
                    if st.button("✏️ Editar", key=f"edit_{log_id}"):
                
                        payload = None
                        try:
                            payload = json.loads(r["detalle_json"]) if str(r["detalle_json"]).strip() else None
                        except Exception:
                            payload = None
                
                        st.session_state.edit_log_id = log_id
                        st.session_state.pending_total = None
                        st.session_state.pending_detail = None
                        st.session_state.pending_payload = None
                        st.session_state.pending_meal = r["meal"]
                
                        # Prefill
                        st.session_state.prefill_meal = r["meal"]
                        st.session_state.prefill_kcal_libres = int(r.get("kcal_libres", 0))
                
                        if payload and isinstance(payload, dict) and isinstance(payload.get("items", []), list):
                            st.session_state.prefill_items = payload["items"]
                        else:
                            st.session_state.prefill_items = None
                
                        # 🔥 Solo esto:
                        st.session_state.force_mode = "Calcular"
                        st.rerun()

                # ELIMINAR
                with b2:
                    if st.button("🗑️ Eliminar", key=f"del_{log_id}"):
                        target_row = find_row_index_by_id(logs_ws, log_id)
                        if target_row is None:
                            st.error("No encontré la fila para borrar.")
                        else:
                            logs_ws.delete_rows(target_row)
                            load_logs_df.clear()
                            st.success(f"ID {log_id} eliminado ✅")
                            st.rerun()

                st.divider()

        # resumen final
        st.subheader(f"Total del día: {round(total_dia)} kcal")
        st.write(f"Delta vs meta: **{'+' if delta>0 else ''}{round(delta)} kcal**")


# ==================================================
# RESUMEN (diario / semanal / mensual) usando DELTA vs META
# ==================================================
if mode == "Resumen":
    logs_all = load_logs_df()
    daily_all = load_daily_status_df()

    if logs_all.empty:
        st.info("Todavía no hay datos en logs.")
    else:
        # agregamos total por fecha
        by_day = logs_all.groupby("fecha", as_index=False)["total_kcal"].sum()
        by_day["total_kcal"] = by_day["total_kcal"].astype(float)

        # join con daily_status
        if not daily_all.empty:
            merged = by_day.merge(daily_all[["fecha", "gym", "meta"]], on="fecha", how="left")
        else:
            merged = by_day.copy()
            merged["gym"] = False
            merged["meta"] = None

        # defaults si no hay status
        def infer_meta(row):
            if pd.notna(row.get("meta")) and int(row["meta"]) > 0:
                return int(row["meta"])
            g = bool(row.get("gym")) if pd.notna(row.get("gym")) else False
            return META_GYM if g else META_NORMAL

        merged["gym"] = merged["gym"].fillna(False)
        merged["meta"] = merged.apply(infer_meta, axis=1)
        merged["delta"] = merged["total_kcal"] - merged["meta"]

        # ordenar por fecha (ISO strings)
        merged = merged.sort_values("fecha").reset_index(drop=True)

        view = st.radio("Vista", ["Diario", "Semanal", "Mensual"], horizontal=True)
        st.divider()

        if view == "Diario":
            # selector de fecha
            fechas = merged["fecha"].tolist()
            sel = st.selectbox("Fecha", options=fechas, index=len(fechas) - 1)
            row = merged[merged["fecha"] == sel].iloc[0]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total", f"{round(float(row['total_kcal']))} kcal")
            c2.metric("Meta", f"{int(row['meta'])} kcal")
            d = float(row["delta"])
            c3.metric("Delta", f"{'+' if d>0 else ''}{round(d)} kcal")
            c4.metric("Gym", "Sí" if bool(row["gym"]) else "No")

            # detalle por comidas ese día
            logs_day = logs_all[logs_all["fecha"] == sel].copy()
            if not logs_day.empty:
                st.subheader("Por comida")
                by_meal = logs_day.groupby("meal")["total_kcal"].sum().reindex(MEALS).dropna()
                st.bar_chart(by_meal)

        elif view == "Semanal":
            # semana: últimos 7 días disponibles (según datos)
            # Usamos ventana móvil: elegís fecha fin
            fechas = merged["fecha"].tolist()
            end_sel = st.selectbox("Semana terminando en", options=fechas, index=len(fechas) - 1)
            end_dt = datetime.fromisoformat(end_sel).date()
            start_dt = end_dt - timedelta(days=6)

            # filtrar por rango (strings ISO)
            mask = merged["fecha"].apply(lambda s: start_dt <= datetime.fromisoformat(s).date() <= end_dt)
            wk = merged[mask].copy()
            if wk.empty:
                st.info("No hay datos en ese rango.")
            else:
                avg_delta = float(wk["delta"].mean())
                sum_delta = float(wk["delta"].sum())
                days_in = int((wk["delta"].abs() <= 100).sum())
                days_total = int(len(wk))
                gym_days = int(wk["gym"].sum())

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Promedio delta", f"{'+' if avg_delta>0 else ''}{round(avg_delta)} kcal")
                c2.metric("Delta total", f"{'+' if sum_delta>0 else ''}{round(sum_delta)} kcal")
                c3.metric("Días en rango ±100", f"{days_in}/{days_total}")
                c4.metric("Días con gym", f"{gym_days}")

                st.subheader("Tendencia (delta)")
                chart_df = wk[["fecha", "delta"]].set_index("fecha")
                st.line_chart(chart_df)

                st.subheader("Tabla")
                show = wk[["fecha", "total_kcal", "meta", "delta", "gym"]].copy()
                show["total_kcal"] = show["total_kcal"].round(0).astype(int)
                show["delta"] = show["delta"].round(0).astype(int)
                show["gym"] = show["gym"].apply(lambda x: "Sí" if x else "No")
                st.dataframe(show, use_container_width=True)

        else:  # Mensual
            # elegir mes por YYYY-MM
            merged["ym"] = merged["fecha"].str.slice(0, 7)
            months = merged["ym"].unique().tolist()
            sel_m = st.selectbox("Mes", options=months, index=len(months) - 1)

            mo = merged[merged["ym"] == sel_m].copy()
            if mo.empty:
                st.info("No hay datos para ese mes.")
            else:
                avg_delta = float(mo["delta"].mean())
                days_in = int((mo["delta"].abs() <= 100).sum())
                days_over = int((mo["delta"] > 0).sum())
                days_under = int((mo["delta"] < 0).sum())
                gym_days = int(mo["gym"].sum())

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Promedio delta", f"{'+' if avg_delta>0 else ''}{round(avg_delta)} kcal")
                c2.metric("Días en rango ±100", f"{days_in}/{len(mo)}")
                c3.metric("Sobre meta", f"{days_over}")
                c4.metric("Con gym", f"{gym_days}")

                st.subheader("Tendencia (delta)")
                st.line_chart(mo[["fecha", "delta"]].set_index("fecha"))

                st.subheader("Tabla")
                show = mo[["fecha", "total_kcal", "meta", "delta", "gym"]].copy()
                show["total_kcal"] = show["total_kcal"].round(0).astype(int)
                show["delta"] = show["delta"].round(0).astype(int)
                show["gym"] = show["gym"].apply(lambda x: "Sí" if x else "No")
                st.dataframe(show, use_container_width=True)
