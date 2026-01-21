import fitz
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import copy
import math
import json

# ---------- Helper functions ----------
def bbox_contains(bbox, x, y):
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1

def bbox_merge(b1, b2):
    x0 = min(b1[0], b2[0])
    y0 = min(b1[1], b2[1])
    x1 = max(b1[2], b2[2])
    y1 = max(b1[3], b2[3])
    return (x0, y0, x1, y1)

def words_in_bbox(words, bbox):
    x0, y0, x1, y1 = bbox
    inside = [w for w in words if w[0] >= x0-0.1 and w[2] <= x1+0.1 and w[1] >= y0-0.1 and w[3] <= y1+0.1]
    inside_sorted = sorted(inside, key=lambda w: (w[1], w[0]))
    return inside_sorted

def nearest_word_index(words_list, click_x, click_y):
    best_i = None
    best_d = None
    for i, w in enumerate(words_list):
        cx = (w[0] + w[2]) / 2.0
        cy = (w[1] + w[3]) / 2.0
        d = math.hypot(cx - click_x, cy - click_y)
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    return best_i

# ---------- Main App ----------
class PDFParaEditor:
    def __init__(self, master):
        self.master = master
        master.title("PDF Paragraph Editor")

        self.doc = None
        self.current_page = 0
        self.paragraphs_by_page = {}
        self.selected_indices = set()
        self.undo_stack = []
        self.last_right_click = None   # stored in UN-SCALED (original PDF) coords
        self.split_marker = None
        self.page_pix_image = None

        # Zoom (scale)
        self.zoom = 0.6  # default 60% size; change as needed

        # ---------- UI ----------
        top_bar = tk.Frame(master, bg="#ddd")
        top_bar.pack(side="top", fill="x")
        tk.Button(top_bar, text="Open PDF", command=self.open_pdf).pack(side="left", padx=5, pady=5)
        tk.Button(top_bar, text="Export HTML", command=self.export_html).pack(side="right", padx=5)
        tk.Button(top_bar, text="Save paratag.json", command=self.save_paratag).pack(side="right", padx=5)
        self.page_label = tk.Label(top_bar, text="Page 0 / 0", bg="#ddd")
        self.page_label.pack(side="left", padx=10)

        # Zoom controls
        tk.Button(top_bar, text="Zoom −", command=self.zoom_out).pack(side="left", padx=4)
        tk.Button(top_bar, text="Zoom +", command=self.zoom_in).pack(side="left")
        tk.Button(top_bar, text="Reset Zoom", command=self.zoom_reset).pack(side="left", padx=4)
        self.zoom_label = tk.Label(top_bar, text=f"{int(self.zoom*100)}%", bg="#ddd")
        self.zoom_label.pack(side="left", padx=6)

        top_bar2 = tk.Frame(master, bg="#ddd")
        top_bar2.pack(side="top", fill="x")
        tk.Button(top_bar2, text="Save PDF", command=self.save_pdf).pack(side="right", padx=5, pady=5)

        main = tk.PanedWindow(master, sashwidth=6, sashrelief="raised")
        main.pack(fill="both", expand=True)

        # Left canvas with scrollbars
        left_frame = tk.Frame(main)
        self.canvas = tk.Canvas(left_frame, bg="#333")
        self.hbar = tk.Scrollbar(left_frame, orient="horizontal", command=self.canvas.xview)
        self.vbar = tk.Scrollbar(left_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.config(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.hbar.pack(side="bottom", fill="x")
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True, side="left")
        main.add(left_frame, minsize=200)

        # Right HTML preview
        right_frame = tk.Frame(main)
        self.html_preview = tk.Text(right_frame, wrap="word", font=("Consolas", 11))
        self.html_preview.pack(fill="both", expand=True)
        main.add(right_frame, minsize=200)

        # Bindings
        self.canvas.bind("<Button-1>", self.on_canvas_left_click)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        master.bind("<Return>", self.on_split_horizontal)
        master.bind("v", self.on_split_vertical)
        master.bind("V", self.on_split_vertical)
        master.bind("p", self.on_merge)
        master.bind("P", self.on_merge)
        master.bind("<Control-z>", self.on_undo)
        master.bind("<Right>", lambda e: self.next_page())
        master.bind("<Left>", lambda e: self.prev_page())

        # Go-to-page input in the second top bar
        self.goto_entry = tk.Entry(top_bar2, width=5)
        self.goto_entry.pack(side="left", padx=2)
        self.goto_entry.bind("<Return>", self.goto_page_event)

        self.goto_btn = tk.Button(top_bar2, text="•", command=self.goto_page_button)
        self.goto_btn.pack(side="left")

        # internal storage for drawn rect ids
        self.canvas_rects = []

    # ---------- Open PDF ----------
    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            self.doc = fitz.open(path)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open PDF: {e}")
            return

        self.paragraphs_by_page.clear()
        self.current_page = 0
        for pno in range(len(self.doc)):
            page = self.doc.load_page(pno)
            blocks = page.get_text("blocks")
            words = page.get_text("words")
            paras = []
            for b in blocks:
                x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                w_in = words_in_bbox(words, (x0, y0, x1, y1))
                paras.append({'bbox': (x0, y0, x1, y1), 'text': text.strip(), 'words': w_in})
            self.paragraphs_by_page[pno] = paras
        self.show_page()

    # ---------- Show Page ----------
    def show_page(self):
        if not self.doc:
            return
        page = self.doc.load_page(self.current_page)

        # render with zoom (scale) matrix
        zoom_matrix = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=zoom_matrix)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.page_pix_image = ImageTk.PhotoImage(img)

        # clear canvas and set scrollregion
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.create_image(0, 0, image=self.page_pix_image, anchor="nw")

        # draw paragraph boxes (scale bbox coordinates for display)
        self.canvas_rects = []
        paras = self.paragraphs_by_page.get(self.current_page, [])
        for idx, para in enumerate(paras):
            x0, y0, x1, y1 = para['bbox']

            # scale coordinates for display
            sx0, sy0 = x0 * self.zoom, y0 * self.zoom
            sx1, sy1 = x1 * self.zoom, y1 * self.zoom

            rect = self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline="red", width=2)
            label = self.canvas.create_text(sx0+4, sy0+2, text=f"P{idx+1}", anchor="nw", fill="white", font=("Arial", 10, "bold"))
            self.canvas_rects.append(rect)

        self.redraw_selection()
        self.update_html_preview()
        self.page_label.config(text=f"Page {self.current_page+1} / {len(self.doc)}")
        self.zoom_label.config(text=f"{int(self.zoom*100)}%")

    # ---------- HTML Preview ----------
    def update_html_preview(self):
        self.html_preview.delete("1.0", "end")
        paras = self.paragraphs_by_page.get(self.current_page, [])
        for idx, para in enumerate(paras):
            self.html_preview.insert("end", f"<p id='p{idx+1}'>{para['text']}</p>\n")

    # ---------- Selection ----------
    def on_canvas_left_click(self, event):
        if not self.doc:
            return

        # convert canvas (scaled) coords to PDF (original) coords
        ux = self.canvas.canvasx(event.x) / self.zoom
        uy = self.canvas.canvasy(event.y) / self.zoom

        paras = self.paragraphs_by_page.get(self.current_page, [])
        clicked_idx = None
        for idx, para in enumerate(paras):
            if bbox_contains(para['bbox'], ux, uy):
                clicked_idx = idx
                break
        if clicked_idx is None:
            return

        ctrl = (event.state & 0x0004) != 0
        if ctrl:
            if clicked_idx in self.selected_indices:
                self.selected_indices.remove(clicked_idx)
            else:
                self.selected_indices.add(clicked_idx)
        else:
            self.selected_indices = {clicked_idx}
        self.redraw_selection()
        self.update_html_preview()

    def redraw_selection(self):
        for idx, rect in enumerate(self.canvas_rects):
            color = "blue" if idx in self.selected_indices else "red"
            self.canvas.itemconfig(rect, outline=color, width=3 if idx in self.selected_indices else 2)

    # ---------- Right-click for split ----------
    def on_canvas_right_click(self, event):
        if not self.doc:
            return

        # convert canvas coords to PDF coords (unscaled)
        ux = self.canvas.canvasx(event.x) / self.zoom
        uy = self.canvas.canvasy(event.y) / self.zoom

        paras = self.paragraphs_by_page.get(self.current_page, [])
        clicked_idx = None
        for idx, para in enumerate(paras):
            if bbox_contains(para['bbox'], ux, uy):
                clicked_idx = idx
                break
        if clicked_idx is None:
            messagebox.showinfo("Split", "Right-click inside paragraph to set split point.")
            return

        # store unscaled coords for later splitting
        self.last_right_click = {'page': self.current_page, 'para_index': clicked_idx, 'x': ux, 'y': uy}

        # show marker on canvas at scaled coords
        sx = ux * self.zoom
        sy = uy * self.zoom
        r = 4
        if self.split_marker:
            try:
                self.canvas.delete(self.split_marker)
            except Exception:
                pass
        self.split_marker = self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill="yellow", outline="black")

    # ---------- Split Horizontal ----------
    def on_split_horizontal(self, event):
        if not self.last_right_click: return
        if self.last_right_click['page'] != self.current_page:
            messagebox.showwarning("Split", "Split point is on another page.")
            return

        pi = self.last_right_click['para_index']
        paras = self.paragraphs_by_page[self.current_page]
        if pi < 0 or pi >= len(paras):
            return
        para = paras[pi]
        words = para.get('words', [])
        if not words:
            return

        # use last_right_click unscaled coords for nearest word search
        idx_word = nearest_word_index(words, self.last_right_click['x'], self.last_right_click['y'])
        if idx_word is None:
            return

        self.push_undo()

        left_words = words[:idx_word+1]
        right_words = words[idx_word+1:]
        if not right_words:
            messagebox.showinfo("Split", "Split location produced empty right paragraph.")
            return
        left_text = " ".join(w[4] for w in left_words)
        right_text = " ".join(w[4] for w in right_words)
        lx0, ly0 = min(w[0] for w in left_words), min(w[1] for w in left_words)
        lx1, ly1 = max(w[2] for w in left_words), max(w[3] for w in left_words)
        rx0, ry0 = min(w[0] for w in right_words), min(w[1] for w in right_words)
        rx1, ry1 = max(w[2] for w in right_words), max(w[3] for w in right_words)
        paras.pop(pi)
        paras.insert(pi, {'bbox': (rx0, ry0, rx1, ry1), 'text': right_text, 'words': right_words})
        paras.insert(pi, {'bbox': (lx0, ly0, lx1, ly1), 'text': left_text, 'words': left_words})

        self.last_right_click = None
        if self.split_marker:
            try:
                self.canvas.delete(self.split_marker)
            except Exception:
                pass
            self.split_marker = None
        self.show_page()
        messagebox.showinfo("Split", f"P{pi+1} split horizontally.")

    # ---------- Split Vertical ----------
    def on_split_vertical(self, event):
        if not self.last_right_click: return
        if self.last_right_click['page'] != self.current_page:
            messagebox.showwarning("Split", "Split point is on another page.")
            return

        pi = self.last_right_click['para_index']
        paras = self.paragraphs_by_page[self.current_page]
        if pi < 0 or pi >= len(paras):
            return
        para = paras[pi]
        x0, y0, x1, y1 = para['bbox']
        mid_x = (x0 + x1) / 2
        # split words by x < mid_x
        words_left = [w for w in para.get('words', []) if (w[0] + w[2]) / 2 <= mid_x]
        words_right = [w for w in para.get('words', []) if (w[0] + w[2]) / 2 > mid_x]
        if not words_left or not words_right:
            messagebox.showinfo("Split", "Cannot split vertically (no words on one side).")
            return

        self.push_undo()
        left_text = " ".join(w[4] for w in words_left)
        right_text = " ".join(w[4] for w in words_right)
        lx0, ly0 = min(w[0] for w in words_left), min(w[1] for w in words_left)
        lx1, ly1 = max(w[2] for w in words_left), max(w[3] for w in words_left)
        rx0, ry0 = min(w[0] for w in words_right), min(w[1] for w in words_right)
        rx1, ry1 = max(w[2] for w in words_right), max(w[3] for w in words_right)
        paras.pop(pi)
        paras.insert(pi, {'bbox': (rx0, ry0, rx1, ry1), 'text': right_text, 'words': words_right})
        paras.insert(pi, {'bbox': (lx0, ly0, lx1, ly1), 'text': left_text, 'words': words_left})
        self.show_page()
        messagebox.showinfo("Split", f"P{pi+1} split vertically.")

    # ---------- Merge ----------
    def on_merge(self, event):
        if len(self.selected_indices) < 2:
            messagebox.showinfo("Merge", "Select 2+ adjacent paragraphs (Ctrl+Click).")
            return
        paras = self.paragraphs_by_page[self.current_page]
        sel = sorted(self.selected_indices)
        for a, b in zip(sel, sel[1:]):
            if b != a + 1:
                messagebox.showwarning("Merge", "Selected must be adjacent.")
                return
        self.push_undo()
        first = sel[0]
        merged_text = []
        merged_words = []
        merged_bbox = paras[first]['bbox']
        # pop from end to keep indices stable
        for idx in reversed(sel):
            p = paras.pop(idx)
            merged_text.insert(0, p['text'])
            merged_words = p.get('words', []) + merged_words
            merged_bbox = bbox_merge(merged_bbox, p['bbox'])
        paras.insert(first, {'bbox': merged_bbox, 'text': "\n".join(merged_text), 'words': merged_words})
        self.selected_indices = {first}
        self.show_page()
        messagebox.showinfo("Merge", f"Paragraphs merged into P{first+1}.")

    # ---------- Undo ----------
    def push_undo(self):
        # store deep copy of paragraphs_by_page
        self.undo_stack.append(copy.deepcopy(self.paragraphs_by_page))

    def on_undo(self, event):
        if not self.undo_stack:
            return
        self.paragraphs_by_page = self.undo_stack.pop()
        self.show_page()

    # ---------- Page navigation ----------
    def next_page(self):
        if not self.doc:
            return
        if self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self.show_page()

    def prev_page(self):
        if not self.doc:
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.show_page()

    # ------- go to ----
    def goto_page_event(self, event):
        self.goto_page()

    def goto_page_button(self):
        self.goto_page()

    def goto_page(self):
        if not self.doc:
            return
        page_str = self.goto_entry.get().strip()
        if not page_str.isdigit():
            messagebox.showwarning("Go to Page", "Please enter a valid page number.")
            return
        page_no = int(page_str)
        if page_no < 1 or page_no > len(self.doc):
            messagebox.showwarning("Go to Page", f"Page number must be between 1 and {len(self.doc)}.")
            return
        self.current_page = page_no - 1
        self.show_page()

    # ---------- Save paratag ----------
    def save_paratag(self):
        if not self.paragraphs_by_page:
            return
        out = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not out:
            return
        data = {}
        for pno, paras in self.paragraphs_by_page.items():
            lst = []
            for para in paras:
                x0, y0, x1, y1 = para['bbox']
                lst.append({'x1': x0, 'y1': y0, 'x2': x1, 'y2': y1, 'text': para['text']})
            data[f"page_{pno+1}"] = lst
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("Saved", "Paragraph tags saved.")

    # ---------- Export HTML ----------
    def export_html(self):
        if not self.paragraphs_by_page:
            return
        out = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if not out:
            return
        lines = ["<!doctype html>", "<html><head><meta charset='utf-8'></head><body>"]
        for pno, paras in sorted(self.paragraphs_by_page.items()):
            for para in paras:
                txt = para['text'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"<p>{txt}</p>")
        lines.append("</body></html>")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Exported", "HTML exported.")

    # ---------- Save updated PDF ----------
    def save_pdf(self):
        if not self.doc:
            messagebox.showwarning("Save PDF", "No PDF loaded.")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            title="Save PDF As"
        )
        if not save_path:
            return

        try:
            # Just save a visual copy of the current PDF
            self.doc.save(save_path)
            messagebox.showinfo("Saved", f"PDF saved successfully to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save PDF:\n{e}")

    # ---------- Zoom controls ----------
    def zoom_in(self):
        # increase zoom by 20%
        self.zoom = min(3.0, self.zoom * 1.2)
        self.show_page()

    def zoom_out(self):
        # decrease zoom by ~17%
        self.zoom = max(0.1, self.zoom / 1.2)
        self.show_page()

    def zoom_reset(self):
        self.zoom = 0.6
        self.show_page()

# ---------- Run ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = PDFParaEditor(root)
    root.geometry("1200x800")
    root.title("Zone")
    root.mainloop()
