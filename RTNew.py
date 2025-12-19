import os
import io
import shutil
import uuid

import altair as alt
import pandas as pd
import streamlit as st


# -------------------------------------------------
# Page setup
# -------------------------------------------------
st.set_page_config(
    page_title="Civic Indicators – Reporting Tool",
    layout="wide",
    page_icon="📊",
)

st.title("📊 Civic Indicators – Domain-based Reporting Tool")
st.markdown(
    """
    **Explore domain-based indicators over time.**
    
    Use the sidebar to filter data and customize the visualization.
    """
)


# -------------------------------------------------
# Embed info content (replacing info_content.py)
# -------------------------------------------------
# -------------------------------------------------
# Embed info content (replacing info_content.py)
# NOTE: Definitions are now loaded from 'Indicator_Definitions.xlsx'.
# -------------------------------------------------
variable_info_md = "" # Deprecated, keeping empty variable just in case until full cleanup

# -------------------------------------------------
# Load Indicator Definitions (External Excel)
# -------------------------------------------------
@st.cache_data

def expand_indicator_string(code_str):
    """
    Expands "E025-E029" -> E025, E026... E029.
    """
    if not isinstance(code_str, str): return code_str
    if "-" not in code_str: return code_str
    
    parts = code_str.split(',')
    expanded = []
    
    for p in parts:
        p = p.strip()
        if not p: continue
        
        alpha_match = re.search(r'^([A-Za-z_]*)(\d+)-([A-Za-z_]*)(\d+)$', p)
        if alpha_match:
            pref1, num1, pref2, num2 = alpha_match.groups()
            if pref1 == pref2:
                try:
                    start, end = int(num1), int(num2)
                    if start < end:
                        for i in range(start, end + 1):
                            if len(num1) > len(str(start)):
                                val = f"{i:0{len(num1)}d}"
                            else:
                                val = str(i)
                            expanded.append(f"{pref1}{val}")
                    else:
                        expanded.append(p)
                except: expanded.append(p)
            else:
                expanded.append(p)
        else:
            # Fallback numeric only 1-5 check from before, strictly simpler now?
            # Actually the regex above handles 1-5 (empty prefix).
            # But let's check simple split for robustness if regex fails?
            expanded.append(p)
            
    return ",".join(expanded)

def load_definitions():
    """
    Loads schema and item descriptions from 'Indicator_Definitions.xlsx'.
    Returns:
        schema (dict): {Variable: {col: val, ...}}
        item_descs (dict): {Code: Description}
    """
    # Resolve path relative to this script file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(script_dir, "Indicator_Definitions.xlsx")
    
    # Check if file exists
    if not os.path.exists(filename):
        # Fallback: Try just the filename in CWD (useful if __file__ is weird in some envs)
        if os.path.exists("Indicator_Definitions.xlsx"):
            filename = "Indicator_Definitions.xlsx"
        else:
             return {}, {}

    try:
        # Load Schema
        df_schema = pd.read_excel(filename, sheet_name="Schema")

        # AUTOMATIC EXPANSION OF RANGES (e.g. 5-9 -> 5,6,7,8,9)
        # We apply this to columns that likely contain indicator lists.
        target_cols = ["Items", "Indicators", "Questions", "Variable list"]
        for col in df_schema.columns:
            if col in target_cols or "item" in col.lower():
                 df_schema[col] = df_schema[col].apply(lambda x: expand_indicator_string(x) if isinstance(x, str) else x)
        
        df_schema["Variable"] = df_schema["Variable"].astype(str).str.strip()
        
        # Convert to dict keyed by Variable
        # orient='index' gives {index: {col: val}}, so we set index first
        schema = df_schema.set_index("Variable").to_dict(orient="index")

        # Load Items
        df_items = pd.read_excel(filename, sheet_name="Items")

        # AUTOMATIC EXPANSION FOR ITEMS SHEET (Code Column)
        if "Code" in df_items.columns:
            # 1. Expand ranges in strings "1-5" -> "1,2,3,4,5"
            df_items["Code"] = df_items["Code"].apply(lambda x: expand_indicator_string(x) if isinstance(x, str) else x)
            # 2. Split comma lists into real lists
            df_items["Code"] = df_items["Code"].astype(str).str.split(',')
            # 3. Explode rows (duplicates Description for each expanded Code)
            df_items = df_items.explode("Code")
            # 4. Clean up
            df_items["Code"] = df_items["Code"].str.strip()
    
        df_items["Code"] = df_items["Code"].astype(str).str.strip()
        df_items["Description"] = df_items["Description"].astype(str).str.strip()
        
        # Convert to dict {Code: Description}
        item_descs = dict(zip(df_items["Code"], df_items["Description"]))
        
        return schema, item_descs
        
    except Exception as e:
        st.sidebar.error(f"Error loading definitions: {e}")
        return {}, {}

def get_schema_dict():
    """Wrapper to return schema dict from cached loader."""
    s, _ = load_definitions()
    return s

def get_item_descriptions():
    """Wrapper to return items dict from cached loader."""
    _, i = load_definitions()
    return i

# -------------------------------------------------
# Load & reshape data (ResultswithSE.xlsx style)
# -------------------------------------------------
# -------------------------------------------------
# Load & reshape data (Results v02.xlsx style)
# -------------------------------------------------
@st.cache_data
def load_long_data(file_input, sheet: str = 0) -> pd.DataFrame:
    """
    Reads Results v02.xlsx, where:
    - Header Row 0: Variable/Question Codes (e.g. D1_Justification) + COUNTRY, YEAR
    - Header Row 1: Statistics (Mean, Standard Error of Mean, Count)
    - Data rows start from row 2
    
    Returns one row per (Domain, Question, Country, Year) with:
        value = mean, se = standard error, n = sample size, ci_low, ci_high
    """
    temp_copy = None
    try:
        # Check if file_input is a string path and if we might need to copy it
        # Try reading directly first
        try:
            df = pd.read_excel(file_input, sheet_name=sheet, header=[0, 1])
        except PermissionError:
            # File likely locked (e.g. open in Excel). Try copying to temp.
            if isinstance(file_input, str) and os.path.exists(file_input):
                st.warning(f"File '{file_input}' seems to be locked (open in another app?). Attempting to read via temporary copy...")
                temp_dir = os.path.abspath(os.path.dirname(file_input)) # Copy to same dir to avoid cross-drive issues
                temp_copy = os.path.join(temp_dir, f"temp_read_{uuid.uuid4().hex[:8]}.xlsx")
                shutil.copy(file_input, temp_copy)
                df = pd.read_excel(temp_copy, sheet_name=sheet, header=[0, 1])
            else:
                raise # Re-raise if not a local file we can find
        
        # Flatten columns to handle the MultiIndex
        # Col structure example: ('COUNTRY', 'Unnamed: 0_level_1'), ('D1_Justification', 'Mean')
        
        # Identify Country and Year columns
        # They are likely the first two, but let's be robust
        country_col = None
        year_col = None
        
        new_cols = []
        possible_stats = ["Mean", "Standard Error of Mean", "Count", "Standard Deviation"]
        
        # Iterate to rename and identify
        for idx, col in enumerate(df.columns):
            l0, l1 = col
            l0_str = str(l0).strip()
            l1_str = str(l1).strip()
            
            # Identify ID columns
            if "COUNTRY" in l0_str.upper():
                country_col = idx
                new_cols.append(("Country", ""))
            elif "YEAR" in l0_str.upper():
                year_col = idx
                new_cols.append(("Year", ""))
            else:
                # Keep as is: (Question, Stat)
                # If l1 is weird (Unnamed...), it implies it might be a single-header column or mistakenly read
                if "Unnamed" in l1_str:
                    l1_str = ""
                new_cols.append((l0_str, l1_str))
                
        df.columns = pd.MultiIndex.from_tuples(new_cols)
        
        # Rename checking
        if country_col is None or year_col is None:
            # Fallback: assume 0 is Country, 1 is Year
            df = df.rename(columns={df.columns[0]: ("Country", ""), df.columns[1]: ("Year", "")})
            
        # Melt
        # We want to stack the Question level, keeping Country and Year
        # But pandas melt doesn't easily support multi-index melting into separate columns for Level 0 and Level 1
        # Alternative: Stack level 0 (Questions)
        
        # Set index to Country, Year
        df = df.set_index([("Country", ""), ("Year", "")])
        df.index.names = ["Country", "Year"]
        
        # Checking if index is unique? Likely not if duplicates exist, but assume unique for Country-Year
        # Stack the first level (Question Codes) -> This moves D1... to rows, leaving Stats as columns
        # However, the columns are (Question, Stat).
        # We want columns to be Stats, and Question to be a new index level.
        
        stacked = df.stack(level=0)
        
        # Now Index is (Country, Year, Question)
        # Columns are the Stats (Mean, Standard Error of Mean, Count, etc.)
        
        # Reset index to make them columns
        long = stacked.reset_index()
        long = long.rename(columns={"level_2": "Question"}) # default name for stacked level
        
        # Rename Stat columns
        # Map: 'Mean' -> value, 'Standard Error of Mean' -> se, 'Count' -> n
        # Note: Actual strings from file might vary, so be careful
        stat_map = {
            "Mean": "value",
            "Standard Error of Mean": "se",
            "Count": "n"
        }
        
        # Normalize column names
        current_cols = list(long.columns)
        new_names = {}
        for c in current_cols:
            c_str = str(c).strip()
            if c_str in stat_map:
                new_names[c] = stat_map[c_str]
                
        long = long.rename(columns=new_names)
        
        # Ensure we have 'value'
        if "value" not in long.columns:
            # Try finding a column that looks like mean
            for c in long.columns:
                if "mean" in str(c).lower():
                    long = long.rename(columns={c: "value"})
                    break
        
        # Coerce numeric columns to numbers, turning errors (strings) to NaN
        numeric_cols = ["value", "se", "n"]
        for col in numeric_cols:
            if col in long.columns:
                long[col] = pd.to_numeric(long[col], errors='coerce')

        # Drop rows with no value
        long = long.dropna(subset=["value"])
        
        # Clean types
        long["Year"] = pd.to_numeric(long["Year"], errors='coerce').astype("Int64") # Handle potential NaNs safely first
        long = long.dropna(subset=["Year"])
        long["Year"] = long["Year"].astype(int)
        
        # Add Domain info from Schema
        schema = get_schema_dict()
        
        def get_domain(q):
            # Look up q in schema
            # Schema is {Variable: {Domain: ..., ...}}
            # Variable might match Question
            # Try exact match
            if q in schema:
                return schema[q].get("Domain", "Unknown")
            # Try stripping
            if q.strip() in schema:
                return schema[q.strip()].get("Domain", "Unknown")
            return "Unknown"
            
        long["Domain"] = long["Question"].apply(get_domain)
        
        # Filter out Unknown domains if desired? keeping them for now but maybe warn?
        
        # Order columns
        cols = ["Domain", "Question", "Country", "Year", "value"]
        for extra in ["se", "n"]:
            if extra in long.columns:
                cols.append(extra)
                
        long = long[cols]
        
        return long

    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()
    finally:
        # Cleanup temp file
        if temp_copy and os.path.exists(temp_copy):
            try:
                os.remove(temp_copy)
            except:
                pass


# Check if default file exists (case-insensitive search)
default_filename = "Results v02.xlsx"
data_source = None

# Try exact match first
if os.path.exists(default_filename):
    data_source = default_filename
else:
    # Try case-insensitive match in current directory
    files = [f for f in os.listdir(".") if os.path.isfile(f)]
    for f in files:
        if f.lower() == default_filename.lower():
            data_source = f
            break

if not data_source:
    st.warning(
        f"⚠️ '{default_filename}' not found in the current directory. Please upload the data file."
    )
    uploaded_file = st.sidebar.file_uploader("Upload Data File", type=["xlsx"])
    if uploaded_file:
        data_source = uploaded_file

if data_source:
    long_df = load_long_data(data_source)
    if long_df.empty:
        st.error("Data loading failed or returned empty dataset.")
        st.stop()
else:
    st.info("Waiting for data file...")
    st.stop()


# -------------------------------------------------
# Sidebar controls
# -------------------------------------------------
st.sidebar.header("⚙️ Configuration")

# --- Data Selection ---
with st.sidebar.expander("1. Data Selection", expanded=True):
    # Domain
    domains = sorted(long_df["Domain"].unique())
    selected_domain = st.selectbox("Domain", domains)

    dom_df = long_df[long_df["Domain"] == selected_domain]

    # Show availability info
    avail_years = sorted(dom_df["Year"].unique())
    if avail_years:
        st.caption(f"📅 Data available: {min(avail_years)} - {max(avail_years)}")

    # Questions within domain
    questions = sorted(dom_df["Question"].unique())

    # --- Select All / Clear All Buttons ---
    c_all, c_clear = st.columns(2)

    # Session state key for selection
    if "selected_questions_key" not in st.session_state:
        st.session_state.selected_questions_key = [questions[0]] if questions else []

    if c_all.button("Select All"):
        st.session_state.selected_questions_key = questions
        st.rerun()

    if c_clear.button("Clear All"):
        st.session_state.selected_questions_key = []
        st.rerun()

    # Requires Streamlit 1.38+ for st.pills; fall back if missing
    if hasattr(st, "pills"):
        selected_questions = st.pills(
            "Indicators (questions)",
            questions,
            selection_mode="multi",
            key="selected_questions_key",
        )
    else:
        selected_questions = st.multiselect(
            "Indicators (questions)",
            questions,
            default=st.session_state.selected_questions_key,
            key="selected_questions_key",
        )

    # Countries
    countries = sorted(dom_df["Country"].unique())
    
    # Track domain changes to reset country selection
    if "last_selected_domain" not in st.session_state:
        st.session_state.last_selected_domain = selected_domain
        # Initialize selection to all countries
        st.session_state.selected_countries_key = countries
    
    # If domain changed, reset selection to all new countries
    if st.session_state.last_selected_domain != selected_domain:
        st.session_state.selected_countries_key = countries
        st.session_state.last_selected_domain = selected_domain

    selected_countries = st.multiselect(
        "Countries",
        countries,
        key="selected_countries_key",
        default=None, # Default is handled by key/session_state
    )

    # Year range
    years = sorted(dom_df["Year"].unique())
    if years:
        y_min, y_max = int(min(years)), int(max(years))
        selected_year_range = st.slider(
            "Year range",
            y_min,
            y_max,
            (y_min, y_max),
        )
    else:
        selected_year_range = (0, 0)

# --- Visual Settings ---
with st.sidebar.expander("2. Visual Settings", expanded=False):
    # Chart Type
    chart_type = st.selectbox(
        "Chart Type",
        ["Line Chart", "Bar Chart"],
        index=0,
    )

    # Layout
    layout = st.radio(
        "Plot layout",
        ["Single figure (all countries)", "Country panels"],
        index=0,
    )

    # Show column control if we are faceting (either by country or by indicator)
    show_grid_control = (layout == "Country panels") or (
        layout == "Single figure (all countries)" and len(selected_questions) > 1
    )

    grid_columns = 2
    if show_grid_control:
        grid_columns = st.slider("Grid columns (width)", 1, 6, 2)

    # Graph style
    graph_style = st.selectbox(
        "Graph style",
        [
            "Colorblind-safe (default)",
            "Vibrant (Tableau 10)",
            "Pastel (Soft)",
            "Earth Tones (Muted)",
            "Monochrome (blue shades)",
            "Black & white (line styles)",
            "Highlight focal country",
        ],
        index=0,
    )

    # Theme presets
    theme = st.selectbox(
        "Theme preset",
        [
            "Academic (light)",
            "OECD grey",
            "Dark dashboard",
            "Pastel report",
            "The Economist",
            "Financial Times",
        ],
        index=0,
    )

    # Focal country
    focal_country = None
    if graph_style == "Highlight focal country":
        focal_country = st.selectbox(
            "Focal country",
            countries,
            index=0,
        )

    # Error Bar Settings
    error_bar_type = st.selectbox(
        "Error Bars / Confidence Intervals",
        ["95% Confidence Interval", "Standard Error", "None"],
        index=0
    )


# -------------------------------------------------
# Filtered data for plotting
# -------------------------------------------------
if not selected_questions or not selected_countries:
    st.warning("Please select at least one indicator and one country.")
    st.stop()

plot_df = dom_df[
    (dom_df["Question"].isin(selected_questions))
    & (dom_df["Country"].isin(selected_countries))
    & (dom_df["Year"].between(selected_year_range[0], selected_year_range[1]))
]

if plot_df.empty:
    st.warning("No data for this combination. Try widening the year range or adding countries.")
    st.stop()

# Calculate error bars / CI
if "se" in plot_df.columns:
    if error_bar_type == "95% Confidence Interval":
        z_mult = 1.96
    elif error_bar_type == "Standard Error":
        z_mult = 1.0
    else:
        z_mult = 0.0
        
    if error_bar_type != "None":
        plot_df["ci_low"] = plot_df["value"] - z_mult * plot_df["se"]
        plot_df["ci_high"] = plot_df["value"] + z_mult * plot_df["se"]
    else:
        plot_df["ci_low"] = pd.NA
        plot_df["ci_high"] = pd.NA
else:
    plot_df["ci_low"] = pd.NA
    plot_df["ci_high"] = pd.NA

# Check for missing countries
present_countries = set(plot_df["Country"].unique())
missing_countries = set(selected_countries) - present_countries
if missing_countries:
    st.warning(
        "⚠️ The following countries have no data for the selected period and are not shown: "
        + ", ".join(sorted(missing_countries))
    )


# -------------------------------------------------
# Main Content: Dashboard Layout
# -------------------------------------------------
tab1 = st.container()

with tab1:
    # --- 1. KPI Metrics ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Countries", len(selected_countries))
    m2.metric("Indicators", len(selected_questions))
    m3.metric("Years", f"{selected_year_range[0]} - {selected_year_range[1]}")
    m4.metric("Data Points", len(plot_df))

    st.divider()

    # --- 2. Chart Section ---
    st.subheader(f"📈 Analysis: {selected_domain}")

    # --- Style helpers ---
    def get_country_color_encoding():
        """Color mapping for countries, depending on graph style."""
        if graph_style == "Colorblind-safe (default)":
            palette = [
                "#1b9e77",
                "#d95f02",
                "#7570b3",
                "#e7298a",
                "#66a61e",
                "#e6ab02",
                "#a6761d",
                "#666666",
            ]
            return alt.Color(
                "Country:N",
                title="Country",
                scale=alt.Scale(range=palette),
            )

        if graph_style == "Vibrant (Tableau 10)":
            # Tableau 10 standard
            palette = [
                "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
                "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"
            ]
            return alt.Color("Country:N", title="Country", scale=alt.Scale(range=palette))

        if graph_style == "Pastel (Soft)":
            # Brewer Pastel1 + Pastel2 mix
            palette = [
                "#fbb4ae", "#b3cde3", "#ccebc5", "#decbe4", "#fed9a6",
                "#ffffcc", "#e5d8bd", "#fddaec", "#f2f2f2"
            ]
            return alt.Color("Country:N", title="Country", scale=alt.Scale(range=palette))

        if graph_style == "Earth Tones (Muted)":
            # Muted earth tones
            palette = [
                "#8c564b", "#c49c94", "#7f7f7f", "#c7c7c7", "#bcbd22",
                "#dbdb8d", "#17becf", "#9edae5"
            ]
            return alt.Color("Country:N", title="Country", scale=alt.Scale(range=palette))

        if graph_style == "Monochrome (blue shades)":
            return alt.Color(
                "Country:N",
                title="Country",
                scale=alt.Scale(scheme="blues"),
            )

        if graph_style == "Highlight focal country" and focal_country is not None:
            return alt.condition(
                alt.datum.Country == focal_country,
                alt.value("#1f77b4"),  # highlight
                alt.value("#CCCCCC"),  # others
            )

        return alt.value("black")

    def get_stroke_dash_encoding():
        """Line style mapping (used for black & white)."""
        if graph_style == "Black & white (line styles)":
            return alt.StrokeDash(
                "Country:N",
                title="Country",
                sort=selected_countries,
            )
        return alt.value([1, 0])

    def style_chart(chart: alt.Chart) -> alt.Chart:
        """Apply theme preset: fonts, fill, grid, legend, etc."""
        chart = (
            chart.configure_axis(labelFontSize=13, titleFontSize=15)
            .configure_legend(titleFontSize=14, labelFontSize=12)
            .configure_title(fontSize=18, anchor="start")
        )

        if theme == "Academic (light)":
            chart = chart.configure_view(strokeWidth=0, fill="white").configure_axis(
                grid=True, gridColor="#DDDDDD"
            )
        elif theme == "OECD grey":
            chart = chart.configure_view(
                stroke="#CCCCCC", strokeWidth=1, fill="white"
            ).configure_axis(grid=True, gridColor="#E0E0E0")
        elif theme == "Dark dashboard":
            chart = (
                chart.configure_view(strokeWidth=0, fill="#111111")
                .configure_axis(
                    labelColor="white",
                    titleColor="white",
                    grid=True,
                    gridColor="#333333",
                )
                .configure_legend(titleColor="white", labelColor="white")
                .configure_title(color="white")
            )
        elif theme == "Pastel report":
            chart = chart.configure_view(strokeWidth=0, fill="#FAFAFA").configure_axis(
                grid=True, gridColor="#F0F0F0"
            )
        elif theme == "The Economist":
            chart = chart.configure_view(strokeWidth=0, fill="#d5e4eb").configure_axis(
                grid=True,
                gridColor="white",
                labelFont="Verdana",
                titleFont="Verdana",
            ).configure_title(font="Verdana", fontSize=20).configure_legend(
                labelFont="Verdana", titleFont="Verdana"
            )
        elif theme == "Financial Times":
            chart = chart.configure_view(strokeWidth=0, fill="#fff1e0").configure_axis(
                grid=True,
                gridColor="#e3cbb0",
                labelFont="Georgia",
                titleFont="Georgia",
            ).configure_title(font="Georgia", fontSize=20).configure_legend(
                labelFont="Georgia", titleFont="Georgia"
            )

        return chart

    color_encoding = get_country_color_encoding()
    stroke_dash_encoding = get_stroke_dash_encoding()

    # --- Plotting Logic ---
    def create_single_chart(
        data: pd.DataFrame,
        title_text: str,
        x_axis_title: str = "Year",
        y_axis_title: str = "Value",
        color_enc=None,
        dash_enc=None,
        x_off=None,
        show_ci_flag: bool = True,
        height: int = 450,
    ) -> alt.Chart:
        
        # Determine unique years for the axis ticks
        chart_years = sorted(data["Year"].dropna().unique().astype(int))
        
        base = alt.Chart(data)

        # Main layer: bar or line
        if chart_type == "Bar Chart":
            main_mark = base.mark_bar()
        else:
            main_mark = base.mark_line(point=True)

        main = main_mark.encode(
            x=alt.X("Year:Q", title=x_axis_title, axis=alt.Axis(format="04d", values=chart_years)),
            y=alt.Y("value:Q", title=y_axis_title),
            color=color_enc,
            strokeDash=dash_enc,
            xOffset=x_off,
            tooltip=[
                "Country",
                "Year",
                "Question",
                alt.Tooltip("value:Q", title="Mean"),
                alt.Tooltip("se:Q", title="SE", format=".3f"),
                alt.Tooltip("n:Q", title="N"),
                alt.Tooltip("ci_low:Q", title="CI low", format=".3f"),
                alt.Tooltip("ci_high:Q", title="CI high", format=".3f"),
            ],
            order="Year",
        )

        layers = [main]

        # Optional CI layer
        if (
            show_ci_flag
            and "ci_low" in data.columns
            and "ci_high" in data.columns
            and data["ci_low"].notna().any()
        ):
            if chart_type == "Bar Chart":
                err = base.mark_errorbar().encode(
                    x=alt.X("Year:Q", title=x_axis_title, axis=alt.Axis(format="04d", values=chart_years)),
                    y=alt.Y("ci_low:Q", title=y_axis_title),
                    y2="ci_high:Q",
                    color=color_enc,
                    xOffset=x_off,
                )
            else:
                err = base.mark_errorband(opacity=0.2).encode(
                    x=alt.X("Year:Q", title=x_axis_title, axis=alt.Axis(format="04d", values=chart_years)),
                    y=alt.Y("ci_low:Q", title=y_axis_title),
                    y2="ci_high:Q",
                    color=color_enc,
                )
            layers.insert(0, err)

        chart = alt.layer(*layers).properties(
            title=title_text,
            height=height,  # Dynamic height
        )
        return style_chart(chart)

    # Layouts
    if layout == "Single figure (all countries)":
        if len(selected_questions) > 1:
            # Multiple indicators -> grid of charts, one per indicator
            cols = st.columns(grid_columns)
            for i, q in enumerate(selected_questions):
                q_data = plot_df[plot_df["Question"] == q]
                chart = create_single_chart(
                    q_data,
                    title_text=f"{q}",
                    y_axis_title="Value",
                    color_enc=color_encoding,
                    dash_enc=stroke_dash_encoding
                    if chart_type == "Line Chart"
                    else alt.value([0, 0]),
                    x_off="Country:N" if chart_type == "Bar Chart" else alt.value(0),
                    show_ci_flag=(error_bar_type != "None"),
                )
                with cols[i % grid_columns]:
                    st.altair_chart(chart, width="stretch")
        else:
            # One indicator -> single chart
            chart = create_single_chart(
                plot_df,
                title_text=f"{selected_questions[0]} – {selected_domain}",
                y_axis_title=selected_questions[0],
                color_enc=color_encoding,
                dash_enc=stroke_dash_encoding
                if chart_type == "Line Chart"
                else alt.value([0, 0]),
                x_off="Country:N" if chart_type == "Bar Chart" else alt.value(0),
                show_ci_flag=(error_bar_type != "None"),
                height=600,  # Increased height
            )
            
            # Left aligned, narrower (approx 60% width)
            c_chart, _ = st.columns([3, 2])
            with c_chart:
                st.altair_chart(chart, width="stretch")
    else:
        # Country panels -> grid of charts, one per country
        if graph_style == "Black & white (line styles)":
            panel_color = alt.value("black")
            panel_dash = alt.StrokeDash("Question:N", title="Indicator")
        else:
            panel_color = alt.Color("Question:N", title="Indicator")
            panel_dash = alt.value([1, 0])

        cols = st.columns(grid_columns)
        for i, country in enumerate(selected_countries):
            c_data = plot_df[plot_df["Country"] == country]
            if c_data.empty:
                continue
            chart = create_single_chart(
                c_data,
                title_text=f"{country}",
                y_axis_title="Value",
                color_enc=panel_color,
                dash_enc=panel_dash
                if chart_type == "Line Chart"
                else alt.value([0, 0]),
                x_off="Question:N" if chart_type == "Bar Chart" else alt.value(0),
                show_ci_flag=(error_bar_type != "None"),
            )
            with cols[i % grid_columns]:
                st.altair_chart(chart, width="stretch")

    # --- 3. Footer / Export ---
    st.divider()

    # --- Selected Indicator Definitions ---
    if selected_questions:
        st.subheader("📖 Indicator Definitions")
        # from info_content import get_schema_dict, get_item_descriptions # MERGED

        schema = get_schema_dict()
        item_descs = get_item_descriptions()

        for q in selected_questions:
            info = schema.get(q)
            if info:
                with st.expander(f"ℹ️ {q}", expanded=False):
                    items_used = info.get("Items Used", "N/A")
                    st.markdown(
                        f"""
                        - **Interpretation**: {info.get('Interpretation', 'N/A')}
                        - **Method**: {info.get('Method', 'N/A')}
                        - **Items Used**: {items_used}
                        - **Domain**: {info.get('Domain', 'N/A')}
                        """
                    )

                    # Try to find relevant item descriptions
                    import re

                    relevant_items = []
                    for code, desc in item_descs.items():
                        # 1) Exact substring match
                        if code in items_used:
                            relevant_items.append(f"- **{code}**: {desc}")
                        else:
                            # 2) Range parsing, e.g. A065–A074
                            ranges = re.findall(
                                r"([A-Z]\d+)[-–—]([A-Z]\d+)", items_used
                            )
                            for start, end in ranges:
                                if start[0] == end[0] == code[0]:
                                    try:
                                        s_num = int(start[1:])
                                        e_num = int(end[1:])
                                        c_num = int(code[1:])
                                        if s_num <= c_num <= e_num:
                                            relevant_items.append(
                                                f"- **{code}**: {desc}"
                                            )
                                            break
                                    except Exception:
                                        pass

                    if relevant_items:
                        st.markdown("**Constituent Items:**")
                        relevant_items = sorted(list(set(relevant_items)))
                        for item_txt in relevant_items:
                            st.markdown(item_txt)

    st.divider()
    with st.expander("📥 Export & Data View", expanded=False):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown("### Download")
            csv = plot_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                csv,
                "filtered_data.csv",
                "text/csv",
                key="download-csv",
                use_container_width=True,
            )

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                plot_df.to_excel(writer, sheet_name="Data", index=False)

            st.download_button(
                "Download Excel",
                buffer.getvalue(),
                "filtered_data.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download-excel",
                use_container_width=True,
            )

        with c2:
            st.markdown("### Raw Data Preview")
            # Optional quick summary of SE / N
            if "se" in plot_df.columns and "n" in plot_df.columns:
                se_valid = plot_df["se"].dropna()
                n_valid = plot_df["n"].dropna()
                if not se_valid.empty and not n_valid.empty:
                    st.markdown(
                        f"- Median SE: **{se_valid.median():.3f}** "
                        f"(min: {se_valid.min():.3f}, max: {se_valid.max():.3f})  \n"
                        f"- Median N: **{int(n_valid.median())}** "
                        f"(min: {int(n_valid.min())}, max: {int(n_valid.max())})"
                    )
            st.dataframe(plot_df, height=200, use_container_width=True)
