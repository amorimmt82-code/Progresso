"""
Servidor backend que conecta via gRPC ao servidor TopControl FoodProcess
e serve os dados agrupados via REST API para o frontend React.

Busca dados de:
  - StatisticService: totais de pesagem por usuário/equipamento
  - ReportService: pesagens por hora (punnets por período)
  - TimeTrackingService: registros individuais de login/logout

Uso:
  python server.py
"""

import threading
import json
import time
import copy
import subprocess
import base64
import re
import os
import unicodedata
from datetime import datetime, timedelta

try:
    import pyodbc
    HAS_PYODBC = True
except ImportError:
    HAS_PYODBC = False
    print("[AVISO] pyodbc não instalado. Conexão ao DCS2nG desabilitada.")
from flask import Flask, jsonify, request as flask_request
from flask import Flask, jsonify, request as flask_request, send_from_directory
from flask_cors import CORS
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

# Serve built frontend from dist/ if it exists
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
app = Flask(__name__, static_folder=DIST_DIR if os.path.isdir(DIST_DIR) else None, static_url_path="")
CORS(app)


def build_processo_label(ds_ordem, ds_operacao):
    parts = [p for p in [
        (ds_ordem or "").strip(),
        (ds_operacao or "").strip(),
    ] if p]
    return " - ".join(parts)


def normalize_match_text(value):
    normalized = unicodedata.normalize("NFKD", (value or "").strip())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', ascii_text).lower()


def normalize_match_token(token):
    token = (token or "").strip().lower()
    if token.endswith("gr") and token[:-2].isdigit():
        token = f"{token[:-2]}g"

    aliases = {
        "rosa": "rose",
        "rosada": "rose",
        "rosado": "rose",
        "rose": "rose",
    }
    return aliases.get(token, token)


def tokenize_match_text(value):
    tokens = []
    for tok in re.split(r'[^a-z0-9]+', normalize_match_text(value)):
        normalized = normalize_match_token(tok)
        if len(normalized) >= 3:
            tokens.append(normalized)

        # Capture embedded weights like 10x500gr -> 500g for cross-format matching.
        for grams in re.findall(r'(\d+)g?r\b', normalized):
            weight_token = f"{grams}g"
            if len(weight_token) >= 3:
                tokens.append(weight_token)
    return tokens


def collect_article_hints(grouped):
    article_counts = {}

    for group in grouped:
        article = (group.get("currentArticle") or "").strip()
        if article:
            article_counts[article] = article_counts.get(article, 0) + 1

    if not article_counts:
        for group in grouped:
            for entry in group.get("productionEntries", []):
                article = (entry.get("articleName") or "").strip()
                if not article:
                    continue
                weight = max(int(entry.get("punnets") or 0), 1)
                article_counts[article] = article_counts.get(article, 0) + weight

    return [
        {"text": article, "weight": weight}
        for article, weight in sorted(article_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]


def collect_recent_order_context(grouped):
    latest_registered_at = ""
    latest_entries = []

    for group in grouped:
        for entry in group.get("productionEntries", []):
            registered_at = (entry.get("registeredAt") or "").strip()
            if not registered_at:
                continue

            if registered_at > latest_registered_at:
                latest_registered_at = registered_at
                latest_entries = [entry]
            elif registered_at == latest_registered_at:
                latest_entries.append(entry)

    if not latest_entries:
        return "", []

    customer_counts = {}
    article_counts = {}
    for entry in latest_entries:
        customer = (entry.get("customerName") or "").strip()
        article = (entry.get("articleName") or "").strip()
        weight = max(int(entry.get("punnets") or 0), 1)

        if customer:
            customer_counts[customer] = customer_counts.get(customer, 0) + weight
        if article:
            article_counts[article] = article_counts.get(article, 0) + weight

    loja = ""
    if customer_counts:
        loja = max(customer_counts.items(), key=lambda item: (item[1], item[0]))[0]

    article_hints = [
        {"text": article, "weight": weight}
        for article, weight in sorted(article_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]

    return loja, article_hints


def choose_process_banner(process_candidates, loja="", article_hints=None):
    if not process_candidates:
        return ""

    article_hints = article_hints or []
    loja_norm = normalize_match_text(loja)

    def match_signal(candidate_text, hint_text, weight=1):
        hint_norm = normalize_match_text(hint_text)
        if not hint_norm:
            return (0, 0, 0)

        candidate_tokens = set(tokenize_match_text(candidate_text))
        hint_tokens = tokenize_match_text(hint_text)
        hits = sum(1 for tok in hint_tokens if tok in candidate_tokens)
        return (
            1 if hint_norm in candidate_text else 0,
            hits,
            hits * max(int(weight or 0), 1),
        )

    def candidate_score(candidate):
        haystack = normalize_match_text(
            f"{candidate.get('ds_ordem', '')} {candidate.get('ds_operacao', '')}"
        )

        article_exact = 0
        article_hits = 0
        article_weighted_hits = 0
        for hint in article_hints:
            exact, hits, weighted_hits = match_signal(
                haystack,
                hint.get("text", ""),
                hint.get("weight", 1),
            )
            article_exact = max(article_exact, exact)
            article_hits = max(article_hits, hits)
            article_weighted_hits += weighted_hits

        loja_exact = 0
        loja_hits = 0
        if loja_norm:
            loja_exact, loja_hits, _ = match_signal(haystack, loja, 1)

        return (
            loja_exact,
            loja_hits,
            article_exact,
            article_weighted_hits,
            article_hits,
            candidate.get("count", 0),
            candidate.get("last_entry", ""),
        )

    best_match = max(process_candidates, key=candidate_score)
    best_score = candidate_score(best_match)
    if any(best_score[:5]):
        return build_processo_label(best_match.get("ds_ordem", ""), best_match.get("ds_operacao", ""))

    fallback = max(
        process_candidates,
        key=lambda candidate: (candidate.get("count", 0), candidate.get("last_entry", "")),
    )
    return build_processo_label(fallback.get("ds_ordem", ""), fallback.get("ds_operacao", ""))

GRPC_SERVER = "192.168.30.8:37270"
TSHARK_PATH = r"C:\Program Files\Wireshark\tshark.exe"
TSHARK_IFACE = os.environ.get("TSHARK_IFACE", "Wi-Fi 2")
PRODUCTION_PROCESS_TYPE_ID = "019bdadd-25a2-a3bb-a686-3ceb5594ebc1"
EXCLUDED_USERS = {"MATHEUS"}

# DCS2nG Database config
DCS2NG_SERVER = os.environ.get("DCS2NG_SERVER", "10.0.0.3")
DCS2NG_DATABASE = os.environ.get("DCS2NG_DATABASE", "Dcs2nG")
DCS2NG_DRIVER = os.environ.get("DCS2NG_DRIVER", "{ODBC Driver 17 for SQL Server}")
DCS2NG_USER = os.environ.get("DCS2NG_USER", "matheus.amorim")
DCS2NG_PASSWORD = os.environ.get("DCS2NG_PASSWORD", "Apw7124")

# Armazena dados processados
data_store = {
    "grouped": [],
    "weighing_count": 0,
    "login_count": 0,
    "punnet_count": 0,
    "last_scan": None,
    "scan_count": 0,
    "source": "gRPC",
    "token_status": "pending",
}

data_lock = threading.Lock()

# DCS2nG data cache
dcs2ng_store = {
    "nr_identificacao": {},
    "cd_rcs_humano": {},
    "ds_ordem": "",
    "ds_operacao": "",
    "processo": "",
    "process_candidates": [],
    "last_fetch": 0,
    "status": "pending",
}
dcs2ng_lock = threading.Lock()

# Token global (loaded from .token file or env var, auto-refreshed via tshark)
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
auth_token = os.environ.get("GRPC_TOKEN", None)
if not auth_token and os.path.exists(TOKEN_FILE):
    auth_token = open(TOKEN_FILE).read().strip()
token_lock = threading.Lock()


# ========== gRPC REFLECTION HELPERS ==========

def build_pool(channel, token=None):
    """Builds a DescriptorPool from server reflection."""
    pool = DescriptorPool()
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    added = set()
    meta = [("authorization", f"Bearer {token}")] if token else None

    def add_file(fn):
        if fn in added:
            return
        req = reflection_pb2.ServerReflectionRequest(file_by_filename=fn)
        for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
            if r.HasField("file_descriptor_response"):
                for b in r.file_descriptor_response.file_descriptor_proto:
                    fd = dp2.FileDescriptorProto()
                    fd.ParseFromString(b)
                    if fd.name not in added:
                        for dep in fd.dependency:
                            add_file(dep)
                        try:
                            pool.Add(fd)
                        except Exception:
                            pass
                        added.add(fd.name)

    def add_sym(symbol):
        req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
        for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
            if r.HasField("file_descriptor_response"):
                for b in r.file_descriptor_response.file_descriptor_proto:
                    fd = dp2.FileDescriptorProto()
                    fd.ParseFromString(b)
                    if fd.name not in added:
                        for dep in fd.dependency:
                            add_file(dep)
                        try:
                            pool.Add(fd)
                        except Exception:
                            pass
                        added.add(fd.name)

    for sym in [
        "topcontrol.gamma.ps.core.statistics.StatisticService",
        "topcontrol.gamma.ps.core.analytics.ReportService",
        "topcontrol.gamma.ps.core.timetracking.TimeTrackingService",
    ]:
        add_sym(sym)

    return pool


# ========== TOKEN CAPTURE ==========

def capture_token_from_traffic(max_attempts=3):
    """Captures Bearer token from DesktopClient's gRPC traffic using tshark."""
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[TOKEN] Tentativa {attempt}/{max_attempts} de captura via tshark (60s)...")
            result = subprocess.run(
                [
                    TSHARK_PATH, "-i", TSHARK_IFACE,
                    "-f", "port 37270",
                    "-d", "tcp.port==37270,http2",
                    "-T", "fields",
                    "-e", "http2.header.value",
                    "-a", "duration:60",
                    "-l",
                ],
                capture_output=True, text=True, timeout=75,
            )
            output = result.stdout
            # Find Bearer token in output
            match = re.search(r"Bearer (eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", output)
            if match:
                return match.group(1)
            print(f"[TOKEN] Nenhum Bearer encontrado na tentativa {attempt}")
        except subprocess.TimeoutExpired:
            print(f"[TOKEN] Timeout na tentativa {attempt}")
        except Exception as e:
            print(f"[TOKEN] Erro ao capturar: {e}")
    return None


def get_token_expiry(token):
    """Extracts expiry time from JWT token payload."""
    try:
        payload = token.split(".")[1]
        # Add padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims.get("exp", 0)
    except Exception:
        return 0


def is_token_valid(token):
    """Checks if token is still valid (with 5min margin)."""
    if not token:
        return False
    exp = get_token_expiry(token)
    return time.time() < (exp - 300)


def ensure_token():
    """Ensures we have a valid token, capturing from traffic if needed."""
    global auth_token
    with token_lock:
        if is_token_valid(auth_token):
            return auth_token
        print("[TOKEN] Capturando token do tráfego gRPC...")
        with data_lock:
            data_store["token_status"] = "capturing"
        token = capture_token_from_traffic()
        if token and is_token_valid(token):
            auth_token = token
            # Save to file for persistence
            try:
                with open(TOKEN_FILE, "w") as f:
                    f.write(token)
            except Exception:
                pass
            exp = get_token_expiry(token)
            remaining = (exp - time.time()) / 3600
            print(f"[TOKEN] Capturado! Expira em {remaining:.1f}h")
            with data_lock:
                data_store["token_status"] = "valid"
            return auth_token
        print("[TOKEN] Falha ao capturar token")
        with data_lock:
            data_store["token_status"] = "failed"
        return None


# ========== DCS2nG DATABASE ==========

def get_dcs2ng_connection():
    """Connects to SQL Server DCS2nG database."""
    if not HAS_PYODBC:
        return None
    try:
        if DCS2NG_USER:
            conn_str = (
                f"DRIVER={DCS2NG_DRIVER};SERVER={DCS2NG_SERVER};"
                f"DATABASE={DCS2NG_DATABASE};UID={DCS2NG_USER};PWD={DCS2NG_PASSWORD}"
            )
        else:
            conn_str = (
                f"DRIVER={DCS2NG_DRIVER};SERVER={DCS2NG_SERVER};"
                f"DATABASE={DCS2NG_DATABASE};Trusted_Connection=yes"
            )
        return pyodbc.connect(conn_str, timeout=10)
    except Exception as e:
        print(f"[DCS2NG] Erro ao conectar: {e}")
        return None


def fetch_dcs2ng_data(target_date=None):
    """Fetches Nr Identificação and process info from DCS2nG."""
    conn = get_dcs2ng_connection()
    if not conn:
        with dcs2ng_lock:
            dcs2ng_store["status"] = "no_connection"
        return {}

    result = {
        "nr_identificacao": {},
        "cd_rcs_humano": {},
        "ds_ordem": "",
        "ds_operacao": "",
        "processo": "",
        "process_candidates": [],
    }
    try:
        cursor = conn.cursor()

        # Nr Identificação + CdRcsHumano: use both Nome and NomeAbreviado for matching
        cursor.execute("""
            SELECT rh.Nome, rh.NomeAbreviado, ai.Identificacao, rh.CdRcsHumano
            FROM dbo.RcsHumanos rh WITH(NOLOCK)
            INNER JOIN dbo.AqdIdentificacoes ai WITH(NOLOCK)
                ON ai.UIRelacao = rh.UIRcsHumano
            WHERE rh.Activo = 1 AND ai.Activo = 1
        """)
        nr_map = {}
        cd_map = {}
        for row in cursor.fetchall():
            nome = (row[0] or "").strip()
            nome_abrev = (row[1] or "").strip()
            identificacao = str(row[2]).strip() if row[2] else ""
            cd_rcs = str(row[3]).strip() if row[3] else ""
            # Store multiple key variants for each person
            for n in [nome, nome_abrev]:
                if not n:
                    continue
                nr_map[n.lower()] = identificacao
                cd_map[n.lower()] = cd_rcs
                # Also store without spaces (TopControl concatenates names)
                no_spaces = re.sub(r'\s+', '', n).lower()
                nr_map[no_spaces] = identificacao
                cd_map[no_spaces] = cd_rcs
        result["nr_identificacao"] = nr_map
        result["cd_rcs_humano"] = cd_map

        # Current process candidates (DsOrdem + DsOperacao) for the target date.
        # The final banner is chosen later based on the detected loja/customer.
        date_str = (target_date or datetime.now()).strftime("%Y-%m-%d")
        next_day = ((target_date or datetime.now()) + timedelta(days=1)).strftime("%Y-%m-%d") if target_date else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT DsOrdem, DsOperacao, COUNT(*) as cnt, MAX(DtMaxInicio) as last_entry
            FROM dbo.vwHorasProducaoPHC WITH(NOLOCK)
            WHERE DtMaxInicio >= ? AND DtMaxInicio < ?
              AND LOWER(DsOrdem) NOT LIKE '%servi%gerais%'
              AND LOWER(DsOperacao) NOT LIKE '%servi%gerais%'
              AND LOWER(DsOrdem) NOT LIKE '%etiqueta%'
              AND LOWER(DsOrdem) NOT LIKE '%trabalho n_o atribu%'
              AND LOWER(DsOrdem) NOT LIKE '%stock%'
            GROUP BY DsOrdem, DsOperacao
            ORDER BY COUNT(*) DESC, MAX(DtMaxInicio) DESC
        """, (date_str, next_day))
        process_candidates = []
        for row in cursor.fetchall():
            process_candidates.append({
                "ds_ordem": (row[0] or "").strip(),
                "ds_operacao": (row[1] or "").strip(),
                "count": int(row[2] or 0),
                "last_entry": str(row[3]) if row[3] else "",
            })
        result["process_candidates"] = process_candidates
        if process_candidates:
            best_candidate = max(
                process_candidates,
                key=lambda candidate: (candidate.get("count", 0), candidate.get("last_entry", "")),
            )
            result["ds_ordem"] = best_candidate["ds_ordem"]
            result["ds_operacao"] = best_candidate["ds_operacao"]
            result["processo"] = build_processo_label(result["ds_ordem"], result["ds_operacao"])

        # Update global cache (for live mode)
        if target_date is None:
            with dcs2ng_lock:
                dcs2ng_store["nr_identificacao"] = nr_map
                dcs2ng_store["cd_rcs_humano"] = cd_map
                dcs2ng_store["ds_ordem"] = result["ds_ordem"]
                dcs2ng_store["ds_operacao"] = result["ds_operacao"]
                dcs2ng_store["processo"] = result["processo"]
                dcs2ng_store["process_candidates"] = result["process_candidates"]
                dcs2ng_store["last_fetch"] = time.time()
                dcs2ng_store["status"] = "connected"

        print(f"[DCS2NG] {len(nr_map)} identificações, processo: {result['processo']}")

    except Exception as e:
        print(f"[DCS2NG] Erro: {e}")
        with dcs2ng_lock:
            dcs2ng_store["status"] = "error"
    finally:
        conn.close()

    return result


def match_nr_identificacao(user_name, nr_map):
    """Matches TopControl user name to DCS2nG Nr Identificação.
    
    TopControl concatenates names without spaces (e.g. 'AashaChhetri').
    DCS2nG stores them as 'Aasha Chhetri' (NomeAbreviado) or full name.
    We store both with/without spaces as keys. Also handle slight spelling diffs.
    """
    if not user_name or not nr_map:
        return ""
    name_lower = user_name.strip().lower()
    # Direct match
    if name_lower in nr_map:
        return nr_map[name_lower]
    # Match without spaces (TopControl concatenates names)
    name_no_spaces = re.sub(r'\s+', '', name_lower)
    if name_no_spaces in nr_map:
        return nr_map[name_no_spaces]
    # Exact match on no-spaces variant
    for db_name, nr_id in nr_map.items():
        db_no_spaces = re.sub(r'\s+', '', db_name)
        if name_no_spaces == db_no_spaces:
            return nr_id
    # Strip single-char middle initials from TopControl name
    # e.g. MayaraVSilva -> [Mayara, V, Silva] -> strip 'V' -> mayarasilva
    parts = re.findall(r'[A-Z][a-z]*', user_name.strip())
    if parts:
        long_parts = [p.lower() for p in parts if len(p) > 1]
        name_stripped = ''.join(long_parts)
        if name_stripped != name_no_spaces and name_stripped in nr_map:
            return nr_map[name_stripped]
    # Fuzzy: check if one contains the other (handles middle initials, suffixes)
    for db_name, nr_id in nr_map.items():
        db_no_spaces = re.sub(r'\s+', '', db_name)
        if len(name_no_spaces) >= 6 and len(db_no_spaces) >= 6:
            if name_no_spaces in db_no_spaces or db_no_spaces in name_no_spaces:
                return nr_id
    # Levenshtein-like: allow 1-2 char difference for typos (Mutasse vs Matusse)
    if len(name_no_spaces) >= 8:
        for db_name, nr_id in nr_map.items():
            db_no_spaces = re.sub(r'\s+', '', db_name)
            if abs(len(name_no_spaces) - len(db_no_spaces)) <= 2 and len(db_no_spaces) >= 8:
                # Quick edit distance check (max 2)
                dist = _edit_distance(name_no_spaces, db_no_spaces, max_dist=2)
                if dist <= 2:
                    return nr_id
    # Last resort: match first+last name parts if unique
    # e.g. SilviaVSilva -> first='silvia', last='silva'
    # DB 'Silvia Vaz da Silva' -> first='silvia', last='silva' -> MATCH
    if parts and len(long_parts) >= 2:
        first_last = long_parts[0] + long_parts[-1]
        seen_ids: set = set()
        matches = []
        for k, v in nr_map.items():
            k_words = k.strip().split()
            db_fl = (k_words[0] + k_words[-1]) if len(k_words) >= 2 else re.sub(r'\s+', '', k)
            if db_fl == first_last and v not in seen_ids:
                matches.append((k, v))
                seen_ids.add(v)
        if len(matches) == 1:
            return matches[0][1]
    # Fallback: first name only if unique
    if parts:
        first_name = parts[0].lower()
        if len(first_name) >= 4:
            matches = [(k, v) for k, v in nr_map.items() if k.startswith(first_name)]
            if len(matches) == 1:
                return matches[0][1]
    return ""


def _edit_distance(s1, s2, max_dist=2):
    """Simple edit distance with early termination."""
    if abs(len(s1) - len(s2)) > max_dist:
        return max_dist + 1
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j] + (0 if c1 == c2 else 1), prev[j+1] + 1, curr[j] + 1))
        if min(curr) > max_dist:
            return max_dist + 1
        prev = curr
    return prev[-1]


def enrich_grouped_data(grouped, nr_map, cd_map=None):
    """Adds nrIdentificacao, cdRcsHumano and cpm to each grouped entry."""
    if cd_map is None:
        cd_map = {}
    for g in grouped:
        g["nrIdentificacao"] = match_nr_identificacao(g["user"], nr_map)
        g["cdRcsHumano"] = match_nr_identificacao(g["user"], cd_map) if cd_map else ""
        working_minutes = g["totalWorkingTimeMs"] / 60000.0 if g.get("totalWorkingTimeMs") else 0
        if working_minutes > 0:
            g["cpm"] = round(g["totalPunnets"] / working_minutes, 2)
        else:
            g["cpm"] = 0


def build_group_identity_key(group):
    """Builds a stable identity key for an operator across device changes."""
    user = (group.get("user") or "").strip()
    cd_rcs_humano = (group.get("cdRcsHumano") or "").strip()
    nr_identificacao = (group.get("nrIdentificacao") or "").strip()
    if cd_rcs_humano or nr_identificacao:
        return f"{user}|{cd_rcs_humano}|{nr_identificacao}"
    return f"{user}|{(group.get('device') or '').strip()}"


def append_unique_device(devices, device):
    device_name = (device or "").strip()
    if device_name and device_name not in devices:
        devices.append(device_name)


def collect_group_devices(group):
    devices = []

    for session in sorted(group.get("sessionEntries", []), key=lambda entry: entry.get("loginTime", "")):
        append_unique_device(devices, session.get("device"))

    for entry in sorted(group.get("productionEntries", []), key=lambda item: item.get("registeredAt", "")):
        append_unique_device(devices, entry.get("deviceName"))

    if not devices:
        for device_name in group.get("devices", []):
            append_unique_device(devices, device_name)
        append_unique_device(devices, group.get("device"))

    return devices


def finalize_group_metrics(group, now_dt=None):
    group["productionEntries"].sort(key=lambda entry: entry.get("registeredAt", ""))
    if group["productionEntries"]:
        latest_entry = group["productionEntries"][-1]
        group["currentArticle"] = latest_entry.get("articleName", "")
        group["currentCustomer"] = latest_entry.get("customerName", "")

    group["sessionEntries"].sort(key=lambda entry: entry.get("loginTime", ""))

    devices = collect_group_devices(group)
    group["devices"] = devices
    group["device"] = " / ".join(devices) if devices else (group.get("device") or "")

    working_minutes = group["totalWorkingTimeMs"] / 60000.0 if group.get("totalWorkingTimeMs") else 0
    if working_minutes > 0:
        group["cpm"] = round(group["totalPunnets"] / working_minutes, 2)
    else:
        group["cpm"] = 0

    effective_now = now_dt or datetime.now()
    for entry in group["productionEntries"]:
        start_dt = parse_iso_datetime(entry.get("registeredAt"))
        end_dt = parse_iso_datetime(entry.get("endedAt"))

        interval_minutes = 0.0
        if start_dt and end_dt and end_dt > start_dt:
            interval_minutes = (end_dt - start_dt).total_seconds() / 60.0
        elif start_dt:
            end_dt = start_dt + timedelta(hours=1)
            interval_minutes = 60.0

        overlap_minutes = calculate_session_overlap_minutes(start_dt, end_dt, group["sessionEntries"], effective_now)
        effective_minutes = overlap_minutes or interval_minutes
        if effective_minutes > 0:
            entry["cpm"] = round(entry["punnets"] / effective_minutes, 2)
        else:
            entry["cpm"] = 0


def merge_grouped_data_by_identity(grouped):
    """Merges grouped operator data across devices when the identity matches."""
    merged = {}

    for group in grouped:
        key = build_group_identity_key(group)
        if key not in merged:
            merged[key] = copy.deepcopy(group)
            continue

        target = merged[key]
        target["totalWeight"] += group.get("totalWeight", 0)
        target["totalPunnets"] += group.get("totalPunnets", 0)
        target["bloqueios"] += group.get("bloqueios", 0)
        target["totalSessions"] += group.get("totalSessions", 0)
        target["totalWorkingTimeMs"] += group.get("totalWorkingTimeMs", 0)

        target["articles"] = list(dict.fromkeys(target.get("articles", []) + group.get("articles", [])))
        target["customers"] = list(dict.fromkeys(target.get("customers", []) + group.get("customers", [])))
        target["productionEntries"].extend(copy.deepcopy(group.get("productionEntries", [])))
        target["sessionEntries"].extend(copy.deepcopy(group.get("sessionEntries", [])))

        if not target.get("nrIdentificacao"):
            target["nrIdentificacao"] = group.get("nrIdentificacao", "")
        if not target.get("cdRcsHumano"):
            target["cdRcsHumano"] = group.get("cdRcsHumano", "")

    merged_list = list(merged.values())
    effective_now = datetime.now()
    for group in merged_list:
        group["totalWeight"] = round(group.get("totalWeight", 0), 3)
        finalize_group_metrics(group, effective_now)

    return merged_list


# ========== HELPER ==========

def fmt_local_dt(ldt):
    """Formats a LocalDateTime protobuf message to ISO string."""
    if not ldt or not ldt.year:
        return ""
    return f"{ldt.year:04d}-{ldt.month:02d}-{ldt.day:02d}T{ldt.hour:02d}:{ldt.minute:02d}:{ldt.second:02d}"


def fmt_duration(seconds):
    """Formats seconds to HH:MM:SS string."""
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def parse_iso_datetime(value):
    """Parses an ISO datetime string to a naive datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def calculate_session_overlap_minutes(start_dt, end_dt, session_entries, now_dt=None):
    """Returns how many session minutes overlap the provided time range."""
    if not start_dt or not end_dt or end_dt <= start_dt:
        return 0.0

    effective_now = now_dt or datetime.now()
    overlap_seconds = 0.0

    for session in session_entries:
        login_dt = parse_iso_datetime(session.get("loginTime"))
        if not login_dt:
            continue

        logout_dt = parse_iso_datetime(session.get("logoutTime")) or effective_now
        if logout_dt <= start_dt or login_dt >= end_dt:
            continue

        overlap_start = max(start_dt, login_dt)
        overlap_end = min(end_dt, logout_dt)
        if overlap_end > overlap_start:
            overlap_seconds += (overlap_end - overlap_start).total_seconds()

    return overlap_seconds / 60.0


def get_multilingual_name(msg, lang="en"):
    """Extracts name from MultilingualString, preferring the given language."""
    if hasattr(msg, "translations") and lang in msg.translations:
        return msg.translations[lang]
    if hasattr(msg, "value"):
        return msg.value
    return str(msg)


# ========== gRPC DATA FETCH ==========

def fetch_all_data(pool, channel, token):
    """Fetches statistics, hourly weighing report, and login records."""
    meta = [("authorization", f"Bearer {token}")]

    # 1) Weighing Statistics (totals per user/device/article)
    WStatReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest"))
    WStatResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataResponse"))

    wreq = WStatReq()
    wreq.time_dimension = 0  # NONE
    wreq.dimensions.extend([2, 3, 0])  # USER, DEVICE, ARTICLE
    wreq.metrics.extend([1, 14, 18, 33])  # QUANTITY_SUM, WEIGHT_KG, AVG_WEIGHT_KG, QUANTITY_NOT_ACCEPTED
    fc = wreq.filter_configurations.add()
    fc.time_filter.time_filter = 2  # TODAY

    stat_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.statistics.StatisticService/GetWeighingStatisticData",
        request_serializer=WStatReq.SerializeToString,
        response_deserializer=WStatResp.FromString,
    )(wreq, metadata=meta)

    # 2) WeighingReport HOUR (per-hour punnets per user/device/article)
    WRepReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
    WRepResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))

    rreq = WRepReq()
    rreq.time_filter = 3  # TODAY
    rreq.time_dimension = 2  # HOUR
    rreq.process_type_id.value = PRODUCTION_PROCESS_TYPE_ID
    rreq.dimensions.extend([3, 4, 1, 6])  # USER, DEVICE, ARTICLE, CUSTOMER
    rreq.metrics.extend([1, 14, 17])  # QUANTITY, WEIGHT_KG, AVERAGE_WEIGHT_KG

    report_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
        request_serializer=WRepReq.SerializeToString,
        response_deserializer=WRepResp.FromString,
    )(rreq, metadata=meta)

    # 3) GetLogins (individual login/logout records for today)
    LReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.timetracking.GetLoginsRequest"))
    LResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.timetracking.GetLoginsResponse"))

    lreq = LReq()
    lreq.time_filter = 3  # TODAY

    login_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.timetracking.TimeTrackingService/GetLogins",
        request_serializer=LReq.SerializeToString,
        response_deserializer=LResp.FromString,
    )(lreq, metadata=meta)

    return stat_resp, report_resp, login_resp


def process_all_data(stat_resp, report_resp, login_resp):
    """Processes all gRPC responses into grouped data for the frontend."""
    grouped_map = {}

    def ensure_group(user, device):
        key = f"{user}|{device}"
        if key not in grouped_map:
            grouped_map[key] = {
                "user": user,
                "device": device,
                "totalWeight": 0,
                "totalPunnets": 0,
                "bloqueios": 0,
                "totalSessions": 0,
                "totalWorkingTimeMs": 0,
                "articles": [],
                "customers": [],
                "currentArticle": "",
                "currentCustomer": "",
                "productionEntries": [],
                "sessionEntries": [],
            }
        return grouped_map[key]

    # 1) Build base groups from statistics (totals)
    for rec in stat_resp.records:
        user = rec.user.display_name if rec.HasField("user") else ""
        device = rec.device.name if rec.HasField("device") else ""
        article = rec.article.name if rec.HasField("article") else ""
        if not user:
            continue
        if user.upper() in EXCLUDED_USERS:
            continue

        group = ensure_group(user, device)
        weight = float(rec.totals.weight_kg.value) if rec.totals.HasField("weight_kg") else 0
        qty = int(float(rec.totals.quantity_sum.value)) if rec.totals.HasField("quantity_sum") else 0
        bloqueios = int(float(rec.totals.quantity_not_accepted.value)) if rec.totals.HasField("quantity_not_accepted") else 0

        group["totalWeight"] += weight
        group["bloqueios"] += bloqueios

        if article and article not in group["articles"]:
            group["articles"].append(article)

    # 2) Add hourly production entries from WeighingReport
    for item in report_resp.items:
        user = item.user_display_name
        device = item.device_name
        article = item.article_name
        if not user:
            continue
        if user.upper() in EXCLUDED_USERS:
            continue

        group = ensure_group(user, device)

        # Access 'from' field (Python keyword) via descriptor
        f = getattr(item, item.DESCRIPTOR.fields_by_number[1].name)
        t = item.to
        time_from = f"{f.hour:02d}:{f.minute:02d}" if f.year else "?"
        time_to = f"{t.hour:02d}:{t.minute:02d}" if t.year else "?"

        qty = item.quantity.value if item.HasField("quantity") else "0"
        wkg = item.weight_kg.value if item.HasField("weight_kg") else "0"
        avg = item.average_weight_kg.value if item.HasField("average_weight_kg") else "0"

        customer = item.customer_name if hasattr(item, 'customer_name') else ""

        group["productionEntries"].append({
            "articleName": article,
            "timeRange": f"{time_from} - {time_to}",
            "registeredAt": fmt_local_dt(f),
            "endedAt": fmt_local_dt(t),
            "punnets": int(float(qty)),
            "netWeight": round(float(wkg), 3),
            "avgWeight": round(float(avg), 3),
            "deviceName": device,
            "customerName": customer,
        })
        group["totalPunnets"] += int(float(qty))

        if customer and customer not in group["customers"]:
            group["customers"].append(customer)

    # 3) Add individual login/logout sessions from GetLogins
    for login in login_resp.items:
        user = login.user.display_name if login.HasField("user") else ""
        device = login.device.name if login.HasField("device") else ""
        if not user:
            continue
        if user.upper() in EXCLUDED_USERS:
            continue

        group = ensure_group(user, device)

        activity = ""
        if login.HasField("activity") and login.activity.HasField("name"):
            activity = get_multilingual_name(login.activity.name, "en")

        line_name = login.line.name if login.HasField("line") else ""
        login_time = fmt_local_dt(login.login_time) if login.HasField("login_time") else ""
        logout_time = fmt_local_dt(login.logout_time) if login.HasField("logout_time") else ""

        working_secs = login.working_time.seconds if login.HasField("working_time") else 0
        working_ms = working_secs * 1000

        group["totalSessions"] += 1
        group["totalWorkingTimeMs"] += working_ms

        group["sessionEntries"].append({
            "activity": activity,
            "loginTime": login_time,
            "logoutTime": logout_time,
            "workingTime": fmt_duration(working_secs),
            "line": line_name,
            "device": device,
        })

    # Finalize per-device groups before optional identity merge.
    for group in grouped_map.values():
        group["nrIdentificacao"] = ""
        group["cdRcsHumano"] = ""
        finalize_group_metrics(group)

    return list(grouped_map.values())


# ========== MAIN SCAN LOOP ==========

def scan_grpc():
    """Thread that polls gRPC services every 5 seconds."""
    pool = None
    channel = None

    while True:
        try:
            token = ensure_token()
            if not token:
                print("[SCAN] Sem token válido, aguardando...")
                time.sleep(10)
                continue

            if channel is None:
                print("[gRPC] Conectando a", GRPC_SERVER)
                channel = grpc.insecure_channel(GRPC_SERVER)
                pool = build_pool(channel, token)
                print("[gRPC] Pool carregado, pronto para consultas")

            stat_resp, report_resp, login_resp = fetch_all_data(pool, channel, token)
            grouped = process_all_data(stat_resp, report_resp, login_resp)

            w_count = len(stat_resp.records)
            r_count = len(report_resp.items)
            l_count = len(login_resp.items)
            total_punnets = sum(g["totalPunnets"] for g in grouped)

            with data_lock:
                data_store["grouped"] = grouped
                data_store["weighing_count"] = w_count
                data_store["login_count"] = l_count
                data_store["punnet_count"] = total_punnets
                data_store["last_scan"] = time.time()
                data_store["scan_count"] += 1
                data_store["token_status"] = "valid"

            print(f"[SCAN #{data_store['scan_count']}] {w_count} stats, {r_count} hourly, {l_count} logins, {total_punnets} punnets, {len(grouped)} grupos")

            # Refresh DCS2nG data every 60 seconds
            with dcs2ng_lock:
                last_dcs = dcs2ng_store["last_fetch"]
            if time.time() - last_dcs > 60:
                try:
                    fetch_dcs2ng_data()
                except Exception as e:
                    print(f"[DCS2NG] Erro no refresh: {e}")

        except grpc.RpcError as e:
            code = e.code()
            print(f"[ERRO gRPC] {code} - {e.details()}")
            if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
                print("[TOKEN] Token invalidado pelo servidor, recapturando...")
                with token_lock:
                    global auth_token
                    auth_token = None
                with data_lock:
                    data_store["token_status"] = "expired"
                # Reset channel so pool is rebuilt with new token
                channel = None
                pool = None
            elif code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                channel = None
                pool = None
        except Exception as e:
            print(f"[ERRO] Scan: {e}")
            channel = None
            pool = None

        time.sleep(5)


# ========== ROTAS DA API ==========

# Cache for history queries (avoids re-fetching same date)
history_cache = {}
history_cache_lock = threading.Lock()

def fetch_data_for_date(pool, channel, token, target_date):
    """Fetches statistics, hourly weighing report, and login records for a specific date."""
    meta = [("authorization", f"Bearer {token}")]
    y, m, d = target_date.year, target_date.month, target_date.day

    # 1) Weighing Statistics
    WStatReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest"))
    WStatResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataResponse"))

    wreq = WStatReq()
    wreq.time_dimension = 0  # NONE
    wreq.dimensions.extend([2, 3, 0])  # USER, DEVICE, ARTICLE
    wreq.metrics.extend([1, 14, 18, 33])  # QUANTITY_SUM, WEIGHT_KG, AVG_WEIGHT_KG, QUANTITY_NOT_ACCEPTED
    fc = wreq.filter_configurations.add()
    fc.time_filter.time_filter = 1  # STATISTIC_TIME_FILTER_DATE
    fc.time_filter.date.year = y
    fc.time_filter.date.month = m
    fc.time_filter.date.day = d

    stat_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.statistics.StatisticService/GetWeighingStatisticData",
        request_serializer=WStatReq.SerializeToString,
        response_deserializer=WStatResp.FromString,
    )(wreq, metadata=meta)

    # 2) WeighingReport HOUR
    WRepReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
    WRepResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))

    rreq = WRepReq()
    rreq.time_filter = 2  # REPORT_TIME_FILTER_DATE
    rreq.date.year = y
    rreq.date.month = m
    rreq.date.day = d
    rreq.time_dimension = 2  # HOUR
    rreq.process_type_id.value = PRODUCTION_PROCESS_TYPE_ID
    rreq.dimensions.extend([3, 4, 1, 6])  # USER, DEVICE, ARTICLE, CUSTOMER
    rreq.metrics.extend([1, 14, 17])  # QUANTITY, WEIGHT_KG, AVERAGE_WEIGHT_KG

    report_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
        request_serializer=WRepReq.SerializeToString,
        response_deserializer=WRepResp.FromString,
    )(rreq, metadata=meta)

    # 3) GetLogins
    LReq = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.timetracking.GetLoginsRequest"))
    LResp = GetMessageClass(pool.FindMessageTypeByName(
        "topcontrol.gamma.ps.core.timetracking.GetLoginsResponse"))

    lreq = LReq()
    lreq.time_filter = 2  # LOGIN_TIME_FILTER_DATE
    lreq.date.year = y
    lreq.date.month = m
    lreq.date.day = d

    login_resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.timetracking.TimeTrackingService/GetLogins",
        request_serializer=LReq.SerializeToString,
        response_deserializer=LResp.FromString,
    )(lreq, metadata=meta)

    return stat_resp, report_resp, login_resp


@app.route("/api/data")
def get_data():
    """Retorna dados consolidados (hoje)."""
    with data_lock:
        grouped = data_store["grouped"]

    with dcs2ng_lock:
        nr_map = dcs2ng_store["nr_identificacao"]
        cd_map = dcs2ng_store["cd_rcs_humano"]
        processo = dcs2ng_store["processo"]
        process_candidates = dcs2ng_store["process_candidates"]
        dcs_status = dcs2ng_store["status"]

    # Enrich with DCS2nG data
    enriched = copy.deepcopy(grouped)
    enrich_grouped_data(enriched, nr_map, cd_map)
    enriched = merge_grouped_data_by_identity(enriched)

    loja, article_hints = collect_recent_order_context(enriched)
    if not loja:
        all_customers = []
        for g in enriched:
            if g.get("currentCustomer"):
                all_customers.append(g["currentCustomer"])
        loja = max(set(all_customers), key=all_customers.count) if all_customers else ""
    if not article_hints:
        article_hints = collect_article_hints(enriched)
    processo_banner = choose_process_banner(process_candidates, loja, article_hints) or processo

    with data_lock:
        return jsonify({
            "grouped": enriched,
            "processoBanner": processo_banner,
            "lojaBanner": loja,
            "dcsStatus": dcs_status,
            "stats": {
                "productionEntries": data_store["weighing_count"],
                "sessionEntries": data_store["login_count"],
                "punnetCount": data_store["punnet_count"],
                "groupedCount": len(enriched),
                "lastScan": data_store["last_scan"],
                "scanCount": data_store["scan_count"],
                "filesFound": [],
                "source": data_store["source"],
                "tokenStatus": data_store["token_status"],
            },
        })


@app.route("/api/history")
def get_history():
    """Retorna dados para uma data específica. Parâmetro ?date=YYYY-MM-DD"""
    date_str = flask_request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parâmetro 'date' é obrigatório (YYYY-MM-DD)"}), 400

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400

    # Check cache (cache for 60 seconds)
    cache_key = date_str
    with history_cache_lock:
        if cache_key in history_cache:
            cached_time, cached_data = history_cache[cache_key]
            if time.time() - cached_time < 60:
                return jsonify(cached_data)

    # Need to fetch from gRPC
    token = ensure_token()
    if not token:
        return jsonify({"error": "Sem token válido"}), 503

    try:
        channel = grpc.insecure_channel(GRPC_SERVER)
        pool = build_pool(channel, token)
        stat_resp, report_resp, login_resp = fetch_data_for_date(pool, channel, token, target_date)
        grouped = process_all_data(stat_resp, report_resp, login_resp)

        # Enrich with DCS2nG data
        dcs_data = fetch_dcs2ng_data(target_date=target_date)
        enrich_grouped_data(grouped, dcs_data.get("nr_identificacao", {}), dcs_data.get("cd_rcs_humano", {}))
        grouped = merge_grouped_data_by_identity(grouped)
        total_punnets = sum(g["totalPunnets"] for g in grouped)

        all_customers = []
        for g in grouped:
            if g.get("currentCustomer"):
                all_customers.append(g["currentCustomer"])
        loja = max(set(all_customers), key=all_customers.count) if all_customers else ""
        article_hints = collect_article_hints(grouped)
        processo_banner = choose_process_banner(
            dcs_data.get("process_candidates", []),
            loja,
            article_hints,
        ) or dcs_data.get("processo", "")

        result = {
            "grouped": grouped,
            "processoBanner": processo_banner,
            "lojaBanner": loja,
            "stats": {
                "productionEntries": len(stat_resp.records),
                "sessionEntries": len(login_resp.items),
                "punnetCount": total_punnets,
                "groupedCount": len(grouped),
                "date": date_str,
                "source": "gRPC",
                "tokenStatus": "valid",
            },
        }

        # Cache the result
        with history_cache_lock:
            history_cache[cache_key] = (time.time(), result)

        print(f"[HISTORY] {date_str}: {len(stat_resp.records)} stats, {len(report_resp.items)} hourly, {len(login_resp.items)} logins, {total_punnets} punnets, {len(grouped)} grupos")
        return jsonify(result)

    except grpc.RpcError as e:
        code = e.code()
        print(f"[HISTORY ERRO] {code} - {e.details()}")
        if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
            with token_lock:
                global auth_token
                auth_token = None
            return jsonify({"error": "Token expirado, tente novamente"}), 401
        return jsonify({"error": f"Erro gRPC: {code}"}), 500
    except Exception as e:
        print(f"[HISTORY ERRO] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/history/range")
def get_history_range():
    """Retorna dados agregados para um intervalo de datas.
    Parâmetros: ?start=YYYY-MM-DD&end=YYYY-MM-DD"""
    start_str = flask_request.args.get("start")
    end_str = flask_request.args.get("end")
    if not start_str or not end_str:
        return jsonify({"error": "Parâmetros 'start' e 'end' são obrigatórios (YYYY-MM-DD)"}), 400

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400

    if end_date < start_date:
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days > 31:
        return jsonify({"error": "Intervalo máximo de 31 dias"}), 400

    token = ensure_token()
    if not token:
        return jsonify({"error": "Sem token válido"}), 503

    try:
        channel = grpc.insecure_channel(GRPC_SERVER)
        pool = build_pool(channel, token)

        days_data = []
        current = start_date
        while current <= end_date:
            try:
                stat_resp, report_resp, login_resp = fetch_data_for_date(pool, channel, token, current)
                grouped = process_all_data(stat_resp, report_resp, login_resp)
                dcs_data = fetch_dcs2ng_data(target_date=current)
                enrich_grouped_data(grouped, dcs_data.get("nr_identificacao", {}), dcs_data.get("cd_rcs_humano", {}))
                grouped = merge_grouped_data_by_identity(grouped)
                total_punnets = sum(g["totalPunnets"] for g in grouped)
                total_weight = sum(g["totalWeight"] for g in grouped)
                all_customers = []
                for g in grouped:
                    if g.get("currentCustomer"):
                        all_customers.append(g["currentCustomer"])
                loja = max(set(all_customers), key=all_customers.count) if all_customers else ""
                article_hints = collect_article_hints(grouped)
                processo_banner = choose_process_banner(
                    dcs_data.get("process_candidates", []),
                    loja,
                    article_hints,
                ) or dcs_data.get("processo", "")
                days_data.append({
                    "date": current.strftime("%Y-%m-%d"),
                    "grouped": grouped,
                    "totalPunnets": total_punnets,
                    "totalWeight": round(total_weight, 3),
                    "operatorCount": len(grouped),
                    "processoBanner": processo_banner,
                })
                print(f"[RANGE] {current.strftime('%Y-%m-%d')}: {len(grouped)} grupos, {total_punnets} cestas")
            except Exception as e:
                print(f"[RANGE] {current.strftime('%Y-%m-%d')}: Erro - {e}")
                days_data.append({
                    "date": current.strftime("%Y-%m-%d"),
                    "grouped": [],
                    "totalPunnets": 0,
                    "totalWeight": 0,
                    "operatorCount": 0,
                    "processoBanner": "",
                })
            current += timedelta(days=1)

        combined_source = [group for day in days_data for group in day["grouped"]]
        combined_list = merge_grouped_data_by_identity(combined_source)

        result = {
            "days": days_data,
            "combined": combined_list,
            "start": start_str,
            "end": end_str,
            "totalDays": len(days_data),
            "daysWithData": sum(1 for d in days_data if d["operatorCount"] > 0),
        }
        print(f"[RANGE] {start_str} a {end_str}: {len(days_data)} dias, {len(combined_list)} operadores")
        return jsonify(result)

    except grpc.RpcError as e:
        code = e.code()
        print(f"[RANGE ERRO] {code} - {e.details()}")
        if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
            with token_lock:
                auth_token = None
            return jsonify({"error": "Token expirado, tente novamente"}), 401
        return jsonify({"error": f"Erro gRPC: {code}"}), 500
    except Exception as e:
        print(f"[RANGE ERRO] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug-dcs")
def debug_dcs():
    """Debug endpoint to check DCS2nG data."""
    with dcs2ng_lock:
        nr_count = len(dcs2ng_store["nr_identificacao"])
        sample_keys = list(dcs2ng_store["nr_identificacao"].keys())[:20]
        sample_data = {k: dcs2ng_store["nr_identificacao"][k] for k in sample_keys}
        return jsonify({
            "status": dcs2ng_store["status"],
            "last_fetch": dcs2ng_store["last_fetch"],
            "nr_count": nr_count,
            "processo": dcs2ng_store["processo"],
            "ds_ordem": dcs2ng_store["ds_ordem"],
            "ds_operacao": dcs2ng_store["ds_operacao"],
            "sample_nr_map": sample_data,
        })


@app.route("/api/debug-orders")
def debug_orders():
    """Debug: list ALL orders for today from DCS2nG."""
    conn = get_dcs2ng_connection()
    if not conn:
        return jsonify({"error": "Sem conexão DCS2nG"}), 503
    try:
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT DsOrdem, DsOperacao, COUNT(*) as cnt, MAX(DtMaxInicio) as last_entry
            FROM dbo.vwHorasProducaoPHC WITH(NOLOCK)
            WHERE DtMaxInicio >= ? AND DtMaxInicio < ?
            GROUP BY DsOrdem, DsOperacao
            ORDER BY MAX(DtMaxInicio) DESC
        """, (today, tomorrow))
        orders = []
        for row in cursor.fetchall():
            orders.append({
                "ds_ordem": (row[0] or "").strip(),
                "ds_operacao": (row[1] or "").strip(),
                "count": row[2],
                "last_entry": str(row[3]) if row[3] else "",
            })
        return jsonify({"date": today, "orders": orders})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/status")
def get_status():
    """Retorna status do monitoramento."""
    with data_lock:
        return jsonify({
            "running": True,
            "lastScan": data_store["last_scan"],
            "scanCount": data_store["scan_count"],
            "source": data_store["source"],
            "tokenStatus": data_store["token_status"],
            "weighingRecords": data_store["weighing_count"],
            "loginRecords": data_store["login_count"],
            "punnetCount": data_store["punnet_count"],
            "groupedCount": len(data_store["grouped"]),
            "server": GRPC_SERVER,
        })


# Serve frontend SPA (catch-all for non-API routes)
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the built frontend from dist/ folder."""
    if os.path.isdir(DIST_DIR):
        file_path = os.path.join(DIST_DIR, path)
        if path and os.path.isfile(file_path):
            return send_from_directory(DIST_DIR, path)
        return send_from_directory(DIST_DIR, "index.html")
    return "Frontend not built. Run: npm run build", 404


if __name__ == "__main__":
    print("=" * 60)
    print("  SERVIDOR - Dados DesktopClient via gRPC")
    print("=" * 60)
    print(f"  Servidor gRPC: {GRPC_SERVER}")
    print(f"  APIs: StatisticService + ReportService + TimeTrackingService")
    print()

    # Inicia fetch DCS2nG imediatamente
    print("[DCS2NG] Buscando dados iniciais...")
    try:
        fetch_dcs2ng_data()
    except Exception as e:
        print(f"[DCS2NG] Erro no fetch inicial: {e}")

    # Inicia thread de monitoramento gRPC
    scan_thread = threading.Thread(target=scan_grpc, daemon=True)
    scan_thread.start()

    print("[SERVER] API disponível em http://localhost:5000")
    print("[SERVER] Endpoints:")
    print("  GET  /api/data            - Dados consolidados (hoje)")
    print("  GET  /api/history?date=   - Dados por data (YYYY-MM-DD)")
    print("  GET  /api/status          - Status do monitoramento")
    print()

    app.run(host="0.0.0.0", port=5000, debug=False)
