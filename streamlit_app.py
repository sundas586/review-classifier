import base64
import html
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import report
import sheets
from classifier import SchemaError, api_key, build_questions, daily_requests_left, is_decision_model
from defaults import DEFAULT_SCHEMA
from runner import META_COLS, run

# Settings come from the environment (.env locally, Secrets when hosted), not from the page.
MODEL = os.getenv("PRIMARY_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
FALLBACK = os.getenv("FALLBACK_MODEL", "")
IS_FREE = MODEL.endswith(":free")
WORKERS = int(os.getenv("WORKERS", "4"))
RPM = int(os.getenv("MAX_REQUESTS_PER_MIN", "18" if IS_FREE else "0"))
BATCH_SIZE = 1 if is_decision_model(MODEL) else int(os.getenv("REVIEWS_PER_REQUEST", "25"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "1000"))
FREE_REQUESTS_PER_MIN = 20

WAIT_MESSAGE = "Please wait. This is a prototype, so it can take a few minutes for a big sheet."
FIELD_MEANING = {
    "sentiment": "Is the customer happy, unhappy or neutral?",
    "category": "What is the review mostly about?",
    "tags": "Short labels, for example late delivery or great quality",
    "priority": "How urgent is it to reply?",
    "has_issue": "Is the customer reporting a problem?",
}
PROTOTYPE_NOTE = (
    f"The free version can check up to about {FREE_REQUESTS_PER_MIN * BATCH_SIZE} reviews per minute."
    if IS_FREE else "This is a prototype, so larger sheets can take a few minutes."
)
PAGES = {"use": "Use the App for free", "about": "About the app", "messages": "Messages", "premium": "Premium plans"}
PAGE_ICONS = {
    "use": ":material/space_dashboard:", "about": ":material/menu_book:",
    "messages": ":material/chat:", "premium": ":material/workspace_premium:",
}
SOON_PAGES = {
    "messages": {
        "subtitle": "Talk to our team and get help, all in one place.",
        "art": "soon_messages.svg",
        "badge": "Under construction",
        "heading": "Messages are on the way",
        "text": "We are building a simple inbox inside this app where you can ask a question, share feedback and read our "
                "replies. It is not ready yet. Thank you for your patience.",
        "chips": ("Ask a question", "Get help", "Share feedback"),
    },
    "premium": {
        "subtitle": "More for teams that want to do more with their reviews.",
        "art": "soon_premium.svg",
        "badge": "Coming soon",
        "heading": "Premium plans are coming soon",
        "text": "We are getting our premium plans ready. The details and prices will be shown here as soon as they are "
                "available. Until then you can keep using the app for free.",
        "chips": ("Free plan: available now", "Premium: coming soon"),
    },
}

WELCOME_POPUP = os.getenv("WELCOME_POPUP", "1") != "0"
USERS_COUNT = os.getenv("USERS_COUNT", "1,200")  # shown in the welcome pop-up: set it to your real number
AVATAR_COLORS = ["#b8a9f8", "#d7f24d", "#f9c9a4", "#a9e4d4", "#f6b8c9"]
# Sample feedback for the prototype. Replace with real customer quotes before launch.
TESTIMONIALS = (
    ("Priya S.", "Customer Care Lead, online store", "We used to read reviews one by one. Now we see what customers are unhappy about in minutes."),
    ("Daniel R.", "E-commerce Manager", "The charts made it easy to show my team exactly where we need to improve."),
    ("Aisha K.", "Founder, home goods shop", "I just pasted my Google Sheet link and had my answers back. No set-up, no training."),
    ("Marcus T.", "Product Owner", "Seeing the high priority reviews first saves us hours every single week."),
    ("Elena V.", "Operations Manager", "Simple, fast and clear. Even my non-technical colleagues use it."),
)
TESTIMONIAL_SECONDS = 6

st.set_page_config(page_title="Review Classifier", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
html { font-size: 17.5px; }
.stApp { background: #e4e4e8; }
.block-container { max-width: 1500px; padding: 14px 14px 4rem 28px; }
[data-testid="stElementContainer"]:has(style) { display: none !important; }
[data-testid="stCaptionContainer"] p, [data-testid="stCaptionContainer"] { font-size: 0.95rem; }
[data-testid="stWidgetLabel"] p { font-size: 1rem; }
[data-testid="stMain"] input { font-size: 1rem; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, h4 { color: #1c1c1e; letter-spacing: -0.01em; }

/* left panel */
section[data-testid="stSidebar"] { background: transparent; border: none; }
[data-testid="stSidebarContent"] { background: #1c1c1e; margin: 14px 0 14px 14px; border-radius: 28px; height: calc(100vh - 28px); position: relative; }
[data-testid="stSidebarHeader"] { display: none; }
[data-testid="stSidebar"] .brand { display: flex; align-items: center; gap: 10px; color: #fff; font-size: 1.25rem; font-weight: 700; margin: 8px 0 26px; }
[data-testid="stSidebar"] .logo { width: 34px; height: 34px; border-radius: 10px; background: #d7f24d; color: #1c1c1e;
                                  display: inline-flex; align-items: center; justify-content: center; font-weight: 800; font-size: 0.95rem; }
[data-testid="stSidebar"] button { border: none; border-radius: 999px; justify-content: flex-start; padding: 0.7rem 1.1rem; font-weight: 600; transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease; }
[data-testid="stSidebar"] button > div { justify-content: flex-start; width: 100%; gap: 10px; }
[data-testid="stSidebar"] button [data-testid="stMarkdownContainer"] { text-align: left; }
[data-testid="stSidebar"] button:hover { transform: translateX(3px); }
[data-testid="stSidebar"] button p { color: inherit; }
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] { background: transparent; color: #c9c9d1; }
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover { background: rgba(255,255,255,0.09); color: #fff; }
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] { background: #fff; color: #1c1c1e; }
.side-card { position: fixed; left: 32px; bottom: 32px; width: 272px; background: #d7f24d; border-radius: 22px; padding: 18px 18px 20px; }
.side-card h4 { margin: 0 0 6px; color: #1c1c1e; font-size: 1.1rem; }
.side-card p { margin: 0; color: #2b2d12; font-size: 0.85rem; line-height: 1.45; }

/* page title */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin: 0 0 18px; }
.page-head h1 { margin: 0; font-size: 2.3rem; font-weight: 800; }
.page-head p { margin: 4px 0 0; color: #6b6b73; font-size: 0.98rem; }
.chip { background: #fff; color: #1c1c1e; border-radius: 999px; padding: 8px 18px; font-size: 0.85rem; font-weight: 600; white-space: nowrap; }

/* cards */
div[class*="st-key-card"] { background: #fff; border-radius: 22px; padding: 22px 26px; margin-bottom: 6px; }
div[class*="st-key-card_dark"] { background: #1c1c1e; }
div[class*="st-key-card_dark"] h3, div[class*="st-key-card_dark"] p, div[class*="st-key-card_dark"] span { color: #fff; }
[data-testid="stMain"] div[class*="st-key-card_dark"] button { background: #d7f24d; color: #1c1c1e; border: none; }
[data-testid="stMain"] div[class*="st-key-card_dark"] button p { color: #1c1c1e; font-weight: 600; }
[data-testid="stMain"] div[class*="st-key-card_dark"] button:hover { background: #e6ff63; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 6px 0 18px; }
.card { background: #fff; border-radius: 22px; padding: 20px 22px; }
.card .num { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; background: #d7f24d;
             color: #1c1c1e; border-radius: 50%; font-size: 0.9rem; font-weight: 700; margin-bottom: 10px; }
.card h4 { margin: 0 0 6px; font-size: 1.05rem; }
.card p { margin: 0; color: #6b6b73; font-size: 0.92rem; line-height: 1.5; }
@media (max-width: 800px) { .steps { grid-template-columns: 1fr; } }

/* hero */
.hero2 { display: grid; grid-template-columns: 1.05fr 1fr; align-items: center; min-height: 300px; margin: 0 0 20px; overflow: hidden;
         border-radius: 30px; background: linear-gradient(135deg, #f1ecff 0%, #fff1e6 100%); position: relative; }
.hero-text { padding: 36px 8px 36px 44px; position: relative; z-index: 1; }
.eyebrow { display: inline-block; background: #fff; border-radius: 999px; padding: 6px 14px; font-size: 0.8rem; font-weight: 700; color: #6d4cf0; margin-bottom: 14px; }
.hero-text h1 { margin: 0 0 12px; font-size: 3.6rem; line-height: 1.02; font-weight: 800; color: #1c1c1e; }
.hero-text h1 .grad { background: linear-gradient(90deg, #7c5cf6 0%, #f97316 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero-text p { margin: 0 0 18px; color: #52525b; font-size: 1.05rem; line-height: 1.55; max-width: 460px; }
.pills span { display: inline-block; background: #fff; border-radius: 999px; padding: 7px 15px; margin: 0 8px 8px 0; font-size: 0.82rem; font-weight: 600; color: #1c1c1e;
              transition: transform 0.2s ease, background 0.2s ease; }
.pills span:hover { transform: translateY(-2px); background: #d7f24d; }
.hero-art { align-self: stretch; min-height: 300px; background-repeat: no-repeat; background-position: center right; background-size: contain; }
@media (max-width: 900px) { .hero2 { grid-template-columns: 1fr; } .hero-art { min-height: 220px; } .hero-text h1 { font-size: 2.6rem; } }

/* insight cards */
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 4px 0 16px; }
.kpi { border-radius: 24px; padding: 20px 22px; background: #fff; }
.kpi small { display: block; font-size: 0.82rem; opacity: 0.75; margin-bottom: 8px; }
.kpi b { display: block; font-size: 2.1rem; line-height: 1.1; font-weight: 800; }
.kpi span { display: block; margin-top: 6px; font-size: 0.82rem; opacity: 0.7; }
.kpi.lime { background: #d7f24d; } .kpi.dark { background: #1c1c1e; color: #fff; } .kpi.purple { background: #b8a9f8; }
.kpi.dark b, .kpi.dark small, .kpi.dark span { color: #fff; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, 1fr); } }

/* motion */
@keyframes rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
div[class*="st-key-card"], .hero2, .kpis, .steps, .page-head { animation: rise 0.5s ease both; }
div[class*="st-key-card"], .card, .kpi, [data-testid="stMetric"] { transition: transform 0.2s ease, box-shadow 0.2s ease; }
div[class*="st-key-card"]:hover, .card:hover, .kpi:hover, [data-testid="stMetric"]:hover { transform: translateY(-3px); box-shadow: 0 16px 32px rgba(28, 28, 30, 0.10); }
[data-testid="stMain"] button { transition: transform 0.15s ease, background 0.2s ease; }
[data-testid="stMain"] button:hover { transform: translateY(-1px); }
[data-testid="stMain"] [role="tablist"] { gap: 8px; border-bottom: none; box-shadow: none; }
[data-testid="stMain"] [data-testid="stTab"] { background: #fff; border-radius: 999px; padding: 8px 20px; border: none !important; box-shadow: none; transition: background 0.2s ease, transform 0.15s ease; }
[data-testid="stMain"] [data-testid="stTab"]:hover { transform: translateY(-1px); }
[data-testid="stMain"] [data-testid="stTab"][aria-selected="true"] { background: #1c1c1e; }
[data-testid="stMain"] [data-testid="stTab"][aria-selected="true"] p { color: #fff; }
[data-testid="stMain"] [data-testid="stTab"]::after, [data-testid="stMain"] [data-testid="stTab"]::before, [data-testid="stMain"] [role="tablist"]::after, [data-testid="stMain"] [role="tablist"]::before { display: none; }
[data-testid="stMain"] [data-baseweb="tab-highlight"], [data-testid="stMain"] [data-baseweb="tab-border"] { display: none; }
[data-testid="stDataFrame"] button[aria-label="Download as CSV"] { display: none; }

/* left panel: 'soon' badges and the premium button */
[data-testid="stSidebar"] [class*="st-key-nav_messages"] button, [data-testid="stSidebar"] [class*="st-key-nav_premium"] button { position: relative; }
[data-testid="stSidebar"] [class*="st-key-nav_messages"] button::after, [data-testid="stSidebar"] [class*="st-key-nav_premium"] button::after {
    content: "SOON"; position: absolute; right: 14px; top: 50%; transform: translateY(-50%); background: #d7f24d; color: #1c1c1e;
    font-size: 0.6rem; font-weight: 800; letter-spacing: 0.04em; border-radius: 999px; padding: 3px 9px; }
[data-testid="stSidebar"] [class*="st-key-nav_premium"] button[data-testid="stBaseButton-secondary"] { background: linear-gradient(90deg, rgba(139,124,246,0.28), rgba(246,161,90,0.28)); color: #fff; }
[data-testid="stSidebar"] [class*="st-key-nav_premium"] button[data-testid="stBaseButton-secondary"]:hover { background: linear-gradient(90deg, rgba(139,124,246,0.42), rgba(246,161,90,0.42)); }
@media (max-height: 700px) { .side-card { display: none; } }

/* pages that are not ready yet */
.soon { display: grid; grid-template-columns: 1.1fr 1fr; align-items: center; gap: 24px; min-height: 420px; padding: 34px 44px; border-radius: 30px; background: #fff; animation: rise 0.5s ease both; }
.soon-art { align-self: stretch; min-height: 320px; background-repeat: no-repeat; background-position: center; background-size: contain; animation: bob 4.5s ease-in-out infinite; }
.soon-text .badge { display: inline-block; background: #f5b942; color: #1c1c1e; border-radius: 999px; padding: 6px 16px; font-size: 0.8rem; font-weight: 800; letter-spacing: 0.03em; margin-bottom: 16px; }
.soon-text h2 { margin: 0 0 12px; font-size: 2.2rem; line-height: 1.12; font-weight: 800; color: #1c1c1e; }
.soon-text p { margin: 0 0 20px; color: #52525b; font-size: 1.05rem; line-height: 1.6; max-width: 480px; }
@keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
@media (max-width: 900px) { .soon { grid-template-columns: 1fr; padding: 24px; } }

/* welcome pop-up: blur and soften everything behind it */
div[data-testid="stDialog"] { backdrop-filter: blur(12px) saturate(1.1); -webkit-backdrop-filter: blur(12px) saturate(1.1);
                              background-color: rgba(60, 52, 110, 0.22) !important; animation: fadein 0.3s ease both; }
@keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
div[role="dialog"] { border-radius: 32px !important; background: #f4f1ff !important; box-shadow: 0 30px 80px rgba(28, 28, 30, 0.28); }
.welcome { position: relative; text-align: center; padding: 30px 24px 22px; border-radius: 26px; background-size: cover; background-position: center; overflow: hidden; }
.welcome .avatars { display: flex; justify-content: center; margin-bottom: 16px; }
.welcome .avatars span { width: 48px; height: 48px; margin-left: -12px; border-radius: 50%; border: 3px solid #fff; display: inline-flex; align-items: center;
                         justify-content: center; font-size: 0.8rem; font-weight: 800; color: #1c1c1e; box-shadow: 0 6px 14px rgba(28, 28, 30, 0.12); }
.welcome .avatars span:first-child { margin-left: 0; }
.welcome .big { font-size: 4.6rem; line-height: 1; font-weight: 800; letter-spacing: -0.03em; color: #1c1c1e; animation: pop 0.7s ease both; }
.welcome .label { margin: 8px 0 18px; font-size: 1rem; font-weight: 600; color: #3f3f46; }
.welcome h3 { margin: 0 0 8px; font-size: 1.45rem; font-weight: 800; }
.welcome p { margin: 0 auto 14px; max-width: 440px; color: #52525b; font-size: 1rem; line-height: 1.55; }
.welcome .ticks span { display: inline-block; background: rgba(255, 255, 255, 0.85); border-radius: 999px; padding: 6px 14px; margin: 0 4px 8px; font-size: 0.82rem; font-weight: 600; }
@keyframes pop { from { transform: scale(0.85); opacity: 0; } to { transform: none; opacity: 1; } }

/* testimonials */
.testi { position: relative; border-radius: 26px; background: #fff; padding: 28px 34px 22px; overflow: hidden; }
.testi h4 { margin: 0 0 14px; font-size: 1.05rem; }
.t-stage { position: relative; min-height: 190px; }
.t-slide { position: absolute; inset: 0; opacity: 0; }
.t-stars { color: #f5b942; letter-spacing: 2px; font-size: 1.1rem; margin-bottom: 8px; }
.t-quote { font-size: 1.3rem; line-height: 1.5; font-weight: 600; color: #1c1c1e; margin: 0 0 18px; max-width: 880px; }
.t-who { display: flex; align-items: center; gap: 12px; }
.t-who .av { width: 46px; height: 46px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 800; color: #1c1c1e; }
.t-who b { display: block; font-size: 1rem; }
.t-who small { color: #6b6b73; font-size: 0.88rem; }
.t-dots { display: flex; gap: 8px; margin-top: 6px; }
.t-dot { height: 8px; width: 8px; border-radius: 999px; background: #d4d4da; }
.t-note { margin-top: 10px; color: #9a9aa3; font-size: 0.78rem; }

/* numbers and buttons */
[data-testid="stMetric"] { background: #fff; border-radius: 20px; padding: 16px 18px; }
[data-testid="stMetricLabel"] p { color: #6b6b73; font-size: 0.82rem; }
[data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 700; color: #1c1c1e; }
[data-testid="stMain"] button[data-testid="stBaseButton-primary"] { background: #1c1c1e; color: #fff; border: none; border-radius: 999px; }
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover { background: #38383d; color: #fff; }
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"], [data-testid="stMain"] a[data-testid="stBaseLinkButton-secondary"] { background: #fff; border: 1px solid #d4d4da; border-radius: 999px; }
[data-testid="stMain"] [data-testid="stExpander"] { background: #fff; border-radius: 16px; border: none; }
[data-testid="stMain"] [data-testid="stTextInput"] input, [data-testid="stMain"] [data-testid="stNumberInput"] input { border-radius: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

password = os.getenv("APP_PASSWORD")
if password and st.text_input("Access code", type="password") != password:
    st.stop()


def header(title, subtitle):
    st.markdown(
        f'<div class="page-head"><div><h1>{title}</h1><p>{subtitle}</p></div><span class="chip">Prototype</span></div>',
        unsafe_allow_html=True,
    )


ASSETS = Path(globals().get("__file__", "streamlit_app.py")).resolve().parent / "assets"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


def hero_css():
    """The picture behind the title: assets/hero.png (or .jpg/.webp) if one is added, else the built-in illustration."""
    path = next((ASSETS / f"hero{ext}" for ext in IMAGE_TYPES if (ASSETS / f"hero{ext}").is_file()), None)
    if path is None:
        return ""
    uri = f"data:{IMAGE_TYPES[path.suffix]};base64," + base64.b64encode(path.read_bytes()).decode()
    if path.suffix == ".svg":
        return f'.hero-art {{ background-image: url("{uri}"); }}'
    return (  # a photo fills the whole card, faded on the left so the title stays readable
        ".hero2 { background-image: linear-gradient(90deg, rgba(255,255,255,0.96) 0%, rgba(255,255,255,0.75) 45%, rgba(255,255,255,0) 100%), "
        f'url("{uri}"); background-size: cover; background-position: center; }}'
    )


def hero():
    st.markdown(f"<style>{hero_css()}</style>", unsafe_allow_html=True)
    st.markdown(
        '<div class="hero2"><div class="hero-text"><span class="eyebrow">AI review analysis</span>'
        '<h1>Review <span class="grad">Classifier</span></h1>'
        "<p>Turn raw customer reviews into clear, structured insights: sentiment, topics, tags and more.</p>"
        '<div class="pills"><span>Sentiment</span><span>Category</span><span>Tags</span><span>Priority</span><span>Issue detection</span></div>'
        '</div><div class="hero-art"></div></div>',
        unsafe_allow_html=True,
    )


def data_uri(path):
    return f"data:{IMAGE_TYPES[path.suffix]};base64," + base64.b64encode(path.read_bytes()).decode()


def soon_page(kind):
    """A friendly 'not ready yet' page with a picture, for features that are still being built."""
    cfg = SOON_PAGES[kind]
    header(PAGES[kind], cfg["subtitle"])
    st.markdown(f'<style>.soon-art {{ background-image: url("{data_uri(ASSETS / cfg["art"])}"); }}</style>', unsafe_allow_html=True)
    chips = "".join(f"<span>{c}</span>" for c in cfg["chips"])
    st.markdown(
        f'<div class="soon"><div class="soon-art"></div><div class="soon-text"><span class="badge">{cfg["badge"]}</span>'
        f'<h2>{cfg["heading"]}</h2><p>{cfg["text"]}</p><div class="pills">{chips}</div></div></div>',
        unsafe_allow_html=True,
    )


def initials(name):
    return "".join(part[0] for part in name.replace(".", "").split()[:2]).upper()


@st.dialog("Welcome", width="medium")
def welcome_dialog():
    st.markdown(f'<style>.welcome {{ background-image: url("{data_uri(ASSETS / "welcome_bg.svg")}"); }}</style>', unsafe_allow_html=True)
    avatars = "".join(f'<span style="background:{AVATAR_COLORS[i % len(AVATAR_COLORS)]}">{initials(n)}</span>' for i, (n, _, _) in enumerate(TESTIMONIALS[:4]))
    st.markdown(
        f'<div class="welcome"><div class="avatars">{avatars}</div>'
        f'<div class="big">+{USERS_COUNT}</div><div class="label">teams already use Review Classifier</div>'
        "<h3>Welcome! We are glad you are here.</h3>"
        "<p>Turn your customer reviews into clear answers in a few clicks. Paste the link of your Google Sheet, press one "
        "button, and see what your customers really think.</p>"
        '<div class="ticks"><span>Free to use</span><span>No sign-up needed</span><span>Charts you can download</span></div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Get started", type="primary", width="stretch"):
        st.rerun()


def testimonials():
    """One happy-customer quote at a time, changing every few seconds (done in CSS, so it needs no clicks or reruns)."""
    n, seconds = len(TESTIMONIALS), TESTIMONIAL_SECONDS
    share, cycle = 100 / n, n * seconds
    st.markdown(
        f"<style>@keyframes tslide {{ 0% {{ opacity: 0; transform: translateY(12px); }} 2% {{ opacity: 1; transform: none; }} "
        f"{share - 2:.2f}% {{ opacity: 1; transform: none; }} {share:.2f}% {{ opacity: 0; transform: translateY(-8px); }} 100% {{ opacity: 0; }} }}"
        f"@keyframes tdot {{ 0%, {share:.2f}% {{ background: #1c1c1e; width: 26px; }} {share + 0.01:.2f}%, 100% {{ background: #d4d4da; width: 8px; }} }}"
        f".t-slide {{ animation: tslide {cycle}s linear infinite backwards; }} .t-dot {{ animation: tdot {cycle}s linear infinite; }}</style>",
        unsafe_allow_html=True,
    )
    slides = "".join(
        f'<div class="t-slide" style="animation-delay:{i * seconds}s"><div class="t-stars">★★★★★</div>'
        f'<p class="t-quote">“{quote}”</p><div class="t-who"><span class="av" style="background:{AVATAR_COLORS[i % len(AVATAR_COLORS)]}">{initials(name)}</span>'
        f"<div><b>{name}</b><small>{role}</small></div></div></div>"
        for i, (name, role, quote) in enumerate(TESTIMONIALS)
    )
    dots = "".join(f'<span class="t-dot" style="animation-delay:-{((n - i) % n) * seconds}s"></span>' for i in range(n))
    st.markdown(
        f'<div class="testi"><h4>What our users say</h4><div class="t-stage">{slides}</div><div class="t-dots">{dots}</div>'
        '<div class="t-note">Sample feedback shown for this prototype.</div></div>',
        unsafe_allow_html=True,
    )


# left panel
page = st.session_state.setdefault("page", "use")
with st.sidebar:
    st.markdown('<div class="brand"><span class="logo">RC</span>Review Classifier</div>', unsafe_allow_html=True)
    for key, text in PAGES.items():
        if st.button(text, icon=PAGE_ICONS[key], key=f"nav_{key}", type="primary" if page == key else "secondary", width="stretch"):
            st.session_state["page"] = key
            st.rerun()
    st.markdown(f'<div class="side-card"><h4>Prototype</h4><p>{PROTOTYPE_NOTE}</p></div>', unsafe_allow_html=True)


if WELCOME_POPUP and not st.session_state.get("welcomed"):
    st.session_state["welcomed"] = True  # only the first time in a visit
    welcome_dialog()

if page in SOON_PAGES:
    soon_page(page)
    st.stop()


# ------------------------------------------------------------------ About the app
if page == "about":
    schema = DEFAULT_SCHEMA
    header("About the app", "A short guide: what the app does, how to get your Google Sheet ready, and what you will see.")

    WRITES = sheets.can_write()  # False for customers for now: they download the results instead
    with st.container(key="card_about_what"):
        st.subheader("What it does")
        st.markdown(
            "Review Classifier reads your customer reviews. For every review it tells you whether the customer is happy "
            "or unhappy, what the review is about, and how urgent it is. "
            + (
                "The results are saved in your Google Sheet, and you also get simple charts that you can download as a PDF."
                if WRITES else
                "You see the results here, and you can download them as an Excel file, plus the charts as a PDF."
            )
        )

    cards = (
        (
            ("Get your sheet ready", "Add three tabs to your Google Sheet: Data (your reviews), Categorization and Summary (both empty)."),
            ("Paste your link", "Copy the link of your Google Sheet, paste it in *Use the App for free* and press Load / refresh data."),
            ("See your results", "The app fills in the Categorization and Summary tabs for you. You also see charts here."),
        ) if WRITES else (
            ("Get your sheet ready", "Put your reviews in a Google Sheet, on a tab named Data."),
            ("Paste your link", "Copy the link of your Google Sheet, paste it in *Use the App for free* and press Load / refresh data."),
            ("Download your results", "See your results here, then download them as an Excel file and a PDF of the charts."),
        )
    )
    st.markdown(
        '<div class="steps">'
        + "".join(f'<div class="card"><span class="num">{n}</span><h4>{title}</h4><p>{text}</p></div>' for n, (title, text) in enumerate(cards, 1))
        + "</div>",
        unsafe_allow_html=True,
    )

    DATA_FORMAT = (
        "| review_id | product | review_text |\n|---|---|---|\n"
        "| R0042 | Steel Water Bottle 750ml | Lid leaks in my bag, ruined my laptop sleeve |\n"
        "| R0043 | Wireless Earbuds X2 | Great sound, battery lasts all day |\n\n"
    )
    NOTE = (
        "**Please note.** This is a prototype, so a big sheet can take a few minutes. Your reviews are checked by an "
        "AI service, so please do not use private or confidential information."
    )

    if not WRITES:
        good_to_know = (
            f"**Step 1. Put your reviews in a tab named {sheets.DATA_TAB}.** Tabs are the small pages at the bottom of "
            "Google Sheets.\n\n"
            f"**Step 2. Fill in the {sheets.DATA_TAB} tab in the same way every time.** Put these three headings in the "
            "first row, then write one review in each row below. Here are two example rows:\n\n"
            + DATA_FORMAT
            + "**Step 3. Let the app read your sheet.** Open your Google Sheet and click **Share**. Under *General access* "
            "choose **Anyone with the link**. *Viewer* is enough.\n\n"
            "**Step 4. Press *Load / refresh data*.** The app reads your latest reviews, so new and changed reviews are "
            f"included. It never changes your sheet. Reviews that have not changed since last time are not checked again.\n\n"
            "**Step 5. Download your results.** You get two files:\n\n"
            "- **Excel file (review_summary.xlsx)** with three sheets: "
            f"**{sheets.DATA_TAB}** (your reviews), **{sheets.CATEGORIZATION_TAB}** (every review with its answers) and "
            f"**{sheets.SUMMARY_TAB}** (the totals).\n"
            "- **PDF file (review_summary.pdf)** with the charts, easy to share or print.\n\n"
            + NOTE
        )
    else:
        if sheets.uses_script():
            sharing = (
                "Open your Google Sheet and click **Share**. Under *General access* choose **Anyone with the link**, then "
                "change *Viewer* to **Editor**. With *Viewer* the app can read your reviews, but it cannot save the results."
            )
        else:
            sharing = (
                "Open your Google Sheet and click **Share**. Either choose **Anyone with the link** and change *Viewer* to "
                "**Editor**, or add the email address shown on the *Use the App for free* page as an **Editor**. With *Viewer* "
                "the app can read your reviews, but it cannot save the results."
            )
        good_to_know = (
            "**Step 1. Add three tabs to your Google Sheet.** Tabs are the small pages at the bottom of Google Sheets. "
            "Give them exactly these names:\n\n"
            "| Tab name | What to put in it |\n|---|---|\n"
            f"| **{sheets.DATA_TAB}** | Your reviews (see Step 2) |\n"
            f"| **{sheets.CATEGORIZATION_TAB}** | Leave it empty. The app fills it in |\n"
            f"| **{sheets.SUMMARY_TAB}** | Leave it empty. The app fills it in |\n\n"
            f"**Step 2. Fill in the {sheets.DATA_TAB} tab in the same way every time.** Put these three headings in the "
            "first row, then write one review in each row below. Here are two example rows:\n\n"
            + DATA_FORMAT
            + "**Step 3. Allow the app to use your sheet.** " + sharing + "\n\n"
            "**Step 4. Press *Load / refresh data*.** The app then does this:\n\n"
            f"- It reads your latest reviews from the {sheets.DATA_TAB} tab. New and changed reviews are included.\n"
            f"- It clears the {sheets.CATEGORIZATION_TAB} and {sheets.SUMMARY_TAB} tabs and fills them in again. "
            "Please do not type in these two tabs, because anything you add there will be removed.\n"
            f"- It never changes your {sheets.DATA_TAB} tab.\n"
            "- Reviews that have not changed since last time are not checked again, so pressing the button again is quick.\n\n"
            "**Step 5. Download.** You can also download an Excel file (review_summary.xlsx) with the three sheets, and a "
            "PDF file with the charts.\n\n"
            + NOTE
        )

    with st.container(key="card_about_good"):
        st.subheader("Good to know")
        st.markdown(good_to_know)

    with st.container(key="card_about_fields"):
        st.subheader("What will be analysed")
        st.markdown("Every review is checked for the same five things:")
        table = "| What we check | What it tells you | Possible answers |\n|---|---|---|\n" + "\n".join(
            f"| **{f['name']}** | {FIELD_MEANING.get(f['name'], '')} | {', '.join(f.get('options', [])) or 'yes or no'} |"
            for f in schema["fields"]
        )
        st.markdown(table)
        st.caption("This list is the same for every sheet. You do not need to choose anything.")

    with st.container(key="card_about_results"):
        st.subheader("Reading the results")
        st.markdown(
            "- **The four coloured cards** give you the quick answers: how many reviews are positive, how many mention a "
            "problem, which topic is discussed most, and how many reviews need attention first (high priority).\n"
            "- **Summary & charts**: one chart for each of the five things above. Hover over a chart to see the exact "
            "numbers. Click *Download charts (PDF)* to save them and share them with others.\n"
            "- **Download Excel file**: one Excel file with three sheets (Data, Categorization and Summary) that you can open, "
            "filter and share.\n"
            "- **Classified reviews**: every review with its answers. Type a word such as *refund* in the search box, or "
            "click the buttons (for example *negative* or *high*) to see only the reviews you care about.\n"
            "- **Processed / Failed**: how many reviews were understood, and how many could not be. A review that could "
            "not be understood is marked `failed`. The app never guesses. You can try those again.\n"
            "- **Requests used, Total time, Reviews / sec, Request avg / p95**: these show how fast the AI worked. You "
            "can ignore them.\n"
            "- **Continue remaining reviews**: this button appears if the run stopped early (for example because the free "
            "daily limit was reached). The reviews that were already done are kept.\n"
            "- **Process all reviews again**: checks every review from the start, even the ones that were already done."
        )
    testimonials()
    st.stop()


# ------------------------------------------------------------------ Use the app
def load_sheet(url, script=None):
    try:
        with st.spinner("Reading your Google Sheet..."):
            data = sheets.read_data(url, script)
            previous = sheets.read_categorization(url, script)
    except sheets.SheetsError as e:
        show_error(e)
        return
    st.session_state["sheet"] = {
        "data": data, "previous": previous, "url": url.strip(), "script": script,
        "loads": st.session_state.get("sheet", {}).get("loads", 0) + 1,
    }


def show_error(e):
    """The friendly message, and for an administrator the technical reply under 'Technical details'."""
    st.error(str(e))
    if getattr(e, "detail", ""):
        with st.expander("Technical details (for the person who set this up)"):
            st.code(e.detail, language=None)


def reset_results():
    for key in ("data_id", "result", "write_msg"):
        st.session_state.pop(key, None)


@st.cache_data(show_spinner=False)
def make_pdf(schema, result):
    return report.build_pdf(schema, result)


@st.cache_data(show_spinner=False)
def make_excel(schema, data, result):
    return report.build_excel(schema, data, result)


def figure(spec):
    labels, values = report.trimmed(spec)
    data = pd.DataFrame({"label": labels, "count": values})
    if spec["kind"] == "pie":
        fig = px.pie(data, names="label", values="count", color="label", title=spec["title"],
                     color_discrete_map=dict(zip(labels, report.colors_for(labels))), template="plotly_white", hole=0.55)
    elif spec["kind"] == "bar":
        fig = px.bar(data, x="label", y="count", title=spec["title"], labels={"label": spec["field"]},
                     color_discrete_sequence=report.PALETTE[:1], template="plotly_white")
    else:
        fig = px.bar(data, x="count", y="label", orientation="h", title=spec["title"], labels={"label": spec["field"]},
                     color_discrete_sequence=report.PALETTE[:1], template="plotly_white")
        fig.update_yaxes(autorange="reversed")
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=56, b=10),
                      title_font=dict(size=16, color="#1c1c1e"))
    return fig


hero()

# 1. connect the sheet
with st.container(key="card_connect"):
    st.subheader("1. Connect your Google Sheet")
    st.caption("First time here? Open *About the app* in the left menu for a short, simple guide.")
    url = st.text_input("Google Sheet link", placeholder="https://docs.google.com/spreadsheets/d/...")
    script = None  # a customer's own Google connection is switched off for now (the server's setting, if any, is used)

    if sheets.can_write() and sheets.uses_script():
        st.markdown(
            "Before you continue, open your Google Sheet and click **Share**. Choose **Anyone with the link** and set it "
            "to **Editor**. This lets the app save your results."
        )
    elif sheets.can_write():
        st.markdown(
            "Before you continue, open your Google Sheet and click **Share**. Either choose **Anyone with the link** and "
            "set it to **Editor**, or add this email address as an **Editor**:"
        )
        st.code(sheets.service_account_email(), language=None)
    else:
        st.markdown(
            "Before you continue, open your Google Sheet and click **Share**. Under *General access* choose "
            "**Anyone with the link**. *Viewer* is enough."
        )
    if st.button("Load / refresh data", type="primary"):
        load_sheet(url, script)

sheet = st.session_state.get("sheet")
if sheet is None:
    reset_results()
    st.info("Paste the link of your Google Sheet and press Load / refresh data.")
    st.stop()

inputs = sheet["data"]
data_id = (sheet["url"], sheet["loads"])

# the classification is fixed, the customer does not choose it
schema = DEFAULT_SCHEMA

# a column of the customer's that shares a name with one of our result columns is kept under another name
reserved = {f["name"] for f in schema["fields"]} | set(META_COLS)
inputs = inputs.rename(columns={c: f"{c}_original" for c in inputs.columns if c in reserved})
resume = sheets.with_previous_results(inputs, sheet["previous"], schema)

limit = min(len(inputs), MAX_ROWS)
with st.container(key="card_preview"):
    st.subheader("Your reviews")
    st.dataframe(inputs.head(10), width="stretch")
    rows = st.number_input(f"Number of reviews to process (up to {limit})", 1, limit, limit)

if is_decision_model(MODEL):
    skipped = build_questions(schema)[1]
    if skipped:
        st.info(
            "These fields cannot be filled in automatically and will stay empty: " + ", ".join(skipped)
            + ". A tags field needs options (the possible tags)."
        )


def write_back(result):
    script = sheet.get("script")
    if not sheets.can_write(script):
        return  # read-only: the results are only shown on this page
    try:
        with st.spinner("Writing the results to your Google Sheet..."):
            sheets.write_categorization(sheet["url"], result, script)
            sheets.write_summary(sheet["url"], report.summary_rows(schema, result), script)
        st.session_state["write_msg"] = (
            "success",
            f"Done! Your results are saved in your Google Sheet: the reviews are in the '{sheets.CATEGORIZATION_TAB}' tab "
            f"and the totals are in the '{sheets.SUMMARY_TAB}' tab.",
            "",
        )
    except sheets.SheetsError as e:
        st.session_state["write_msg"] = ("error", str(e), e.detail)


def process(frame):
    if not api_key():
        st.error("The service is not configured yet. Please contact the administrator.")
        st.stop()
    models = [m for m in (MODEL, FALLBACK) if m]

    pending = len(frame) if "status" not in frame else int((frame["status"] != "done").sum())
    needed = -(-pending // BATCH_SIZE)
    if IS_FREE:
        left = daily_requests_left()
        if left is not None and needed > left:
            st.error(
                f"You have almost used up today's free limit. This run needs about {needed} more requests, but only {left} "
                "are left. The limit starts again at midnight UTC. Please choose fewer reviews, or come back tomorrow."
            )
            st.stop()

    note = st.info(WAIT_MESSAGE) if pending else None
    bar = st.progress(0.0, text="Starting...")

    def update(n, total, _):
        bar.progress(n / total, text=f"Processed {n} of {total} reviews")

    try:
        result, stats = run(frame, schema, models, WORKERS, RPM, update, batch_size=BATCH_SIZE)
    except SchemaError as e:
        st.error(f"These settings cannot be used: {e}")
        st.stop()
    except Exception as e:
        st.error("Something unexpected went wrong while processing. Please try again in a moment.")
        with st.expander("Technical details"):
            st.code(repr(e))
        st.stop()
    finally:
        if note is not None:
            note.empty()
        bar.empty()
    st.session_state["result"] = (result, stats)
    write_back(result)  # always: the two tabs are emptied and filled again


# new reviews: drop the old results and start processing straight away
new_input = st.session_state.get("data_id") != data_id
if new_input:
    reset_results()
    st.session_state["data_id"] = data_id

# 2. results
st.subheader("2. Results")
label = "Process all reviews again" if "result" in st.session_state else "Process reviews"
if st.button(label):
    process(inputs.head(rows))  # everything again, even reviews already finished in the sheet
elif new_input:
    process(resume.head(rows))  # reviews finished earlier (found in the Categorization tab) are not repeated

if "result" not in st.session_state:
    st.stop()

result, stats = st.session_state["result"]

kind, text, detail = st.session_state.get("write_msg", (None, "", ""))
if kind == "success":
    st.success(text)
elif kind == "error":
    show_error(sheets.SheetsError(text, detail))
left_col, right_col, _ = st.columns([1, 1, 2])
left_col.link_button("Open my Google Sheet", sheet["url"])
if sheets.can_write(sheet.get("script")) and right_col.button("Write results to the sheet again"):
    write_back(result)
    st.rerun()

if not stats["attempted"]:
    st.info("These reviews were already done earlier, so the saved results from your sheet are shown.")

cols = st.columns(7 if stats["cost"] else 6)
cols[0].metric("Processed", f"{stats['done']} / {stats['attempted']}")
cols[1].metric("Failed", stats["failed"])
cols[2].metric("Requests used", stats["requests"])
cols[3].metric("Total time", f"{stats['elapsed_s']:.1f}s")
cols[4].metric("Reviews / sec", f"{stats['records_per_s']:.2f}")
cols[5].metric("Request avg / p95", f"{stats['avg_latency_s']:.1f}s / {stats['p95_latency_s']:.1f}s")
if stats["cost"]:
    cols[6].metric("Cost", f"${stats['cost']:.4f}", f"${stats['cost'] / max(stats['done'], 1) * 1000:.3f} per 1,000", delta_color="off")

if stats["stopped"]:
    st.warning(
        f"Processing stopped early. {stats['stopped']}\n\n"
        "The reviews that were finished are kept. Press **Continue remaining reviews** to carry on."
    )

if (stats["failed"] or stats["not_processed"]) and st.button("Continue remaining reviews"):
    process(result)
    st.rerun()

done = result[result["status"] == "done"]
choice_fields = [f for f in schema["fields"] if f["type"] == "choice"]


def is_yes(value):
    return str(value).strip().lower() in ("true", "yes", "1")


def kpi(style, label, value, note):
    return f'<div class="kpi {style}"><small>{label}</small><b>{value}</b><span>{note}</span></div>'


if len(done) and {"sentiment", "category", "priority", "has_issue"} <= set(done.columns):
    top_category = done["category"].mode().iat[0]
    issues = int(done["has_issue"].map(is_yes).sum())
    st.markdown(
        '<div class="kpis">'
        + kpi("lime", "Positive reviews", f"{(done['sentiment'] == 'positive').mean():.0%}", f"{int((done['sentiment'] == 'positive').sum())} of {len(done)} reviews")
        + kpi("dark", "Reviews with a problem", issues, f"{issues / len(done):.0%} of all reviews")
        + kpi("purple", "Most discussed category", html.escape(str(top_category)), f"{(done['category'] == top_category).mean():.0%} of reviews")
        + kpi("", "High priority", int((done["priority"] == "high").sum()), "reviews that need attention first")
        + "</div>",
        unsafe_allow_html=True,
    )

with st.container(key="card_dark_download"):
    head, excel_col, pdf_col = st.columns([2.4, 1, 1], vertical_alignment="center")
    head.subheader("Download your results")
    head.caption("Excel: your reviews, every review with its answers, and the totals. PDF: the charts.")
    excel_col.download_button(
        "Download Excel file", make_excel(schema, sheet["data"], result), "review_summary.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="excel_download", on_click="ignore", icon=":material/table_view:", width="stretch",
    )
    pdf_col.download_button(
        "Download charts (PDF)", make_pdf(schema, result), "review_summary.pdf", "application/pdf",
        key="pdf_download", on_click="ignore", icon=":material/picture_as_pdf:", width="stretch",
    )

tab_charts, tab_reviews = st.tabs(["Summary & charts", "Classified reviews"])

with tab_charts:
    charts = [figure(spec) for spec in report.chart_specs(schema, done)]
    for i in range(0, len(charts), 2):
        row = st.columns(2)
        for n, (col, fig) in enumerate(zip(row, charts[i:i + 2])):
            with col:
                with st.container(key=f"card_chart_{i + n}"):
                    st.plotly_chart(fig, width="stretch")

with tab_reviews:
    table = done
    with st.container(key="card_table"):
        st.subheader("Classified reviews")
        search = st.text_input("Search the reviews", placeholder="for example: refund, battery, leaks", key="search")
        if search.strip():
            text_columns = [c for c in ("product", "review_text") if c in table.columns]
            hit = table[text_columns].apply(lambda col: col.astype(str).str.contains(search.strip(), case=False, regex=False)).any(axis=1)
            table = table[hit]
        for f in choice_fields:
            picked = st.pills(f["name"], f["options"], selection_mode="multi", key=f"pill_{f['name']}")
            if picked:
                table = table[table[f["name"]].isin(picked)]
        st.caption(f"Showing {len(table)} of {len(done)} classified reviews")
        st.dataframe(table.drop(columns=["latency_s"], errors="ignore"), width="stretch")
