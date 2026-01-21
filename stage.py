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

def words_in_bbox(words, bbox):
    x0, y0, x1, y1 = bbox
    inside = [w for w in words if w[0] >= x0-0.1 and w[2] <= x1+0.1 and w[1] >= y0-0.1 and w[3] <= y1+0.1]
    return sorted(inside, key=lambda w: (w[1], w[0]))

# ---------- Main App ----------
class PDFParaEditor:
    def __init__(self, master):
        self.master = master
        master.title("PDF Paragraph Editor")

        # document state
        self.doc = None
        self.current_page = 0
        self.paragraphs_by_page = {}
        self.selected_indices = set()
        self.undo_stack = []
        self.last_right_click = None
        self.split_marker = None

        # image & scaling
        self.page_pil = None            # PIL Image at original pix size
        self.page_tk = None             # Tk PhotoImage used on canvas
        self.scale = 1.0                # current scale factor (1.0 = original pix size)
        self.min_scale = 0.1
        self.max_scale = 5.0

        # ---------- UI ----------
        top_bar = tk.Frame(master, bg="#ddd")
        top_bar.pack(side="top", fill="x")

        tk.Button(top_bar, text="Open PDF", command=self.open_pdf).pack(side="left", padx=5, pady=5)
        tk.Button(top_bar, text="Export HTML", command=self.export_html).pack(side="right", padx=5)
        tk.Button(top_bar, text="Save paratag.json", command=self.save_paratag).pack(side="right", padx=5)
        tk.Button(top_bar, text="Save PDF", command=self.save_pdf).pack(side="right", padx=5)

        self.page_label = tk.Label(top_bar, text="Page 0 / 0", bg="#ddd")
        self.page_label.pack(side="left", padx=10)

        # goto
        self.goto_entry = tk.Entry(top_bar, width=5)
        self.goto_entry.pack(side="left", padx=2)
        self.goto_entry.bind("<Return>", self.goto_page_event)
        self.goto_btn = tk.Button(top_bar, text="Go", command=self.goto_page_button)
        self.goto_btn.pack(side="left", padx=2)

        # zoom controls
        tk.Button(top_bar, text="Fit Width", command=self.fit_width).pack(side="left", padx=6)
        tk.Button(top_bar, text="Zoom -", command=lambda: self.change_scale(0.9)).pack(side="left")
        tk.Button(top_bar, text="Zoom +", command=lambda: self.change_scale(1.1)).pack(side="left")

        main = tk.PanedWindow(master, sashwidth=6, sashrelief="raised")
        main.pack(fill="both", expand=True)

        # Left canvas frame with scrollbars
        left_frame = tk.Frame(main)
        left_frame.pack(fill="both", expand=True)
        self.hbar = tk.Scrollbar(left_frame, orient=tk.HORIZONTAL)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.vbar = tk.Scrollbar(left_frame, orient=tk.VERTICAL)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = tk.Canvas(left_frame, bg="#666",
                                xscrollcommand=self.hbar.set,
                                yscrollcommand=self.vbar.set)
        self.canvas.pack(fill="both", expand=True)
        self.hbar.config(command=self.canvas.xview)
        self.vbar.config(command=self.canvas.yview)
        main.add(left_frame, minsize=400)

        # Right HTML preview
        right_frame = tk.Frame(main)
        self.html_preview = tk.Text(right_frame, wrap="word", font=("Consolas", 10))
        self.html_preview.pack(fill="both", expand=True)
        main.add(right_frame, minsize=400)

        # Bindings
        self.canvas.bind("<Button-1>", self.on_canvas_left_click)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<Configure>", self.on_canvas_configure)  # to re-fit if needed
        # mouse wheel for scroll / zoom
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)      # Windows/mac wheel
        self.canvas.bind_all("<Button-4>", self.on_mousewheel)        # Linux wheel up
        self.canvas.bind_all("<Button-5>", self.on_mousewheel)        # Linux wheel down

        master.bind("<Control-z>", self.on_undo)
        master.bind("<Right>", lambda e: self.next_page())
        master.bind("<Left>", lambda e: self.prev_page())
        master.bind("<Control-Up>", self.ctrl_up)
        master.bind("<Control-Down>", self.ctrl_down)

        # store rects for canvas elements so we can update when scaling
        self.canvas_image_id = None
        self.canvas_rects = []
        self.canvas_labels = []

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
            for idx, b in enumerate(blocks):
                x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                w_in = words_in_bbox(words, (x0, y0, x1, y1))
                paras.append({'bbox': (x0, y0, x1, y1), 'text': text.strip(), 'words': w_in, 'number': idx+1})
            self.paragraphs_by_page[pno] = paras
        self.scale = 1.0
        self.show_page()

    # ---------- Show Page ----------
    def show_page(self):
        if not self.doc:
            return
        page = self.doc.load_page(self.current_page)
        pix = page.get_pixmap()
        # store original PIL image (RGB)
        self.page_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # apply current scale to create the displayed image
        display_w = max(1, int(self.page_pil.width * self.scale))
        display_h = max(1, int(self.page_pil.height * self.scale))
        resized = self.page_pil.resize((display_w, display_h), Image.LANCZOS)
        self.page_tk = ImageTk.PhotoImage(resized)

        # clear canvas and create image
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, image=self.page_tk, anchor="nw")

        # set scrollregion to full image size
        self.canvas.config(scrollregion=(0, 0, display_w, display_h))

        # draw rectangles and labels scaled
        self.canvas_rects = []
        self.canvas_labels = []
        paras = self.paragraphs_by_page.get(self.current_page, [])
        for idx, para in enumerate(paras):
            x0, y0, x1, y1 = para['bbox']
            sx0, sy0, sx1, sy1 = (x0*self.scale, y0*self.scale, x1*self.scale, y1*self.scale)
            rect = self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline="red", width=2, tags=("para_rect", f"p{idx}"))
            label = self.canvas.create_text(sx0+4, sy0+2, text=f"P{para['number']}", anchor="nw", fill="blue", font=("Arial",10,"bold"), tags=("para_label", f"p{idx}"))
            self.canvas_rects.append(rect)
            self.canvas_labels.append(label)

        # re-draw selection & marker
        self.redraw_selection()
        self.update_html_preview()
        self.page_label.config(text=f"Page {self.current_page+1} / {len(self.doc)}")

        # if split marker exists and belongs to this page, redraw it scaled
        if self.split_marker:
            try:
                self.canvas.delete(self.split_marker)
            except:
                pass
            self.split_marker = None
        if self.last_right_click and self.last_right_click.get('page') == self.current_page:
            lx = self.last_right_click['x'] * self.scale
            ly = self.last_right_click['y'] * self.scale
            r = 4
            self.split_marker = self.canvas.create_oval(lx-r, ly-r, lx+r, ly+r, fill="yellow")

    # ---------- Update HTML Preview ----------
    def update_html_preview(self):
        self.html_preview.delete("1.0","end")
        paras = self.paragraphs_by_page.get(self.current_page, [])
        for para in paras:
            self.html_preview.insert("end", f"<p id='p{para['number']}'>{para['text']}</p>\n")

    # ---------- Map event coords back to original PDF coordinates ----------
    def canvas_to_pdf_coords(self, canvas_x, canvas_y):
        # account for scrolling offset (canvas coords include scroll)
        # canvas.canvasx and canvasy map screen coords to canvas coords — use those
        cx = self.canvas.canvasx(canvas_x)
        cy = self.canvas.canvasy(canvas_y)
        # map by scale
        if self.scale != 0:
            return (cx / self.scale, cy / self.scale)
        return (cx, cy)

    # ---------- Selection ----------
    def on_canvas_left_click(self, event):
        if not self.doc:
            return
        # map click to pdf coords
        px, py = self.canvas_to_pdf_coords(event.x, event.y)
        paras = self.paragraphs_by_page.get(self.current_page, [])
        clicked_idx = None
        for idx, para in enumerate(paras):
            if bbox_contains(para['bbox'], px, py):
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
        # update rect outlines according to selection, keep positions scaled
        for idx, rect in enumerate(self.canvas_rects):
            color = "blue" if idx in self.selected_indices else "red"
            width = 3 if idx in self.selected_indices else 2
            try:
                self.canvas.itemconfig(rect, outline=color, width=width)
            except:
                pass

    # ---------- Right-click for split ----------
    def on_canvas_right_click(self, event):
        if not self.doc:
            return
        # map to pdf coords
        px, py = self.canvas_to_pdf_coords(event.x, event.y)
        paras = self.paragraphs_by_page.get(self.current_page, [])
        clicked_idx = None
        for idx, para in enumerate(paras):
            if bbox_contains(para['bbox'], px, py):
                clicked_idx = idx
                break
        if clicked_idx is None:
            messagebox.showinfo("Split", "Right-click inside paragraph to set split point.")
            return
        # store click in pdf coords for accurate behavior across scales
        self.last_right_click = {'page': self.current_page, 'para_index': clicked_idx, 'x': px, 'y': py}
        # draw marker scaled
        r = 4
        if self.split_marker:
            try: self.canvas.delete(self.split_marker)
            except: pass
        sx, sy = px*self.scale, py*self.scale
        self.split_marker = self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill="yellow")

    # ---------- Swap block positions (move up/down) ----------
    def push_undo(self):
        # store shallow copy of structure (deepcopy paragraphs_by_page to be safe)
        self.undo_stack.append(copy.deepcopy(self.paragraphs_by_page))

    def ctrl_up(self, event):
        paras = self.paragraphs_by_page.get(self.current_page, [])
        if len(self.selected_indices) != 1:
            return
        idx = next(iter(self.selected_indices))
        if idx == 0:
            return
        self.push_undo()
        paras[idx - 1], paras[idx] = paras[idx], paras[idx - 1]
        for i, p in enumerate(paras): p['number'] = i + 1
        self.selected_indices = {idx - 1}
        self.show_page()

    def ctrl_down(self, event):
        paras = self.paragraphs_by_page.get(self.current_page, [])
        if len(self.selected_indices) != 1:
            return
        idx = next(iter(self.selected_indices))
        if idx >= len(paras) - 1:
            return
        self.push_undo()
        paras[idx], paras[idx + 1] = paras[idx + 1], paras[idx]
        for i, p in enumerate(paras): p['number'] = i + 1
        self.selected_indices = {idx + 1}
        self.show_page()

    # ---------- Navigation ----------
    def next_page(self):
        if self.doc and self.current_page < len(self.doc)-1:
            self.current_page += 1
            self.show_page()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.show_page()

    def goto_page_event(self, event): self.goto_page()
    def goto_page_button(self): self.goto_page()
    def goto_page(self):
        if not self.doc: return
        page_str = self.goto_entry.get().strip()
        if not page_str.isdigit(): return
        page_no = int(page_str)
        if page_no < 1 or page_no > len(self.doc): return
        self.current_page = page_no - 1
        self.show_page()

    # ---------- Save JSON ----------
    def save_paratag(self):
        if not self.paragraphs_by_page: return
        out = filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")])
        if not out: return
        data = {}
        for pno,paras in self.paragraphs_by_page.items():
            lst = []
            for para in paras:
                x0,y0,x1,y1 = para['bbox']
                lst.append({'x1':x0,'y1':y0,'x2':x1,'y2':y1,'text':para['text'], 'number': para['number']})
            data[f"page_{pno+1}"] = lst
        with open(out,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False)
        messagebox.showinfo("Saved","Paragraph tags saved.")

    # ---------- Export HTML ----------
    def export_html(self):
        if not self.paragraphs_by_page: return
        out = filedialog.asksaveasfilename(defaultextension=".html",filetypes=[("HTML","*.html")])
        if not out: return
        lines = ["<!doctype html>","<html><head><meta charset='utf-8'></head><body>"]
        for pno,paras in sorted(self.paragraphs_by_page.items()):
            paras_sorted = sorted(paras, key=lambda p: p['number'])
            for para in paras_sorted:
                txt = para['text'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                lines.append(f"<p id='p{para['number']}'>{txt}</p>")
        lines.append("</body></html>")
        with open(out,"w",encoding="utf-8") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Exported","HTML exported.")

    # ---------- Save PDF ----------
    def save_pdf(self):
        if not self.doc:
            messagebox.showwarning("Save PDF", "No PDF loaded.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf",filetypes=[("PDF files", "*.pdf")],title="Save PDF As")
        if not out:
            return
        try:
            self.doc.save(out, incremental=False, encryption=fitz.PDF_ENCRYPT_KEEP)
            messagebox.showinfo("Saved", f"PDF saved successfully to:\n{out}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save PDF:\n{e}")

    # ---------- Undo ----------
    def on_undo(self, event=None):
        if not self.undo_stack:
            return
        self.paragraphs_by_page = self.undo_stack.pop()
        self.show_page()

    # ---------- Zoom / Fit / Scroll handling ----------
    def change_scale(self, factor, center=None):
        # factor multiplies current scale
        new_scale = max(self.min_scale, min(self.max_scale, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-6:
            return
        # optionally keep center point stable
        if center is None:
            # use canvas center in canvas coords
            center = (self.canvas.winfo_width()//2, self.canvas.winfo_height()//2)
        # map center to PDF coords before scale
        pdf_cx, pdf_cy = self.canvas_to_pdf_coords(center[0], center[1])
        self.scale = new_scale
        self.show_page()
        # after redraw, scroll so the pdf_cx,pdf_cy remains at center
        # map pdf coords to canvas coords after scaling:
        new_canvas_cx = pdf_cx * self.scale
        new_canvas_cy = pdf_cy * self.scale
        # compute top-left canvasx/canvasy to position so that new_canvas_cx is centered
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        tx = new_canvas_cx - canvas_width//2
        ty = new_canvas_cy - canvas_height//2
        self.canvas.xview_moveto(max(0, tx) / max(1, self.canvas.bbox("all")[2]))
        self.canvas.yview_moveto(max(0, ty) / max(1, self.canvas.bbox("all")[3]))

    def fit_width(self):
        if not self.page_pil:
            return
        canvas_w = self.canvas.winfo_width()
        if canvas_w <= 1:
            # canvas not yet laid out; try later
            self.master.after(100, self.fit_width)
            return
        new_scale = canvas_w / self.page_pil.width
        # clamp
        new_scale = max(self.min_scale, min(self.max_scale, new_scale))
        self.scale = new_scale
        self.show_page()
        # reset scroll to left/top
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def on_canvas_configure(self, event):
        # optionally keep fit-to-width behavior? we won't auto-fit every resize,
        # but if scale was previously set by fit_width and we want to maintain,
        # user can press Fit Width again. For now, just ensure scrollregion is OK.
        if self.page_tk:
            self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def on_mousewheel(self, event):
        # Ctrl + wheel => zoom
        ctrl = (event.state & 0x0004) != 0
        if ctrl:
            # get mouse pos relative to canvas to use as zoom center
            mx, my = event.x, event.y
            delta = 0
            if hasattr(event, 'delta'):
                delta = event.delta
            else:
                # button4/5 on some linux
                delta = 120 if event.num == 4 else -120
            if delta > 0:
                self.change_scale(1.1, center=(mx, my))
            else:
                self.change_scale(0.9, center=(mx, my))
        else:
            # regular scroll: move canvas
            # On Windows delta is multiples of 120
            move = 0
            if hasattr(event, 'delta'):
                move = -1 * int(event.delta/120)
            else:
                move = 1 if event.num == 5 else -1
            # shift key => horizontal
            if (event.state & 0x0001) != 0:  # Shift pressed
                self.canvas.xview_scroll(move, "units")
            else:
                self.canvas.yview_scroll(move, "units")

# ---------- Run ----------
if __name__=="__main__":
    root = tk.Tk()
    app = PDFParaEditor(root)
    root.geometry("1200x800")
    root.title("Stage")
    root.mainloop()
