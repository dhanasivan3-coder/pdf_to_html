import fitz  # PyMuPDF
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import copy

class PDFHTMLSyncEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF to HTML Sync Editor - Zoom-to-Fit + Delete Modes + Undo + Keyboard Nav + Page Jump")
        self.doc = None
        self.page = None
        self.page_image = None
        self.blocks = []                # original block coords (PDF space)
        self.block_visual_rects = []    # scaled block coords for display/selection
        self.deleted_blocks = {}
        self.history = []
        self.block_rect_ids = []
        self.current_page = 0

        self.selected_block = None
        self.drag_start = None
        self.drag_rect_id = None
        self.drag_area = None

        self.scale = 1.0
        self.last_canvas_size = (0, 0)

        # ===== BUTTON BAR =====
        top_bar = tk.Frame(root, bg="#ececec")
        top_bar.pack(fill="x", side="top")

        tk.Button(top_bar, text="Open PDF", command=self.open_pdf).pack(side="left", padx=5, pady=5)
        tk.Button(top_bar, text="Prev Page", command=self.prev_page).pack(side="left", padx=5)
        tk.Button(top_bar, text="Next Page", command=self.next_page).pack(side="left", padx=5)
        tk.Button(top_bar, text="Export HTML", command=self.export_html).pack(side="right", padx=5, pady=5)
        tk.Button(top_bar, text="Save PDF", command=self.save_pdf).pack(side="right", padx=5, pady=5)

        # === PAGE NUMBER LABEL ===
        self.page_label = tk.Label(top_bar, text="Page: 0 / 0", bg="#ececec", font=("Arial", 10, "bold"), cursor="hand2")
        self.page_label.pack(side="left", padx=15)
        self.page_label.bind("<Button-1>", self.jump_to_page)  # click to jump

        # ===== MAIN SPLIT AREA =====
        main_frame = tk.PanedWindow(root, sashwidth=6, sashrelief="raised")
        main_frame.pack(fill="both", expand=True)

        # LEFT SIDE (PDF)
        self.left_frame = tk.Frame(main_frame, bg="lightgray")
        self.canvas = tk.Canvas(self.left_frame, bg="gray")
        self.canvas.pack(fill="both", expand=True)

        # Bind events
        self.canvas.bind("<Button-1>", self.select_block)
        self.canvas.bind("<ButtonPress-3>", self.start_drag)
        self.canvas.bind("<B3-Motion>", self.dragging)
        self.canvas.bind("<ButtonRelease-3>", self.end_drag)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

        self.root.bind("<Delete>", self.delete_action)
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Right>", lambda e: self.next_page())
        self.root.bind("<Left>", lambda e: self.prev_page())

        # RIGHT SIDE (HTML)
        self.right_frame = tk.Frame(main_frame)
        self.html_text = tk.Text(self.right_frame, wrap="word", font=("Consolas", 10))
        self.html_text.pack(fill="both", expand=True)

        main_frame.add(self.left_frame, minsize=400)
        main_frame.add(self.right_frame, minsize=400)

    # ===== OPEN PDF =====
    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        self.doc = fitz.open(path)
        self.deleted_blocks.clear()
        self.history.clear()
        self.current_page = 0
        self.show_page()

    # ===== HANDLE CANVAS RESIZE =====
    def on_canvas_configure(self, event):
        # If canvas size changed significantly, redraw page to fit
        new_size = (event.width, event.height)
        if new_size != self.last_canvas_size:
            self.last_canvas_size = new_size
            # Redraw current page to recompute scale
            self.show_page()

    # ===== SHOW PAGE (zoom-to-fit) =====
    def show_page(self):
        if not self.doc:
            return
        self.page = self.doc.load_page(self.current_page)

        # get canvas size to compute scale-to-fit
        canvas_w = max(self.canvas.winfo_width(), 100)
        canvas_h = max(self.canvas.winfo_height(), 100)

        # original page size
        rect = self.page.mediabox
        page_w = rect.width
        page_h = rect.height

        # compute scale that fits entire page into canvas (with margin)
        margin = 16
        scale_x = (canvas_w - margin) / page_w
        scale_y = (canvas_h - margin) / page_h
        # choose the smaller scale so whole page is visible (zoom out if needed)
        self.scale = min(scale_x, scale_y, 1.0)
        if self.scale <= 0:
            self.scale = 1.0

        mat = fitz.Matrix(self.scale, self.scale)
        pix = self.page.get_pixmap(matrix=mat)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.page_image = ImageTk.PhotoImage(img)

        # Clear canvas and draw
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.page_image, anchor="nw")

        # Prepare blocks and scaled rectangles for interaction
        self.blocks = self.page.get_text("blocks")
        self.block_visual_rects.clear()
        self.block_rect_ids.clear()
        self.selected_block = None

        deleted = self.deleted_blocks.get(self.current_page, [])
        html = ""

        for i, b in enumerate(self.blocks):
            x0, y0, x1, y1, text, *_ = b
            sx0, sy0, sx1, sy1 = x0 * self.scale, y0 * self.scale, x1 * self.scale, y1 * self.scale
            self.block_visual_rects.append((sx0, sy0, sx1, sy1))

            if i in deleted:
                # draw cross using scaled coords
                self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline="gray", width=1, dash=(3,3))
                self.canvas.create_line(sx0, sy0, sx1, sy1, fill="red", width=2)
                self.canvas.create_line(sx0, sy1, sx1, sy0, fill="red", width=2)
            else:
                rect_id = self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline="red", width=1)
                self.block_rect_ids.append(rect_id)
                html += f"<p>{text.strip()}</p>\n"

        # Update HTML preview
        self.html_text.delete("1.0", "end")
        self.html_text.insert("1.0", html)

        total_pages = len(self.doc)
        self.page_label.config(text=f"Page: {self.current_page + 1} / {total_pages}")

        # Update scrollregion so entire scaled page is reachable if larger than canvas
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))

    # ===== CLICK PAGE LABEL TO JUMP =====
    def jump_to_page(self, event):
        if not self.doc:
            return
        total = len(self.doc)
        num = simpledialog.askinteger("Go to Page", f"Enter page number (1 - {total}):")
        if num is None:
            return
        if 1 <= num <= total:
            self.current_page = num - 1
            self.show_page()
        else:
            messagebox.showwarning("Invalid", "Page number out of range!")

    # ===== SELECT BLOCK =====
    def select_block(self, event):
        self.selected_block = None
        # remove previous selection highlight
        self.canvas.delete("selection")
        # event.x/y are in canvas coordinates (already scaled)
        ex, ey = event.x, event.y
        for i, (sx0, sy0, sx1, sy1) in enumerate(self.block_visual_rects):
            if sx0 <= ex <= sx1 and sy0 <= ey <= sy1:
                self.selected_block = i
                # highlight scaled rectangle
                self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline="blue", width=2, tags="selection")
                break

    # ===== DELETE KEY ACTION =====
    def delete_action(self, event):
        if not self.doc:
            return
        # push current state for undo
        self.history.append(copy.deepcopy(self.deleted_blocks))

        # Left click delete (selected block)
        if self.selected_block is not None:
            lst = self.deleted_blocks.setdefault(self.current_page, [])
            if self.selected_block not in lst:
                lst.append(self.selected_block)
            self.selected_block = None
            self.show_page()
            return

        # Right drag delete
        if self.drag_area:
            x0, y0, x1, y1 = self.drag_area
            to_delete = []
            for i, (sx0, sy0, sx1, sy1) in enumerate(self.block_visual_rects):
                # Check overlap with drag area (all in scaled canvas coords)
                if not (sx1 < x0 or sx0 > x1 or sy1 < y0 or sy0 > y1):
                    lst = self.deleted_blocks.setdefault(self.current_page, [])
                    if i not in lst:
                        lst.append(i)
                        to_delete.append(i)

            self.drag_area = None
            self.show_page()

    # ===== DRAG SELECTION =====
    def start_drag(self, event):
        self.drag_start = (event.x, event.y)
        if self.drag_rect_id:
            self.canvas.delete(self.drag_rect_id)
        self.drag_rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="yellow", width=2, dash=(3, 3)
        )

    def dragging(self, event):
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        self.canvas.coords(self.drag_rect_id, x0, y0, event.x, event.y)

    def end_drag(self, event):
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y
        if x0 > x1: x0, x1 = x1, x0
        if y0 > y1: y0, y1 = y1, y0
        self.drag_start = None
        self.drag_area = (x0, y0, x1, y1)
        if self.drag_rect_id:
            self.canvas.delete(self.drag_rect_id)
            self.drag_rect_id = None
        # draw final visible selection rectangle
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="yellow", width=2, tags="selection")

    # ===== NAVIGATION =====
    def next_page(self):
        if not self.doc or self.current_page >= len(self.doc) - 1:
            return
        self.current_page += 1
        self.show_page()

    def prev_page(self):
        if not self.doc or self.current_page == 0:
            return
        self.current_page -= 1
        self.show_page()

    # ===== UNDO =====
    def undo(self, event):
        if not self.history:
            return
        self.deleted_blocks = self.history.pop()
        self.show_page()

    # ===== EXPORT HTML =====
    def export_html(self):
        if not self.doc:
            return
        html = "<html><body>\n"
        for pg in range(len(self.doc)):
            page = self.doc.load_page(pg)
            blocks = page.get_text("blocks")
            deleted = self.deleted_blocks.get(pg, [])
            for i, b in enumerate(blocks):
                if i not in deleted:
                    html += f"<p>{b[4].strip()}</p>\n"
        html += "</body></html>"
        save_path = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML Files", "*.html")])
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            messagebox.showinfo("Saved", "HTML exported successfully!")

    # ===== SAVE PDF WITH REDACTIONS =====
    def save_pdf(self):
        if not self.doc:
            return
        
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF Files", "*.pdf")])
        if not save_path:
            return
        
        for pg_num in range(len(self.doc)):
            page = self.doc.load_page(pg_num)
            deleted = self.deleted_blocks.get(pg_num, [])
            blocks = page.get_text("blocks")
            for i in deleted:
                if i < len(blocks):
                    x0, y0, x1, y1, *_ = blocks[i]
                    page.add_redact_annot(fitz.Rect(x0, y0, x1, y1), fill=(1,1,1))
            # Apply redactions to remove text
            page.apply_redactions()
        
        self.doc.save(save_path)
        messagebox.showinfo("Saved", f"Updated PDF saved to:\n{save_path}")


# ===== RUN =====
if __name__ == '__main__':
    root = tk.Tk()
    root.geometry("1000x700")
    app = PDFHTMLSyncEditor(root)
    root.title("Delete")
    root.mainloop()
