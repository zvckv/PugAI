# =============================================================================
# PUG AI — Application de chat local basée sur GPT4All + Streamlit
# =============================================================================

import streamlit as st
import streamlit.components.v1 as components
from gpt4all import GPT4All
import uuid
import json
import datetime
import io
import threading
import os
import glob

import pypdf
try:
    import docx2txt
except ImportError:
    docx2txt = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None


# =============================================================================
# CONFIGURATION DE LA PAGE
# =============================================================================

# Utilisation de st.session_state pour gérer l'état de la sidebar
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "expanded"

st.set_page_config(
    page_title="Pug AI",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state=st.session_state.sidebar_state,
)


# =============================================================================
# FONCTIONS — Gestion des discussions
# =============================================================================

SAUVEGARDE_DIR = "sauvegardes_pug"
os.makedirs(SAUVEGARDE_DIR, exist_ok=True)

def sauvegarder_tout():
    with open("historique_pug.json", "w", encoding="utf-8") as f:
        json.dump(st.session_state.discussions, f, ensure_ascii=False, indent=2)

def sauvegarder_horodatee():
    horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = os.path.join(SAUVEGARDE_DIR, f"sauvegarde_{horodatage}.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(st.session_state.discussions, f, ensure_ascii=False, indent=2)
    sauvegardes = sorted(glob.glob(os.path.join(SAUVEGARDE_DIR, "sauvegarde_*.json")))
    for old in sauvegardes[:-20]:
        try:
            os.remove(old)
        except Exception:
            pass
    return chemin

def charger_tout():
    try:
        with open("historique_pug.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def creer_nouvelle_discussion(titre_initial="Nouvelle discussion"):
    id_unique = str(uuid.uuid4())
    st.session_state.discussions[id_unique] = {
        "titre": titre_initial,
        "messages": [],
        "epinglé": False,
    }
    st.session_state.discussion_actuelle = id_unique
    st.session_state.document_contexte = ""
    st.session_state.document_nom = ""
    sauvegarder_tout()
    return id_unique

def interrompre():
    st.session_state.stop_generation = True


# =============================================================================
# FONCTIONS — Extraction de texte
# =============================================================================

def extraire_texte_pdf(fichier_bytes):
    lecteur = pypdf.PdfReader(io.BytesIO(fichier_bytes))
    return "".join(page.extract_text() or "" for page in lecteur.pages).strip()

def extraire_texte_docx(fichier_bytes):
    if docx2txt is None:
        return "[Erreur] docx2txt n'est pas installé. Lancez : pip install docx2txt"
    return docx2txt.process(io.BytesIO(fichier_bytes))

def extraire_texte_txt(fichier_bytes):
    try:
        return fichier_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return fichier_bytes.decode("latin-1")

def extraire_texte(fichier_uploade):
    nom = fichier_uploade.name.lower()
    contenu = fichier_uploade.read()
    try:
        if nom.endswith(".pdf"):
            return extraire_texte_pdf(contenu), None
        elif nom.endswith(".docx"):
            return extraire_texte_docx(contenu), None
        elif nom.endswith(".txt"):
            return extraire_texte_txt(contenu), None
        else:
            return "", "Format non supporté. Utilisez PDF, DOCX ou TXT."
    except Exception as e:
        return "", f"Erreur lors de la lecture : {e}"

def tronquer_contexte(texte, max_chars=3000):
    if len(texte) <= max_chars:
        return texte
    return texte[:max_chars] + "\n\n[... document tronqué ...]"


# =============================================================================
# FONCTIONS — Synthèse vocale
# =============================================================================

_tts_stop_event = threading.Event()
_tts_moteur_ref = [None]

def lire_texte_tts(texte):
    if pyttsx3 is None:
        st.warning("pyttsx3 n'est pas installé. Lancez : pip install pyttsx3")
        return
    arreter_tts()
    _tts_stop_event.clear()

    def _lire():
        try:
            moteur = pyttsx3.init()
            _tts_moteur_ref[0] = moteur
            moteur.setProperty("rate", 160)
            moteur.setProperty("volume", 1.0)
            moteur.say(texte)
            moteur.startLoop(False)
            while not _tts_stop_event.is_set():
                if not moteur.iterate():
                    break
            moteur.endLoop()
        except Exception:
            pass
        finally:
            _tts_moteur_ref[0] = None
            st.session_state.tts_actif = False

    threading.Thread(target=_lire, daemon=True).start()
    st.session_state.tts_actif = True

def arreter_tts():
    _tts_stop_event.set()
    moteur = _tts_moteur_ref[0]
    if moteur is not None:
        try:
            moteur.stop()
        except Exception:
            pass
        _tts_moteur_ref[0] = None
    st.session_state.tts_actif = False


# =============================================================================
# CONSTANTES
# =============================================================================

MODES_PERSONNALITE = {
    "Sérieux":     "Tu es un assistant professionnel, précis et factuel. Tu vas droit au but.",
    "Créatif":     "Tu es un assistant créatif et imaginatif. Tu proposes des idées originales et inattendues.",
    "Sarcastique": "Tu es un assistant sarcastique et légèrement ironique, mais toujours utile malgré tout.",
    "Pédagogue":   "Tu es un assistant pédagogue. Tu expliques toujours avec des exemples simples et des analogies.",
}

LONGUEUR_TOKENS = {
    "Courte":    400,
    "Normale":   1000,
    "Détaillée": 2000,
}

LANGUES_REPONSE = {
    "Français":         "Réponds toujours en français.",
    "English":          "Always reply in English.",
    "Español":          "Responde siempre en español.",
    "Deutsch":          "Antworte immer auf Deutsch.",
    "Auto (détection)": "",
}

SUGGESTIONS_DEMARRAGE = [
    "Explique-moi la blockchain simplement",
    "Aide-moi à rédiger un email professionnel",
    "Donne-moi 5 astuces de productivité",
    "Résume le concept de machine learning",
    "Crée un plan d'action pour un projet",
    "Quels sont les défis du changement climatique ?",
]


# =============================================================================
# SESSION STATE
# =============================================================================

defaults = {
    "discussions":                charger_tout(),
    "corbeille":                  {},
    "discussion_actuelle":        None,
    "stop_generation":            False,
    "mes_preferences":            "",
    "document_contexte":          "",
    "document_nom":               "",
    "mode_personnalite":          "Sérieux",
    "longueur_reponse":           "Normale",
    "langue_reponse":             "Français",
    "renommer_id":                None,
    "tts_actif":                  False,
    "theme":                      "Clair",
    "confirmer_suppr_id":         None,
    "recherche_messages":         "",
    "indicateur_ecriture":        False,
    "derniere_sauvegarde_auto":   None,
    "afficher_corbeille":         False,
    "sidebar_epinglees_ouvert":   True,
    "sidebar_recentes_ouvert":    True,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.discussions:
    creer_nouvelle_discussion()
if st.session_state.discussion_actuelle is None:
    st.session_state.discussion_actuelle = list(st.session_state.discussions.keys())[0]

id_conv = st.session_state.discussion_actuelle

# Sauvegarde auto toutes les 5 min
maintenant = datetime.datetime.now()
derniere = st.session_state.derniere_sauvegarde_auto
if derniere is None or (maintenant - derniere).total_seconds() > 300:
    if st.session_state.discussions:
        sauvegarder_horodatee()
    st.session_state.derniere_sauvegarde_auto = maintenant


# =============================================================================
# CSS — thème dynamique
# =============================================================================

theme = st.session_state.get("theme", "Clair")

if theme == "Sombre":
    tv = {
        "surface":          "#1A1210",
        "surface2":         "#221815",
        "border":           "#3A2820",
        "text_main":        "#F0E6DF",
        "text_muted":       "#9E8577",
        "bubble_ai_bg":     "#2A1E18",
        "bubble_ai_border": "#4A3020",
        "bubble_ai_color":  "#F0E6DF",
        "input_bg":         "#221815",
        "input_color":      "#F0E6DF",
        "metric_bg":        "#221815",
        "tts_bg":           "#2A1E18",
        "tts_border":       "#4A3020",
        "tts_color":        "#FF7043",
        "search_highlight": "#4A3020",
    }
else:
    tv = {
        "surface":          "#F5EFE8",
        "surface2":         "#EDE5DC",
        "border":           "#C8BDB4",
        "text_main":        "#1A0F08",
        "text_muted":       "#5C4A3E",
        "bubble_ai_bg":     "#FFFFFF",
        "bubble_ai_border": "#C8BDB4",
        "bubble_ai_color":  "#1A0F08",
        "input_bg":         "#FFFFFF",
        "input_color":      "#1A0F08",
        "metric_bg":        "#EDE5DC",
        "tts_bg":           "#FFF0EA",
        "tts_border":       "#FFCCBC",
        "tts_color":        "#B03A10",
        "search_highlight": "#FFE0CC",
    }

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&display=swap');

    :root {{
        --orange:       #E25822;
        --orange-light: #FF7043;
        --orange-pale:  #FFF0EA;
        --orange-mid:   #FFCCBC;
        --surface:      {tv["surface"]};
        --surface2:     {tv["surface2"]};
        --border:       {tv["border"]};
        --text-main:    {tv["text_main"]};
        --text-muted:   {tv["text_muted"]};
        --radius:       10px;
        --shadow:       0 2px 10px rgba(0,0,0,0.09);
    }}

    html, body, [class*="css"] {{
        font-family: 'Sora', sans-serif !important;
    }}

    .main, .block-container {{
        background: var(--surface) !important;
        padding-top: 1.5rem !important;
    }}

    .main p, .main li, .main span, .main div,
    .main label, .main h1, .main h2, .main h3,
    .main h4, .main h5, .main h6,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] div,
    [data-testid="stMarkdownContainer"] strong,
    [data-testid="stMarkdownContainer"] em,
    [data-testid="stMarkdownContainer"] code,
    .stCaption, .stCaption p,
    .stInfo p, .stSuccess p, .stWarning p, .stError p {{
        color: {tv["text_main"]} !important;
    }}

    small, .caption, [data-testid="stCaptionContainer"] p {{
        color: {tv["text_muted"]} !important;
    }}

    /* ── App Icon / Logo Background (Uniquement lui en noir !) ────────────── */
    .logo-bg {{
        background: linear-gradient(135deg, #111111 0%, #333333 100%);
        border-radius: 12px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 12px rgba(17,17,17,0.3);
    }}
    .logo-bg-main {{ width: 56px; height: 56px; }}
    .logo-bg-main img {{ width: 38px; }}
    .logo-bg-sidebar {{ width: 44px; height: 44px; }}
    .logo-bg-sidebar img {{ width: 28px; }}

    /* ── Sidebar ──────────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {{
        background: {tv["surface2"]} !important;
        border-right: 1px solid {tv["border"]};
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] li {{
        color: {tv["text_main"]} !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background: {tv["surface"]} !important;
        border: 1px solid {tv["border"]} !important;
        color: {tv["text_main"]} !important;
        border-radius: 8px !important;
        font-size: 0.82rem !important;
        font-family: 'Sora', sans-serif !important;
        padding: 6px 10px !important;
        transition: background 0.18s, border-color 0.18s;
        font-weight: 600 !important;
        width: 100% !important;
    }}
    [data-testid="stSidebar"] .stButton > button *,
    [data-testid="stSidebar"] .stButton > button p,
    [data-testid="stSidebar"] .stButton > button span,
    [data-testid="stSidebar"] .stButton > button div,
    [data-testid="stSidebar"] .stButton > button small {{
        color: {tv["text_main"]} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: var(--orange) !important;
        border-color: var(--orange) !important;
        color: #fff !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover *,
    [data-testid="stSidebar"] .stButton > button:hover p,
    [data-testid="stSidebar"] .stButton > button:hover span {{
        color: #fff !important;
    }}
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stTextInput label {{
        color: {tv["text_main"]} !important;
    }}
    [data-testid="stSidebar"] .stSelectbox > div > div {{
        background: {tv["input_bg"]} !important;
        border: 1px solid {tv["border"]} !important;
        border-radius: 8px !important;
        color: {tv["input_color"]} !important;
    }}
    [data-testid="stSidebar"] .stTextInput input {{
        background: {tv["input_bg"]} !important;
        border: 1px solid {tv["border"]} !important;
        border-radius: 8px !important;
        color: {tv["input_color"]} !important;
    }}
    [data-testid="stSidebar"] .stTextInput input::placeholder {{
        color: {tv["text_muted"]} !important;
    }}
    [data-testid="stSidebar"] hr {{
        border-color: {tv["border"]} !important;
        margin: 10px 0 !important;
    }}

    /* Bouton toggle discret pour sections sidebar */
    [data-testid="stSidebar"] .sidebar-toggle-btn .stButton > button {{
        background: transparent !important;
        border: 1px solid transparent !important;
        color: {tv["text_muted"]} !important;
        font-size: 0.68rem !important;
        padding: 2px 7px !important;
        height: auto !important;
        min-height: unset !important;
        width: auto !important;
        border-radius: 4px !important;
        font-weight: 400 !important;
        box-shadow: none !important;
    }}
    [data-testid="stSidebar"] .sidebar-toggle-btn .stButton > button:hover {{
        background: {tv["surface"]} !important;
        border-color: var(--orange) !important;
        color: var(--orange) !important;
    }}

    .sidebar-label {{
        font-size: 0.67rem;
        font-weight: 700;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: {tv["text_muted"]} !important;
        margin: 14px 0 4px;
        display: block;
    }}

    /* Stats sidebar */
    .sidebar-stats {{
        background: {tv["surface"]} !important;
        border-radius: 8px;
        padding: 8px 12px;
        margin-bottom: 8px;
        font-size: 0.76rem;
        color: {tv["text_main"]} !important;
        border: 1px solid {tv["border"]};
    }}
    .sidebar-stats strong {{ color: var(--orange) !important; }}

    .autosave-badge {{
        font-size: 0.67rem;
        color: {tv["text_muted"]} !important;
        margin-top: 4px;
        display: block;
        text-align: center;
        opacity: 0.8;
    }}

    .corbeille-item {{
        background: {tv["surface"]};
        border: 1px solid {tv["border"]};
        border-radius: 8px;
        padding: 8px 10px;
        margin-bottom: 6px;
    }}
    .corbeille-item span {{ color: {tv["text_main"]} !important; }}

    /* ── En-tête principal ────────────────────────────────────────────────── */
    .pug-header {{
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 10px 0 20px;
        border-bottom: 2px solid var(--border);
        margin-bottom: 20px;
    }}
    .pug-header h1 {{
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
        color: {tv["text_main"]} !important;
        letter-spacing: -0.4px;
    }}
    .pug-header .badge {{
        font-size: 0.76rem;
        background: var(--orange-pale);
        border: 1px solid var(--orange-mid);
        color: var(--orange) !important;
        padding: 2px 10px;
        border-radius: 20px;
        font-weight: 600;
    }}
    .pug-header .subtitle {{
        font-size: 0.8rem;
        color: {tv["text_muted"]} !important;
        margin-top: 2px;
        font-weight: 400;
    }}

    /* ── Chat ──────────────────────────────────────────────────────────────── */
    .chat-row {{
        display: flex;
        margin-bottom: 3px;
        align-items: flex-end;
        gap: 10px;
        width: 100%;
    }}
    .chat-row-user      {{ flex-direction: row-reverse; }}
    .chat-row-assistant {{ flex-direction: row; }}

    /* AVATARS MIS A JOUR */
    .avatar {{
        width: 34px;
        height: 34px;
        border-radius: 50%;
        object-fit: contain;
        flex-shrink: 0;
        box-shadow: var(--shadow);
    }}
    
    .avatar-ai {{
        background: linear-gradient(135deg, #111111 0%, #333333 100%);
        padding: 6px; /* Espace intérieur pour que le logo ne touche pas les bords */
    }}
    
    .avatar-user {{
        background: var(--orange-pale);
        border: 1.5px solid var(--orange-mid);
        padding: 5px; /* Petit fond de couleur avec bordure élégante */
    }}

    .bubble {{
        max-width: 74%;
        padding: 12px 17px;
        font-size: 0.94rem;
        line-height: 1.7;
        word-break: break-word;
    }}
    .bubble-user {{
        background: linear-gradient(135deg, var(--orange) 0%, var(--orange-light) 100%);
        color: #ffffff !important;
        border-radius: 18px 18px 4px 18px;
        box-shadow: 0 3px 12px rgba(226,88,34,0.25);
    }}
    .bubble-assistant {{
        background: {tv["bubble_ai_bg"]};
        border: 1.5px solid {tv["bubble_ai_border"]};
        color: {tv["bubble_ai_color"]} !important;
        border-radius: 4px 18px 18px 18px;
        box-shadow: var(--shadow);
    }}
    .bubble-assistant p, .bubble-assistant li,
    .bubble-assistant span, .bubble-assistant strong {{
        color: {tv["bubble_ai_color"]} !important;
    }}

    .msg-time {{
        font-size: 0.68rem;
        color: {tv["text_muted"]} !important;
        margin: 2px 0 8px 44px; /* Décalé à cause du nouvel avatar plus grand */
        opacity: 0.7;
    }}
    .msg-time-user {{
        text-align: right;
        margin: 2px 44px 8px 0;
    }}

    .search-highlight {{
        background: {tv["search_highlight"]};
        border-radius: 3px;
        padding: 0 2px;
        font-weight: 600;
    }}

    /* Indicateur d'écriture */
    .typing-indicator {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 12px;
    }}
    .typing-dots {{
        display: flex;
        gap: 5px;
        align-items: center;
    }}
    .typing-dots span {{
        width: 8px; height: 8px;
        background: var(--orange);
        border-radius: 50%;
        animation: bounce 1.2s infinite;
    }}
    .typing-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
    .typing-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes bounce {{
        0%, 80%, 100% {{ transform: translateY(0); opacity: 0.4; }}
        40%            {{ transform: translateY(-7px); opacity: 1; }}
    }}

    .search-banner {{
        background: var(--orange-pale);
        border: 1.5px solid var(--orange-mid);
        border-radius: var(--radius);
        padding: 8px 14px;
        margin-bottom: 12px;
        font-size: 0.84rem;
        color: #3B1E0A !important;
    }}

    .msg-actions {{
        display: flex;
        gap: 5px;
        margin-left: 44px; /* Ajusté avec les avatars */
        margin-bottom: 14px;
    }}
    .msg-actions .stButton > button {{
        background: {tv["surface2"]} !important;
        border: 1px solid {tv["border"]} !important;
        color: {tv["text_muted"]} !important;
        border-radius: 6px !important;
        font-size: 0.73rem !important;
        padding: 2px 10px !important;
        height: auto !important;
        min-height: unset !important;
        line-height: 1.5 !important;
        font-family: 'Sora', sans-serif !important;
        transition: all 0.14s;
    }}
    .msg-actions .stButton > button:hover {{
        border-color: var(--orange) !important;
        color: var(--orange) !important;
        background: var(--orange-pale) !important;
    }}

    .tts-banner {{
        display: flex;
        align-items: center;
        gap: 8px;
        background: {tv["tts_bg"]};
        border: 1.5px solid {tv["tts_border"]};
        padding: 8px 14px;
        border-radius: var(--radius);
        margin-bottom: 12px;
        font-size: 0.85rem;
        color: {tv["tts_color"]} !important;
        animation: pulse 1.8s infinite;
    }}
    .tts-banner::before {{
        content: '';
        display: inline-block;
        width: 7px; height: 7px;
        background: {tv["tts_color"]};
        border-radius: 50%;
    }}
    @keyframes pulse {{
        0%, 100% {{ opacity: 1; }}
        50%       {{ opacity: 0.55; }}
    }}

    .doc-banner {{
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--orange-pale);
        border: 1.5px solid var(--orange-mid);
        padding: 9px 14px;
        border-radius: var(--radius);
        margin-bottom: 14px;
        font-size: 0.87rem;
        color: #3B1E0A !important;
    }}
    .doc-banner strong {{ color: var(--orange) !important; }}

    .empty-state {{
        text-align: center;
        padding: 38px 0 14px;
    }}
    .empty-state h2 {{
        color: var(--orange) !important;
        font-size: 1.4rem;
        font-weight: 700;
        margin-bottom: 5px;
    }}
    .empty-state p {{
        color: {tv["text_muted"]} !important;
        font-size: 0.88rem;
    }}

    div[data-testid="stHorizontalBlock"] .stButton > button {{
        font-size: 0.83rem !important;
        text-align: left !important;
        white-space: normal !important;
        height: auto !important;
        padding: 10px 13px !important;
        background: {tv["surface2"]} !important;
        border: 1.5px solid {tv["border"]} !important;
        color: {tv["text_main"]} !important;
        border-radius: var(--radius) !important;
        line-height: 1.4 !important;
        font-family: 'Sora', sans-serif !important;
        transition: all 0.16s !important;
    }}
    div[data-testid="stHorizontalBlock"] .stButton > button:hover {{
        border-color: var(--orange) !important;
        background: var(--orange-pale) !important;
        color: var(--orange) !important;
    }}

    [data-testid="stTabs"] button {{
        font-family: 'Sora', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.87rem !important;
        color: {tv["text_muted"]} !important;
    }}
    [data-testid="stTabs"] button[aria-selected="true"] {{
        color: var(--orange) !important;
        border-bottom-color: var(--orange) !important;
    }}

    [data-testid="metric-container"] {{
        background: {tv["metric_bg"]} !important;
        border: 1.5px solid {tv["border"]} !important;
        border-radius: var(--radius) !important;
        padding: 14px !important;
        box-shadow: var(--shadow);
    }}
    [data-testid="metric-container"] label {{
        color: {tv["text_muted"]} !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
    }}
    [data-testid="metric-container"] [data-testid="stMetricValue"] {{
        color: {tv["text_main"]} !important;
        font-weight: 700 !important;
    }}

    .stTextArea textarea, .stTextInput input {{
        background: {tv["input_bg"]} !important;
        border-color: {tv["border"]} !important;
        color: {tv["input_color"]} !important;
        border-radius: 8px !important;
        font-family: 'Sora', sans-serif !important;
    }}
    .stTextArea label, .stTextInput label,
    .stFileUploader label, .stSelectbox label {{
        color: {tv["text_main"]} !important;
        font-weight: 500 !important;
    }}

    .action-bar .stButton > button {{
        background: {tv["surface2"]} !important;
        border: 1.5px solid {tv["border"]} !important;
        color: {tv["text_main"]} !important;
        border-radius: 8px !important;
        font-size: 0.83rem !important;
        font-family: 'Sora', sans-serif !important;
        transition: all 0.15s;
    }}
    .action-bar .stButton > button:hover {{
        border-color: var(--orange) !important;
        color: var(--orange) !important;
    }}

    .word-count {{
        font-size: 0.72rem;
        color: {tv["text_muted"]} !important;
        text-align: right;
        margin-top: -8px;
        margin-bottom: 6px;
    }}

    ::-webkit-scrollbar {{ width: 4px; height: 4px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: {tv["border"]}; border-radius: 10px; }}

    /* Cache le footer de Streamlit mais GARDE LE HEADER pour la flèche native */
    #MainMenu, footer {{ visibility: hidden; }}

    /* Personnalisation du bouton hamburger natif de Streamlit */
    [data-testid="collapsedControl"] {{
        color: var(--orange) !important;
        background: {tv["surface2"]} !important;
        border: 1px solid {tv["border"]} !important;
        border-radius: 8px !important;
        padding: 5px !important;
        box-shadow: var(--shadow) !important;
        transition: all 0.2s ease-in-out;
    }}
    [data-testid="collapsedControl"]:hover {{
        background: var(--orange-pale) !important;
        border-color: var(--orange) !important;
    }}
    [data-testid="collapsedControl"] svg {{
        fill: var(--orange) !important;
    }}

</style>
""", unsafe_allow_html=True)


# =============================================================================
# TITRE ONGLET DYNAMIQUE
# =============================================================================

_titre_conv = st.session_state.discussions.get(
    st.session_state.discussion_actuelle, {}
).get("titre", "Pug AI")
st.markdown(
    f"<script>document.title = '{_titre_conv[:40]} — Pug AI';</script>",
    unsafe_allow_html=True,
)


# =============================================================================
# CHARGEMENT DU MODELE
# =============================================================================

@st.cache_resource
def charger_moteur_rapide():
    return GPT4All(model_name="Phi-3-mini-4k-instruct.Q4_0.gguf", n_threads=8)

model_local = charger_moteur_rapide()


# =============================================================================
# EN-TETE
# =============================================================================

st.markdown(f"""
<div class="pug-header">
    <div class="logo-bg logo-bg-main">
        <img src="https://cdn-user-icons.flaticon.com/245314/245314621/1780568418876.svg?token=exp=1780569417~hmac=e0ac2a050006984645830edad0a08222">
    </div>
    <div>
        <h1>Pug AI</h1>
        <div class="subtitle">Modèle local · Données privées</div>
    </div>
    <span class="badge">Local · Privé</span>
</div>
""", unsafe_allow_html=True)


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    # ── En-tête de la sidebar avec le bouton Thème ───────────────────────
    col_logo, col_theme = st.columns([0.8, 0.2])
    with col_logo:
        st.markdown("""
            <div style="display:flex;align-items:center;gap:12px;padding:8px 0 16px;">
                <div class="logo-bg logo-bg-sidebar">
                    <img src="https://cdn-user-icons.flaticon.com/245314/245314621/1780568418876.svg?token=exp=1780569417~hmac=e0ac2a050006984645830edad0a08222">
                </div>
                <span style="font-size:1.1rem;font-weight:700;color:var(--text-main);">Pug AI</span>
            </div>
        """, unsafe_allow_html=True)
        
    with col_theme:
        # Un bouton icône discret pour changer le thème (Lune pour clair, Soleil pour sombre)
        icone_theme = "🌙" if theme == "Clair" else "☀️"
        st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
        if st.button(icone_theme, help="Changer le thème", use_container_width=True):
            st.session_state.theme = "Sombre" if theme == "Clair" else "Clair"
            st.rerun()

    if st.button("+ Nouvelle discussion", use_container_width=True):
        creer_nouvelle_discussion()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # Stats globales
    total_discussions = len(st.session_state.discussions)
    total_messages = sum(len(d.get("messages", [])) for d in st.session_state.discussions.values())
    total_mots = sum(
        sum(len(m["content"].split()) for m in d.get("messages", []))
        for d in st.session_state.discussions.values()
    )
    st.markdown(
        f'<div class="sidebar-stats">'
        f'<strong>{total_discussions}</strong> discussions · '
        f'<strong>{total_messages}</strong> messages<br>'
        f'<strong>{total_mots:,}</strong> mots au total'
        f'</div>',
        unsafe_allow_html=True,
    )

    if st.session_state.derniere_sauvegarde_auto:
        heure_save = st.session_state.derniere_sauvegarde_auto.strftime("%H:%M")
        st.markdown(
            f'<span class="autosave-badge"> Sauvegarde auto à {heure_save}</span>',
            unsafe_allow_html=True,
        )

    st.markdown("<hr>", unsafe_allow_html=True)

    # Personnalité
    st.markdown('<span class="sidebar-label">Personnalité</span>', unsafe_allow_html=True)
    mode_choisi = st.selectbox(
        "Personnalité", options=list(MODES_PERSONNALITE.keys()),
        index=list(MODES_PERSONNALITE.keys()).index(st.session_state.mode_personnalite),
        label_visibility="collapsed",
    )
    st.session_state.mode_personnalite = mode_choisi

    # Longueur
    st.markdown('<span class="sidebar-label">Longueur de réponse</span>', unsafe_allow_html=True)
    longueur_choisie = st.selectbox(
        "Longueur", options=list(LONGUEUR_TOKENS.keys()),
        index=list(LONGUEUR_TOKENS.keys()).index(st.session_state.longueur_reponse),
        label_visibility="collapsed",
    )
    st.session_state.longueur_reponse = longueur_choisie

    # Langue
    st.markdown('<span class="sidebar-label">Langue de réponse</span>', unsafe_allow_html=True)
    langue_choisie = st.selectbox(
        "Langue", options=list(LANGUES_REPONSE.keys()),
        index=list(LANGUES_REPONSE.keys()).index(st.session_state.langue_reponse),
        label_visibility="collapsed",
    )
    st.session_state.langue_reponse = langue_choisie

    st.markdown("<hr>", unsafe_allow_html=True)

    # Recherche
    recherche = st.text_input("", value="", placeholder="Rechercher une discussion…")

    # Corbeille
    nb_corbeille = len(st.session_state.corbeille)
    lbl_corbeille = f"🗑️ Corbeille ({nb_corbeille})" if nb_corbeille else "🗑️ Corbeille"
    if st.button(lbl_corbeille, use_container_width=True):
        st.session_state.afficher_corbeille = not st.session_state.afficher_corbeille
        st.rerun()

    if st.session_state.afficher_corbeille:
        if not st.session_state.corbeille:
            st.caption("La corbeille est vide.")
        else:
            for cid, cinfo in list(st.session_state.corbeille.items()):
                nb_msg_c = len(cinfo.get("messages", []))
                st.markdown(
                    f'<div class="corbeille-item">'
                    f'<span style="font-size:0.8rem;font-weight:600;">{cinfo["titre"][:28]}</span><br>'
                    f'<span style="font-size:0.7rem;opacity:0.7;">{nb_msg_c} messages</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                col_rest, col_vide = st.columns(2)
                with col_rest:
                    if st.button("Restaurer", key=f"rest_{cid}", use_container_width=True):
                        st.session_state.discussions[cid] = cinfo
                        del st.session_state.corbeille[cid]
                        sauvegarder_tout(); st.rerun()
                with col_vide:
                    if st.button("Suppr. déf.", key=f"vide_{cid}", use_container_width=True):
                        del st.session_state.corbeille[cid]; st.rerun()
            if st.button("Vider la corbeille", use_container_width=True):
                st.session_state.corbeille = {}; st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Fonction affichage discussion ─────────────────────────────────────
    def afficher_discussion_sidebar(id_id, info, epingle):
        titre_affiche = info["titre"][:26] + "…" if len(info["titre"]) > 26 else info["titre"]
        is_active = (id_id == st.session_state.discussion_actuelle)

        if st.session_state.renommer_id == id_id:
            nouveau_titre = st.text_input(
                "Renommer", value=info["titre"],
                key=f"rename_{id_id}", label_visibility="collapsed"
            )
            c1, c2 = st.columns(2)
            if c1.button("Ok", key=f"ok_{id_id}"):
                st.session_state.discussions[id_id]["titre"] = nouveau_titre
                st.session_state.renommer_id = None
                sauvegarder_tout(); st.rerun()
            if c2.button("Annuler", key=f"cancel_{id_id}"):
                st.session_state.renommer_id = None; st.rerun()
        else:
            nb = len(info.get("messages", []))
            nb_label = f"  ({nb})" if nb > 0 else ""
            col_txt, col_pin, col_ren, col_del = st.columns([0.52, 0.16, 0.16, 0.16])
            with col_txt:
                label = f"**{titre_affiche}{nb_label}**" if is_active else f"{titre_affiche}{nb_label}"
                if st.button(label, key=f"btn_{id_id}", use_container_width=True):
                    st.session_state.discussion_actuelle = id_id
                    st.session_state.confirmer_suppr_id = None
                    st.rerun()
            with col_pin:
                if st.button("📌" if not epingle else "📍", key=f"pin_{id_id}"):
                    st.session_state.discussions[id_id]["epinglé"] = not epingle
                    sauvegarder_tout(); st.rerun()
            with col_ren:
                if st.button("✏️", key=f"ren_{id_id}"):
                    st.session_state.renommer_id = id_id; st.rerun()
            with col_del:
                if st.session_state.confirmer_suppr_id == id_id:
                    if st.button("Oui", key=f"del_ok_{id_id}"):
                        st.session_state.corbeille[id_id] = st.session_state.discussions[id_id]
                        del st.session_state.discussions[id_id]
                        if st.session_state.discussion_actuelle == id_id:
                            st.session_state.discussion_actuelle = None
                        st.session_state.confirmer_suppr_id = None
                        sauvegarder_tout(); st.rerun()
                else:
                    if st.button("🗑️", key=f"del_{id_id}"):
                        st.session_state.confirmer_suppr_id = id_id; st.rerun()

    epinglees = [(i, d) for i, d in st.session_state.discussions.items() if d.get("epinglé")]
    recentes  = [(i, d) for i, d in st.session_state.discussions.items() if not d.get("epinglé")]

    # ── Épinglées avec toggle ─────────────────────────────────────────────
    if epinglees:
        col_ep_lbl, col_ep_btn = st.columns([0.78, 0.22])
        with col_ep_lbl:
            st.markdown('<span class="sidebar-label">Épinglées</span>', unsafe_allow_html=True)
        with col_ep_btn:
            icone_ep = "▼" if st.session_state.sidebar_epinglees_ouvert else "▶"
            st.markdown('<div class="sidebar-toggle-btn">', unsafe_allow_html=True)
            if st.button(icone_ep, key="toggle_epinglees"):
                st.session_state.sidebar_epinglees_ouvert = not st.session_state.sidebar_epinglees_ouvert
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        if st.session_state.sidebar_epinglees_ouvert:
            for id_id, info in epinglees:
                if recherche.lower() in info["titre"].lower():
                    afficher_discussion_sidebar(id_id, info, epingle=True)

    # ── Récentes avec toggle ──────────────────────────────────────────────
    col_rec_lbl, col_rec_btn = st.columns([0.78, 0.22])
    with col_rec_lbl:
        st.markdown('<span class="sidebar-label">Récentes</span>', unsafe_allow_html=True)
    with col_rec_btn:
        icone_rec = "▼" if st.session_state.sidebar_recentes_ouvert else "▶"
        st.markdown('<div class="sidebar-toggle-btn">', unsafe_allow_html=True)
        if st.button(icone_rec, key="toggle_recentes"):
            st.session_state.sidebar_recentes_ouvert = not st.session_state.sidebar_recentes_ouvert
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    if st.session_state.sidebar_recentes_ouvert:
        for id_id, info in recentes:
            if recherche.lower() in info["titre"].lower():
                afficher_discussion_sidebar(id_id, info, epingle=False)


# =============================================================================
# ONGLETS
# =============================================================================

onglet_chat, onglet_docs, onglet_stats, onglet_profil = st.tabs([
    "Discussion",
    "Documents",
    "Statistiques",
    "Profil",
])


# =============================================================================
# ONGLET 1 — CHAT
# =============================================================================

with onglet_chat:
    messages_actuels = st.session_state.discussions[id_conv]["messages"]

    if st.session_state.document_nom:
        st.markdown(
            f'<div class="doc-banner">Document actif : <strong>{st.session_state.document_nom}</strong></div>',
            unsafe_allow_html=True,
        )
        if st.button("Retirer le document", key="remove_doc"):
            st.session_state.document_contexte = ""
            st.session_state.document_nom = ""
            st.rerun()

    if st.session_state.get("tts_actif", False):
        col_tts_info, col_tts_stop = st.columns([0.75, 0.25])
        with col_tts_info:
            st.markdown('<div class="tts-banner">Lecture audio en cours</div>', unsafe_allow_html=True)
        with col_tts_stop:
            if st.button("Couper le son", key="stop_tts_global"):
                arreter_tts(); st.rerun()

    # Recherche dans les messages
    col_srch, col_srch_clear = st.columns([0.85, 0.15])
    with col_srch:
        terme_recherche = st.text_input(
            "", placeholder="Rechercher dans les messages…",
            value=st.session_state.recherche_messages,
            key="input_recherche_msgs",
            label_visibility="collapsed",
        )
    with col_srch_clear:
        if st.button("✕", key="clear_search"):
            st.session_state.recherche_messages = ""; st.rerun()
    st.session_state.recherche_messages = terme_recherche

    if terme_recherche:
        nb_r = sum(1 for m in messages_actuels if terme_recherche.lower() in m["content"].lower())
        st.markdown(
            f'<div class="search-banner">🔍 <strong>{nb_r}</strong> résultat{"s" if nb_r > 1 else ""} '
            f'pour <em>« {terme_recherche} »</em></div>',
            unsafe_allow_html=True,
        )

    def surligner(texte, terme):
        if not terme:
            return texte
        import re
        return re.compile(re.escape(terme), re.IGNORECASE).sub(
            lambda m: f'<span class="search-highlight">{m.group()}</span>', texte
        )

    messages_a_afficher = [
        m for m in messages_actuels
        if not terme_recherche or terme_recherche.lower() in m["content"].lower()
    ]

    for idx, m in enumerate(messages_a_afficher):
        heure_msg = m.get("heure", "")
        contenu_affiche = surligner(m["content"], terme_recherche)

        if m["role"] == "user":
            st.markdown(f"""
                <div class="chat-row chat-row-user">
                    <div class="bubble bubble-user">{contenu_affiche}</div>
                    <img src="https://cdn-icons-png.flaticon.com/512/1946/1946429.png" class="avatar avatar-user">
                </div>
            """, unsafe_allow_html=True)
            if heure_msg:
                st.markdown(f'<div class="msg-time msg-time-user">{heure_msg}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"""
                <div class="chat-row chat-row-assistant">
                    <img src="https://cdn-user-icons.flaticon.com/245314/245314621/1780568418876.svg?token=exp=1780569417~hmac=e0ac2a050006984645830edad0a08222" class="avatar avatar-ai">
                    <div class="bubble bubble-assistant">{contenu_affiche}</div>
                </div>
            """, unsafe_allow_html=True)
            if heure_msg:
                st.markdown(f'<div class="msg-time">{heure_msg}</div>', unsafe_allow_html=True)

            with st.container():
                st.markdown('<div class="msg-actions">', unsafe_allow_html=True)
                act1, act2, act3, act4, act5, _sp = st.columns([0.09, 0.08, 0.08, 0.11, 0.11, 0.53])

                with act1:
                    if st.button("Copier", key=f"copy_{idx}"):
                        texte_js = m['content'].replace("\\","\\\\").replace("`","\\`").replace("$","\\$")
                        components.html(f"<script>navigator.clipboard.writeText(`{texte_js}`);</script>", height=0)
                        st.toast("Réponse copiée")

                with act2:
                    if st.button("Lire", key=f"tts_{idx}"):
                        lire_texte_tts(m["content"]); st.rerun()

                with act3:
                    if st.session_state.get("tts_actif", False):
                        if st.button("Stop", key=f"stop_{idx}"):
                            arreter_tts(); st.rerun()

                with act4:
                    if st.button("↑ Court", key=f"court_{idx}"):
                        with st.spinner("Reformulation…"):
                            with model_local.chat_session():
                                version_courte = model_local.generate(
                                    f"Reformule ce texte de façon plus courte et concise :\n\n{m['content']}",
                                    temp=0.3, max_tokens=300)
                        idx_reel = messages_actuels.index(m)
                        messages_actuels.insert(idx_reel + 1, {
                            "role": "assistant",
                            "content": f"[Version courte]\n{version_courte.strip()}",
                            "heure": datetime.datetime.now().strftime("%H:%M"),
                        })
                        sauvegarder_tout(); st.rerun()

                with act5:
                    if st.button("↓ Long", key=f"long_{idx}"):
                        with st.spinner("Développement…"):
                            with model_local.chat_session():
                                version_longue = model_local.generate(
                                    f"Développe et enrichis ce texte avec plus de détails :\n\n{m['content']}",
                                    temp=0.4, max_tokens=800)
                        idx_reel = messages_actuels.index(m)
                        messages_actuels.insert(idx_reel + 1, {
                            "role": "assistant",
                            "content": f"[Version détaillée]\n{version_longue.strip()}",
                            "heure": datetime.datetime.now().strftime("%H:%M"),
                        })
                        sauvegarder_tout(); st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.get("indicateur_ecriture", False):
        st.markdown("""
            <div class="typing-indicator">
                <img src="https://cdn-user-icons.flaticon.com/245314/245314621/1780568418876.svg?token=exp=1780569417~hmac=e0ac2a050006984645830edad0a08222"
                     class="avatar avatar-ai">
                <div class="typing-dots">
                    <span></span><span></span><span></span>
                </div>
            </div>
        """, unsafe_allow_html=True)

    if not messages_actuels:
        st.markdown("""
            <div class="empty-state">
                <h2>Bonjour, que puis-je faire pour vous ?</h2>
                <p>Posez une question ou choisissez une suggestion ci-dessous.</p>
            </div>
        """, unsafe_allow_html=True)
        cols = st.columns(3)
        for i, suggestion in enumerate(SUGGESTIONS_DEMARRAGE):
            with cols[i % 3]:
                if st.button(suggestion, key=f"sug_{i}", use_container_width=True):
                    st.session_state.discussions[id_conv]["messages"].append(
                        {"role": "user", "content": suggestion,
                         "heure": datetime.datetime.now().strftime("%H:%M")})
                    sauvegarder_tout()
                    st.rerun()

    user_input = st.chat_input("Posez votre question…")

    if user_input:
        heure_envoi = datetime.datetime.now().strftime("%H:%M")
        st.session_state.discussions[id_conv]["messages"].append(
            {"role": "user", "content": user_input, "heure": heure_envoi})

        if len(st.session_state.discussions[id_conv]["messages"]) == 1:
            titre_auto = user_input[:42].strip() + ("…" if len(user_input) > 42 else "")
            st.session_state.discussions[id_conv]["titre"] = titre_auto
            
        sauvegarder_tout()
        st.rerun()

    # === DÉCLENCHEMENT AUTOMATIQUE DE L'IA ===
    if messages_actuels and messages_actuels[-1]["role"] == "user":
        st.session_state.indicateur_ecriture = True
        zone_totale = st.empty()
        pref       = st.session_state.get("mes_preferences", "")
        mode_desc  = MODES_PERSONNALITE[st.session_state.mode_personnalite]
        doc_ctx    = st.session_state.document_contexte
        langue_dir = LANGUES_REPONSE[st.session_state.langue_reponse]
        max_tok    = LONGUEUR_TOKENS[st.session_state.longueur_reponse]

        consigne = f"Tu es Pug AI. {mode_desc}"
        if langue_dir: consigne += f" {langue_dir}"
        if pref:       consigne += f" {pref}"
        if doc_ctx:
            extrait = tronquer_contexte(doc_ctx)
            consigne += f"\n\nDocument fourni :\n\n---\n{extrait}\n---"

        with st.spinner("Pug AI réfléchit…"):
            with model_local.chat_session(system_prompt=consigne):
                dernier_texte = messages_actuels[-1]["content"]
                generateur = model_local.generate(dernier_texte, temp=0.7, max_tokens=max_tok, streaming=True)
                reponse_complete = ""
                st.session_state.stop_generation = False
                for morceau in generateur:
                    if st.session_state.stop_generation:
                        break
                    reponse_complete += morceau
                    zone_totale.markdown(f"""
                        <div class="chat-row chat-row-assistant">
                            <img src="https://cdn-user-icons.flaticon.com/245314/245314621/1780568418876.svg?token=exp=1780569417~hmac=e0ac2a050006984645830edad0a08222" class="avatar avatar-ai">
                            <div class="bubble bubble-assistant">{reponse_complete} ▌</div>
                        </div>
                    """, unsafe_allow_html=True)

                st.session_state.discussions[id_conv]["messages"].append(
                    {"role": "assistant", "content": reponse_complete.strip(),
                     "heure": datetime.datetime.now().strftime("%H:%M")})
                st.session_state.indicateur_ecriture = False
                sauvegarder_tout()
                st.rerun()

    if messages_actuels:
        st.markdown(f"<hr style='margin:18px 0 10px;border-color:{tv['border']}'>", unsafe_allow_html=True)
        nb_msg = len(messages_actuels)
        nb_words = sum(len(m["content"].split()) for m in messages_actuels)
        st.markdown(f"<p class='word-count'>{nb_msg} messages · {nb_words:,} mots</p>", unsafe_allow_html=True)

        st.markdown('<div class="action-bar">', unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.button("Interrompre", on_click=interrompre, use_container_width=True)

        if c2.button("Régénérer", use_container_width=True):
            msgs = st.session_state.discussions[id_conv]["messages"]
            if msgs and msgs[-1]["role"] == "assistant":
                msgs.pop(); sauvegarder_tout(); st.rerun()

        if c3.button("Effacer", use_container_width=True):
            st.session_state.discussions[id_conv]["messages"] = []
            sauvegarder_tout(); st.rerun()

        horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        titre_conv = st.session_state.discussions[id_conv]["titre"]
        export_txt = "\n\n".join(f"[{m['role'].upper()}] {m['content']}" for m in messages_actuels)
        lignes_md = [f"# {titre_conv}\n", f"*Exporté le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}*\n\n---\n"]
        for m in messages_actuels:
            lignes_md.append(f"**{'Vous' if m['role']=='user' else 'Pug AI'}**\n\n{m['content']}\n\n---\n")
        export_md = "\n".join(lignes_md)

        with c4:
            col_exp1, col_exp2 = st.columns(2)
            col_exp1.download_button("Export .txt", data=export_txt,
                file_name=f"pug_ai_{horodatage}.txt", use_container_width=True)
            col_exp2.download_button("Export .md", data=export_md,
                file_name=f"pug_ai_{horodatage}.md", mime="text/markdown", use_container_width=True)

        if c5.button("Supprimer", use_container_width=True):
            st.session_state.corbeille[id_conv] = st.session_state.discussions[id_conv]
            del st.session_state.discussions[id_conv]
            st.session_state.discussion_actuelle = None
            sauvegarder_tout(); st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


# =============================================================================
# ONGLET 2 — DOCUMENTS
# =============================================================================

with onglet_docs:
    st.markdown(f"<h3 style='color:{tv['text_main']}'>Gestion des documents</h3>", unsafe_allow_html=True)
    st.caption("Déposez un fichier pour que Pug AI puisse l'analyser dans la discussion.")

    fichier = st.file_uploader("Choisissez un fichier", type=["pdf", "docx", "txt"])

    if fichier is not None:
        with st.spinner(f"Lecture de « {fichier.name} »…"):
            texte_extrait, erreur = extraire_texte(fichier)
        if erreur:
            st.error(erreur)
        else:
            st.session_state.document_contexte = texte_extrait
            st.session_state.document_nom      = fichier.name
            st.success(f"{fichier.name} chargé — {len(texte_extrait):,} caractères extraits")
            with st.expander("Aperçu du texte extrait"):
                st.text(texte_extrait[:500] + ("…" if len(texte_extrait) > 500 else ""))

            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Générer un résumé", use_container_width=True):
                    with st.spinner("Résumé en cours…"):
                        with model_local.chat_session():
                            r = model_local.generate(
                                f"Voici un document :\n\n{tronquer_contexte(texte_extrait)}\n\n"
                                "Fais-en un résumé clair en français en 10 à 15 lignes.",
                                temp=0.3, max_tokens=600)
                    st.info(r)
            with col_b:
                if st.button("Extraire les infos clés", use_container_width=True):
                    with st.spinner("Extraction en cours…"):
                        with model_local.chat_session():
                            r = model_local.generate(
                                f"Voici un document :\n\n{tronquer_contexte(texte_extrait)}\n\n"
                                "Liste les informations clés en français sous forme de points.",
                                temp=0.2, max_tokens=600)
                    st.info(r)

            st.markdown("---")
            if st.button("Suggérer des questions sur ce document", use_container_width=True):
                with st.spinner("Génération des questions…"):
                    with model_local.chat_session():
                        r = model_local.generate(
                            f"Voici un document :\n\n{tronquer_contexte(texte_extrait, 1500)}\n\n"
                            "Propose 5 questions pertinentes. Réponds en français, liste numérotée.",
                            temp=0.5, max_tokens=400)
                st.success(r)

    if st.session_state.document_nom and fichier is None:
        st.info(f"Document actif en mémoire : {st.session_state.document_nom}")
        if st.button("Effacer le document du contexte"):
            st.session_state.document_contexte = ""
            st.session_state.document_nom = ""; st.rerun()


# =============================================================================
# ONGLET 3 — STATISTIQUES
# =============================================================================

with onglet_stats:
    st.markdown(f"<h3 style='color:{tv['text_main']}'>Statistiques de la conversation</h3>", unsafe_allow_html=True)
    messages_actuels = st.session_state.discussions[id_conv]["messages"]

    if not messages_actuels:
        st.info("Aucun message dans cette conversation pour l'instant.")
    else:
        nb_total       = len(messages_actuels)
        nb_user        = sum(1 for m in messages_actuels if m["role"] == "user")
        nb_assistant   = nb_total - nb_user
        mots_user      = sum(len(m["content"].split()) for m in messages_actuels if m["role"] == "user")
        mots_assistant = sum(len(m["content"].split()) for m in messages_actuels if m["role"] == "assistant")
        tokens_estimes = int((mots_user + mots_assistant) * 1.3)
        longueurs_ia   = [len(m["content"].split()) for m in messages_actuels if m["role"] == "assistant"]
        moy_ia         = int(sum(longueurs_ia) / len(longueurs_ia)) if longueurs_ia else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Messages total",  nb_total)
        c2.metric("Vos messages",    nb_user)
        c3.metric("Réponses Pug AI", nb_assistant)
        c4, c5, c6 = st.columns(3)
        c4.metric("Mots (vous)",    f"{mots_user:,}")
        c5.metric("Mots (IA)",      f"{mots_assistant:,}")
        c6.metric("Tokens estimés", f"{tokens_estimes:,}")
        st.metric("Longueur moy. réponse IA", f"{moy_ia} mots")

        st.markdown("---")
        import pandas as pd
        df = pd.DataFrame([
            {"Echange": i+1, "Mots": len(m["content"].split()),
             "Role": "Vous" if m["role"]=="user" else "Pug AI"}
            for i, m in enumerate(messages_actuels)
        ])
        
        # FIX DU GRAPHIQUE
        if not df.empty:
            df_pivot = df.pivot_table(index="Echange", columns="Role", values="Mots", fill_value=0)
            couleurs_map = {"Vous": "#E25822", "Pug AI": "#FFAB91"}
            couleurs_actives = [couleurs_map.get(colonne, "#E25822") for colonne in df_pivot.columns]
            st.bar_chart(df_pivot, color=couleurs_actives)

        st.markdown("---")
        for m in messages_actuels[-6:]:
            rl  = "Vous" if m["role"] == "user" else "Pug AI"
            ap  = m["content"][:120] + ("…" if len(m["content"]) > 120 else "")
            hr  = f" · {m['heure']}" if m.get("heure") else ""
            st.markdown(
                f"<p style='color:{tv['text_main']}'><strong>{rl}</strong>{hr} — {ap}</p>",
                unsafe_allow_html=True)

        st.markdown("---")
        horodatage = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lignes_export = [f"=== Export Pug AI — {horodatage} ===\n"]
        for m in messages_actuels:
            lignes_export.append(f"[{'VOUS' if m['role']=='user' else 'PUG AI'}]\n{m['content']}\n")
        lignes_export.append(
            f"\n--- Stats ---\nMessages : {nb_total} | Mots vous : {mots_user} | "
            f"Mots IA : {mots_assistant} | Tokens : {tokens_estimes}")
        st.download_button("Télécharger l'export complet",
            data="\n".join(lignes_export),
            file_name=f"pug_ai_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

    st.markdown("---")
    st.markdown(f"<p style='font-weight:600;color:{tv['text_main']}'>Sauvegardes automatiques</p>", unsafe_allow_html=True)
    sauvegardes = sorted(glob.glob(os.path.join(SAUVEGARDE_DIR, "sauvegarde_*.json")), reverse=True)
    if not sauvegardes:
        st.caption("Aucune sauvegarde disponible pour l'instant.")
    else:
        for sv in sauvegardes[:10]:
            nom_sv = os.path.basename(sv)
            try:
                ts = nom_sv.replace("sauvegarde_","").replace(".json","")
                dt = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S")
                label_sv = dt.strftime("%d/%m/%Y à %H:%M:%S")
            except Exception:
                label_sv = nom_sv
            with open(sv, "rb") as f:
                contenu_sv = f.read()
            st.download_button(f"📥 {label_sv}", data=contenu_sv,
                file_name=nom_sv, mime="application/json", key=f"dl_sv_{nom_sv}")


# =============================================================================
# ONGLET 4 — PROFIL
# =============================================================================

with onglet_profil:
    st.markdown(f"<h3 style='color:{tv['text_main']}'>Configuration de Pug AI</h3>", unsafe_allow_html=True)

    nouvelles_instructions = st.text_area(
        "Instructions système personnalisées",
        value=st.session_state.get("mes_preferences", ""),
        height=180,
        placeholder="Ex : 'Sois très concis', 'Utilise des bullet points', 'Tutoie-moi'…",
    )
    if st.button("Enregistrer les instructions", type="primary"):
        st.session_state.mes_preferences = nouvelles_instructions
        try:
            sauvegarder_tout(); st.success("Instructions mises à jour.")
        except Exception as e:
            st.error(f"Erreur : {e}")

    st.markdown("---")
    st.markdown(f"<p style='font-weight:600;color:{tv['text_main']}'>Modes de personnalité</p>", unsafe_allow_html=True)
    for nom, desc in MODES_PERSONNALITE.items():
        st.markdown(f"<p style='color:{tv['text_main']}'><strong>{nom}</strong> — {desc}</p>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"<p style='font-weight:600;color:{tv['text_main']}'>Modules optionnels</p>", unsafe_allow_html=True)
    etat_docx = "installé" if docx2txt else "absent — pip install docx2txt"
    etat_tts  = "installé" if pyttsx3  else "absent — pip install pyttsx3"
    st.markdown(f"<p style='color:{tv['text_main']}'>docx2txt (Word) : {etat_docx}</p>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{tv['text_main']}'>pyttsx3 (synthèse vocale) : {etat_tts}</p>", unsafe_allow_html=True)
    st.markdown("---")
    st.info("Les instructions et le mode de personnalité s'appliquent à toutes vos conversations.")