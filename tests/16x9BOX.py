import tkinter as tk

class FloatingBox:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("16:9 Floating Box")
        
        # Initial size (480x270 is 16:9)
        self.root.geometry("480x270")
        
        # Keeps the window on top of all others
        self.root.attributes("-topmost", True)
        
        # Set a background color
        self.root.configure(bg='#3498db')

        # The Ratio (16/9 = 1.777...)
        self.ratio = 16 / 9

        # Bind the resize event
        self.root.bind("<Configure>", self.maintain_aspect_ratio)

        self.root.mainloop()

    def maintain_aspect_ratio(self, event):
        # We only care about the main window resizing, not its children
        if event.widget == self.root:
            # Calculate what the height SHOULD be based on current width
            calculated_height = int(event.width / self.ratio)
            
            # If current height isn't correct, force it
            if event.height != calculated_height:
                self.root.geometry(f"{event.width}x{calculated_height}")

if __name__ == "__main__":
    FloatingBox()