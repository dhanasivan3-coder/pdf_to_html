"""
PDF Paragraph Tagger — All Options (Updated)

Features added:
- AUTO entity conversion (default ON) with toolbar toggle
- Save HTML wrapped in minimal HTML shell
- Infer headings by font size (button)
- Expanded entity map (math, greek, latin)
- Nesting preference toggle for bold+italic (<b><i>..</i></b> or <i><b>..</b></i>)
- Save All Pages (wrapped) — produces nested <section> structures for headings
Save as: pdf_paratag_editor_all_options.py
Dependencies: pip install pymupdf pillow
"""

import fitz
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import json
import math
import re
import copy

# ---------- Settings ----------
AUTO_ENTITIES = True            # default ON
NESTING_PREF = 'b_outside_i'    # or 'i_outside_b' ; default b outside i

# ---------- State ----------
class State:
    def __init__(self):
        self.doc = None
        self.page_index = 0
        self.zoom = 1.0
        self.regions = {}            # {page_idx: [ {id, rect, text, tag}, ... ] }
        self.drag_start = None
        self.current_rect_id = None
        self.selected_region = None  # (page_idx, idx)
        self.img_holder = {'pil': None, 'tk': None}
        self.undo_stack = []
        self.redo_stack = []

state = State()

# ---------- Helpers ----------
def push_undo():
    state.undo_stack.append(copy.deepcopy(state.regions))
    state.redo_stack.clear()

def do_undo(root, canvas, html_text, listbox):
    if not state.undo_stack:
        messagebox.showinfo('Undo', 'Nothing to undo')
        return
    state.redo_stack.append(copy.deepcopy(state.regions))
    state.regions = state.undo_stack.pop()
    state.selected_region = None
    render_current_page(root, canvas, html_text, listbox)

def do_redo(root, canvas, html_text, listbox):
    if not state.redo_stack:
        messagebox.showinfo('Redo', 'Nothing to redo')
        return
    state.undo_stack.append(copy.deepcopy(state.regions))
    state.regions = state.redo_stack.pop()
    state.selected_region = None
    render_current_page(root, canvas, html_text, listbox)

def render_page_image(page, zoom):
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    return img

def page_to_image_coords(px, py, img_w, img_h, page):
    sx = img_w / page.rect.width
    sy = img_h / page.rect.height
    return px * sx, py * sy

def image_to_page_coords(ix, iy, img_w, img_h, page):
    sx = page.rect.width / img_w
    sy = page.rect.height / img_h
    return ix * sx, iy * sy

def rect_normalize(r):
    x0,y0,x1,y1 = r
    return (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))

def rect_from_tuple(t):
    x0,y0,x1,y1 = t
    return fitz.Rect(x0,y0,x1,y1)

def generate_region_id(page_idx, idx):
    return f'p{page_idx+1}_r{idx+1}'

# ---------- Expanded Symbol entities (AUTO) ----------
# This map includes math symbols, Greek letters, and common Latin accented characters.
HTML_ENTITY_MAP = {
    # basic typography
    '©': '&copy;', '®': '&reg;', '™': '&trade;',
    '—': '&mdash;', '–': '&ndash;', '·': '&middot;', '…': '&hellip;',
    '“': '&ldquo;', '”': '&rdquo;', '‘': '&lsquo;', '’': '&rsquo;',
    '•': '&bull;', '°': '&deg;',

    # currency
    '£': '&pound;', '€': '&euro;', '₹': '&#8377;',

    # math symbols
    '±': '&plusmn;', '×': '&times;', '÷': '&divide;',
    '≤': '&le;', '≥': '&ge;', '≠': '&ne;', '≈': '&asymp;',
    '≡': '&equiv;', '∼': '&sim;', '∑': '&sum;', '∏': '&prod;',
    '∫': '&int;', '√': '&radic;', '∞': '&infin;', '∂': '&part;',
    '∇': '&nabla;', '∈': '&in;', '∉': '&notin;', '∅': '&#8709;',
    '∝': '&prop;', '∴': '&there4;', '∵': '&because;',
    '⇒': '&rArr;', '⇔': '&hArr;', '←': '&larr;', '→': '&rarr;',
    '↔': '&harr;', '↦': '&#8614;',
    '≅': '&cong;', '∗': '&lowast;',

    # greek lowercase
    'α': '&alpha;','β': '&beta;','γ': '&gamma;','δ': '&delta;',
    'ε': '&epsilon;','ζ': '&zeta;','η': '&eta;','θ': '&theta;',
    'ι': '&iota;','κ': '&kappa;','λ': '&lambda;','μ': '&mu;',
    'ν': '&nu;','ξ': '&xi;','ο': '&omicron;','π': '&pi;',
    'ρ': '&rho;','σ': '&sigma;','τ': '&tau;','υ': '&upsilon;',
    'φ': '&phi;','χ': '&chi;','ψ': '&psi;','ω': '&omega;',
    'ς': '&sigmaf;','ϑ': '&#976;',

    # greek uppercase
    'Α': '&Alpha;','Β': '&Beta;','Γ': '&Gamma;','Δ': '&Delta;',
    'Ε': '&Epsilon;','Ζ': '&Zeta;','Η': '&Eta;','Θ': '&Theta;',
    'Ι': '&Iota;','Κ': '&Kappa;','Λ': '&Lambda;','Μ': '&Mu;',
    'Ν': '&Nu;','Ξ': '&Xi;','Ο': '&Omicron;','Π': '&Pi;',
    'Ρ': '&Rho;','Σ': '&Sigma;','Τ': '&Tau;','Υ': '&Upsilon;',
    'Φ': '&Phi;','Χ': '&Chi;','Ψ': '&Psi;','Ω': '&Omega;',

    # latin accented letters (common)
    'á': '&aacute;','à': '&agrave;','â': '&acirc;','ä': '&auml;','ã': '&atilde;','å': '&aring;',
    'Á': '&Aacute;','À': '&Agrave;','Â': '&Acirc;','Ä': '&Auml;','Ã': '&Atilde;','Å': '&Aring;',
    'é': '&eacute;','è': '&egrave;','ê': '&ecirc;','ë': '&euml;',
    'É': '&Eacute;','È': '&Egrave;','Ê': '&Ecirc;','Ë': '&Euml;',
    'í': '&iacute;','ì': '&igrave;','î': '&icirc;','ï': '&iuml;',
    'Í': '&Iacute;','Ì': '&Igrave;','Î': '&Icirc;','Ï': '&Iuml;',
    'ó': '&oacute;','ò': '&ograve;','ô': '&ocirc;','ö': '&ouml;','õ': '&otilde;',
    'Ó': '&Oacute;','Ò': '&Ograve;','Ô': '&Ocirc;','Ö': '&Ouml;','Õ': '&Otilde;',
    'ú': '&uacute;','ù': '&ugrave;','û': '&ucirc;','ü': '&uuml;',
    'Ú': '&Uacute;','Ù': '&Ugrave;','Û': '&Ucirc;','Ü': '&Uuml;',
    'ñ': '&ntilde;','Ñ': '&Ntilde;','ç': '&ccedil;','Ç': '&Ccedil;',
    'œ': '&oelig;','Œ': '&OElig;','æ': '&aelig;','Æ': '&AElig;',

    # punctuation/quotes
    '‹': '&lsaquo;','›': '&rsaquo;','«': '&laquo;','»': '&raquo;',
}

def apply_html_entities(text):
    if not text:
        return text
    # Simple replace — do longer keys first to avoid partial collision (not usually needed here)
    for k, v in HTML_ENTITY_MAP.items():
        text = text.replace(k, v)
    return text

# ---------- Bold & Italic detection & HTML escaping ----------
# PyMuPDF span['flags'] bitmask:
#   bit 1 (2) => italic
#   bit 4 (16) => bold

def wrap_span_text(s, is_bold, is_italic):
    """
    Wrap span text according to current nesting preference.
    """
    if is_bold and is_italic:
        if NESTING_PREF == 'b_outside_i':
            return f"<b><i>{s}</i></b>"
        else:
            return f"<i><b>{s}</b></i>"
    elif is_bold:
        return f"<b>{s}</b>"
    elif is_italic:
        return f"<i>{s}</i>"
    else:
        return s

def extract_text_from_rect(page, rect):
    """
    Extract text inside rect from page; wrap spans with <i>, <b> in the chosen nesting order.
    """
    txt_parts = []
    d = page.get_text('dict', clip=rect)
    blocks = d.get('blocks', [])
    for b in blocks:
        for line in b.get('lines', []):
            line_parts = []
            for span in line.get('spans', []):
                s = span.get('text', '')
                if not s:
                    continue
                s = s.replace('\n', ' ').strip()
                if not s:
                    continue
                flags = int(span.get('flags', 0))
                is_italic = bool(flags & 2)
                is_bold = bool(flags & 16)
                wrapped = wrap_span_text(s, is_bold, is_italic)
                line_parts.append(wrapped)
            if line_parts:
                txt_parts.append(" ".join(line_parts))
    return "\n".join(txt_parts).strip()

def escape_html_keep_bi_and_entities(text):
    """
    Escape text for HTML preview while preserving <b>/<i> tags and valid entities.
    """
    if not text:
        return ''

    # placeholders
    ph_b_open = "@@B_OPEN@@"
    ph_b_close = "@@B_CLOSE@@"
    ph_i_open = "@@I_OPEN@@"
    ph_i_close = "@@I_CLOSE@@"

    # protect nested <b><i>...</i></b> or <i><b>...</b></i>
    def protect_nested(m):
        inner = m.group(1)
        inner_escaped = inner.replace('<', '&lt;').replace('>', '&gt;')
        # detect actual nesting sequence to restore later exactly as found
        seq = m.group(0)
        if seq.lower().startswith('<b>'):
            return ph_b_open + ph_i_open + inner_escaped + ph_i_close + ph_b_close
        else:
            return ph_i_open + ph_b_open + inner_escaped + ph_b_close + ph_i_close

    text_prot = re.sub(r'<b>\s*<i>(.*?)</i>\s*</b>', protect_nested, text, flags=re.S|re.I)
    text_prot = re.sub(r'<i>\s*<b>(.*?)</b>\s*</i>', protect_nested, text_prot, flags=re.S|re.I)

    # Protect <b>...</b>
    def protect_b(m):
        inner = m.group(1)
        inner_escaped = inner.replace('<', '&lt;').replace('>', '&gt;')
        return ph_b_open + inner_escaped + ph_b_close
    text_prot = re.sub(r'<b>(.*?)</b>', protect_b, text_prot, flags=re.S|re.I)

    # Protect <i>...</i>
    def protect_i(m):
        inner = m.group(1)
        inner_escaped = inner.replace('<', '&lt;').replace('>', '&gt;')
        return ph_i_open + inner_escaped + ph_i_close
    text_prot = re.sub(r'<i>(.*?)</i>', protect_i, text_prot, flags=re.S|re.I)

    # Escape leftover angle brackets
    text_prot = text_prot.replace('<', '&lt;').replace('>', '&gt;')

    # Escape '&' that are NOT part of a valid entity (named or numeric)
    def amp_repl(m):
        idx = m.start()
        following = text_prot[idx+1:idx+1+30]
        if re.match(r'(#\d+;|#x[0-9a-fA-F]+;|[a-zA-Z][a-zA-Z0-9]+;)', following):
            return '&'
        return '&amp;'
    text_prot = re.sub(r'&', lambda m: amp_repl(m), text_prot)

    # Restore placeholders
    text_prot = text_prot.replace(ph_b_open, '<b>').replace(ph_b_close, '</b>')
    text_prot = text_prot.replace(ph_i_open, '<i>').replace(ph_i_close, '</i>')

    return text_prot

# ---------- Build nested sections helper ----------
def build_nested_sections_from_regions(regs, page_index, page):
    """
    Build nested <section> structure from ordered 'regs' list.
    regs: list of {'id','rect','text','tag'} in reading order.
    page_index: zero-based page number (used to form ids).
    page: fitz.Page instance for fallbacks if necessary.

    Produces a string chunk of HTML with nested <section id="..."> elements.
    Section id scheme: "<page>.<n>.<m>..." (e.g. "2", "2.1", "2.1.1")
    Only h1..h4 affect nesting. Other tags (p, li, fig, etc.) go into the current open section.
    """
    level_map = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4}
    counters = [0, 0, 0, 0, 0]  # index by level
    open_stack = []  # stack of opened section levels
    out = []

    def close_to_level(target_level):
        nonlocal open_stack, out
        while open_stack and open_stack[-1] >= target_level:
            out.append('</section>')
            open_stack.pop()

    base_opened = False

    for r in regs:
        tag = (r.get('tag') or 'p').lower()
        text = r.get('text') or extract_text_from_rect(page, fitz.Rect(*r['rect']))
        if AUTO_ENTITIES:
            text = apply_html_entities(text)
        text_esc = escape_html_keep_bi_and_entities(text)

        if tag in level_map:
            lvl = level_map[tag]
            # increment counter for this level and reset lower levels
            counters[lvl] += 1
            for lower in range(lvl+1, 5):
                counters[lower] = 0

            # ensure base section open
            if not base_opened:
                top_id = str(page_index + 1)
                out.append(f'<section id="{top_id}">')
                open_stack.append(0)  # sentinel (0) for page-level
                base_opened = True

            # close any sections that are at >= this level
            close_to_level(lvl)

            # new section id using counters up to this level
            nums = [str(page_index + 1)]
            for i in range(1, lvl+1):
                nums.append(str(counters[i]))
            sec_id = ".".join(nums)

            out.append(f'<section id="{sec_id}">')
            open_stack.append(lvl)

            # add the heading inside
            out.append(f'<{tag} id="{r["id"]}">{text_esc}</{tag}>' )
        else:
            # normal content — open base if needed
            if not base_opened:
                top_id = str(page_index + 1)
                out.append(f'<section id="{top_id}">')
                open_stack.append(0)
                base_opened = True
            safe_id = r.get('id','')
            out.append(f'<{tag} id="{safe_id}">{text_esc}</{tag}>')

    # close all opened sections
    while open_stack:
        out.append('</section>')
        open_stack.pop()

    return "\n".join(out)

# ---------- Rendering / UI actions ----------
def open_pdf(root, canvas, html_text, listbox):
    path = filedialog.askopenfilename(filetypes=[('PDF files','*.pdf'), ('All files','*.*')])
    if not path:
        return
    try:
        state.doc = fitz.open(path)
    except Exception as e:
        messagebox.showerror('Error', f'Cannot open PDF: {e}')
        return
    state.page_index = 0
    state.regions = {}
    state.undo_stack.clear(); state.redo_stack.clear()
    render_current_page(root, canvas, html_text, listbox)

def render_current_page(root, canvas, html_text, listbox):
    canvas.delete('all')
    listbox.delete(0, tk.END)
    html_text.config(state='normal')
    html_text.delete('1.0', tk.END)

    if not state.doc:
        html_text.insert(tk.END, '<!-- Open a PDF -->')
        html_text.config(state='disabled')
        return

    page = state.doc[state.page_index]
    target_w = 430
    zoom = target_w / page.rect.width if page.rect.width>0 else 1.0
    state.zoom = zoom
    pil = render_page_image(page, zoom)
    state.img_holder['pil'] = pil
    state.img_holder['tk'] = ImageTk.PhotoImage(pil)
    canvas.config(width=pil.width, height=pil.height)
    canvas.create_image(0,0,anchor='nw',image=state.img_holder['tk'],tags='pdfimg')

    regs = state.regions.get(state.page_index, [])
    for idx, r in enumerate(regs):
        x0,y0,x1,y1 = r['rect']
        x0_i, y0_i = page_to_image_coords(x0, y0, pil.width, pil.height, page)
        x1_i, y1_i = page_to_image_coords(x1, y1, pil.width, pil.height, page)
        canvas.create_rectangle(x0_i, y0_i, x1_i, y1_i, outline='red', width=2, tags=(f'reg_{idx}', 'region'))
        icon_x = max(2, x0_i + 4)
        icon_y = max(2, y0_i + 4)
        canvas.create_text(icon_x, icon_y, text=(r.get('tag','p') or 'p'), anchor='nw', font=('Helvetica',10,'bold'), tags=(f'icon_{idx}',))
        listbox.insert(tk.END, f"{r['id']} [{r.get('tag','p')}]  ({int(y0)}-{int(y1)})")

    # Update HTML preview using nested sections
    update_html_from_regions(html_text)
    root.title(f'PDF Tagger - Page {state.page_index+1}/{len(state.doc)}')

# ---------- Mouse / selection ----------
def canvas_mouse_down(event, canvas):
    state.drag_start = (event.x, event.y)
    if state.current_rect_id:
        try:
            canvas.delete(state.current_rect_id)
        except Exception:
            pass
    state.current_rect_id = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='green', dash=(4,2), tags=('current',))

def canvas_mouse_drag(event, canvas):
    if state.drag_start and state.current_rect_id:
        x0,y0 = state.drag_start
        canvas.coords(state.current_rect_id, x0, y0, event.x, event.y)

def canvas_mouse_up(event, canvas, html_text, listbox):
    if not state.drag_start:
        return
    x0,y0 = state.drag_start
    x1,y1 = event.x, event.y
    if state.current_rect_id:
        try:
            canvas.delete(state.current_rect_id)
        except Exception:
            pass
    state.current_rect_id = None
    state.drag_start = None

    if not state.doc:
        return
    page = state.doc[state.page_index]
    img_w, img_h = state.img_holder['pil'].size
    px0, py0 = image_to_page_coords(x0, y0, img_w, img_h, page)
    px1, py1 = image_to_page_coords(x1, y1, img_w, img_h, page)
    rect = rect_normalize((px0, py0, px1, py1))
    if abs(rect[2]-rect[0]) < 2 or abs(rect[3]-rect[1]) < 2:
        return
    push_undo()
    regs = state.regions.setdefault(state.page_index, [])
    rid = generate_region_id(state.page_index, len(regs))
    raw_text = extract_text_from_rect(page, rect_from_tuple(rect))
    # AUTO: apply symbol entities to extracted text if enabled
    if AUTO_ENTITIES:
        raw_text = apply_html_entities(raw_text)
    rdict = {'id': rid, 'rect': rect, 'text': raw_text, 'tag': 'p'}
    regs.append(rdict)
    render_current_page(root, canvas, html_text, listbox)

def listbox_select(event, canvas, html_text):
    sel = event.widget.curselection()
    if not sel:
        return
    idx = sel[0]
    state.selected_region = (state.page_index, idx)
    highlight_region_in_canvas(canvas, idx)
    highlight_region_in_html(html_text, state.page_index, idx)

def highlight_region_in_canvas(canvas, idx):
    canvas.delete('hl')
    if not state.doc or state.page_index not in state.regions:
        return
    regs = state.regions.get(state.page_index, [])
    if not (0 <= idx < len(regs)):
        return
    page = state.doc[state.page_index]
    pil = state.img_holder['pil']
    r = regs[idx]
    x0,y0,x1,y1 = r['rect']
    x0_i, y0_i = page_to_image_coords(x0, y0, pil.width, pil.height, page)
    x1_i, y1_i = page_to_image_coords(x1, y1, pil.width, pil.height, page)
    canvas.create_rectangle(x0_i, y0_i, x1_i, y1_i, outline='blue', width=3, tags=('hl',))

def canvas_right_click(event, canvas, listbox, html_text):
    if not state.doc:
        return
    page = state.doc[state.page_index]
    img_w, img_h = state.img_holder['pil'].size
    px, py = image_to_page_coords(event.x, event.y, img_w, img_h, page)
    regs = state.regions.get(state.page_index, [])
    found_idx = None
    for idx in range(len(regs)-1, -1, -1):
        x0,y0,x1,y1 = regs[idx]['rect']
        if x0 <= px <= x1 and y0 <= py <= y1:
            found_idx = idx
            break
    if found_idx is not None:
        state.selected_region = (state.page_index, found_idx)
        try:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(found_idx)
            listbox.see(found_idx)
        except Exception:
            pass
        highlight_region_in_canvas(canvas, found_idx)
        try:
            highlight_region_in_html_by_id(html_text, state.page_index, found_idx)
        except Exception:
            pass
    else:
        state.selected_region = None
        listbox.selection_clear(0, tk.END)
        canvas.delete('hl')
        html_text.tag_remove('sel_reg', '1.0', tk.END)

# ---------- HTML sync & splitting ----------
def update_html_from_regions(html_text):
    html_text.config(state='normal')
    html_text.delete('1.0', tk.END)
    if not state.doc:
        html_text.insert(tk.END, '<!-- Open a PDF -->')
        html_text.config(state='disabled')
        return
    page = state.doc[state.page_index]
    regs = state.regions.get(state.page_index, [])
    if regs:
        html_fragment = build_nested_sections_from_regions(regs, state.page_index, page)
    else:
        html_fragment = '<!-- No regions on this page -->'
    html_text.insert(tk.END, html_fragment)
    html_text.config(state='disabled')

def highlight_region_in_html(html_text, page_idx, idx):
    if page_idx not in state.regions:
        return
    regs = state.regions[page_idx]
    if not (0 <= idx < len(regs)):
        return
    rid = regs[idx]['id']
    html_text.tag_remove('sel_reg', '1.0', tk.END)
    txt = html_text.get('1.0', tk.END)
    pattern = re.compile(rf"<p[^>]*\bid\s*=\s*['\"]{re.escape(rid)}['\"][^>]*>.*?</p\s*>", flags=re.S | re.I)
    m = pattern.search(txt)
    if not m:
        # try headings and other tags
        pattern2 = re.compile(rf"<[^>]+\bid\s*=\s*['\"]{re.escape(rid)}['\"][^>]*>.*?</[^>]+>", flags=re.S | re.I)
        m = pattern2.search(txt)
        if not m:
            return
    start_index = html_text.index(f'1.0+{m.start()}chars')
    end_index = html_text.index(f'1.0+{m.end()}chars')
    html_text.tag_add('sel_reg', start_index, end_index)
    html_text.tag_config('sel_reg', background='#ffff99')

def highlight_region_in_html_by_id(html_text, page_idx, idx):
    highlight_region_in_html(html_text, page_idx, idx)

def sync_html_to_pdf(html_text, canvas):
    txt = html_text.get('1.0', tk.END)
    for m in re.finditer(r"<([a-z0-9]+)[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"][^>]*>", txt, flags=re.I|re.S):
        pid = m.group(2)
        regs = state.regions.get(state.page_index, [])
        for idx, r in enumerate(regs):
            if r['id'] == pid:
                state.selected_region = (state.page_index, idx)
                highlight_region_in_canvas(canvas, idx)
                highlight_region_in_html_by_id(html_text, state.page_index, idx)
                return
    messagebox.showinfo('Sync', 'Could not find a matching region id on this page.')

def split_region_at_html_cursor(html_text, canvas, listbox):
    cursor = html_text.index(tk.INSERT)
    txt = html_text.get('1.0', tk.END)
    abs_offset = int(html_text.count('1.0', cursor)[0])
    for m in re.finditer(r"<p[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</p\s*>", txt, flags=re.S|re.I):
        s, e = m.start(), m.end()
        if s <= abs_offset <= e:
            pid = m.group(1)
            inner = m.group(2)
            inner_plain = re.sub(r"<.*?>", "", inner)
            rel = abs_offset - (s + m.group(0).find('>') + 1)
            rel = max(0, min(len(inner_plain), rel))
            regs = state.regions.get(state.page_index, [])
            for idx, r in enumerate(regs):
                if r['id'] == pid:
                    rect = r['rect']
                    total = len(inner_plain) if len(inner_plain) > 0 else 1
                    ratio = rel / total
                    y0 = rect[1]; y1 = rect[3]
                    split_y = y0 + (y1 - y0) * ratio
                    push_undo()
                    r1 = (rect[0], rect[1], rect[2], split_y)
                    r2 = (rect[0], split_y, rect[2], rect[3])
                    regs.pop(idx)
                    regs.insert(idx, {'id': generate_region_id(state.page_index, len(regs)), 'rect': r2, 'text': '', 'tag': r.get('tag','p')})
                    regs.insert(idx, {'id': generate_region_id(state.page_index, len(regs)), 'rect': r1, 'text': '', 'tag': r.get('tag','p')})
                    render_current_page(root, canvas, html_text, listbox)
                    return
    messagebox.showinfo('Split', 'Could not find a paragraph containing the cursor.')

# ---------- Word-level click split ----------
def canvas_click_word(event, canvas, html_text, listbox):
    if not state.doc:
        return
    page = state.doc[state.page_index]
    img_w, img_h = state.img_holder['pil'].size
    px, py = image_to_page_coords(event.x, event.y, img_w, img_h, page)
    words = page.get_text('words')
    nearest = None
    min_d = 1e9
    for w in words:
        wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
        if wx0 <= px <= wx1 and wy0 <= py <= wy1:
            nearest = w; break
        cx = (wx0 + wx1) / 2; cy = (wy0 + wy1) / 2
        d = (cx - px)**2 + (cy - py)**2
        if d < min_d:
            min_d = d; nearest = w
    if not nearest:
        return
    split_y = nearest[3]
    regs = state.regions.get(state.page_index, [])
    for idx, r in enumerate(regs):
        x0,y0,x1,y1 = r['rect']
        if x0 <= px <= x1 and y0 <= split_y <= y1:
            push_undo()
            r1 = (x0, y0, x1, split_y)
            r2 = (x0, split_y, x1, y1)
            regs.pop(idx)
            regs.insert(idx, {'id': generate_region_id(state.page_index, len(regs)), 'rect': r2, 'text': '', 'tag': r.get('tag','p')})
            regs.insert(idx, {'id': generate_region_id(state.page_index, len(regs)), 'rect': r1, 'text': '', 'tag': r.get('tag','p')})
            render_current_page(root, canvas, html_text, listbox)
            return

# ---------- Tagging ----------
def set_tag_for_selected(tag, canvas, html_text, listbox):
    sel = state.selected_region
    if not sel:
        messagebox.showinfo('Tag', 'Select a region first.')
        return
    pidx, idx = sel
    regs = state.regions.get(pidx, [])
    if not (0 <= idx < len(regs)):
        return
    push_undo()
    regs[idx]['tag'] = tag
    # update id to include tag prefix
    regs[idx]['id'] = f"{tag}_{regs[idx]['id']}"
    render_current_page(root, canvas, html_text, listbox)

def key_tag_handler(event, canvas, html_text, listbox):
    key = event.keysym.lower()
    mapping = {'h':'h1','j':'h2','k':'h3','l':'h4','f':'fig','t':'table','p':'p','n':'fn','b':'li','m':'lm'}
    if key not in mapping:
        return
    new_tag = mapping[key]
    sel = state.selected_region
    if not sel:
        return
    page_idx, reg_idx = sel
    regs = state.regions.get(page_idx, [])
    if not (0 <= reg_idx < len(regs)):
        return
    push_undo()
    reg = regs[reg_idx]
    old_id = reg['id']
    reg['tag'] = new_tag
    reg['id'] = f"{new_tag}_{old_id}"
    # update preview HTML fragment if present
    html = html_text.get('1.0', 'end-1c')
    id_pat = re.compile(rf"(<([a-z0-9]+)([^>]*)\bid\s*=\s*(['\"])"+re.escape(old_id)+r"\4([^>]*)>)(.*?)(</\2\s*>)", flags=re.S|re.I)
    m = id_pat.search(html)
    if m:
        attrs_before = (m.group(3) + m.group(5)).strip()
        attrs_clean = re.sub(r"\bid\s*=\s*(['\"]).*?\1", "", attrs_before)
        new_open = f"<{new_tag}{attrs_clean} id=\"{reg['id']}\">" if attrs_clean else f"<{new_tag} id=\"{reg['id']}\">"
        inner_html = m.group(6)
        new_close = f"</{new_tag}>"
        new_fragment = new_open + inner_html + new_close
        new_html = html[:m.start()] + new_fragment + html[m.end():]
        html_text.config(state='normal')
        html_text.delete('1.0', 'end')
        html_text.insert('1.0', new_html)
        html_text.config(state='disabled')
    render_current_page(root, canvas, html_text, listbox)
    regs_now = state.regions.get(page_idx, [])
    for i, r in enumerate(regs_now):
        if r['id'] == reg['id']:
            state.selected_region = (page_idx, i)
            try:
                listbox.selection_clear(0, tk.END)
                listbox.selection_set(i)
                listbox.see(i)
            except Exception:
                pass
            highlight_region_in_canvas(canvas, i)
            highlight_region_in_html_by_id(html_text, page_idx, i)
            break

# ---------- Auto-detect ----------
def auto_detect(page_idx, canvas, html_text, listbox):
    if not state.doc:
        return
    page = state.doc[page_idx]
    blocks = page.get_text('blocks')
    blocks.sort(key=lambda b: b[1])
    regs_calc = []
    gaps = []
    for i in range(1, len(blocks)):
        gaps.append(blocks[i][1] - blocks[i-1][3])
    median_gap = sorted([g for g in gaps if g>=0] + [0])[len(gaps)//2] if gaps else 0
    threshold = max(5, median_gap * 1.5)
    cur_x0, cur_y0, cur_x1, cur_y1 = None, None, None, None
    for b in blocks:
        bx0, by0, bx1, by1, btext = b[0], b[1], b[2], b[3], b[4]
        if cur_y0 is None:
            cur_x0, cur_y0, cur_x1, cur_y1 = bx0, by0, bx1, by1
        else:
            gap = by0 - cur_y1
            if gap > threshold:
                regs_calc.append((cur_x0, cur_y0, cur_x1, cur_y1))
                cur_x0, cur_y0, cur_x1, cur_y1 = bx0, by0, bx1, by1
            else:
                cur_x0 = min(cur_x0, bx0)
                cur_x1 = max(cur_x1, bx1)
                cur_y1 = max(cur_y1, by1)
    if cur_y0 is not None:
        regs_calc.append((cur_x0, cur_y0, cur_x1, cur_y1))

    if regs_calc:
        push_undo()
    page_regs = state.regions.setdefault(page_idx, [])
    for rr in regs_calc:
        rid = generate_region_id(page_idx, len(page_regs))
        text = extract_text_from_rect(page, fitz.Rect(*rr))
        if AUTO_ENTITIES:
            text = apply_html_entities(text)  # AUTO entities
        page_regs.append({'id': rid, 'rect': rr, 'text': text, 'tag': 'p'})
    render_current_page(root, canvas, html_text, listbox)

# ---------- JSON export/import ----------
def export_json():
    if not state.doc:
        messagebox.showinfo('Export','Open a PDF first')
        return
    path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON','*.json')])
    if not path:
        return
    payload = {'file': getattr(state.doc, 'name', ''), 'pages': {}}
    for pidx, regs in state.regions.items():
        payload['pages'][pidx] = []
        for r in regs:
            payload['pages'][pidx].append({'id': r['id'], 'rect': r['rect'], 'text': r.get('text',''), 'tag': r.get('tag','p')})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    messagebox.showinfo('Export', f'Exported regions to {path}')

def import_json(root, canvas, html_text, listbox):
    path = filedialog.askopenfilename(filetypes=[('JSON','*.json')])
    if not path:
        return
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    pages = payload.get('pages', {})
    new_regs = {}
    for k, v in pages.items():
        pidx = int(k)
        new_regs[pidx] = []
        for r in v:
            text = r.get('text','')
            if AUTO_ENTITIES:
                text = apply_html_entities(text)
            new_regs[pidx].append({'id': r['id'], 'rect': tuple(r['rect']), 'text': text, 'tag': r.get('tag','p')})
    push_undo()
    state.regions = new_regs
    render_current_page(root, canvas, html_text, listbox)

def delete_region(listbox, canvas, html_text):
    sel = listbox.curselection()
    if not sel:
        messagebox.showinfo('Info', 'Select a region to delete')
        return
    idx = sel[0]
    regs = state.regions.get(state.page_index, [])
    if 0 <= idx < len(regs):
        push_undo()
        regs.pop(idx)
        render_current_page(root, canvas, html_text, listbox)

# ---------- Navigation ----------
def prev_page(root, canvas, html_text, listbox):
    if not state.doc:
        return
    if state.page_index > 0:
        state.page_index -= 1
        state.selected_region = None
        render_current_page(root, canvas, html_text, listbox)

def next_page(root, canvas, html_text, listbox):
    if not state.doc:
        return
    if state.page_index < len(state.doc) - 1:
        state.page_index += 1
        state.selected_region = None
        render_current_page(root, canvas, html_text, listbox)

# ---------- Save HTML (wrapped) ----------
def save_html_to_file(html_text):
    # Always wrap the current HTML preview in a minimal HTML shell
    content = html_text.get('1.0', tk.END)
    wrapped = "<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n</head>\n<body>\n" + content + "\n</body>\n</html>"
    path = filedialog.asksaveasfilename(defaultextension='.html', filetypes=[('HTML files','*.html')])
    if not path:
        return
    with open(path, 'w', encoding='utf-8') as f:
        f.write(wrapped)
    messagebox.showinfo('Saved', f'HTML saved to {path}')

# ---------- Save ALL pages (wrapped) - uses nested sections ----------
def save_all_pages_html(html_text):
    """
    Save a single HTML file that contains the extracted/annotated HTML for every page,
    using nested <section> structure guided by heading tags.
    """
    if not state.doc:
        messagebox.showinfo('Save All', 'Open a PDF first')
        return
    path = filedialog.asksaveasfilename(defaultextension='.html', filetypes=[('HTML files','*.html')], title='Save all pages as HTML')
    if not path:
        return

    parts = []
    total_pages = len(state.doc)
    for pidx in range(total_pages):
        page = state.doc[pidx]
        regs = state.regions.get(pidx, [])
        if regs:
            page_fragment = build_nested_sections_from_regions(regs, pidx, page)
        else:
            # fallback — full page text (wrapped in a top-level section)
            full = page.get_text()
            if AUTO_ENTITIES:
                full = apply_html_entities(full)
            full_esc = escape_html_keep_bi_and_entities(full)
            paras = [p.strip() for p in full_esc.split('\n\n') if p.strip()]
            frag_parts = [f'<p>{para}</p>' for para in paras] if paras else [f'<p>{full_esc}</p>']
            page_fragment = f'<section id="{pidx+1}">\n<h2>Page {pidx+1}</h2>\n' + "\n".join(frag_parts) + "\n</section>"

        parts.append(page_fragment)

    wrapped = "<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n<style>\n.pdf-page { page-break-after: always; margin: 20px 0; }\nbody { font-family: sans-serif; }\n</style>\n</head>\n<body>\n" + "\n<hr/>\n".join(parts) + "\n</body>\n</html>"

    with open(path, 'w', encoding='utf-8') as f:
        f.write(wrapped)
    messagebox.showinfo('Saved', f'All pages saved to {path}')

# ---------- Infer headings by font size ----------
def infer_headings_for_page(root, canvas, html_text, listbox):
    """
    For each region on current page, compute average span font size inside its rect.
    Then classify tags by size percentiles:
      - top size -> h1
      - >75% of max -> h2
      - >60% of max -> h3
      - otherwise p
    Finally push undo and update UI.
    """
    if not state.doc:
        messagebox.showinfo('Info', 'Open a PDF first')
        return
    page = state.doc[state.page_index]
    regs = state.regions.get(state.page_index, [])
    if not regs:
        messagebox.showinfo('Info', 'No regions on this page to infer headings for.')
        return

    # compute average font size per region
    sizes = []
    for r in regs:
        rect = fitz.Rect(*r['rect'])
        d = page.get_text('dict', clip=rect)
        total_sz = 0.0
        count = 0
        for b in d.get('blocks', []):
            for line in b.get('lines', []):
                for span in line.get('spans', []):
                    sz = span.get('size', 0)
                    if sz:
                        total_sz += float(sz)
                        count += 1
        avg = (total_sz / count) if count>0 else 0.0
        sizes.append(avg)

    max_sz = max(sizes) if sizes else 0.0
    if max_sz <= 0:
        messagebox.showinfo('Info', 'Could not detect font sizes on this page.')
        return

    push_undo()
    for i, r in enumerate(regs):
        avg = sizes[i]
        ratio = avg / max_sz if max_sz>0 else 0
        if ratio > 0.9:
            new_tag = 'h1'
        elif ratio > 0.75:
            new_tag = 'h2'
        elif ratio > 0.6:
            new_tag = 'h3'
        else:
            new_tag = 'p'
        # update tag and id (prefix)
        r['tag'] = new_tag
        r['id'] = f"{new_tag}_{r['id']}"
    render_current_page(root, canvas, html_text, listbox)
    messagebox.showinfo('Headings', 'Heading inference completed for current page.')

# ---------- Toggle AUTO entities ----------
def toggle_auto_entities(btn, root, canvas, html_text, listbox):
    global AUTO_ENTITIES
    AUTO_ENTITIES = not AUTO_ENTITIES
    btn.config(text=f"AUTO entities: {'ON' if AUTO_ENTITIES else 'OFF'}")
    # re-render current page to show effect
    render_current_page(root, canvas, html_text, listbox)

# ---------- Toggle nesting preference ----------
def toggle_nesting(btn, root, canvas, html_text, listbox):
    global NESTING_PREF
    NESTING_PREF = 'i_outside_b' if NESTING_PREF == 'b_outside_i' else 'b_outside_i'
    btn.config(text=f"Nest: {'b>i' if NESTING_PREF=='b_outside_i' else 'i>b'}")
    # re-render current page so extract_text uses new nesting on new selections
    render_current_page(root, canvas, html_text, listbox)



# ---------- Build UI ----------
root = tk.Tk()
root.geometry('1220x820')
root.title('PDF Paragraph Tagger - All Options (AUTO entities, headings, nesting)')
root.title("Para")
# Left pane: controls + canvas + listbox
left = tk.Frame(root)
left.pack(side='left', fill='y', padx=6, pady=6)

controls = tk.Frame(left)
controls.pack(side='top', pady=4)

open_btn = tk.Button(controls, text='Open PDF', command=lambda: open_pdf(root, canvas, html_text, listbox))
open_btn.grid(row=0, column=0, padx=3)
prev_btn = tk.Button(controls, text='Prev', command=lambda: prev_page(root, canvas, html_text, listbox))
prev_btn.grid(row=0, column=1, padx=3)
next_btn = tk.Button(controls, text='Next', command=lambda: next_page(root, canvas, html_text, listbox))
next_btn.grid(row=0, column=2, padx=3)
auto_btn = tk.Button(controls, text='Auto-Detect', command=lambda: auto_detect(state.page_index, canvas, html_text, listbox))
auto_btn.grid(row=0, column=3, padx=3)
export_btn = tk.Button(controls, text='Export JSON', command=export_json)
export_btn.grid(row=0, column=4, padx=3)
import_btn = tk.Button(controls, text='Import JSON', command=lambda: import_json(root, canvas, html_text, listbox))
import_btn.grid(row=0, column=5, padx=3)
save_html_btn = tk.Button(controls, text='Save HTML (wrapped)', command=lambda: save_html_to_file(html_text))
save_html_btn.grid(row=0, column=6, padx=3)
save_all_btn = tk.Button(controls, text='Save All Pages (wrapped)', command=lambda: save_all_pages_html(html_text))
save_all_btn.grid(row=0, column=7, padx=3)
sync_btn = tk.Button(controls, text='Sync HTML->PDF', command=lambda: sync_html_to_pdf(html_text, canvas))
sync_btn.grid(row=0, column=8, padx=3)
undo_btn = tk.Button(controls, text='Undo', command=lambda: do_undo(root, canvas, html_text, listbox))
undo_btn.grid(row=0, column=9, padx=3)
redo_btn = tk.Button(controls, text='Redo', command=lambda: do_redo(root, canvas, html_text, listbox))
redo_btn.grid(row=0, column=10, padx=3)



# new controls row: AUTO toggle, infer headings, nesting toggle
row2 = tk.Frame(left)
row2.pack(side='top', pady=6)
auto_toggle_btn = tk.Button(row2, text=f"AUTO entities: {'ON' if AUTO_ENTITIES else 'OFF'}",
                            command=lambda: toggle_auto_entities(auto_toggle_btn, root, canvas, html_text, listbox))
auto_toggle_btn.pack(side='left', padx=3)
infer_btn = tk.Button(row2, text='Infer Headings (page)', command=lambda: infer_headings_for_page(root, canvas, html_text, listbox))
infer_btn.pack(side='left', padx=3)
nest_btn = tk.Button(row2, text=f"Nest: {'b>i' if NESTING_PREF=='b_outside_i' else 'i>b'}",
                     command=lambda: toggle_nesting(nest_btn, root, canvas, html_text, listbox))
nest_btn.pack(side='left', padx=3)

instr = tk.Label(left, text='Drag to create rectangle. Ctrl+Click word to split. Select region -> press keys (h,j,k,l,f,t,p,n,b,m) to change tag. Ctrl+Z / Ctrl+Y undo/redo.')
instr.pack(pady=6)

canvas = tk.Canvas(left, bg='grey')
canvas.pack()

listbox_frame = tk.Frame(left)
listbox_frame.pack(fill='x', pady=6)
listbox_label = tk.Label(listbox_frame, text='Regions on page:')
listbox_label.pack(anchor='w')
listbox = tk.Listbox(listbox_frame, height=10)
listbox.pack(fill='x')

# Right pane: HTML editor
right = tk.Frame(root)
right.pack(side='left', fill='both', expand=True, padx=6, pady=6)
html_label = tk.Label(right, text='HTML preview / editor:')
html_label.pack(anchor='w')
html_text = tk.Text(right, wrap='word')
html_text.pack(fill='both', expand=True)
html_text.insert(tk.END, '<!-- Open a PDF to start -->')
html_text.config(state='disabled')

# ---------- Bindings ----------
canvas.bind('<ButtonPress-1>', lambda e: canvas_mouse_down(e, canvas))
canvas.bind('<B1-Motion>', lambda e: canvas_mouse_drag(e, canvas))
canvas.bind('<ButtonRelease-1>', lambda e: canvas_mouse_up(e, canvas, html_text, listbox))
canvas.bind('<Button-3>', lambda e: canvas_right_click(e, canvas, listbox, html_text))
canvas.bind('<Control-Button-1>', lambda e: canvas_click_word(e, canvas, html_text, listbox))

listbox.bind('<<ListboxSelect>>', lambda e: listbox_select(e, canvas, html_text))

html_text.bind('<Return>', lambda e: (split_region_at_html_cursor(html_text, canvas, listbox), 'break'))

root.bind_all('<Control-z>', lambda e: do_undo(root, canvas, html_text, listbox))
root.bind_all('<Control-y>', lambda e: do_redo(root, canvas, html_text, listbox))
root.bind_all('<Key>', lambda e: key_tag_handler(e, canvas, html_text, listbox))

# Arrow keys
# Left arrow -> previous page, Right arrow -> next page
root.bind_all('<Left>', lambda e: prev_page(root, canvas, html_text, listbox))
root.bind_all('<Right>', lambda e: next_page(root, canvas, html_text, listbox))

# Context menu buttons (optional): delete selected region
del_btn = tk.Button(left, text='Delete Region', command=lambda: delete_region(listbox, canvas, html_text))
del_btn.pack(pady=6)

# Start main loop
root.mainloop()
