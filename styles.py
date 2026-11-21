"""Visual theme for the ClassPulse Streamlit frontend."""

APP_CSS = r"""
<style>
:root { --ink:#20243A; --muted:#858BA1; --violet:#7158F4; --violet-dark:#563FDC; --mint:#29AD8A; --line:#E9EAF2; }
html, body, [class*="css"] { font-family:'Inter','Segoe UI',sans-serif; color:var(--ink); }
.stApp { background:radial-gradient(ellipse at 7% 0%,rgba(220,214,255,.34),transparent 31%),linear-gradient(140deg,#F7F8FC 0%,#F1F3F9 100%); }
[data-testid="stHeader"] { background:rgba(255,255,255,.66); }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#171A2C 0%,#20243A 100%); }
[data-testid="stSidebar"] * { color:#E8E9F2; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color:#9198B1; }
[data-testid="stSidebar"] [role="radiogroup"] label { border-radius:10px; padding:7px 10px; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:#2A2E47; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#BEC3D5; }
[data-testid="stSidebar"] [data-testid="stButton"] button { border-color:#484D68; color:#E8E9F2; background:#24283F; }
[data-testid="stSidebar"] [data-testid="stButton"] button:hover { border-color:#8C7AFF; color:white; }
h1,h2,h3 { font-family:'Inter','Segoe UI',sans-serif !important; letter-spacing:-.035em; color:var(--ink); }
h1 { font-weight:800 !important; }
[data-testid="stMainBlockContainer"] { padding-top:2.1rem; max-width:1480px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line) !important; border-radius:16px !important; background:rgba(255,255,255,.9); box-shadow:0 8px 28px rgba(35,42,76,.035); }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 20px; }
.metric-card { min-height:135px; background:rgba(255,255,255,.94); border:1px solid var(--line); border-radius:16px; padding:19px 20px 16px; box-shadow:0 8px 24px rgba(35,42,76,.045); margin-bottom:18px; position:relative; overflow:hidden; }
.metric-card:before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--violet); }
.metric-card.mint:before { background:#31B998; }.metric-card.amber:before { background:#E6AD4D; }.metric-card.blue:before { background:#6286E8; }
.metric-label { color:#858BA1; font-size:11px; font-weight:700; letter-spacing:.08em; }
.metric-value { color:#20243A; font-family:'Inter','Segoe UI',sans-serif; font-size:31px; line-height:1.3; font-weight:800; margin:10px 0 3px; }
.metric-value small { font:600 16px 'DM Sans',sans-serif; color:#8990A4; margin-left:4px; }
.metric-note { color:#858BA1; font-size:12px; }
.page-kicker { color:#725BF1; font-size:11px; letter-spacing:.12em; font-weight:700; margin-bottom:7px; }
.status-pill { display:inline-block; color:#168A6B; background:#E5F7F1; border-radius:20px; padding:4px 9px; font-size:10px; font-weight:700; letter-spacing:.03em; }
.privacy-chip { display:flex; gap:11px; align-items:center; background:#252940; border:1px solid #343953; border-radius:12px; padding:13px 12px; margin:12px 0; }
.privacy-chip b { display:block; font-size:12px; color:#E8E9F2; }.privacy-chip small { display:block; color:#9299B2; font-size:10px; margin-top:3px; }
.privacy-dot { width:8px; height:8px; border-radius:50%; background:#4BD0A9; box-shadow:0 0 0 4px rgba(75,208,169,.12); margin:0 3px; }
.sidebar-brand { display:flex; align-items:center; gap:9px; color:#fff; font:700 18px 'Inter','Segoe UI',sans-serif; margin:5px 0 31px; }
.sidebar-brand b,.brand-lockup b { color:#A99AFF; font-size:11px; margin-left:3px; }
.brand-mark { display:inline-flex; align-items:center; justify-content:center; width:35px; height:35px; background:linear-gradient(135deg,#8069FF,#5842DD); color:white; border-radius:11px; font:800 12px 'Inter','Segoe UI',sans-serif; box-shadow:0 7px 18px rgba(105,83,231,.28); }
.auth-eyebrow { color:#7158F4; text-align:center; font-size:10px; letter-spacing:.16em; font-weight:700; margin:48px 0 13px; }
.auth-title { font-size:46px !important; line-height:1.1 !important; text-align:center; margin-bottom:14px; }
.auth-title span { color:#7158F4; }
.auth-copy { color:#777E95; text-align:center; font-size:15px; line-height:1.7; margin:0 auto 28px; max-width:430px; }
.brand-lockup { display:flex; justify-content:center; align-items:center; gap:9px; color:#20243A; font:700 18px 'Manrope',sans-serif; padding-top:11px; }
.auth-divider { display:flex; align-items:center; gap:12px; margin:20px 0 14px; color:#A0A5B6; font-size:9px; font-weight:700; letter-spacing:.14em; }
.auth-divider:before,.auth-divider:after { content:''; height:1px; background:#DEE1EA; flex:1; }
.auth-footer { text-align:center; color:#969BAE; font-size:11px; margin-top:27px; }
.privacy-note { color:#777E95; background:#F5F3FF; border:1px solid #E7E2FF; border-radius:10px; padding:10px 13px; font-size:12px; margin-top:27px; }
.insight-index { float:right; color:#BBB4F3; font:700 12px 'Manrope',sans-serif; letter-spacing:.12em; }
[data-testid="stForm"] { border:0; padding:0; }
[data-testid="stFormSubmitButton"] button[kind="primary"],button[kind="primary"] { background:linear-gradient(115deg,#785FF6,#5B45DF); border:0; box-shadow:0 7px 16px rgba(98,75,224,.16); }
[data-testid="stFormSubmitButton"] button[kind="primary"]:hover,button[kind="primary"]:hover { background:linear-gradient(115deg,#6D53F0,#4F39D3); }
[data-testid="stFormSubmitButton"] button,[data-testid="stBaseButton-primary"] { background:linear-gradient(115deg,#785FF6,#5B45DF) !important; color:#fff !important; border:0 !important; }
[data-testid="stTextInput"] input,[data-testid="stDateInput"] input { border-radius:10px; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
@media (max-width:800px) { [data-testid="stMainBlockContainer"] { padding:1.2rem 1rem; } .auth-title { font-size:37px !important; } .metric-card { min-height:118px; padding:14px; } .metric-value { font-size:26px; } }
</style>
"""


DARK_THEME_CSS = r"""
<style>
:root { color-scheme: dark; --ink:#EDF0FA; --muted:#A0A8BE; --line:#343A52; }
html, body, [class*="css"] { color:#E9ECF6; }
.stApp { background:radial-gradient(ellipse at 7% 0%,rgba(99,77,190,.17),transparent 34%),linear-gradient(140deg,#101321 0%,#171B2C 100%); color:#E9ECF6; }
[data-testid="stHeader"] { background:rgba(16,19,33,.82); }
[data-testid="stMain"] { color:#E9ECF6; }
h1,h2,h3,h4,p,li,label,[data-testid="stMarkdownContainer"] { color:#E9ECF6; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:#343A52 !important; background:rgba(29,34,52,.92); box-shadow:0 8px 28px rgba(0,0,0,.18); }
[data-testid="stMetric"], .metric-card { background:#20253A; border-color:#343A52; }
.metric-label,.metric-note,.metric-value small { color:#A0A8BE; }
.metric-value { color:#F0F2FB; }
.page-kicker { color:#B5A9FF; }
.privacy-note { color:#D3D7E7; background:#25243A; border-color:#454063; }
.auth-title,.brand-lockup { color:#F0F2FB; }
.auth-copy,.auth-footer { color:#A0A8BE; }
.auth-divider { color:#A0A8BE; }
.auth-divider:before,.auth-divider:after { background:#343A52; }
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stNumberInput"] input,[data-testid="stDateInput"] input,
[data-testid="stSelectbox"] [role="combobox"],[data-testid="stMultiSelect"] [role="combobox"] {
  color:#F0F2FB !important; background:#171B2C !important; border-color:#414762 !important;
}
[data-testid="stDataFrame"] { border-color:#343A52; }
[data-testid="stFileUploader"] section { color:#E9ECF6; background:#171B2C; border-color:#414762; }
[data-testid*="stAlert"], [data-testid*="Notification"], [role="alert"], .stAlert {
  color:#E9ECF6 !important; background:#252A40 !important; border-color:#414762 !important;
}
[data-testid*="stAlert"] *, [data-testid*="Notification"] *, [role="alert"] *, .stAlert * {
  color:#E9ECF6 !important; background-color:transparent !important;
}
[data-testid="stTabs"] button { color:#C5CADB; }
[data-testid="stFormSubmitButton"] button,[data-testid="stBaseButton-primary"] { background:linear-gradient(115deg,#785FF6,#5B45DF) !important; color:#fff !important; border:0 !important; }
button[kind="secondary"] { color:#E9ECF6; background:#252A40; border-color:#414762; }
</style>
"""

