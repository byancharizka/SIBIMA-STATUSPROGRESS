import os
import logging
from io import BytesIO
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import pytz
import requests
import streamlit as st
import plotly.graph_objects as go
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# =========================================================
# 1) PAGE CONFIG - WAJIB PALING ATAS
# =========================================================
st.set_page_config(
    layout="wide",
    page_title="SIBIMA Performance Dashboard - PROCUREMENT & PURCHASING",
    initial_sidebar_state="expanded"
)

# =========================================================
# 2) LOGGING CONFIG
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# =========================================================
# 3) APP CONFIG
# =========================================================
TIMEZONE = pytz.timezone("Asia/Jakarta")
# Ambil tanggal hari ini
today = date.today()

# Default: tanggal 1 bulan aktif sampai hari ini
DEFAULT_START_DATE = date(today.year, today.month, 1)
DEFAULT_END_DATE = today
REQUEST_TIMEOUT = int(os.getenv("SIBIMA_API_TIMEOUT", "60"))


BASE_URL = {
    "outstanding": "https://eas.sibima.id/api/dashboard/",
    "eas": "https://eas.sibima.id/api/",
    "brp": "https://brp.sibima.id/api/"
}

API_TOKEN = os.getenv("SIBIMA_API_TOKEN", "7e92e63988bb1333d28c756718c13f4b0d911aa4b7fc749ddf9b1a0c02d6")

# Pastikan setiap URL diakhiri dengan "/"
for key in BASE_URL:
    if not BASE_URL[key].endswith("/"):
        BASE_URL[key] += "/"

def create_session():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[502, 503, 504, 429],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# =========================================================
# 4) CSS CUSTOM
# =========================================================
st.markdown("""
<style>
/* ====== TITLE UTAMA ====== */
h1 {
    font-size: 1.5rem !important;   /* paling besar */
    font-weight: 800;
    color: #222;
}

/* ====== SUBTITLE & SUBHEADER ====== */
h2, h3, h4, h5, h6 {
    font-size: 1rem !important;   /* lebih kecil dari h1 */
    font-weight: 600;
    color: #444;
}

/* ====== LAYOUT CONTAINER ====== */
.block-container {
    padding-top: 2rem;
    padding-bottom: 1rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 100%;
}

/* ====== METRIC COMPONENTS ====== */
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
}
[data-testid="stMetricValue"] {
    font-size: 0.5rem !important;
}

/* ====== CUSTOM METRIC CARD ====== */
.metric-card {
    background-color: #f4f4f4;
    border: 1px solid #dcdcdc;
    border-radius: 12px;
    padding: 2px;
    box-shadow: 1px 2px 8px rgba(0,0,0,0.05);
    text-align: center;
    margin-top: 3px;
    margin-bottom: 7px;
    margin-left: 2.5px;
    font-size: 0.75rem;
}
            
.metric-card div {
    font-size: 0.67rem !important;
}            

/* ====== SMALL NOTES ====== */
.small-note {
    color: #666;
    font-size: 0.70rem;
}
            
h3, h4, h5 {
    margin-bottom: 0.1rem !important;
}

/* Kurangi jarak antar komponen container */
div[data-testid="stVerticalBlock"] {
    margin-top: 0.1rem !important;
    margin-bottom: 0.1rem !important;
}

/* Kurangi padding default di dalam container */
div[data-testid="stContainer"] {
    padding-top: 0.1rem !important;
    padding-bottom: 0.1rem !important;
}
            

/* ====== FILTER INPUTS ====== */
div[data-testid="stDateInput"], 
div[data-testid="stTextInput"] {
    font-size: 0.7rem !important;   /* ukuran teks lebih kecil */
}

label, .stTextInput label, .stDateInput label {
    font-size: 0.7rem !important;   /* label input lebih kecil */
    color: #555 !important;
}

/* Kurangi tinggi box input agar lebih ramping */
input, textarea {
    font-size: 0.7rem !important;
    padding: 4px 6px !important;
}
            
@media (max-width: 768px) {
    h1 { font-size: 1.2rem !important; }
    h2, h3, h4 { font-size: 0.9rem !important; }
    .metric-card {
        font-size: 0.65rem !important;
        padding: 4px !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 0.7rem !important;
    }
    .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
}

                        
</style>
""", unsafe_allow_html=True)


# =========================================================
# 5) UTILITIES
# =========================================================
def metric_card(label: str, value: str):
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="color: #666; font-size: 0.95rem;">{label}</div>
            <div style="font-size: 0.9rem; font-weight: 700; color: #222;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Pastikan semua kolom ada agar operasi berikutnya aman."""
    if df.empty:
        for col in columns:
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def safe_to_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Konversi kolom ke numerik dengan aman."""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def safe_to_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Konversi kolom tanggal dengan aman dan hilangkan timezone."""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
        try:
            df[col] = df[col].dt.tz_localize(None)
        except Exception:
            pass
    return df


def normalize_text_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Normalisasi string agar aman untuk pencarian."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def safe_unique_count(df: pd.DataFrame, col: str) -> int:
    if df.empty or col not in df.columns:
        return 0
    return df[col].nunique(dropna=True)


def safe_mean(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(df[col].mean()) if not df[col].dropna().empty else 0.0

def safe_sum(df: pd.DataFrame, col: str) -> float:
    if df.empty:
        return 0.0
    if col not in df.columns:
        # fallback ke kolom lain yang mirip
        for alt in ["Nominal", "discount", "price"]:
            if alt in df.columns:
                col = alt
                break
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())



def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


# =========================================================
# 6) API FETCHING
# =========================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_api_data_old(endpoint: str, source: str = "outstanding", start_date=None, end_date=None):
    base_url = BASE_URL.get(source, BASE_URL["outstanding"])
    url = f"{base_url}{endpoint}"
    params = {"date_start": start_date, "date_end": end_date}

    try:
        logger.info("Fetching endpoint=%s from source=%s params=%s", endpoint, source, params)

        # 🔹 Gunakan session dengan retry
        session = create_session()
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict):
            data_layer = payload.get("data", {})
            if isinstance(data_layer, dict):
                rows = data_layer.get("data", [])
                if isinstance(rows, list):
                    df = pd.DataFrame(rows)
                    df = safe_to_datetime(df, "transaction_date")
                    return df
        return pd.DataFrame()

    except Exception as e:
        st.warning(f"Gagal mengambil data dari endpoint {endpoint} ({source}): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def get_api_data_new(endpoint: str, source: str = "eas", start_date=None, end_date=None):
    base_url = BASE_URL.get(source, BASE_URL["eas"])
    url = f"{base_url}{endpoint}"
    params = {
        "date_start": start_date,
        "date_end": end_date,
        "token": API_TOKEN
    }

    try:
        # 🔹 Gunakan session dengan retry
        session = create_session()
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        payload = response.json()

        rows = payload.get("data", [])
        if isinstance(rows, list):
            all_rows = []
            for row in rows:
                items = row.get("items", [])
                if items:
                    for item in items:
                        flat = {**row, **{f"item_{k}": v for k, v in item.items()}}
                        all_rows.append(flat)
                else:
                    all_rows.append(row)

            df = pd.DataFrame(all_rows)
            df = safe_to_datetime(df, "transaction_date")
            return df

        return pd.DataFrame()

    except Exception as e:
        st.warning(f"Gagal mengambil data dari endpoint {endpoint} ({source}): {e}")
        return pd.DataFrame()


def load_all_data(start_date=None, end_date=None) -> dict[str, pd.DataFrame]:
    endpoint_map = {
        "pr": ("pr-balance", {"Tgl. PR": "transaction_date"}),
        "po": ("po-balance", {"Tgl. PO": "transaction_date"}),
        "grn": ("grn-balance", {"Tgl. GRN": "transaction_date"}),
        "do": ("do-balance", {"Tgl. DO": "transaction_date"}),
        "npr": ("outstanding-npr", {"Tanggal": "transaction_date"}),
        #"pur": ("outstanding-pur", {"Tanggal": "transaction_date"})
    }

    result = {}
    for key, (endpoint, rename_map) in endpoint_map.items():
        df = get_api_data_old(endpoint, source="outstanding", start_date=start_date, end_date=end_date)

        if not df.empty:
            df = df.rename(columns=rename_map)
            df = safe_to_datetime(df, "transaction_date")
        result[key] = df

    return result



def load_all_data_new(start_date=None, end_date=None) -> dict[str, pd.DataFrame]:
    # Mapping endpoint baru sesuai API kamu
    endpoint_map_new = {
        "so": ("sales-orders", {"date" : "transaction_date"}),
        "pr": ("purchase-requests",{}),
        "po": ("purchase-orders", {"date" : "transaction_date"}),
        "grn" : ("goods-receipt-notes", {}),
        "do": ("delivery-orders",{}),
        "si" : ("sales-invoices",{})
    }

    result_new = {}
    for key, (endpoint, rename_map_new) in endpoint_map_new.items():
        df = get_api_data_new(endpoint, source="eas", start_date=start_date, end_date=end_date)

        if not df.empty:
            df = df.rename(columns=rename_map_new)
            df = safe_to_datetime(df, "transaction_date")
        result_new[key] = df

    return result_new




# =========================================================
# 7) FILTERS & TRANSFORM
# =========================================================
def apply_cumulative_filter(df: pd.DataFrame, end_date_val) -> pd.DataFrame:
    """
    Ambil SEMUA data dari awal hingga end_date.
    """
    if df.empty or "transaction_date" not in df.columns:
        return df.copy()

    working = df.copy()
    working = safe_to_datetime(working, "transaction_date")

    upper_limit = pd.to_datetime(end_date_val).replace(hour=23, minute=59, second=59)
    return working[
        working["transaction_date"].notna() &
        (working["transaction_date"] <= upper_limit)
    ].copy()

def apply_realization_filter(df: pd.DataFrame, start_date_val, end_date_val) -> pd.DataFrame:
    """
    Ambil data hanya dalam rentang tanggal tertentu (start_date sampai end_date).
    Contoh: 1 Mei 2026 s/d 31 Mei 2026.
    """
    if df.empty or "transaction_date" not in df.columns:
        return df.copy()

    working = df.copy()
    working = safe_to_datetime(working, "transaction_date")

    lower_limit = pd.to_datetime(start_date_val).replace(hour=0, minute=0, second=0)
    upper_limit = pd.to_datetime(end_date_val).replace(hour=23, minute=59, second=59)

    return working[
        working["transaction_date"].notna() &
        (working["transaction_date"] >= lower_limit) &
        (working["transaction_date"] <= upper_limit)
    ].copy()



def apply_search_filter(
    df: pd.DataFrame,
    search_number: str = "",
    search_status: str = "Semua Status",
    search_pic: str = "Semua PIC"
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    working = df.copy()
    working = normalize_text_columns(
        working,
        ["Status", "Status_so", "PIC Procurement", "PIC Purchasing", "PIC", "No. PR", "No. DO", "No. PUR", "No. Transaksi"]
    )

    # Filter nomor transaksi
    if search_number:
        pattern = search_number.strip().lower()
        string_cols = working.select_dtypes(include=["object"]).columns.tolist()
        if string_cols:
            mask_number = working[string_cols].apply(
                lambda col: col.str.lower().str.contains(pattern, na=False)
            ).any(axis=1)
            working = working[mask_number]

    # Filter Status khusus SO saja
    if search_status and search_status != "Semua Status":
        if "Status_so" in working.columns:
            working = working[
                working["Status_so"].str.strip().str.lower() == search_status.strip().lower()
            ]

    # Filter PIC Procurement via Dropdown
    if search_pic and search_pic != "Semua PIC":
        pic_cols = [col for col in ["PIC Procurement", "item_pic_procurement_name", "PIC Purchasing", "PIC"] if col in working.columns]
        if pic_cols:
            mask_pic = working[pic_cols].apply(
                lambda col: col.str.strip().str.lower() == search_pic.strip().lower()
            ).any(axis=1)
            working = working[mask_pic]

    return working.copy()

def assign_unassigned(df: pd.DataFrame, col: str) -> pd.DataFrame:
    working = df.copy()
    if col in working.columns:
        working[col] = working[col].fillna("Unassigned").astype(str).str.strip()
        working.loc[working[col] == "", col] = "Unassigned"
    return working



# =========================================================
# 9) MAIN APP
# =========================================================

def main():
    st.title("SIBIMA Performance Dashboard - PROCUREMENT & PURCHASING")

    # ---------- TOP FILTERS ----------
    today = date.today()
    default_start = date(today.year, today.month, 1)

    #col_head1, col_head2, col_head3, col_head4, col_head5 = st.columns([1, 1, 1, 1, 1])
    col_head1, col_head3, col_head4, col_head5 = st.columns([1, 1, 1, 1])

    with col_head1:
        selected_date_range = st.date_input(
            "Select Date Range 📅",
            value=(default_start, today),
            max_value=today
        )

    #with col_head2:
        #selected_doc_type = st.selectbox("Pilih Jenis Dokumen 📑", ["STATUS PROGRESS"])

    with col_head3:
        search_number = st.text_input("Cari Nomor Transaksi 🔍", placeholder="No. PR / No. DO / No. NPR / No. PUR")


    # ---------- LOAD DATA ----------
    if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2:
        start_date, end_date = selected_date_range
    else:
        start_date, end_date = default_start, today

    with st.spinner("Mengambil data dashboard..."):
        data_old = load_all_data()
        data_new = load_all_data_new(start_date=start_date, end_date=end_date)

    # ---------- ASSIGN DATAFRAME ----------
    df_pr = data_old["pr"]
    df_po = data_old["po"]
    df_grn = data_old["grn"]
    df_do = data_old["do"]
    df_npr = data_old["npr"]
    #df_pur = data_old["pur"]

    df_so_final = data_new["so"]
    df_pr_final = data_new["pr"]
    df_po_final = data_new["po"]
    df_grn_final = data_new["grn"]
    df_do_final = data_new["do"]
    df_si_final = data_new["si"]

    # Pastikan kolom PIC dan Status sesuai
    #SO
    df_so_final = df_so_final.rename(columns={
        "status_description": "Status_so",
        "item_id": "so_detail_id",
        "transaction_number" : "transaction_number_so",
        "item_product_id" : "product_id",
        "item_item_name" : "item_name"
    })
    #PR
    df_pr_final = df_pr_final.rename(columns={
        "item_pic_procurement_name": "PIC Procurement",
        "status_description": "Status_pr",
        "item_id": "pr_detail_id",
        "item_so_detail_id" : "so_detail_id",
        "transaction_number" : "transaction_number_pr",
        "item_product_id" : "product_id"
    })
    #PO
    df_po_final = df_po_final.rename(columns={
        "item_pic_procurement_name": "PIC Procurement",
        "status_description": "Status_po",
        "item_id": "po_detail_id",
        "item_pr_detail_id" : "pr_detail_id",
        "transaction_number" : "transaction_number_po",
        "item_product_id" : "product_id"
    })
    #GRN
    df_grn_final = df_grn_final.rename(columns={
        "item_pic_procurement_name": "PIC Procurement",
        "status_description": "Status_grn",
        "item_id": "grn_detail_id",
        "item_po_detail_id" : "po_detail_id",
        "transaction_number" : "transaction_number_grn",
        "item_product_id" : "product_id"
    })
    #DO
    df_do_final = df_do_final.rename(columns={
        "item_pic_procurement_name": "PIC Procurement",
        "status_description": "Status_do",
        "item_id": "do_detail_id",
        "item_grn_detail_id" : "grn_detail_id",
        "transaction_number" : "transaction_number_do",
        "item_product_id" : "product_id",
        "item_so_detail_id": "so_detail_id",
    })
    #SI
    df_si_final = df_si_final.rename(columns={
        "status_description": "Status_si",
        "item_do_detail_id" : "do_detail_id",
        "item_id": "si_detail_id",
        "transaction_number" : "transaction_number_si",
        "item_product_id" : "product_id"
    })

    df_do = df_do.rename(columns={
        "Status DO": "Status_do"
    })

    # Pastikan kolom tanggal sudah dalam format datetime
    #PR
    df_pr_final = safe_to_datetime(df_pr_final, "transaction_date")
    df_pr_final = safe_to_datetime(df_pr_final, "date_approved")
    df_pr_final = safe_to_datetime(df_pr_final, "date_inprogress")
    df_pr_final = safe_to_datetime(df_pr_final, "date_complete")
    #DO
    df_do_final = safe_to_datetime(df_do_final, "transaction_date")
    df_do_final = safe_to_datetime(df_do_final, "date_approved")
    df_do_final = safe_to_datetime(df_do_final, "date_inprogress")
    df_do_final = safe_to_datetime(df_do_final, "date_complete")
    #NPR
    #df_npr_final = safe_to_datetime(df_npr_final, "transaction_date")
    #df_npr_final = safe_to_datetime(df_npr_final, "date_approved")
    #df_npr_final = safe_to_datetime(df_npr_final, "date_inprogress")
    #df_npr_final = safe_to_datetime(df_npr_final, "date_complete")

    # ---------- EXTRACT UNIQUE STATUS LIST (KHUSUS SO) ----------
    status_list = []
    if "Status_so" in df_so_final.columns:
        status_series = df_so_final["Status_so"].dropna().astype(str).str.strip()
        status_list = [s for s in status_series.unique() if s != "" and s.lower() != "nan"]
        status_list.sort()

    status_options = ["Semua Status"] + status_list

    # ---------- TOP FILTERS ----------
    with col_head4:
        search_status = st.selectbox(
            "Pilih Status SO 🔍",
            options=status_options,
            index=0
        )

    # ---------- EXTRACT UNIQUE PIC LIST ----------
    # Ambil list PIC Procurement unik dari df_pr_final (dan dataframe lain jika perlu)
    pic_list = []
    if "PIC Procurement" in df_pr_final.columns:
        pic_list = df_pr_final["PIC Procurement"].dropna().astype(str).str.strip()
        pic_list = [pic for pic in pic_list.unique() if pic != "" and pic.lower() != "nan"]
        pic_list.sort()

    # Tambahkan opsi 'Semua PIC' di urutan pertama
    pic_options = ["Semua PIC"] + pic_list

    # ---------- TOP FILTERS (Tahap 2: Dropdown PIC) ----------
    with col_head5:
        search_pic = st.selectbox(
            "Pilih PIC Procurement 👤",
            options=pic_options,
            index=0
        )

    # ---------- DEFAULT SAFE COPY ----------
    df_pr_f = df_pr.copy()
    df_po_f = df_po.copy()
    df_grn_f = df_grn.copy()
    df_do_f = df_do.copy()
    df_npr_f = df_npr.copy()
    #df_pur_f = df_pur.copy()
    df_so_final_f = df_so_final.copy()
    df_pr_final_f = df_pr_final.copy()
    df_po_final_f = df_po_final.copy()
    df_grn_final_f = df_grn_final.copy()
    df_do_final_f = df_do_final.copy()
    df_si_final_f = df_si_final.copy()

    # ---------- DATE FILTER ----------
    if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2:
        report_start_date, report_end_date = selected_date_range
        df_so_final_f = apply_cumulative_filter(df_so_final_f, report_end_date)
        df_pr_final_f = apply_cumulative_filter(df_pr_final_f, report_end_date)
        df_po_final_f = apply_cumulative_filter(df_po_final_f, report_end_date)
        df_grn_final_f = apply_cumulative_filter(df_grn_final_f, report_end_date)
        df_do_final_f = apply_cumulative_filter(df_do_final_f, report_end_date)
        df_si_final_f = apply_cumulative_filter(df_si_final_f, report_end_date)
        #df_npr_final_f = apply_cumulative_filter(df_npr_final_f, report_end_date)



        # Tetapkan tanggal awal khusus untuk SO
        so_start_date = date(2026, 1, 11)   # mulai 11 Januari 2026
        report_end_date = today   # atau sesuai input user

        # Filter SO mulai 11 Januari 2026 sesuai periode user
        df_so_final_real = apply_realization_filter(df_so_final, so_start_date, report_end_date)

        # Dataset lain (PR, PO, GRN, DO, SI) ambil SEMUA data tanpa batasan start_date
        df_pr_final_real = apply_cumulative_filter(df_pr_final, report_end_date)
        df_po_final_real = apply_cumulative_filter(df_po_final, report_end_date)
        df_grn_final_real = apply_cumulative_filter(df_grn_final, report_end_date)
        df_do_final_real = apply_cumulative_filter(df_do_final, report_end_date)
        df_si_final_real = apply_cumulative_filter(df_si_final, report_end_date)

    # ---------- SEARCH FILTER ----------
    df_pr_final_f = apply_search_filter(df_pr_final_f, search_number, search_status, search_pic)
    #df_po_f = apply_search_filter(df_po_f, search_number, search_status, search_pic)
    #df_grn_f = apply_search_filter(df_grn_f, search_number, search_status, search_pic)
    #df_do_f = apply_search_filter(df_do_f, search_number, search_status, search_pic)
    #df_npr_f = apply_search_filter(df_npr_f, search_number, search_status, search_pic)
    #df_pur_f = apply_search_filter(df_pur_f, search_number, search_status, search_pic)
    #df_pr_final_real = apply_search_filter(df_pr_final_real, search_number, search_status, search_pic)


    #df_pur_f = ensure_columns(df_pur_f, ["No. PUR", "PIC", "Status"])
    df_so_final_real = ensure_columns(df_so_final_real, ["so_detail_id", "transaction_number_so","Status", "product_id", "item_name"])
    df_pr_final_real = ensure_columns(df_pr_final_real, ["pr_detail_id", "so_detail_id", "transaction_number_pr", "product_id"])
    df_po_final_real = ensure_columns(df_po_final_real, ["po_detail_id", "pr_detail_id", "transaction_number_po", "product_id"])
    df_grn_final_real = ensure_columns(df_grn_final_real, ["po_detail_id", "grn_detail_id", "transaction_number_grn", "product_id"])
    df_do_final_real = ensure_columns(df_do_final_real, ["so_detail_id", "grn_detail_id", "do_detail_id", "transaction_number_do", "product_id"])
    df_si_final_real = ensure_columns(df_si_final_real, ["do_detail_id", "si_detail_id", "transaction_number_si", "product_id"])
    #df_pr_final_real = safe_to_numeric(df_pr_final_real, ["price", "discount", "quantity", "tax1_percentage", "tax2_percentage"])
    #df_so_final_real= safe_to_numeric(df_so_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    #df_pr_final_real= safe_to_numeric(df_pr_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    #df_po_final_real= safe_to_numeric(df_po_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    #df_grn_final_real= safe_to_numeric(df_grn_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    #df_do_final_real= safe_to_numeric(df_do_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    #df_si_final_real= safe_to_numeric(df_si_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])

    # Merge berdasarkan nomor transaksi
    #merged = (df_pr_final_real
          #.merge(df_po_final_real, left_on='transaction_number', right_on='pr_transaction_numbers', how='outer')
          #.merge(df_grn_final_real, left_on='transaction_number', right_on='po_transaction_number', how='outer')
          #.merge(df_do_final_real, left_on='so_transaction_number', right_on='so_transaction_number', how='outer')
          #.merge(df_si_final_real, left_on='so_transaction_number', right_on='so_transaction_number', how='outer'))


    #so_pr = df_so_final_real.merge(df_pr_final_real, left_on='detail_id', right_on='so_detail_id', how='outer')
    #pr_po = so_pr.merge(df_po_final_real, left_on='pr_detail_id', right_on='pr_detail_id', how='outer')
    #po_grn = pr_po.merge(df_grn_final_real, left_on='detail_id', right_on='po_detail_id', how='outer')
    #grn_do = po_grn.merge(df_do_final_real, left_on='so_detail_id', right_on='so_detail_id', how='outer')
    #final_merge = grn_do.merge(df_si_final_real, left_on='so_detail_id', right_on='so_detail_id', how='outer')

    # Hitung jumlah unik dan total baris
    #pr_unique = df_pr_final_real['pr_detail_id'].nunique()
    #pr_total = len(df_pr_final_real)

    #po_unique = df_po_final_real['po_detail_id'].nunique()
    #po_total = len(df_po_final_real)

    #grn_unique = df_grn_final_real['grn_detail_id'].nunique()
    #grn_total = len(df_grn_final_real)   

    #do_unique = df_do_final_real['do_detail_id'].nunique()
    #do_total = len(df_do_final_real)

    #st.write(df_pr_final_real['pr_detail_id'].dtype)
    #st.write(df_po_final_real['pr_detail_id'].dtype)

    # Tampilkan di dashboard
    #st.write("PR detail_id unik:", pr_unique, " | Total baris:", pr_total)
    #st.write("PO detail_id unik:", po_unique, " | Total baris:", po_total)
    #st.write("GRN detail_id unik:", grn_unique, " | Total baris:", grn_total)
    #st.write("DO detail_id unik:", do_unique, " | Total baris:", do_total)
    #df_so_final_real['so_detail_id'] = df_so_final_real['so_detail_id'].astype(str)
    #df_pr_final_real['so_detail_id'] = df_pr_final_real['so_detail_id'].astype(str)
    #df_pr_final_real['pr_detail_id'] = df_pr_final_real['pr_detail_id'].astype(str)
    #df_po_final_real['pr_detail_id'] = df_po_final_real['pr_detail_id'].astype(str)
    #df_po_final_real['po_detail_id'] = df_po_final_real['po_detail_id'].astype(str)
    #df_grn_final_real['po_detail_id'] = df_grn_final_real['po_detail_id'].astype(str)
    #df_grn_final_real['grn_detail_id'] = df_grn_final_real['grn_detail_id'].astype(str)
    #df_do_final_real['grn_detail_id'] = df_do_final_real['grn_detail_id'].astype(str)
    #df_do_final_real['do_detail_id'] = df_do_final_real['do_detail_id'].astype(str)
    #df_si_final_real['do_detail_id'] = df_si_final_real['do_detail_id'].astype(str)


    # Konversi semua kolom ID menjadi integer murni
    for col in [
        "so_detail_id", "pr_detail_id", "po_detail_id",
        "grn_detail_id", "do_detail_id"
    ]:
        for df in [
            df_so_final_real, df_pr_final_real, df_po_final_real,
            df_grn_final_real, df_do_final_real, df_si_final_real
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")


    




    #so_pr = df_so_final_real.merge(df_pr_final_real, left_on='detail_id', right_on='so_detail_id', how='outer')
    #pr_po = so_pr.merge(df_po_final_real, left_on='pr_detail_id', right_on='pr_detail_id', how='outer')
    #po_grn = pr_po.merge(df_grn_final_real, left_on='po_detail_id', right_on='po_detail_id', how='outer')
    #grn_do = po_grn.merge(df_do_final_real, left_on='grn_detail_id', right_on='grn_detail_id', how='outer')
    #final_merge = grn_do.merge(df_si_final_real, left_on='do_detail_id', right_on='do_detail_id', how='outer')


    # Set Subset (Sertakan transaction_date dan beri nama yang spesifik)
    df_so_subset = df_so_final_real[[
        "so_detail_id", "transaction_number_so", "transaction_date", "Status_so", "product_id", "item_name"
    ]].rename(columns={"transaction_date": "transaction_date_so"})

    df_pr_subset = df_pr_final_real[[
        "so_detail_id", "pr_detail_id", "transaction_number_pr", "transaction_date", "Status_pr", "product_id", "PIC Procurement"
    ]].rename(columns={"transaction_date": "transaction_date_pr"})

    df_po_subset = df_po_final_real[[
        "pr_detail_id", "po_detail_id", "transaction_number_po", "transaction_date", "Status_po", "product_id"
    ]].rename(columns={"transaction_date": "transaction_date_po"})

    df_grn_subset = df_grn_final_real[[
        "po_detail_id", "grn_detail_id", "transaction_number_grn", "transaction_date", "Status_grn", "product_id", "vendor_name"
    ]].rename(columns={"transaction_date": "transaction_date_grn"})

    df_do_subset = df_do_final_real[[
        "so_detail_id", "grn_detail_id", "do_detail_id", "transaction_number_do", "transaction_date", "Status_do", "product_id"
    ]].rename(columns={"transaction_date": "transaction_date_do"})

    df_si_subset = df_si_final_real[[
        "do_detail_id", "si_detail_id", "transaction_number_si", "transaction_date", "Status_si", "product_id"
    ]].rename(columns={"transaction_date": "transaction_date_si"})

    # 1. Merge SO ke PR
    # Agar lebih presisi, kita gunakan merge berbasis so_detail_id & product_id
    so_pr = df_so_subset.merge(
        df_pr_subset[df_pr_subset["so_detail_id"].notna()],
        how="left",
        on=["so_detail_id", "product_id"],
        suffixes=("", "_pr")
    )

    # 2. Merge PR ke PO
    pr_po = so_pr.merge(
        df_po_subset[df_po_subset["pr_detail_id"].notna()],
        how="left",
        on=["pr_detail_id", "product_id"],
        suffixes=("", "_po")
    )

    # 3. Merge PO ke GRN
    po_grn = pr_po.merge(
        df_grn_subset[df_grn_subset["po_detail_id"].notna()],
        how="left",
        on=["po_detail_id", "product_id"],
        suffixes=("", "_grn")
    )

    # 4. JALUR A: Join GRN -> DO (Hanya jika grn_detail_id ada)
    po_grn_do_via_grn = po_grn.merge(
        df_do_subset[df_do_subset["grn_detail_id"].notna()].drop(columns=["so_detail_id"], errors="ignore"),
        how="left",
        on=["grn_detail_id", "product_id"],
        suffixes=("", "_do_grn")
    )

    # 5. JALUR B: Join SO -> DO Direct (Hanya jika DO tersebut punya so_detail_id)
    df_do_direct_so = df_do_subset[df_do_subset["so_detail_id"].notna()].copy()
    
    final_do_step = po_grn_do_via_grn.merge(
        df_do_direct_so,
        how="left",
        on=["so_detail_id", "product_id"],
        suffixes=("", "_direct_so")
    )

    # 6. COALESCE: Jika do_detail_id dari GRN kosong, isi dari Direct SO
    for col_base in ["do_detail_id", "transaction_number_do", "Status_do", "transaction_date_do"]:
        col_direct = f"{col_base}_direct_so"
        if col_direct in final_do_step.columns:
            final_do_step[col_base] = final_do_step[col_base].fillna(final_do_step[col_direct])
            final_do_step.drop(columns=[col_direct], inplace=True)

    # Bersihkan kolom duplikat grn_detail_id dari direct_so jika ada
    if "grn_detail_id_direct_so" in final_do_step.columns:
        final_do_step.drop(columns=["grn_detail_id_direct_so"], inplace=True)

    # 7. Join DO -> SI (Hanya jika do_detail_id ada)
    final_merge = final_do_step.merge(
        df_si_subset[df_si_subset["do_detail_id"].notna()],
        how="left",
        on=["do_detail_id", "product_id"],
        suffixes=("", "_si")
    )

    # 8. Saring hanya SO yang valid
    final_merge = final_merge[
        final_merge["so_detail_id"].notna() &
        final_merge["transaction_number_so"].notna()
    ]

    # Pastikan kolom detail_id sudah ada di hasil merge
    # Misalnya: so_detail_id, pr_detail_id, po_detail_id, grn_detail_id, do_detail_id, si_detail_id

    def get_item_status(row):
        if pd.notna(row.get('si_detail_id')):
            return '✅ Sudah sampai Sales Invoice'
        elif pd.notna(row.get('do_detail_id')):
            return '🚚 Sudah sampai Delivery Order'
        elif pd.notna(row.get('grn_detail_id')):
            return '📦 Sudah sampai Goods Receipt'
        elif pd.notna(row.get('po_detail_id')):
            return '📝 Sudah sampai Purchase Order'
        elif pd.notna(row.get('pr_detail_id')):
            return '📄 Masih di Purchase Request'
        else:
            return '⏳ Belum diproses'

    # Tambahkan kolom status_progres ke DataFrame final
    final_merge['status_progres'] = final_merge.apply(get_item_status, axis=1)
    final_merge = apply_search_filter(final_merge, search_number, search_status, search_pic)

    # Contoh implementasi cepat:
    funnel_data = pd.DataFrame({
        "Tahap": ["SO", "PR", "PO", "GRN", "DO", "SI"],
        "Jumlah Item": [
            final_merge["so_detail_id"].nunique(),
            final_merge["pr_detail_id"].nunique(),
            final_merge["po_detail_id"].nunique(),
            final_merge["grn_detail_id"].nunique(),
            final_merge["do_detail_id"].nunique(),
            final_merge["si_detail_id"].nunique()
        ]
    })
    # =====================================================
    # STATUS PROGRESS
    # =====================================================
    #if selected_doc_type == "STATUS PROGRESS":
    with st.container(border=True):
        # --- Tampilkan tabel di dashboard
            #st.subheader("📊 Tabel Lengkap Status Progres Per Item")
            #st.dataframe(final_merge)

            # Misalnya df_final adalah hasil merge
            selected_columns = [
                "so_detail_id",
                "pr_detail_id",
                "transaction_number_pr",
                "po_detail_id",
                "transaction_number_po",
                "grn_detail_id",
                "transaction_number_grn",
                "do_detail_id",
                "transaction_number_do",
                "si_detail_id",
                "transaction_number_si",
                "status_progres"
            ]

            df_display = final_merge[selected_columns]

            # Tampilkan di Streamlit
            st.dataframe(final_merge, use_container_width=True)


            st.download_button(
                label=f"⬇️Download {len(final_merge):,} Baris Data (Filtered).xlsx",
                data=to_excel_bytes(final_merge, sheet_name="Data_Status_Progress"),
                file_name=f"Data_Status_Progress_Export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.caption(f"Menampilkan {len(final_merge):,} baris data yang akan di-download.")

            # Tampilkan ringkasan di dashboard
            status_summary = final_merge['status_progres'].value_counts().reset_index()
            status_summary.columns = ['Status Progres', 'Jumlah Item']

            st.subheader("📊 Status Progres Per Item")
            st.dataframe(status_summary)

            # ==========================================
            # (CUSTOM COLOR MAP)
            # ==========================================
            color_map = {
                '⏳ Belum diproses': '#EF5350', 
                '📄 Masih di Purchase Request': "#ED9A93",                   
                '📝 Sudah sampai Purchase Order': "#94C6EF",     
                '📦 Sudah sampai Goods Receipt': "#1E88E5",   
                '🚚 Sudah sampai Delivery Order': "#7DDFA9", 
                '✅ Sudah sampai Sales Invoice': "#51B071"
            }

            fig_status = px.bar(
                status_summary,
                x='Status Progres',
                y='Jumlah Item',
                color='Status Progres',
                color_discrete_map=color_map,  # <-- Menghubungkan warna custom
                title='Distribusi Status Item',
                text='Jumlah Item'
            )
            fig_status.update_traces(textposition='outside')
            st.plotly_chart(fig_status, use_container_width=True)

            #Funnel Chart (Konversi & Drop-off Dokumen)
            fig_funnel = px.funnel(funnel_data, x="Jumlah Item", y="Tahap", title="⏳Funnel Konversi Item")
            st.plotly_chart(fig_funnel, use_container_width=True)

            # CALCULATE LEAD TIME & TREND
            # 1. Definisikan mapping nama tahapan LEBIH AWAL
            tahap_map = {
                'lt_so_to_pr': '1. SO ➔ PR',
                'lt_pr_to_po': '2. PR ➔ PO',
                'lt_po_to_grn': '3. PO ➔ GRN',
                'lt_grn_to_do': '4. GRN ➔ DO',
                'lt_do_to_si': '5. DO ➔ SI'
            }

            # 2. Hitung Lead Time (dalam hari) untuk tiap tahapan
            final_merge['lt_so_to_pr'] = (
                final_merge['transaction_date_pr'] - final_merge['transaction_date_so']
            ).dt.days
            final_merge['lt_pr_to_po'] = (
                final_merge['transaction_date_po'] - final_merge['transaction_date_pr']
            ).dt.days
            final_merge['lt_po_to_grn'] = (
                final_merge['transaction_date_grn'] - final_merge['transaction_date_po']
            ).dt.days
            final_merge['lt_grn_to_do'] = (
                final_merge['transaction_date_do'] - final_merge['transaction_date_grn']
            ).dt.days
            final_merge['lt_do_to_si'] = (
                final_merge['transaction_date_si'] - final_merge['transaction_date_do']
            ).dt.days
            final_merge['lt_total_so_to_si'] = (
                final_merge['transaction_date_si'] - final_merge['transaction_date_so']
            ).dt.days

            # 3. Periode bulanan berdasarkan tanggal SO
            final_merge['periode_so'] = (
                final_merge['transaction_date_so'].dt.to_period('M').astype(str)
            )

            # 4. Groupby rata-rata durasi per bulan
            df_trend_lt = (
                final_merge.groupby('periode_so')[[
                    'lt_so_to_pr',
                    'lt_pr_to_po',
                    'lt_po_to_grn',
                    'lt_grn_to_do',
                    'lt_do_to_si',
                ]]
                .mean()
                .reset_index()
            )

            # 5. Unpivot (melt) dan petakan nama tahapan
            df_trend_melted = df_trend_lt.melt(
                id_vars=['periode_so'],
                var_name='Tahapan',
                value_name='Rata_Rata_Hari',
            )
            df_trend_melted['Tahapan'] = df_trend_melted['Tahapan'].map(tahap_map)

            # 6. Buat Line Chart Plotly
            fig_line = px.line(
                df_trend_melted,
                x='periode_so',
                y='Rata_Rata_Hari',
                color='Tahapan',
                markers=True,
                title='<b>⏳Tren Rata-Rata Lead Time per Bulan</b>',
                labels={
                    'periode_so': 'Bulan Transaksi SO',
                    'Rata_Rata_Hari': 'Rata-Rata Durasi (Hari)',
                },
            )

            fig_line.update_layout(height=400)
            st.plotly_chart(fig_line, use_container_width=True)


            # VENDOR PERFORMANCE ANALYSIS
            # =====================================================
            st.subheader("🏭 Analisis Kinerja Vendor / Supplier")

            if "vendor_name" in final_merge.columns:
                col_vendor = "vendor_name"

                # Filter hanya item yang memiliki nilai Lead Time PO ➔ GRN
                df_vendor = final_merge[
                    final_merge["lt_po_to_grn"].notna()
                    & final_merge[col_vendor].notna()
                ].copy()

                if not df_vendor.empty:
                    vendor_summary = (
                        df_vendor.groupby(col_vendor)
                        .agg(
                            Total_Item=("grn_detail_id", "count"),
                            Avg_Lead_Time_GRN=("lt_po_to_grn", "mean"),
                        )
                        .reset_index()
                        .sort_values(by="Avg_Lead_Time_GRN", ascending=False)
                        .head(10)  # Top 10 Vendor Terlambat
                    )
                    vendor_summary["Avg_Lead_Time_GRN"] = vendor_summary[
                        "Avg_Lead_Time_GRN"
                    ].round(1)

                    c1, c2 = st.columns(2)
                    with c1:
                        fig_vendor_lt = px.bar(
                            vendor_summary,
                            x="Avg_Lead_Time_GRN",
                            y=col_vendor,
                            orientation="h",
                            color="Avg_Lead_Time_GRN",
                            color_continuous_scale="Reds",
                            title="<b>⏱️ Top 10 Vendor dengan Lead Time PO ➔ GRN Terlama (Hari)</b>",
                            text="Avg_Lead_Time_GRN",
                            labels={
                                "Avg_Lead_Time_GRN": "Rata-Rata Lead Time (Hari)",
                                col_vendor: "Nama Vendor",
                            },
                        )
                        fig_vendor_lt.update_layout(
                            yaxis={"categoryorder": "total ascending"},
                            showlegend=False,
                        )
                        st.plotly_chart(
                            fig_vendor_lt, use_container_width=True
                        )

                    with c2:
                        fig_vendor_vol = px.pie(
                            vendor_summary,
                            values="Total_Item",
                            names=col_vendor,
                            title="<b>📦 Porsi Volume Item per Top Vendor</b>",
                            hole=0.4,
                        )
                        st.plotly_chart(
                            fig_vendor_vol, use_container_width=True
                        )
                else:
                    st.info(
                        "ℹ️ Belum ada transaksi yang memiliki data vendor pada periode ini."
                    )
            else:
                st.warning(
                    "⚠️ Kolom 'vendor_name' belum dimasukkan ke dalam df_grn_subset."
                )

    # ---------- FOOTER INFO ----------
    with st.expander("ℹ️ Informasi Teknis Dashboard"):
        selected_report_date = (
            selected_date_range[1]
            if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2
            else date.today()
        )

        st.markdown(
            f"""
- **Base URL:** `{BASE_URL}`
- **Timeout Request:** `{REQUEST_TIMEOUT}` detik
- **Tanggal report sampai:** `{selected_report_date}`
- **Mode filter tanggal:** kumulatif (semua data sampai tanggal akhir)
- **Cache API:** 600 detik
            """
        )


if __name__ == "__main__":
    main()