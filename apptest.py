import os
import logging
from datetime import date
import pandas as pd
import requests
import pytz
import streamlit as st
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# =========================================================
# 1) PAGE CONFIG
# =========================================================
st.set_page_config(
    layout="wide",
    page_title="SIBIMA Performance Dashboard - PROCUREMENT & PURCHASING",
    initial_sidebar_state="expanded"
)

# =========================================================
# 2) LOGGING CONFIG
# =========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# =========================================================
# 3) APP CONFIG
# =========================================================
TIMEZONE = pytz.timezone("Asia/Jakarta")
today = date.today()
DEFAULT_START_DATE = date(today.year, today.month, 1)
DEFAULT_END_DATE = today
REQUEST_TIMEOUT = int(os.getenv("SIBIMA_API_TIMEOUT", "60"))

BASE_URL = "https://eas.sibima.id/api/"
API_TOKEN = os.getenv("SIBIMA_API_TOKEN", "7e92e63988bb1333d28c756718c13f4b0d911aa4b7fc749ddf9b1a0c02d6")

# =========================================================
# 4) UTILITIES
# =========================================================
@st.cache_data(ttl=600)
def get_api_data(endpoint, start_date_override=None):
    url = f"{BASE_URL}{endpoint}"
    actual_start = start_date_override if start_date_override else "2026-01-01"
    params = {"date_start": actual_start, "date_end": today, "token": API_TOKEN}
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return pd.DataFrame(response.json()['data'])
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error fetching {endpoint}: {e}")
        return pd.DataFrame()

def expand_items(df):
    if df.empty or 'items' not in df.columns: 
        return df
    
    if 'id' in df.columns:
        df = df.rename(columns={'id': 'header_id'})
        
    df_items = df.explode('items')
    items_expanded = df_items['items'].apply(lambda x: x if isinstance(x, dict) else {})
    df_items_detail = pd.json_normalize(items_expanded)
    
    if 'id' in df_items_detail.columns:
        df_items_detail = df_items_detail.rename(columns={'id': 'item_id'})
        
    df_items = df_items.drop(['items'], axis=1).reset_index(drop=True)
    df_final = pd.concat([df_items, df_items_detail], axis=1)
    
    return df_final

def clean_expanded_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    df = df.loc[:, ~df.columns.duplicated()]
    df.columns = df.columns.astype(str)
    
    for c in df.columns:
        if "date" in c.lower():
            df[c] = pd.to_datetime(df[c], errors='coerce')
            
    for c in df.columns:
        if any(k in c.lower() for k in ["price","quantity","total"]):
            try:
                df[c] = pd.to_numeric(df[c].astype(str), errors='coerce').fillna(0)
            except Exception:
                df[c] = 0
                
    return df.drop_duplicates().reset_index(drop=True)

# =========================================================
# 5) GET DATA & PREPARATION
# =========================================================
df_so = get_api_data("sales-orders", start_date_override="2025-12-01")
df_pr = get_api_data("purchase-requests", start_date_override="2025-12-01")
df_po = get_api_data("purchase-orders", start_date_override="2025-12-01")
df_grn = get_api_data("goods-receipt-notes", start_date_override="2025-07-01")
df_do = get_api_data("delivery-orders")
df_si = get_api_data("sales-invoices")

# Expand + clean
dfs = [df_so, df_pr, df_po, df_grn, df_do, df_si]
dfs = [clean_expanded_data(expand_items(df)) for df in dfs]
df_so, df_pr, df_po, df_grn, df_do, df_si = dfs

# Rename standar
def prepare_columns(df, prefix):
    renames = {}
    if 'header_id' in df.columns: renames['header_id'] = f"{prefix}_header_id"
    if 'item_id' in df.columns: renames['item_id'] = f"{prefix}_detail_id"
    if 'transaction_number' in df.columns: renames['transaction_number'] = f"transaction_number_{prefix}"
    if 'status_description' in df.columns: renames['status_description'] = f"Status_{prefix}"
    return df.rename(columns=renames)

df_so = prepare_columns(df_so, "so")
df_pr = prepare_columns(df_pr, "pr")
df_po = prepare_columns(df_po, "po")
df_grn = prepare_columns(df_grn, "grn")
df_do = prepare_columns(df_do, "do")
df_si = prepare_columns(df_si, "si")

# Normalisasi String seluruh kolom ID / Number / Reference
all_dfs = [df_so, df_pr, df_po, df_grn, df_do, df_si]
for df in all_dfs:
    for col in df.columns:
        if any(k in col.lower() for k in ["id", "number", "ref", "code"]):
            df[col] = df[col].astype(str).str.strip().str.upper()

def format_doc_number(val):
    if pd.isna(val) or str(val).strip() in ["", "NAN", "NONE", "0"]:
        return "-"
    return str(val).strip()

# Helper Merge Cerdas yang Mencari Kunci Pasangan Secara Fleksibel
def smart_merge(left_df, right_df, candidate_pairs):
    for left_key, right_key in candidate_pairs:
        if left_key in left_df.columns and right_key in right_df.columns:
            merged = left_df.merge(right_df, left_on=left_key, right_on=right_key, how="left", suffixes=('', '_dup'))
            merged = merged.loc[:, ~merged.columns.duplicated()]
            return merged
    
    # Fallback: jika ada product_id di kedua dataframe
    if "product_id" in left_df.columns and "product_id" in right_df.columns:
        merged = left_df.merge(right_df, on="product_id", how="left", suffixes=('', '_dup'))
        return merged.loc[:, ~merged.columns.duplicated()]
        
    return left_df

# =========================================================
# 6) BUILD PROGRESS TABLE
# =========================================================

def build_progress_table_all():
    # 1️⃣ SO -> PR (Mencari referensi SO di PR)
    pr_candidates = [
        ("so_detail_id", "so_detail_id"),
        ("so_header_id", "sales_order_id"),
        ("so_header_id", "so_id"),
        ("transaction_number_so", "sales_order_number"),
        ("transaction_number_so", "so_number"),
        ("transaction_number_so", "reference_number")
    ]
    so_pr = smart_merge(df_so, df_pr, pr_candidates)

    # 2️⃣ PR -> PO (Mencari referensi PR/SO di PO)
    po_candidates = [
        ("pr_detail_id", "pr_detail_id"),
        ("pr_header_id", "purchase_request_id"),
        ("pr_header_id", "pr_id"),
        ("transaction_number_pr", "purchase_request_number"),
        ("transaction_number_pr", "pr_number"),
        ("so_header_id", "so_id")
    ]
    pr_po = smart_merge(so_pr, df_po, po_candidates)

    # 3️⃣ PO -> GRN (Mencari referensi PO di GRN)
    grn_candidates = [
        ("po_detail_id", "po_detail_id"),
        ("po_header_id", "purchase_order_id"),
        ("po_header_id", "po_id"),
        ("transaction_number_po", "purchase_order_number"),
        ("transaction_number_po", "po_number")
    ]
    po_grn = smart_merge(pr_po, df_grn, grn_candidates)

    # 4️⃣ GRN -> DO (Mencari referensi GRN/SO di DO)
    do_candidates = [
        ("grn_detail_id", "grn_detail_id"),
        ("grn_header_id", "goods_receipt_note_id"),
        ("grn_header_id", "grn_id"),
        ("transaction_number_grn", "grn_number"),
        ("so_header_id", "so_id")
    ]
    grn_do = smart_merge(po_grn, df_do, do_candidates)

    # 5️⃣ DO -> SI (Mencari referensi DO/SO di SI)
    si_candidates = [
        ("do_detail_id", "do_detail_id"),
        ("do_header_id", "delivery_order_id"),
        ("do_header_id", "do_id"),
        ("transaction_number_do", "do_number"),
        ("so_header_id", "so_id")
    ]
    final_merge = smart_merge(grn_do, df_si, si_candidates)

    # Ambil Nomor Transaksi
    for prefix in ["pr", "po", "grn", "do", "si"]:
        col_name = f"transaction_number_{prefix}"
        if col_name in final_merge.columns:
            final_merge[f"Nomor {prefix.upper()}"] = final_merge[col_name].apply(format_doc_number)
        else:
            final_merge[f"Nomor {prefix.upper()}"] = "-"

    progress_cols = [
        "transaction_number_so", "Status_so",
        "Nomor PR", "Nomor PO", "Nomor GRN", "Nomor DO", "Nomor SI"
    ]

    if "product_id" in final_merge.columns:
        progress_cols.insert(2, "product_id")

    progress_table = final_merge[progress_cols].drop_duplicates()
    st.subheader("📊 Progress Tracking untuk Semua SO")
    st.dataframe(progress_table, use_container_width=True)

def build_progress_table(so_number: str):
    df_so_sel = df_so[df_so["transaction_number_so"] == so_number]
    if df_so_sel.empty:
        st.warning(f"Tidak ditemukan data untuk SO {so_number}")
        return

    # Gunakan logika smart_merge yang sama untuk single SO
    so_pr = smart_merge(df_so_sel, df_pr, [("so_detail_id", "so_detail_id"), ("so_header_id", "sales_order_id"), ("so_header_id", "so_id")])
    pr_po = smart_merge(so_pr, df_po, [("pr_detail_id", "pr_detail_id"), ("pr_header_id", "purchase_request_id"), ("pr_header_id", "pr_id")])
    po_grn = smart_merge(pr_po, df_grn, [("po_detail_id", "po_detail_id"), ("po_header_id", "purchase_order_id"), ("po_header_id", "po_id")])
    grn_do = smart_merge(po_grn, df_do, [("grn_detail_id", "grn_detail_id"), ("grn_header_id", "goods_receipt_note_id"), ("grn_header_id", "grn_id")])
    final_merge = smart_merge(grn_do, df_si, [("do_detail_id", "do_detail_id"), ("do_header_id", "delivery_order_id"), ("do_header_id", "do_id")])

    for prefix in ["pr", "po", "grn", "do", "si"]:
        col_name = f"transaction_number_{prefix}"
        if col_name in final_merge.columns:
            final_merge[f"Nomor {prefix.upper()}"] = final_merge[col_name].apply(format_doc_number)
        else:
            final_merge[f"Nomor {prefix.upper()}"] = "-"

    progress_cols = [
        "transaction_number_so", "Status_so",
        "Nomor PR", "Nomor PO", "Nomor GRN", "Nomor DO", "Nomor SI"
    ]

    progress_table = final_merge[progress_cols].drop_duplicates()
    st.subheader(f"📊 Progress Tracking untuk SO {so_number}")
    st.dataframe(progress_table, use_container_width=True)

# =========================================================
# 7) MAIN APP
# =========================================================
def main():
    st.title("SIBIMA Performance Dashboard - PROCUREMENT & PURCHASING")

    mode = st.radio("Pilih Mode Tampilan:", ["Semua SO", "Cari Nomor SO"])
    if mode == "Semua SO":
        build_progress_table_all()
    else:
        search_so_number = st.text_input("Masukkan Nomor SO untuk cek progress 🔍")
        if search_so_number:
            build_progress_table(search_so_number)

if __name__ == "__main__":
    main()