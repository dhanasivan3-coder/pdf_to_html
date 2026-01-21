import html
import re
from html.entities import codepoint2name
import tkinter as tk
from tkinter import filedialog, messagebox


def convert_chars_to_entities(text):
    result = []

    for ch in text:
        cp = ord(ch)

        # Keep normal ASCII characters
        if cp < 128:
            result.append(ch)
            continue

        # Named entity
        if cp in codepoint2name:
            result.append(f"&{codepoint2name[cp]};")
        else:
            # Numeric entity
            result.append(f"&#{cp};")

    return "".join(result)


def main():
    root = tk.Tk()
    root.withdraw()

    messagebox.showinfo("Select Input File", "Choose the input HTML file")

    input_file = filedialog.askopenfilename(
        title="Select Input HTML",
        filetypes=(("HTML Files", "*.html"), ("All Files", "*.*"))
    )
    if not input_file:
        messagebox.showerror("Error", "No input file selected")
        return

    messagebox.showinfo("Select Output File", "Choose where to save converted HTML")

    output_file = filedialog.asksaveasfilename(
        title="Save Output HTML",
        defaultextension=".html",
        filetypes=(("HTML Files", "*.html"), ("All Files", "*.*"))
    )
    if not output_file:
        messagebox.showerror("Error", "No output file selected")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read()

    converted = convert_chars_to_entities(text)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(converted)

    messagebox.showinfo("Done", "Entity conversion completed!")


if __name__ == "__main__":
    main()
